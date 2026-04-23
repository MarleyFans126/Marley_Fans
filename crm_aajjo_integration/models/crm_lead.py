from odoo import models, fields, api, _
from odoo.exceptions import ValidationError
import requests
import json
import logging

_logger = logging.getLogger(__name__)

class CrmLead(models.Model):
    _inherit = 'crm.lead'

    def init(self):
        """Migrate existing AAJJO leads to opportunities in the New stage.

        Covers historical data where the ``is_aajjo`` flag may not have been
        set: anything with ``aajjo_lead_id`` populated or
        ``lead_source_type = 'aajjo'`` is treated as an AAJJO record.
        """
        try:
            new_stage = self.env.ref('crm.stage_lead1', raise_if_not_found=False)
            stage_id = new_stage.id if new_stage else None
            where = """
                (is_aajjo = TRUE
                 OR aajjo_lead_id IS NOT NULL
                 OR lead_source_type = 'aajjo')
                AND type <> 'opportunity'
            """
            if stage_id:
                self.env.cr.execute(
                    f"""
                    UPDATE crm_lead
                    SET type = 'opportunity',
                        stage_id = COALESCE(stage_id, %s),
                        is_aajjo = TRUE
                    WHERE {where}
                    """,
                    (stage_id,),
                )
            else:
                self.env.cr.execute(
                    f"""
                    UPDATE crm_lead
                    SET type = 'opportunity',
                        is_aajjo = TRUE
                    WHERE {where}
                    """
                )
            if self.env.cr.rowcount:
                _logger.info(
                    "[INIT] Converted %d existing AAJJO leads to opportunities.",
                    self.env.cr.rowcount,
                )
            # Move records assigned to OdooBot (id=1) onto a real admin user so
            # they show up under the current user's "My Pipeline".
            admin = self.env.ref('base.user_admin', raise_if_not_found=False)
            if admin and admin.id != 1:
                self.env.cr.execute(
                    """
                    UPDATE crm_lead
                    SET user_id = %s
                    WHERE is_aajjo = TRUE
                      AND type = 'opportunity'
                      AND user_id = 1
                    """,
                    (admin.id,),
                )
                if self.env.cr.rowcount:
                    _logger.info(
                        "[INIT] Reassigned %d AAJJO opportunities from OdooBot to admin.",
                        self.env.cr.rowcount,
                    )
        except Exception as e:
            _logger.warning("[INIT] AAJJO lead→opportunity migration failed: %s", e)

    # -------------------------------------------------------------------------
    # AAJJO INTEGRATION FIELDS
    # -------------------------------------------------------------------------
    # Fields are inherited from crm_lead_automation_engine
    
    # -------------------------------------------------------------------------
    # AAJJO DATA FETCHING METHODS
    # -------------------------------------------------------------------------

    @api.model
    def action_fetch_aajjo_leads(self):
        """ Manually trigger the AAJJO lead sync """
        self.fetch_aajjo_leads_cron()
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Sync Started',
                'message': 'Lead synchronization triggered successfully. Please check logs for details.',
                'type': 'success',
                'sticky': False,
            }
        }

    @api.model
    def fetch_aajjo_leads_cron(self):
        # Configuration
        config = self.env['ir.config_parameter'].sudo()
        base_url = config.get_param('aajjo.base_url', 'https://api.aajjo.com/api/cl/getleads')
        api_username = config.get_param('aajjo.username')
        api_key = config.get_param('aajjo.api_key')
        last_sync = config.get_param('aajjo.last_sync')
        
        if not base_url or not api_key or not api_username:
            return

        url = base_url.rstrip('/')
        headers = {'Authorization': f'Basic {api_username}:{api_key}'}
        
        from datetime import datetime, timedelta
        if last_sync:
            start_dt = str(last_sync)
        else:
            start_dt = (datetime.now() - timedelta(days=7)).strftime('%Y-%m-%d %H:%M:%S')
            
        end_dt = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

        params = {
            'StartDate': start_dt,
            'EndDate': end_dt
        }

        success = False
        try:
            response = requests.get(url, headers=headers, params=params, timeout=15)
            self.env['aajjo.api.log'].create({
                'name': url,
                'request_type': 'GET',
                'request_payload': json.dumps(params),
                'response_payload': response.text[:5000],
                'status_code': response.status_code
            })

            if response.status_code == 200:
                data = response.json()
                _logger.info(f"AAJJO API response data: {str(data)[:500]}")
                leads = data.get('Records', [])
                _logger.info(f"Found {len(leads)} leads to process")
                
                for lead_data in leads:
                    self._process_aajjo_lead(lead_data)
                
                success = True
            else:
                _logger.error(f"AAJJO API error: {response.status_code} - {response.text}")
            
            if success:
                config.set_param('aajjo.last_sync', end_dt)

        except Exception as e:
            _logger.error(f"AAJJO Sync Error: {e}")
            self.env['aajjo.api.log'].create({
                'name': url,
                'request_type': 'GET',
                'error_message': str(e)
            })

    def _process_aajjo_lead(self, data):
        _logger.info(f"Processing AAJJO lead data: {data}")
        mobile = data.get('PhoneNumber', '')
        email = data.get('EmailID', '')
        contact_name = data.get('ContactPerson', '')
        product = data.get('Product', '')
        lead_details = data.get('LeadDetails', '')
        city = data.get('City', '')
        created_date = data.get('CreatedDate', '')
        
        if not mobile and not email:
            _logger.warning("AAJJO lead missing phone and email. Skipping.")
            return False
            
        # Prioritize true LeadID if it exists, otherwise use a composite hash to prevent duplicates
        external_id = data.get('LeadID')
        if not external_id:
            id_string = f"{mobile}-{email}-{product}-{created_date}"
            import hashlib
            external_id = hashlib.md5(id_string.encode('utf-8')).hexdigest()
        else:
            external_id = str(external_id)
        
        # Check against universal external_lead_id field
        existing = self.search([('external_lead_id', '=', external_id)], limit=1)
        if existing:
            _logger.info(f"AAJJO lead {external_id} already exists (ID: {existing.id}). Skipping.")
            return existing

        lead_name = product
        if not lead_name:
            lead_name = f"AAJJO Inquiry - {contact_name or mobile}"
        
        # Land AAJJO records directly in the "New" opportunity stage
        new_stage = self.env.ref('crm.stage_lead1', raise_if_not_found=False)
        if not new_stage:
            new_stage = self.env['crm.stage'].sudo().search(
                [], order='sequence, id', limit=1,
            )

        vals = {
            'name': lead_name,
            'contact_name': contact_name,
            'phone': mobile,
            'email_from': email,
            'aajjo_lead_id': external_id,
            'external_lead_id': external_id,
            'is_aajjo': True,
            'description': lead_details,
            'city': city,
            'type': 'opportunity',
        }
        if new_stage:
            vals['stage_id'] = new_stage.id

        default_team = self.env['crm.team'].search([], limit=1)
        if default_team:
            vals['team_id'] = default_team.id
        
        try:
            lead = self.with_context(aajjo_import=True).create(vals)
            _logger.info(f"Created AAJJO lead {lead.id} for external ID {external_id}")
            return lead
        except Exception as e:
            _logger.error(f"Failed to create AAJJO lead for external ID {external_id}: {e}")
            return False
