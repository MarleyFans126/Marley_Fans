# -*- coding: utf-8 -*-
"""crm.lead extension: AI summary, scoring, activity suggestions."""
import logging

from odoo import api, fields, models, _
from odoo.exceptions import UserError

from ..services.ai_service import AIService
from ..services.exceptions import AIError

_logger = logging.getLogger(__name__)


class CrmLead(models.Model):
    _inherit = 'crm.lead'

    # AI-produced fields. Readonly to humans — only updated via the
    # ``action_*`` buttons or the scheduled cron.
    ai_summary = fields.Text(
        string='AI Summary', readonly=True, copy=False, tracking=False,
    )
    ai_summary_date = fields.Datetime(
        string='AI Summary Generated', readonly=True, copy=False,
    )
    ai_score = fields.Integer(
        string='AI Score', readonly=True, copy=False, aggregator='avg',
        help='0-100. Combines activity, stage progression, urgency signals.',
    )
    ai_priority = fields.Selection(
        selection=[
            ('Low', 'Low'),
            ('Medium', 'Medium'),
            ('High', 'High'),
        ],
        string='AI Priority', readonly=True, copy=False,
    )
    ai_status = fields.Selection(
        selection=[
            ('Hot', 'Hot'),
            ('Warm', 'Warm'),
            ('Cold', 'Cold'),
        ],
        string='AI Status', readonly=True, copy=False, tracking=True,
    )
    ai_score_reason = fields.Char(
        string='AI Score Reason', readonly=True, copy=False,
    )
    ai_suggested_actions = fields.Text(
        string='AI Suggested Actions (raw JSON)', readonly=True,
        copy=False,
        help='Raw JSON from the AI provider. Not displayed directly — '
             'see ``ai_suggested_actions_html`` for the rendered list.',
    )
    ai_suggested_actions_html = fields.Html(
        string='Suggested Next Actions', readonly=True, copy=False,
        compute='_compute_ai_suggested_actions_html', sanitize=True,
        help='Renders the AI suggestions as a styled list — what the '
             'salesperson sees in the form view.',
    )

    @api.depends('ai_suggested_actions')
    def _compute_ai_suggested_actions_html(self):
        """Render the JSON suggestion list as a clean HTML table.

        Falls back to an empty string if the JSON is malformed — never
        raises, so the form view stays usable even on partial data.
        """
        import json as _json
        from markupsafe import escape, Markup

        # Map ``action`` values to a small icon so the table reads
        # at-a-glance. Anything not in this map renders without an icon.
        icons = {
            'call':     '📞',
            'email':    '✉',
            'meeting':  '📅',
            'demo':     '🖥',
            'quote':    '💰',
            'proposal': '📄',
            'followup': '🔁',
            'follow-up':'🔁',
            'task':     '📌',
            'visit':    '📍',
        }

        for rec in self:
            raw = (rec.ai_suggested_actions or '').strip()
            if not raw:
                rec.ai_suggested_actions_html = False
                continue
            try:
                items = _json.loads(raw)
                if not isinstance(items, list):
                    items = []
            except (ValueError, TypeError):
                rec.ai_suggested_actions_html = False
                continue

            rows = []
            for idx, it in enumerate(items, 1):
                if not isinstance(it, dict):
                    continue
                action = (it.get('action') or '').strip().lower()
                icon = icons.get(action, '•')
                label = escape((it.get('action') or '—').title())
                summary = escape(it.get('summary') or '')
                due = it.get('due_in_days')
                if due in (None, ''):
                    due_text = '—'
                else:
                    try:
                        d = int(due)
                        due_text = 'Today' if d <= 0 else (
                            'Tomorrow' if d == 1 else 'in %d days' % d
                        )
                    except (TypeError, ValueError):
                        due_text = escape(str(due))
                rows.append(
                    '<tr>'
                    '<td style="padding:6px 10px; vertical-align:top; '
                    'font-size:14px;">%s</td>'
                    '<td style="padding:6px 10px; vertical-align:top;">'
                    '<b>%s</b></td>'
                    '<td style="padding:6px 10px; vertical-align:top;">'
                    '%s</td>'
                    '<td style="padding:6px 10px; vertical-align:top; '
                    'color:#6b7280; white-space:nowrap;">%s</td>'
                    '</tr>' % (icon, label, summary, due_text)
                )

            if not rows:
                rec.ai_suggested_actions_html = False
                continue

            rec.ai_suggested_actions_html = Markup(
                '<table style="width:100%%; border-collapse:collapse; '
                'font-family:inherit;">'
                '<thead>'
                '<tr style="background:#f9fafb; '
                'border-bottom:1px solid #e5e7eb;">'
                '<th style="padding:6px 10px; text-align:left; '
                'width:32px;"></th>'
                '<th style="padding:6px 10px; text-align:left; '
                'width:120px;">Action</th>'
                '<th style="padding:6px 10px; text-align:left;">'
                'What to do</th>'
                '<th style="padding:6px 10px; text-align:left; '
                'width:100px;">When</th>'
                '</tr></thead>'
                '<tbody>%s</tbody></table>' % ''.join(rows)
            )

    # --- Lead Legitimacy (anti-spam / quality gate) -------------------
    # Populated by the auto-process cron alongside summary + score.
    # The orchestrator refuses to send outreach to leads with verdict
    # 'suspicious' or 'spam' — saves API tokens and protects sender
    # reputation from auto-emailing junk.
    ai_legitimacy_verdict = fields.Selection(
        selection=[
            ('trusted', 'Trusted'),
            ('verified', 'Verified'),
            ('suspicious', 'Suspicious'),
            ('spam', 'Likely Spam'),
        ],
        string='AI Legitimacy', readonly=True, copy=False, index=True,
        tracking=True,
        help='AI assessment of how genuine this lead looks based on '
             'email domain, completeness of info, and description '
             'quality. Suspicious / Spam leads are skipped by the '
             'orchestrator.',
    )
    ai_legitimacy_score = fields.Integer(
        string='Legitimacy Score', readonly=True, copy=False,
        aggregator='avg',
        help='0-100. Higher = more legitimate. Combines email domain '
             'class, data completeness, and LLM judgement.',
    )
    ai_legitimacy_notes = fields.Char(
        string='Legitimacy Notes', readonly=True, copy=False,
        help='One-line AI reasoning for the verdict.',
    )
    ai_legitimacy_signals = fields.Text(
        string='Legitimacy Signals (JSON)', readonly=True, copy=False,
        help='Raw flags collected by the heuristic pre-check: red '
             'flags (disposable email, etc), yellow (missing data), '
             'green (corporate domain, specific intent).',
    )
    ai_legitimacy_signals_html = fields.Html(
        string='Legitimacy Signals', readonly=True, copy=False,
        compute='_compute_ai_legitimacy_signals_html', sanitize=True,
        help='Human-readable view of the raw heuristic flags — what the '
             'salesperson sees in the form view.',
    )
    ai_legitimacy_checked_at = fields.Datetime(
        string='Legitimacy Checked', readonly=True, copy=False,
    )

    # Map cryptic flag codes (as emitted by services/legitimacy.py) to
    # the short business-readable labels we want to show end users.
    # Keep these in sync with services/legitimacy.py — adding a new flag
    # there without a label here just renders the snake_case code.
    _LEGITIMACY_FLAG_LABELS = {
        # Red / negative
        'no_email_address':           'No email address provided',
        'malformed_email':            'Email address is malformed',
        'disposable_email_provider':  'Disposable / throwaway email domain',
        # Yellow / weak negatives
        'free_email_provider':        'Free email provider (gmail/yahoo/etc)',
        'no_phone_provided':          'No phone number',
        'phone_too_short':            'Phone number looks too short',
        'no_company_name':            'No company name given',
        'no_country':                 'Country not specified',
        'description_too_short':      'Description is very short',
        'generic_template_language':  'Description uses generic template wording',
        # Green / positives
        'corporate_email_domain':     'Corporate email domain',
        'plausible_phone_number':     'Phone number looks plausible',
        'company_name_provided':      'Company name provided',
        'email_domain_matches_company': 'Email domain matches company name',
        'country_specified':          'Country specified',
        'specific_description':       'Description is specific and detailed',
    }

    _LEGITIMACY_EMAIL_CLASS_LABELS = {
        'corporate':  'Corporate',
        'free':       'Free provider',
        'disposable': 'Disposable',
        'malformed':  'Malformed',
        'missing':    'Missing',
        'unknown':    'Unknown',
    }

    @api.depends('ai_legitimacy_signals')
    def _compute_ai_legitimacy_signals_html(self):
        """Render the legitimacy signals JSON as a friendly summary.

        We surface three things in plain English:
          * Email class + domain (the most useful one-glance signal)
          * Data completeness (phone / company / country / description)
          * The colour-coded flag list (green = good, yellow = soft
            warning, red = strong warning), each translated from the
            internal snake_case code to a business-readable sentence.

        Falls back gracefully if the JSON is malformed.
        """
        import json as _json
        from markupsafe import escape, Markup

        flag_labels = self._LEGITIMACY_FLAG_LABELS
        email_labels = self._LEGITIMACY_EMAIL_CLASS_LABELS

        def _row(icon, label, value):
            return (
                '<tr>'
                '<td style="padding:4px 10px 4px 0; vertical-align:top; '
                'width:24px; font-size:14px;">%s</td>'
                '<td style="padding:4px 10px 4px 0; vertical-align:top; '
                'color:#6b7280; white-space:nowrap;">%s</td>'
                '<td style="padding:4px 0; vertical-align:top;">%s</td>'
                '</tr>'
            ) % (icon, escape(label), value)

        for rec in self:
            raw = (rec.ai_legitimacy_signals or '').strip()
            if not raw:
                rec.ai_legitimacy_signals_html = False
                continue
            try:
                data = _json.loads(raw)
                if not isinstance(data, dict):
                    data = {}
            except (ValueError, TypeError):
                rec.ai_legitimacy_signals_html = False
                continue

            # --- Block A: at-a-glance summary rows --------------------
            email_class = data.get('email_class') or 'unknown'
            email_class_label = email_labels.get(
                email_class, email_class.title(),
            )
            domain = data.get('domain') or '—'
            email_value = '<b>%s</b> <span style="color:#6b7280;">(%s)</span>' % (
                escape(email_class_label), escape(str(domain)),
            )

            def _yes_no(flag):
                return ('<span style="color:#10b981;">✓ Yes</span>'
                        if data.get(flag)
                        else '<span style="color:#9ca3af;">— No</span>')

            desc_len = data.get('description_length') or 0
            desc_generic = data.get('description_generic')
            if desc_len:
                desc_value = '%d characters' % int(desc_len)
                if desc_generic:
                    desc_value += (' <span style="color:#d97706;">'
                                   '(generic wording)</span>')
            else:
                desc_value = '<span style="color:#9ca3af;">— Not provided</span>'

            summary_rows = [
                _row('📧', 'Email',       Markup(email_value)),
                _row('📱', 'Phone',       Markup(_yes_no('has_phone'))),
                _row('🏢', 'Company',     Markup(_yes_no('has_company'))),
                _row('🌍', 'Country',     Markup(_yes_no('has_country'))),
                _row('📝', 'Description', Markup(desc_value)),
            ]

            summary_table = (
                '<table style="border-collapse:collapse; '
                'font-family:inherit; margin-bottom:12px;">'
                '<tbody>%s</tbody></table>'
            ) % ''.join(summary_rows)

            # --- Block B: colour-coded flag pills ---------------------
            def _pills(flags, bg, border, fg, icon):
                if not flags:
                    return ''
                pieces = []
                for f in flags:
                    label = flag_labels.get(f, f.replace('_', ' ').capitalize())
                    pieces.append(
                        '<span style="display:inline-block; '
                        'padding:3px 10px; margin:2px 4px 2px 0; '
                        'border-radius:12px; background:%s; '
                        'border:1px solid %s; color:%s; font-size:12px;">'
                        '%s %s</span>' % (
                            bg, border, fg, icon, escape(label),
                        )
                    )
                return ''.join(pieces)

            green_pills  = _pills(data.get('green_flags')  or [],
                                  '#ecfdf5', '#a7f3d0', '#065f46', '✓')
            yellow_pills = _pills(data.get('yellow_flags') or [],
                                  '#fffbeb', '#fde68a', '#92400e', '!')
            red_pills    = _pills(data.get('red_flags')    or [],
                                  '#fef2f2', '#fecaca', '#991b1b', '✕')

            sections = []
            if green_pills:
                sections.append(
                    '<div style="margin:6px 0;">'
                    '<div style="font-weight:600; color:#065f46; '
                    'margin-bottom:4px;">Positive signals</div>%s</div>'
                    % green_pills
                )
            if yellow_pills:
                sections.append(
                    '<div style="margin:6px 0;">'
                    '<div style="font-weight:600; color:#92400e; '
                    'margin-bottom:4px;">Soft warnings</div>%s</div>'
                    % yellow_pills
                )
            if red_pills:
                sections.append(
                    '<div style="margin:6px 0;">'
                    '<div style="font-weight:600; color:#991b1b; '
                    'margin-bottom:4px;">Strong warnings</div>%s</div>'
                    % red_pills
                )

            rec.ai_legitimacy_signals_html = Markup(
                summary_table + ''.join(sections)
            )

    # --- Company web research -----------------------------------------
    # Populated by the auto-process cron alongside legitimacy. The cron
    # fetches the lead's company website (derived from email domain),
    # strips HTML to text, and asks the LLM for a short grounded brief.
    # Free/disposable email providers are skipped — they're not company
    # sites.
    ai_company_website = fields.Char(
        string='Researched Company URL', readonly=True, copy=False,
        help='The actual URL that was fetched to produce the company '
             'summary below. Click through to see what the AI saw.',
    )
    ai_company_summary = fields.Text(
        string='Company Summary (from web)', readonly=True, copy=False,
        help='Short brief (3-5 sentences) the AI wrote based on the '
             'company\'s homepage content. Grounded only in the fetched '
             'text — never general-knowledge filler.',
    )
    ai_company_research_status = fields.Selection(
        selection=[
            ('completed', 'Completed'),
            ('skipped', 'Skipped'),
            ('failed', 'Failed'),
        ],
        string='Web Research Status', readonly=True, copy=False,
    )
    ai_company_research_reason = fields.Char(
        string='Web Research Reason', readonly=True, copy=False,
        help='If skipped or failed, why. e.g. "free email provider", '
             '"network error", "JS-rendered site".',
    )
    ai_company_research_date = fields.Datetime(
        string='Web Research At', readonly=True, copy=False,
    )

    # Flagged True after the background auto-processor has run summary +
    # score + activity suggestions for this lead. Indexed so the cron
    # query (``ai_auto_processed = False``) stays fast as the pipeline
    # grows. Set to False on copy so cloned leads get re-processed.
    ai_auto_processed = fields.Boolean(
        string='AI Auto-Processed', readonly=True, copy=False, index=True,
        help='Marked True once the background cron has generated the '
             'AI summary, score, and activity suggestions for this lead. '
             'Manual buttons set this flag too so a lead is never '
             'double-processed.',
    )

    # --- AI Orchestrator state ----------------------------------------
    # Together these fields let the orchestrator cron answer "what's
    # the next step for this lead?" in O(1):
    #   not auto_processed              → wait (auto-process cron handles it)
    #   processed + score >= threshold +
    #   not outreach_initialized        → send initial outreach
    #   inbound_count > outreach_count  → respond to customer reply
    #   exchanges > max OR handed_off   → stop, human takeover
    ai_outreach_initialized = fields.Boolean(
        string='AI Initial Outreach Sent', readonly=True, copy=False,
        index=True,
        help='Has the AI orchestrator sent the first outreach email '
             'to this customer? Flips True after the initial-outreach '
             'step runs successfully.',
    )
    ai_outreach_count = fields.Integer(
        string='AI Emails Sent', readonly=True, copy=False, default=0,
        help='Cumulative count of AI-generated emails sent on this lead.',
    )
    ai_inbound_count = fields.Integer(
        string='Customer Replies Received', readonly=True, copy=False,
        default=0,
        help='Cumulative count of inbound customer emails the '
             'orchestrator has seen and responded to.',
    )
    ai_last_outbound_at = fields.Datetime(
        string='Last AI Email Sent', readonly=True, copy=False,
    )
    ai_last_inbound_at = fields.Datetime(
        string='Last Customer Reply Seen', readonly=True, copy=False,
        help='Set by the orchestrator each time it processes a new '
             'inbound message. Used to decide if there\'s a fresh '
             'reply to answer.',
    )
    ai_handed_off = fields.Boolean(
        string='Handed Off to Human', readonly=True, copy=False,
        index=True,
        help='AI orchestrator has decided to stop auto-replying — '
             'either max exchanges reached or the AI judged the case '
             'too sensitive. A salesperson must take over.',
    )
    ai_handoff_reason = fields.Char(
        string='AI Handoff Reason', readonly=True, copy=False,
    )

    # ------------------------------------------------------------------
    # On create: schedule the auto-process cron to fire ASAP.
    #
    # Why a trigger and not an inline call:
    #   - Inline AI calls in ``create()`` block the lead-creation form
    #     for the duration of the HTTP request (3-5s per provider call,
    #     ×5 calls = ~20s freeze).
    #   - Inline calls hold the request worker, hurting throughput.
    #   - A trigger nudges Odoo's cron heartbeat to pick the row up on
    #     the very next tick (~60s), with no impact on form latency.
    # ``ir.cron._trigger()`` is Odoo's documented mechanism for this
    # exact "process this thing soon" use case.
    # ------------------------------------------------------------------
    @api.model_create_multi
    def create(self, vals_list):
        leads = super().create(vals_list)
        # Only nudge the cron if any newly-created lead is in a
        # processable state. Skip if the user explicitly set
        # ``ai_auto_processed=True`` (tests / bulk imports of
        # already-enriched leads).
        #
        # ``sudo()`` everywhere: ir.cron is admin-only by default, so
        # sales users would otherwise hit AccessError reading
        # ``cron.active``. The trigger itself is an internal mechanism
        # — escalation here is appropriate and bounded.
        if any(not l.ai_auto_processed for l in leads):
            cron = self.env.ref(
                'techmatic_ai_crm.cron_auto_process_leads',
                raise_if_not_found=False,
            )
            if cron:
                cron_sudo = cron.sudo()
                if cron_sudo.active:
                    try:
                        cron_sudo._trigger()
                    except Exception:  # noqa: BLE001 — never block create
                        _logger.warning(
                            'Could not trigger auto-process cron '
                            'after lead creation — falling back to '
                            'scheduled run.',
                            exc_info=True,
                        )
        return leads

    # ------------------------------------------------------------------
    # Button actions.
    # ------------------------------------------------------------------
    def action_generate_ai_summary(self):
        """Button: ``Generate AI Summary``."""
        self.ensure_one()
        self._check_ai_user()
        service = AIService(self.env)
        try:
            text = service.summarize_lead(self)
        except AIError as e:
            raise UserError(_('Could not generate summary: %s') % e) from e
        # Don't flip ``ai_auto_processed`` here — that flag means "the
        # auto-process cron has done a full pass" (summary + score +
        # legitimacy + web research + activities). A manual summary
        # regen is just a partial refresh; if the cron hasn't run yet,
        # we want it to still pick this lead up and do the rest.
        self.write({
            'ai_summary': text,
            'ai_summary_date': fields.Datetime.now(),
        })
        self.message_post(body=_('AI summary regenerated.'))
        return self._notify('AI Summary updated', 'success')

    def action_generate_ai_score(self):
        """Button: ``Score with AI``."""
        self.ensure_one()
        self._check_ai_user()
        service = AIService(self.env)
        try:
            score = service.score_lead(self)
        except AIError as e:
            raise UserError(_('Could not score lead: %s') % e) from e

        priority = score.get('priority') or 'Low'
        status = score.get('status') or 'Cold'
        # Validate against the field selections — defensive against
        # off-script LLM output.
        priority = priority if priority in ('Low', 'Medium', 'High') else 'Low'
        status = status if status in ('Hot', 'Warm', 'Cold') else 'Cold'
        try:
            score_int = max(0, min(100, int(score.get('score') or 0)))
        except (TypeError, ValueError):
            score_int = 0

        # See ``action_generate_ai_summary`` for why we don't flip
        # ``ai_auto_processed`` here.
        self.write({
            'ai_score': score_int,
            'ai_priority': priority,
            'ai_status': status,
            'ai_score_reason': (score.get('reason') or '')[:255],
        })
        self.message_post(body=_(
            'AI scoring: %s / 100 — %s (%s).'
        ) % (score_int, status, priority))
        return self._notify('AI Score updated', 'success')

    def action_open_followup_wizard(self):
        """Button: ``Generate Follow-Up`` → opens the wizard."""
        self.ensure_one()
        self._check_ai_user()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Generate Follow-Up Email'),
            'res_model': 'techmatic.ai.followup.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_lead_id': self.id},
        }

    def action_generate_ai_activities(self):
        """Button: ``Suggest Next Actions``."""
        self.ensure_one()
        self._check_ai_user()
        import json
        service = AIService(self.env)
        try:
            suggestions = service.suggest_activities(self)
        except AIError as e:
            raise UserError(_('Could not suggest activities: %s') % e) from e
        # See ``action_generate_ai_summary`` for why we don't flip
        # ``ai_auto_processed`` here.
        self.write({
            'ai_suggested_actions': json.dumps(suggestions or []),
        })
        return self._notify(
            _('%s suggestion(s) generated.') % len(suggestions or []),
            'success',
        )

    # ------------------------------------------------------------------
    # Cron entry point: AUTO-PROCESS new leads on pipeline entry.
    #
    # Runs ``summarize_lead`` + ``score_lead`` + ``suggest_activities``
    # on every lead where ``ai_auto_processed=False``, then marks the
    # lead as processed so we never re-run. Failures are isolated per
    # lead — one provider hiccup doesn't poison the batch.
    #
    # Note: deliberately does NOT auto-generate follow-up *emails*.
    # That's the higher-risk auto-send feature gated behind the
    # separate Flavor-3 cron below; emails to real customers stay
    # opt-in.
    # ------------------------------------------------------------------
    @api.model
    def _cron_process_pending_ai_leads(self):
        import json as _json
        ICP = self.env['ir.config_parameter'].sudo()
        if ICP.get_param(
                'techmatic_ai_crm.auto_process_enabled', 'True'
        ).lower() != 'true':
            _logger.info('Auto-process disabled in settings — cron skipped.')
            return

        service = AIService(self.env)
        if not service.is_enabled():
            _logger.info(
                'AI service disabled — auto-process cron skipped.'
            )
            return

        try:
            batch = int(ICP.get_param(
                'techmatic_ai_crm.auto_process_batch_size', '20'))
        except (TypeError, ValueError):
            batch = 20
        batch = max(1, min(batch, 100))

        # Oldest pending first — preserves rough FIFO across runs.
        # Use ``won_status='pending'`` (Odoo's canonical open-lead
        # field) rather than probability bounds — many fresh leads have
        # NULL probability when they're sitting in the "New" stage, and
        # NULL fails BOTH ``< 100`` and ``> 0`` in PostgreSQL, which
        # would silently exclude them from the queue.
        pending = self.search([
            ('ai_auto_processed', '=', False),
            ('active', '=', True),
            ('won_status', '=', 'pending'),
        ], order='create_date asc', limit=batch)

        if not pending:
            return

        ok = 0
        for lead in pending:
            try:
                # 0a. Legitimacy / company-shape check (deterministic
                #     heuristics + light LLM). Catches obvious spam.
                legitimacy = service.research_lead_legitimacy(lead)
                # 0b. Live web research — fetch the company's homepage
                #     and have the AI summarize it. Best-effort: silent
                #     skip for free-email providers, soft failure for
                #     unreachable/JS-only sites.
                try:
                    web_result = service.research_company_from_web(lead)
                except AIError:
                    web_result = {
                        'status': 'failed', 'url': None, 'summary': '',
                        'reason': 'AI provider error during web research.',
                    }
                except Exception:  # noqa: BLE001 — boundary; never break the batch
                    _logger.exception(
                        'Web research crashed on lead %s', lead.id,
                    )
                    web_result = {
                        'status': 'failed', 'url': None, 'summary': '',
                        'reason': 'Unexpected error — see server logs.',
                    }
                # 1. Summary
                summary = service.summarize_lead(lead)
                # 2. Score
                score = service.score_lead(lead)
                # 3. Activity suggestions
                try:
                    suggestions = service.suggest_activities(lead)
                except AIError:
                    suggestions = []

                lead.write({
                    'ai_legitimacy_verdict': legitimacy['verdict'],
                    'ai_legitimacy_score': legitimacy['score'],
                    'ai_legitimacy_notes': legitimacy['notes'][:255],
                    'ai_legitimacy_signals': _json.dumps(
                        legitimacy['signals'], indent=2),
                    'ai_legitimacy_checked_at': fields.Datetime.now(),
                    'ai_company_website': web_result.get('url') or False,
                    'ai_company_summary': web_result.get('summary') or False,
                    'ai_company_research_status': web_result.get('status'),
                    'ai_company_research_reason':
                        (web_result.get('reason') or '')[:255] or False,
                    'ai_company_research_date': fields.Datetime.now(),
                    'ai_summary': summary or False,
                    'ai_summary_date': fields.Datetime.now(),
                    'ai_score': max(0, min(100, int(score.get('score') or 0))),
                    'ai_priority': score.get('priority') if score.get('priority') in (
                        'Low', 'Medium', 'High') else 'Low',
                    'ai_status': score.get('status') if score.get('status') in (
                        'Hot', 'Warm', 'Cold') else 'Cold',
                    'ai_score_reason': (score.get('reason') or '')[:255],
                    'ai_suggested_actions': _json.dumps(suggestions or []),
                    'ai_auto_processed': True,
                })
                verdict_emoji = {
                    'trusted': '🟢', 'verified': '🔵',
                    'suspicious': '🟡', 'spam': '🔴',
                }.get(legitimacy['verdict'], '⚪')
                web_status = web_result.get('status')
                web_blurb = {
                    'completed': '🌐 web brief generated',
                    'skipped': '🌐 web research skipped (%s)' % (
                        web_result.get('reason') or '')[:60],
                    'failed': '🌐 web research failed (%s)' % (
                        web_result.get('reason') or '')[:60],
                }.get(web_status, '')
                lead.message_post(body=_(
                    '🤖 <b>AI auto-processed</b>: scored '
                    '<b>%s / 100</b> (%s, %s) — '
                    '%s legitimacy: <b>%s</b> (<i>%s</i>) — %s — '
                    '%s next-action suggestion(s).'
                ) % (
                    lead.ai_score, lead.ai_status, lead.ai_priority,
                    verdict_emoji, legitimacy['verdict'].title(),
                    legitimacy['notes'], web_blurb,
                    len(suggestions or []),
                ))
                ok += 1
            except AIError as e:
                _logger.warning(
                    'Auto-process failed for lead %s (%s): %s — will '
                    'retry on the next run.',
                    lead.id, lead.name, e,
                )
                # Leave ai_auto_processed=False so the next cron tick
                # picks it up again. Bounded retries are implicit via
                # the batch size + cron frequency.
                continue

        _logger.info(
            'AI auto-process: %s / %s leads processed.',
            ok, len(pending),
        )

    # ------------------------------------------------------------------
    # Cron entry point: AI ORCHESTRATOR (the full agent loop).
    #
    # State machine per lead:
    #   not auto_processed              → wait (the auto-process cron
    #                                      will handle it on its tick)
    #   processed + score >= min        → STEP 1: send initial outreach
    #   outreach_initialized            → STEP 2: watch the lead's
    #                                      chatter for new customer
    #                                      messages and respond
    #   exchanges >= max OR handed_off  → STOP — human takes over
    #
    # All three steps share the same audit log
    # (``techmatic.ai.auto.followup.log``) keyed by ``trigger_type``.
    # Every send posts to the lead's chatter so the salesperson can
    # see what the bot did on their behalf.
    # ------------------------------------------------------------------
    @api.model
    def _cron_run_ai_orchestrator(self):
        ICP = self.env['ir.config_parameter'].sudo()
        if ICP.get_param(
                'techmatic_ai_crm.orchestrator_enabled', 'False'
        ).lower() != 'true':
            _logger.info('AI orchestrator disabled — cron skipped.')
            return

        service = AIService(self.env)
        if not service.is_enabled():
            _logger.info('AI service disabled — orchestrator cron skipped.')
            return

        try:
            min_score = int(ICP.get_param(
                'techmatic_ai_crm.orchestrator_min_score', '50'))
            max_exchanges = int(ICP.get_param(
                'techmatic_ai_crm.orchestrator_max_exchanges', '3'))
        except (TypeError, ValueError):
            _logger.warning('Orchestrator: invalid settings — aborting.')
            return
        min_score = max(0, min(min_score, 100))
        max_exchanges = max(1, min(max_exchanges, 10))

        skip_keywords = [
            k.strip().lower() for k in (ICP.get_param(
                'techmatic_ai_crm.orchestrator_skip_keywords', '') or ''
            ).split(',') if k.strip()
        ]

        # ----- STEP 1: leads ready for initial outreach -------------
        # Legitimacy gate built into the domain — never auto-email a
        # lead flagged 'suspicious' or 'spam'. Either the verdict is
        # 'trusted'/'verified', OR it's missing entirely (legacy lead
        # from before the legitimacy field existed — falls back to
        # score-only gating below).
        outreach_candidates = self.search([
            ('active', '=', True),
            ('ai_auto_processed', '=', True),
            ('ai_outreach_initialized', '=', False),
            ('ai_handed_off', '=', False),
            ('ai_score', '>=', min_score),
            ('email_from', '!=', False),
            ('user_id', '!=', False),
            ('probability', '<', 100),
            ('probability', '>', 0),
            '|',
            ('ai_legitimacy_verdict', 'in', ['trusted', 'verified']),
            ('ai_legitimacy_verdict', '=', False),  # legacy leads
        ], order='ai_score desc', limit=20)

        # Hand off any suspicious/spam-flagged lead so it doesn't sit
        # silently — sales needs to know why we skipped it.
        flagged = self.search([
            ('active', '=', True),
            ('ai_auto_processed', '=', True),
            ('ai_outreach_initialized', '=', False),
            ('ai_handed_off', '=', False),
            ('ai_legitimacy_verdict', 'in', ['suspicious', 'spam']),
        ])
        for lead in flagged:
            lead.write({
                'ai_handed_off': True,
                'ai_handoff_reason': (
                    'Legitimacy verdict %s — skipping auto-outreach: %s'
                ) % (lead.ai_legitimacy_verdict, lead.ai_legitimacy_notes or '')[:200],
            })
            lead.message_post(body=_(
                '⚠ <b>AI flagged this lead as %s</b>: %s. '
                'Skipping auto-outreach — %s should review manually.'
            ) % (
                lead.ai_legitimacy_verdict, lead.ai_legitimacy_notes or '—',
                lead.user_id.name or 'a salesperson',
            ), subtype_xmlid='mail.mt_note')

        for lead in outreach_candidates:
            # Only if the lead's owner has opted in.
            if not lead.user_id.techmatic_ai_auto_followup_optin:
                continue
            try:
                self._orchestrator_send_initial(lead, service)
            except Exception:  # noqa: BLE001 — boundary; isolate
                _logger.exception(
                    'Orchestrator: initial outreach failed for lead %s',
                    lead.id,
                )

        # ----- STEP 2: leads with new customer replies --------------
        # Find leads where the most recent message in chatter is an
        # inbound email AFTER our last outbound, AND we haven't yet
        # responded to it.
        candidates_replying = self.search([
            ('active', '=', True),
            ('ai_outreach_initialized', '=', True),
            ('ai_handed_off', '=', False),
            ('email_from', '!=', False),
        ], limit=200)
        for lead in candidates_replying:
            if not lead.user_id or not lead.user_id.techmatic_ai_auto_followup_optin:
                continue
            try:
                self._orchestrator_handle_reply(
                    lead, service, max_exchanges, skip_keywords,
                )
            except Exception:  # noqa: BLE001 — boundary; isolate
                _logger.exception(
                    'Orchestrator: reply step failed for lead %s', lead.id,
                )

    # ------------------------------------------------------------------
    def _orchestrator_send_initial(self, lead, service):
        """STEP 1: draft + send the first outreach email."""
        from markupsafe import escape

        Log = self.env['techmatic.ai.auto.followup.log'].sudo()
        result = service.generate_initial_outreach(lead)

        if not result.get('should_send'):
            # AI declined — don't initialize outreach so we don't try
            # again every cron tick. Hand off to human instead.
            lead.write({
                'ai_handed_off': True,
                'ai_handoff_reason': ('AI declined initial outreach: %s' %
                                      result.get('reason'))[:200],
            })
            lead.message_post(body=_(
                '🤖 AI declined to send initial outreach: %s. '
                'Handing off to %s.'
            ) % (result.get('reason'), lead.user_id.name),
                subtype_xmlid='mail.mt_note',
            )
            return

        subject = result.get('subject') or _('Following up on your interest')
        body = result.get('body_html') or ''
        from_addr = (
            lead.user_id.email_formatted
            or self.env.user.email_formatted
            or False
        )
        success, error = self._orchestrator_send_email(
            lead, subject, body, from_addr,
        )
        Log.create({
            'lead_id': lead.id,
            'user_id': lead.user_id.id,
            'partner_id': lead.partner_id.id or False,
            'email_to': lead.email_from,
            'subject': subject,
            'body_html': body,
            'success': success,
            'error_message': error or False,
            'trigger_type': 'initial_outreach',
            'score_at_send': lead.ai_score,
            'days_inactive_at_send': 0,
        })
        if success:
            lead.write({
                'ai_outreach_initialized': True,
                'ai_outreach_count': lead.ai_outreach_count + 1,
                'ai_last_outbound_at': fields.Datetime.now(),
            })
            lead.message_post(
                body=_(
                    '🤖 <b>AI sent initial outreach</b> (score %s) '
                    '<hr/>%s'
                ) % (lead.ai_score, body),
                subject=subject,
                subtype_xmlid='mail.mt_note',
            )

    def _orchestrator_handle_reply(self, lead, service, max_exchanges,
                                    skip_keywords):
        """STEP 2: detect a new customer reply and respond to it.

        Dedup strategy: we don't filter by ``date > last_outbound_at``
        (sub-second timing collisions in tests + edge cases like
        manual back-dated emails make that brittle). Instead we look
        at the N most-recent inbound messages and exclude any that
        the audit log says we've already responded to.
        """
        Msg = self.env['mail.message'].sudo()
        inbound = Msg.search([
            ('model', '=', 'crm.lead'),
            ('res_id', '=', lead.id),
            ('message_type', '=', 'email'),
        ], order='date desc', limit=10)

        Log = self.env['techmatic.ai.auto.followup.log'].sudo()
        already_replied_ids = set(Log.search([
            ('lead_id', '=', lead.id),
            ('trigger_type', '=', 'inbound_reply'),
            ('success', '=', True),
        ]).mapped(lambda l: l.triggered_by_message_id.id))

        # Filter to (a) customer messages — author is a partner with no
        # internal user link, AND (b) messages we haven't replied to.
        customer_msgs = inbound.filtered(
            lambda m: m.author_id
                      and not m.author_id.user_ids
                      and m.id not in already_replied_ids
        )
        if not customer_msgs:
            return

        # Pick the most recent unanswered customer message.
        msg = customer_msgs[0]

        # Skip keywords — out-of-office, no-reply, etc.
        body_text = (msg.body or '').lower()
        if any(kw in body_text for kw in skip_keywords):
            lead.write({
                'ai_handed_off': True,
                'ai_handoff_reason':
                    'Inbound matched skip keyword — likely autoreply.',
            })
            return

        # Max exchanges? Hand off.
        exchanges = max(lead.ai_outreach_count, lead.ai_inbound_count)
        if exchanges >= max_exchanges:
            lead.write({
                'ai_handed_off': True,
                'ai_handoff_reason': (
                    'Reached max %s exchanges — handing off.'
                ) % max_exchanges,
            })
            lead.message_post(
                body=_(
                    '🤖 AI orchestrator stopped after %s exchanges. '
                    'Handing conversation off to %s.'
                ) % (exchanges, lead.user_id.name),
                subtype_xmlid='mail.mt_note',
            )
            return

        # Ask AI to draft a reply.
        result = service.generate_inbound_reply(lead, msg)
        if not result.get('should_send'):
            lead.write({
                'ai_handed_off': True,
                'ai_handoff_reason': ('AI declined inbound reply: %s' %
                                      result.get('reason'))[:200],
                'ai_inbound_count': lead.ai_inbound_count + 1,
                'ai_last_inbound_at': fields.Datetime.now(),
            })
            lead.message_post(
                body=_(
                    '🤖 AI saw a customer reply but declined to '
                    'auto-respond: %s. Handing off to %s.'
                ) % (result.get('reason'), lead.user_id.name),
                subtype_xmlid='mail.mt_note',
            )
            return

        subject = _('Re: %s') % (lead.name or '')
        body = result.get('body_html') or ''
        from_addr = (
            lead.user_id.email_formatted
            or self.env.user.email_formatted
            or False
        )
        success, error = self._orchestrator_send_email(
            lead, subject, body, from_addr,
        )
        Log.create({
            'lead_id': lead.id,
            'user_id': lead.user_id.id,
            'partner_id': lead.partner_id.id or False,
            'email_to': lead.email_from,
            'subject': subject,
            'body_html': body,
            'success': success,
            'error_message': error or False,
            'trigger_type': 'inbound_reply',
            'triggered_by_message_id': msg.id,
            'score_at_send': lead.ai_score,
            'days_inactive_at_send': 0,
        })
        if success:
            lead.write({
                'ai_outreach_count': lead.ai_outreach_count + 1,
                'ai_inbound_count': lead.ai_inbound_count + 1,
                'ai_last_outbound_at': fields.Datetime.now(),
                'ai_last_inbound_at': msg.date,
            })
            lead.message_post(
                body=_(
                    '🤖 <b>AI replied to customer email</b> '
                    '<hr/>%s'
                ) % body,
                subject=subject,
                subtype_xmlid='mail.mt_note',
            )

    def _orchestrator_send_email(self, lead, subject, body_html, from_addr):
        """Send an email via mail.mail and return (success, error)."""
        try:
            mail = self.env['mail.mail'].sudo().create({
                'subject': subject,
                'body_html': body_html,
                'email_to': lead.email_from,
                'email_from': from_addr,
                'model': 'crm.lead',
                'res_id': lead.id,
                'auto_delete': False,
            })
            mail.send()
            success = mail.state not in ('exception', 'cancel')
            error = mail.failure_reason if not success else False
            return success, error
        except Exception as e:  # noqa: BLE001 — defensive at boundary
            _logger.exception(
                'Orchestrator mail.send failed for lead %s', lead.id,
            )
            return False, str(e)[:255]

    # ------------------------------------------------------------------
    # Cron entry point: AUTO follow-up emails (Flavor 3, high risk).
    #
    # Guardrails (all must pass for a lead to be emailed):
    #   1.  Master switch ``auto_followup_enabled`` is True
    #   2.  Lead's owner has personally opted in via Preferences
    #   3.  Lead's AI score is at or below ``auto_followup_max_score``
    #   4.  Lead has been inactive for at least N days
    #   5.  Lead has no tag in ``auto_followup_skip_tags``
    #   6.  Lead has an outbound ``email_from``
    #   7.  Today's per-user cap hasn't been hit
    #   8.  Lead wasn't auto-emailed at all in the last 14 days (cooldown)
    # ------------------------------------------------------------------
    @api.model
    def _cron_auto_send_followups(self):
        from datetime import timedelta
        import json as _json
        from markupsafe import escape

        ICP = self.env['ir.config_parameter'].sudo()
        if ICP.get_param(
                'techmatic_ai_crm.auto_followup_enabled', 'False'
        ).lower() != 'true':
            _logger.info('Auto follow-up master switch OFF — cron skipped.')
            return

        service = AIService(self.env)
        if not service.is_enabled():
            _logger.info('AI disabled — auto follow-up cron skipped.')
            return

        # ----- Read & validate guardrail knobs ----------------------
        try:
            max_score = int(ICP.get_param(
                'techmatic_ai_crm.auto_followup_max_score', '30'))
            inactive_days = int(ICP.get_param(
                'techmatic_ai_crm.auto_followup_inactive_days', '7'))
            per_user_cap = int(ICP.get_param(
                'techmatic_ai_crm.auto_followup_per_user_cap', '5'))
        except (TypeError, ValueError):
            _logger.warning(
                'Auto follow-up: invalid guardrail values — aborting.'
            )
            return
        # Defensive clamps so a fat-fingered admin can't open the
        # floodgates accidentally.
        max_score = min(max(max_score, 0), 80)
        inactive_days = max(inactive_days, 1)
        per_user_cap = min(max(per_user_cap, 0), 100)
        if per_user_cap == 0:
            _logger.info('Per-user cap is 0 — nothing to send.')
            return

        skip_tag_names = [
            t.strip().lower() for t in (
                ICP.get_param(
                    'techmatic_ai_crm.auto_followup_skip_tags', '') or ''
            ).split(',') if t.strip()
        ]

        now = fields.Datetime.now()
        today = fields.Date.context_today(self)
        cutoff = now - timedelta(days=inactive_days)
        cooldown_cutoff = now - timedelta(days=14)

        # ----- Find candidate leads ---------------------------------
        # Domain only narrows the obvious; Python filters the rest so
        # the rule chain is readable in one place.
        candidates = self.search([
            ('active', '=', True),
            ('probability', '<', 100),
            ('probability', '>', 0),
            ('ai_score', '<=', max_score),
            ('ai_score', '>', 0),  # never auto-email un-scored leads
            ('email_from', '!=', False),
            ('write_date', '<', cutoff),
            ('user_id', '!=', False),
        ], order='ai_score asc, write_date asc')

        Log = self.env['techmatic.ai.auto.followup.log'].sudo()
        sent_per_user = {}     # user_id -> count today
        total_sent = 0
        total_skipped = 0

        for lead in candidates:
            # Per-user cap, computed from the audit log (source of truth).
            uid = lead.user_id.id
            if uid not in sent_per_user:
                sent_per_user[uid] = Log.search_count([
                    ('user_id', '=', uid),
                    ('sent_at', '>=',
                     fields.Datetime.to_datetime(today)),
                    ('success', '=', True),
                ])
            if sent_per_user[uid] >= per_user_cap:
                total_skipped += 1
                continue

            # User opt-in.
            if not lead.user_id.techmatic_ai_auto_followup_optin:
                total_skipped += 1
                continue

            # Skip tags.
            lead_tag_names = {
                (t.name or '').lower() for t in lead.tag_ids
            }
            if lead_tag_names.intersection(skip_tag_names):
                total_skipped += 1
                continue

            # Cooldown — never auto-email the same lead twice in 14 days.
            recent_send = Log.search_count([
                ('lead_id', '=', lead.id),
                ('sent_at', '>=', cooldown_cutoff),
                ('success', '=', True),
            ])
            if recent_send:
                total_skipped += 1
                continue

            # ----- All guardrails passed — generate & send ----------
            try:
                body_text = service.generate_followup_email(
                    lead,
                    instructions=(
                        'This is an AUTOMATED follow-up — keep it short, '
                        'friendly, and end with one specific question or '
                        'CTA. Do not promise anything specific. Do not '
                        'reference internal CRM data or AI scoring.'
                    ),
                )
            except AIError as e:
                _logger.warning('Auto-followup AI failed for lead %s: %s',
                                lead.id, e)
                Log.create({
                    'lead_id': lead.id,
                    'user_id': uid,
                    'partner_id': lead.partner_id.id or False,
                    'email_to': lead.email_from or '',
                    'subject': _('Following up'),
                    'success': False,
                    'error_message': ('AI: %s' % e)[:255],
                    'score_at_send': lead.ai_score,
                    'days_inactive_at_send':
                        (now - lead.write_date).days if lead.write_date else 0,
                })
                continue

            html_body = '<br/>'.join(
                escape(line) for line in (body_text or '').splitlines()
            )
            subject = _('Following up on %s') % (lead.name or _('our last chat'))

            from_addr = (
                lead.user_id.email_formatted or
                self.env.user.email_formatted or False
            )

            try:
                mail = self.env['mail.mail'].sudo().create({
                    'subject': subject,
                    'body_html': html_body,
                    'email_to': lead.email_from,
                    'email_from': from_addr,
                    'model': 'crm.lead',
                    'res_id': lead.id,
                    'auto_delete': False,
                })
                mail.send()
                # Success criterion: the send call returned cleanly AND
                # ``mail.state`` isn't a hard-fail state. In production
                # without SMTP issues this resolves to ``'sent'``; in
                # tests it may remain ``'outgoing'`` (queued in the
                # mail.mail retry pool), which we still count as a
                # successful dispatch from the cron's perspective.
                success = mail.state not in ('exception', 'cancel')
                error = mail.failure_reason if not success else False
            except Exception as e:  # noqa: BLE001 — defensive at the boundary
                success = False
                error = str(e)[:255]
                _logger.exception('Auto-followup send failed for lead %s', lead.id)

            Log.create({
                'lead_id': lead.id,
                'user_id': uid,
                'partner_id': lead.partner_id.id or False,
                'email_to': lead.email_from or '',
                'subject': subject,
                'body_html': html_body,
                'success': success,
                'error_message': error or False,
                'score_at_send': lead.ai_score,
                'days_inactive_at_send':
                    (now - lead.write_date).days if lead.write_date else 0,
            })

            # Visibility: post to the lead's chatter so the owner can see
            # what their bot said.
            lead.message_post(
                body=_(
                    '🤖 <b>Auto follow-up sent</b><br/>'
                    'AI Score: %s · Inactive %s days · To: %s'
                    '<hr/>%s'
                ) % (
                    lead.ai_score,
                    (now - lead.write_date).days if lead.write_date else 0,
                    lead.email_from, html_body,
                ),
                subject=subject,
                subtype_xmlid='mail.mt_note',
            )

            if success:
                sent_per_user[uid] += 1
                total_sent += 1
            else:
                total_skipped += 1

        _logger.info(
            'Auto follow-up cron: %s sent, %s skipped across %s candidates.',
            total_sent, total_skipped, len(candidates),
        )

    # ------------------------------------------------------------------
    # Cron entry point: nightly batch scoring for active leads.
    # ------------------------------------------------------------------
    @api.model
    def _cron_score_active_leads(self, limit=50):
        """Score the N most-recently-updated open leads in one batch.

        Designed to be idempotent and bounded — skips leads scored in
        the last 12 hours so we don't burn the API budget.
        """
        from datetime import timedelta
        cutoff = fields.Datetime.now() - timedelta(hours=12)
        leads = self.search([
            ('active', '=', True),
            ('probability', '<', 100),
            ('probability', '>', 0),
            '|',
            ('ai_score', '=', 0),
            ('write_date', '<', cutoff),
        ], order='write_date desc', limit=limit)
        service = AIService(self.env)
        successes = 0
        for lead in leads:
            try:
                score = service.score_lead(lead)
                lead.write({
                    'ai_score': max(0, min(100, int(score.get('score') or 0))),
                    'ai_priority': score.get('priority') if score.get('priority') in (
                        'Low', 'Medium', 'High') else 'Low',
                    'ai_status': score.get('status') if score.get('status') in (
                        'Hot', 'Warm', 'Cold') else 'Cold',
                    'ai_score_reason': (score.get('reason') or '')[:255],
                })
                successes += 1
            except AIError as e:
                _logger.warning('AI cron skip lead %s: %s', lead.id, e)
                # Don't break the loop — one lead's failure shouldn't
                # poison the batch.
                continue
        _logger.info('AI cron scored %s of %s leads.', successes, len(leads))

    # ------------------------------------------------------------------
    # Helpers.
    # ------------------------------------------------------------------
    def _check_ai_user(self):
        if not self.env.user.has_group(
                'techmatic_ai_crm.group_techmatic_ai_crm_user'):
            raise UserError(_(
                'You do not have permission to use AI features. '
                'Contact your administrator.'
            ))

    def _notify(self, message, kind='success'):
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('AI Assistant'),
                'message': message,
                'type': kind,
                'sticky': False,
            },
        }
