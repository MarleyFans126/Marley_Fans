from odoo import models, fields, api, _
import logging

_logger = logging.getLogger(__name__)

# IndiaMART QUERY_TYPE mapping
QUERY_TYPE_MAP = {
    'W': 'Direct Enquiry',
    'B': 'Buy Lead',
    'P': 'Phone Call',
    'BIZ': 'Catalog View',
    'WA': 'WhatsApp Enquiry',
}

QUERY_TYPE_SELECTION = [
    ('W', 'Direct Enquiry'),
    ('B', 'Buy Lead'),
    ('P', 'Phone Call'),
    ('BIZ', 'Catalog View'),
    ('WA', 'WhatsApp Enquiry'),
]


class CrmLead(models.Model):
    _inherit = 'crm.lead'

    # Overriding standard fields to make them mandatory
    phone = fields.Char()
    email_from = fields.Char()

    # New Fields
    second_salesperson_id = fields.Many2one(
        'res.users',
        string="Second Sales",
        help="Secondary sales person who follows up if primary is unavailable",
        domain=[('share', '=', False)]
    )

    # business_area Selection field removed — replaced by cascading
    # business_state_id / business_city_id / business_area_id
    # defined in crm_lead_automation_engine

    # External ID with index and uniqueness
    external_lead_id = fields.Char(
        string="External Lead ID",
        index=True,
        copy=False
    )

    _external_lead_unique = models.Constraint(
        'UNIQUE(external_lead_id)',
        message='External Lead ID must be unique!'
    )

    # Lead Source Type (Reporting)
    lead_source_type = fields.Selection([
        ('indiamart', 'IndiaMART'),
        ('aajjo', 'AAJJO'),
    ], string='Lead Source Type', compute='_compute_lead_source_type', store=True, default=False)

    is_manual_lead = fields.Boolean(
        string="Is Manual Lead",
        compute='_compute_is_manual_lead',
        store=True
    )

    # IndiaMART query type field
    lead_query_type = fields.Selection(
        QUERY_TYPE_SELECTION,
        string='Lead Query Type',
        help='IndiaMART lead type based on QUERY_TYPE',
    )

    @api.depends('is_indiamart', 'is_aajjo')
    def _compute_is_manual_lead(self):
        for lead in self:
            lead.is_manual_lead = not (getattr(lead, 'is_aajjo', False) or lead.is_indiamart)

    @api.depends('is_indiamart', 'external_lead_id', 'is_manual_lead')
    def _compute_lead_source_type(self):
        for lead in self:
            if lead.is_indiamart:
                lead.lead_source_type = 'indiamart'
            elif getattr(lead, 'is_aajjo', False):
                lead.lead_source_type = 'aajjo'

    # =========================================================================
    # IndiaMART Pull API Integration
    #
    # Two modes of operation:
    #   1. Historical backfill — fetches last 365 days in 7-day batches
    #      (one batch per cron run to respect rate limits)
    #   2. Normal sync — rolling window for new leads every cron run
    #
    # Key generation rule: IndiaMART only makes historical leads available
    # 24 hours after the API key is generated.  Before that only live/new
    # leads can be fetched.
    # =========================================================================

    @api.model
    def fetch_indiamart_leads(self, is_cron=True):
        """Main entry point — called by cron and manual-fetch button."""
        import requests
        from datetime import timedelta, timezone

        config = self.env['indiamart.config'].sudo().search([], limit=1)
        if not config:
            _logger.error("IndiaMART Config missing.")
            return
        if not config.is_active and is_cron:
            return
        if not config.api_key:
            _logger.error("IndiaMART API Key is missing.")
            return

        now = fields.Datetime.now()
        IST = timezone(timedelta(hours=5, minutes=30))

        # ── Mock server shortcut ──
        if config.is_mock_server:
            start_dt = now - timedelta(minutes=10)
            self._do_api_call(
                config, now, start_dt, now, IST,
                sync_mode='normal', is_mock=True,
            )
            return

        # ── Key-generation-time guard ──
        # Per IndiaMART docs: historical data before the key generation
        # time is only available 24 hours after key was generated.
        key_too_new = False
        if config.key_generated_date:
            if (now - config.key_generated_date) < timedelta(hours=24):
                key_too_new = True
                _logger.info(
                    "IndiaMART API key generated < 24 h ago — "
                    "skipping historical backfill, fetching new leads only."
                )
        elif not config.historical_sync_done:
            _logger.warning(
                "IndiaMART 'Key Generated Date' is not set. "
                "Please set it in CRM → Settings → IndiaMART Integration "
                "to enable proper historical backfill."
            )

        # ── Normal rolling-window mode — fetch new leads only ──
        self._run_normal_sync(config, now, IST, is_cron)

    # ------------------------------------------------------------------
    # Normal sync  (rolling window, every cron run)
    # ------------------------------------------------------------------

    @api.model
    def _run_normal_sync(self, config, now, IST, is_cron):
        from datetime import timedelta

        # ── Rate-limit guard ──
        # IndiaMART requires minimum 5 minutes between API calls.
        # Skip this run if last call was less than 5 minutes ago.
        if config.last_end_time and (now - config.last_end_time) < timedelta(minutes=5):
            _logger.info(
                "IndiaMART: skipping — less than 5 min since last sync."
            )
            return

        # ── Time window ──
        # start = previous end_time (no overlap, no gap)
        # UNIQUE_QUERY_ID dedup handles any edge-case duplicates.
        if config.last_end_time:
            start_dt = config.last_end_time
        else:
            start_dt = now - timedelta(minutes=10)

        end_dt = now
        sync_mode = 'normal' if is_cron else 'manual'

        result = self._do_api_call(
            config, now, start_dt, end_dt, IST, sync_mode=sync_mode,
        )

        # Advance window on everything except rate-limit / auth failure
        if result not in ('rate_limited', 'auth_error'):
            config.write({
                'last_start_time': start_dt,
                'last_end_time': now,
                'last_sync_datetime': now,
            })

    # ------------------------------------------------------------------
    # Historical backfill  (one 7-day batch per cron run)
    # ------------------------------------------------------------------

    @api.model
    def _run_historical_batch(self, config, now, IST):
        from datetime import timedelta

        # Where to start this batch
        if config.historical_sync_cursor:
            start_dt = config.historical_sync_cursor
        else:
            start_dt = now - timedelta(days=365)

        # ── Safeguard: API only allows last 365 days from today ──
        # If cron was paused and cursor fell behind, clamp it.
        earliest_allowed = now - timedelta(days=365)
        if start_dt < earliest_allowed:
            _logger.warning(
                "IndiaMART historical cursor %s is older than 365 days. "
                "Clamping to %s.", start_dt, earliest_allowed,
            )
            start_dt = earliest_allowed

        batch_end = start_dt + timedelta(days=7)
        if batch_end > now:
            batch_end = now

        _logger.info(
            "IndiaMART historical backfill | batch %s → %s",
            start_dt, batch_end,
        )

        result = self._do_api_call(
            config, now, start_dt, batch_end, IST, sync_mode='historical',
        )

        if result == 'rate_limited':
            # Don't advance cursor — retry same batch next cron run
            return
        if result == 'auth_error':
            return

        # Advance cursor on success, no_leads (CODE 204), AND error
        # (CODE 400 = "365 days only" → skip this range and move on)
        if batch_end >= now:
            # Historical sync complete!
            # Do NOT touch last_end_time — normal sync manages it
            # via the alternating schedule above.
            config.write({
                'historical_sync_done': True,
                'historical_sync_cursor': False,
                'last_sync_datetime': now,
            })
            _logger.info("IndiaMART historical backfill COMPLETE.")
        else:
            config.write({
                'historical_sync_cursor': batch_end,
            })

    # ------------------------------------------------------------------
    # Core API call + lead processing  (single request)
    # ------------------------------------------------------------------

    @api.model
    def _do_api_call(self, config, now, start_dt, end_dt, IST,
                     sync_mode='normal', is_mock=False):
        """Execute one IndiaMART API call, process leads, log everything.

        Returns one of:
            'success'       – leads processed (or zero leads, 204)
            'no_leads'      – 204 / empty response
            'rate_limited'  – 429
            'auth_error'    – 401
            'error'         – any other failure
        """
        import requests
        from datetime import timezone

        url = ''
        start_str = end_str = ''

        try:
            # ── Build URL ──
            if is_mock:
                url = ("https://run.mocky.io/v3/"
                       "2e0b57e7-36e2-401d-b2de-563ac945e128")
            else:
                base = config.api_base_url.rstrip('/')
                # Convert UTC → IST
                start_ist = start_dt.replace(
                    tzinfo=timezone.utc).astimezone(IST)
                end_ist = end_dt.replace(
                    tzinfo=timezone.utc).astimezone(IST)
                # DD-Mon-YYYYHH:MM:SS  (e.g. 01-Jan-202409:00:00)
                start_str = start_ist.strftime('%d-%b-%Y%H:%M:%S')
                end_str = end_ist.strftime('%d-%b-%Y%H:%M:%S')
                url = (f"{base}/?glusr_crm_key={config.api_key}"
                       f"&start_time={start_str}&end_time={end_str}")

            _logger.info(
                "IndiaMART API [%s] | start=%s | end=%s",
                sync_mode, start_str or 'mock', end_str or 'mock',
            )

            # ── HTTP request ──
            response = requests.get(url, timeout=30)
            status = response.status_code

            # ── HTTP-level response codes ──
            if status == 204:
                _logger.info("IndiaMART 204 — No new leads found.")
                self._log_fetch(url, 204, 0, 0, 0, 0,
                                note='No new leads found',
                                start_str=start_str, end_str=end_str,
                                sync_mode=sync_mode)
                return 'no_leads'

            if status == 401:
                msg = ("IndiaMART 401 — Invalid / expired API key. "
                       "Regenerate at IndiaMART Lead Manager.")
                _logger.error(msg)
                self._log_fetch(url, 401, 0, 0, 0, 0, error=msg,
                                start_str=start_str, end_str=end_str,
                                sync_mode=sync_mode)
                return 'auth_error'

            if status == 429:
                msg = ("IndiaMART 429 — Rate limited. "
                       "Will retry on next cron run (10 min).")
                _logger.warning(msg)
                self._log_fetch(url, 429, 0, 0, 0, 0, error=msg,
                                start_str=start_str, end_str=end_str,
                                sync_mode=sync_mode)
                return 'rate_limited'

            if status == 400:
                msg = (f"IndiaMART 400 — Bad request. "
                       f"Response: {response.text[:500]}")
                _logger.error(msg)
                self._log_fetch(url, 400, 0, 0, 0, 0, error=msg,
                                start_str=start_str, end_str=end_str,
                                sync_mode=sync_mode)
                return 'error'

            if status >= 500:
                msg = (f"IndiaMART {status} — Server error. "
                       f"Response: {response.text[:500]}")
                _logger.error(msg)
                self._log_fetch(url, status, 0, 0, 0, 0, error=msg,
                                start_str=start_str, end_str=end_str,
                                sync_mode=sync_mode)
                return 'error'

            if status != 200:
                msg = (f"IndiaMART unexpected HTTP {status}: "
                       f"{response.text[:500]}")
                _logger.error(msg)
                self._log_fetch(url, status, 0, 0, 0, 0, error=msg,
                                start_str=start_str, end_str=end_str,
                                sync_mode=sync_mode)
                return 'error'

            # ── Parse JSON body (HTTP 200) ──
            data = response.json()
            leads_data = []

            if isinstance(data, dict):
                # ── In-body CODE handling ──
                # IndiaMART always returns HTTP 200; the real status is
                # in the JSON body CODE field per their documentation.
                api_code = data.get('CODE')
                if api_code is not None and int(api_code) != 200:
                    api_code = int(api_code)
                    api_msg = data.get('MESSAGE', '')
                    _logger.info(
                        "IndiaMART body CODE=%s STATUS=%s MSG=%s",
                        api_code, data.get('STATUS'), api_msg,
                    )

                    # CODE 204 — No new leads in this time window
                    if api_code == 204:
                        self._log_fetch(
                            url, 204, 0, 0, 0, 0,
                            note='No new leads found',
                            start_str=start_str, end_str=end_str,
                            sync_mode=sync_mode)
                        return 'no_leads'

                    # CODE 401 — Invalid / expired API key
                    if api_code == 401:
                        self._log_fetch(
                            url, 401, 0, 0, 0, 0,
                            error=f'Auth error (CODE 401): {api_msg[:200]}',
                            start_str=start_str, end_str=end_str,
                            sync_mode=sync_mode)
                        return 'auth_error'

                    # CODE 429 — Rate limited (> 1 hit per 5 min or
                    # > 5 hits per min → key blocked 15 min)
                    if api_code == 429:
                        self._log_fetch(
                            url, 429, 0, 0, 0, 0,
                            error=f'Rate limit (CODE 429): {api_msg[:200]}',
                            start_str=start_str, end_str=end_str,
                            sync_mode=sync_mode)
                        return 'rate_limited'

                    # CODE 400 — Bad request (date range > 7 days,
                    # or > 365 days old, or missing date params)
                    if api_code == 400:
                        self._log_fetch(
                            url, 400, 0, 0, 0, 0,
                            error=f'Bad request (CODE 400): {api_msg[:200]}',
                            start_str=start_str, end_str=end_str,
                            sync_mode=sync_mode)
                        return 'error'

                    # CODE 500 — IndiaMART server error
                    if api_code == 500:
                        self._log_fetch(
                            url, 500, 0, 0, 0, 0,
                            error=f'Server error (CODE 500): {api_msg[:200]}',
                            start_str=start_str, end_str=end_str,
                            sync_mode=sync_mode)
                        return 'error'

                    # Any other non-200 body code
                    self._log_fetch(
                        url, api_code,
                        data.get('TOTAL_RECORDS', 0), 0, 0, 0,
                        note=f'API CODE {api_code}: {api_msg[:200]}',
                        start_str=start_str, end_str=end_str,
                        sync_mode=sync_mode)
                    return 'no_leads'

                # Extract leads array
                if data.get('STATUS') == 'SUCCESS':
                    leads_data = data.get('RESPONSE', [])
                elif 'RESPONSE' in data:
                    leads_data = data['RESPONSE']
                elif 'data' in data:
                    leads_data = data['data']
            elif isinstance(data, list):
                leads_data = data

            # "No Record Found" string response
            if isinstance(leads_data, str):
                _logger.info("IndiaMART returned message: %s", leads_data)
                self._log_fetch(url, 200, 0, 0, 0, 0,
                                note=f'API message: {leads_data}',
                                start_str=start_str, end_str=end_str,
                                sync_mode=sync_mode)
                return 'no_leads'

            _logger.info("IndiaMART returned %d lead(s).", len(leads_data))

            # ── Process leads ──
            created, dup, invalid = self._process_leads(leads_data)

            _logger.info(
                "IndiaMART [%s] done | fetched=%d created=%d "
                "dup=%d invalid=%d",
                sync_mode, len(leads_data), created, dup, invalid,
            )
            resp_text = (
                response.text[:5000]
                if len(leads_data) < 50
                else f'[{len(leads_data)} leads — truncated]'
            )
            self._log_fetch(
                url, 200, len(leads_data), created, dup, invalid,
                response_text=resp_text,
                start_str=start_str, end_str=end_str,
                sync_mode=sync_mode,
            )
            return 'success'

        except Exception as e:
            _logger.error("IndiaMART Fetch Exception: %s", e, exc_info=True)
            self.env['indiamart.log'].sudo().create({
                'name': 'Fetch Exception',
                'request_url': url or 'N/A',
                'error_message': str(e),
                'status_code': 0,
                'sync_mode': sync_mode,
                'api_start_time': start_str or False,
                'api_end_time': end_str or False,
            })
            return 'error'

    # ------------------------------------------------------------------
    # Lead processing  (dedup + create)
    # ------------------------------------------------------------------

    @api.model
    def _process_leads(self, leads_data):
        """Iterate API leads, deduplicate by UNIQUE_QUERY_ID, create CRM leads.

        Returns (created_count, skipped_dup, skipped_invalid).
        """
        created_count = 0
        skipped_dup = 0
        skipped_invalid = 0

        stage = self.env['crm.stage'].sudo().search([], limit=1)
        team = self.env['crm.team'].sudo().search([], limit=1)
        source = self.env.ref(
            'crm_indiamart_integration.utm_source_indiamart',
            raise_if_not_found=False,
        )

        for api_lead in leads_data:
            # ── Dedup key: UNIQUE_QUERY_ID ──
            api_lead_id = str(
                api_lead.get('UNIQUE_QUERY_ID')
                or api_lead.get('QUERY_ID')
                or api_lead.get('lead_id')
                or ''
            ).strip()
            if not api_lead_id:
                skipped_invalid += 1
                continue

            # Duplicate check
            if self.env['crm.lead'].sudo().search_count([
                ('external_lead_id', '=', api_lead_id),
            ]):
                skipped_dup += 1
                continue

            # ── Field mapping ──
            phone = (
                api_lead.get('SENDER_MOBILE')
                or api_lead.get('mobile')
                or api_lead.get('SENDER_PHONE')
                or api_lead.get('phone')
            )
            email = (
                api_lead.get('SENDER_EMAIL')
                or api_lead.get('email')
            )

            if not phone or not email:
                _logger.warning(
                    "Skipping lead %s — missing phone or email.",
                    api_lead_id,
                )
                skipped_invalid += 1
                continue

            query_type_raw = api_lead.get('QUERY_TYPE', '')
            query_type = (
                query_type_raw
                if query_type_raw in dict(QUERY_TYPE_SELECTION)
                else False
            )

            try:
                self.env['crm.lead'].sudo().create({
                    'name': (
                        api_lead.get('QUERY_PRODUCT_NAME')
                        or api_lead.get('product')
                        or 'New Inquiry'
                    ),
                    'contact_name': (
                        api_lead.get('SENDER_NAME')
                        or api_lead.get('name')
                    ),
                    'partner_name': (
                        api_lead.get('SENDER_COMPANY')
                        or api_lead.get('company')
                    ),
                    'phone': phone,
                    'email_from': email,
                    'description': (
                        api_lead.get('QUERY_MESSAGE')
                        or api_lead.get('product')
                    ),
                    'city': (
                        api_lead.get('SENDER_CITY')
                        or api_lead.get('city')
                    ),
                    'state_id': self._resolve_state(
                        api_lead.get('SENDER_STATE')
                    ),
                    'zip': api_lead.get('SENDER_PINCODE') or False,
                    'street': api_lead.get('SENDER_ADDRESS') or False,
                    'source_id': source.id if source else False,
                    'is_indiamart': True,
                    'stage_id': stage.id if stage else False,
                    'team_id': team.id if team else False,
                    'external_lead_id': api_lead_id,
                    'lead_query_type': query_type,
                    'type': 'lead',
                    'active': True,
                    'lead_source_type': 'indiamart',
                    'second_salesperson_id': False,
                    'business_state_id': self._resolve_state(
                        api_lead.get('SENDER_STATE')
                    ),
                    'business_city_id': self._resolve_business_city(
                        api_lead.get('SENDER_CITY') or api_lead.get('city'),
                        self._resolve_state(api_lead.get('SENDER_STATE')),
                    ),
                })
                created_count += 1
            except Exception as e:
                _logger.error(
                    "Lead creation failed for %s: %s", api_lead_id, e,
                )

        return created_count, skipped_dup, skipped_invalid

    # ------------------------------------------------------------------
    # Helper methods
    # ------------------------------------------------------------------

    @api.model
    def _update_config_times(self, config, now, start_dt):
        """Update rolling window timestamps on config."""
        vals = {'last_end_time': now}
        if start_dt:
            vals['last_start_time'] = start_dt
        config.write(vals)

    @api.model
    def _log_fetch(self, url, status, fetched, created,
                   skipped_dup=0, skipped_invalid=0,
                   error=None, note=None, response_text=None,
                   start_str='', end_str='', sync_mode='normal'):
        """Create an indiamart.log entry with full details."""
        self.env['indiamart.log'].sudo().create({
            'name': note or (
                'Lead Fetch Success' if status == 200
                else f'API Response {status}'
            ),
            'request_type': 'GET',
            'request_url': url,
            'status_code': status,
            'leads_fetched': fetched,
            'leads_created': created,
            'leads_skipped_dup': skipped_dup,
            'leads_skipped_invalid': skipped_invalid,
            'error_message': error or False,
            'response_payload': response_text or False,
            'api_start_time': start_str or False,
            'api_end_time': end_str or False,
            'sync_mode': sync_mode,
        })

    @api.model
    def _resolve_state(self, state_name):
        """Resolve an Indian state name to res.country.state id."""
        if not state_name:
            return False
        india = self.env['res.country'].search(
            [('code', '=', 'IN')], limit=1,
        )
        if not india:
            return False
        state = self.env['res.country.state'].search([
            ('country_id', '=', india.id),
            ('name', 'ilike', state_name.strip()),
        ], limit=1)
        return state.id if state else False

    @api.model
    def _resolve_business_city(self, city_name, state_id):
        """Resolve a city name to business.city id."""
        if not city_name:
            return False
        domain = [('name', 'ilike', city_name.strip())]
        if state_id:
            domain.append(('state_id', '=', state_id))
        city = self.env['business.city'].search(domain, limit=1)
        return city.id if city else False

    def action_manual_fetch(self):
        self.fetch_indiamart_leads(is_cron=False)
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'IndiaMART Sync',
                'message': 'Manual fetch triggered.',
                'type': 'success',
                'sticky': False,
            },
        }

    @api.model
    def cron_fetch_indiamart(self):
        self.fetch_indiamart_leads(is_cron=True)
