import logging

from odoo import models, fields, api
import requests

_logger = logging.getLogger(__name__)


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    aajjo_api_url = fields.Char(string='AAJJO API URL', config_parameter='aajjo.base_url', default='https://api.aajjo.com/api/cl/getleads')
    aajjo_username = fields.Char(string='AAJJO Username', config_parameter='aajjo.username')
    aajjo_api_key = fields.Char(string='AAJJO API Key', config_parameter='aajjo.api_key')
    enable_aajjo_sync = fields.Boolean(string='Enable AAJJO Sync', config_parameter='aajjo.enable_integration')
    last_sync_datetime = fields.Datetime(string='Last Sync Datetime', config_parameter='aajjo.last_sync', readonly=True)

    def init(self):
        """Ensure the AAJJO settings view is active on every module load.

        A previous init() in crm_lead_automation_engine may have
        deactivated it. This guarantees it comes back on upgrade.
        """
        try:
            self.env.cr.execute("""
                UPDATE ir_ui_view SET active = TRUE
                WHERE key = 'crm_aajjo_integration.res_config_settings_view_form'
                  AND active = FALSE
            """)
            if self.env.cr.rowcount:
                _logger.info("[AAJJO] Reactivated AAJJO settings view.")
        except Exception as e:
            _logger.warning("[AAJJO] Could not reactivate settings view: %s", e)

    def action_verify_connection(self):
        self.ensure_one()
        if not self.aajjo_api_url or not self.aajjo_api_key or not self.aajjo_username:
             return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'Missing Configuration',
                    'message': 'Please enter API URL, Username, and API Key.',
                    'type': 'warning',
                    'sticky': False,
                }
            }
        
        url = self.aajjo_api_url.rstrip('/')
        headers = {'Authorization': f'Basic {self.aajjo_username}:{self.aajjo_api_key}'}
        params = {
            'StartDate': '2023-01-01 00:00:00',
            'EndDate': '2023-01-01 23:59:59'
        }
        
        try:
            # Short timeout for verification
            response = requests.get(url, headers=headers, params=params, timeout=5)
            response.raise_for_status()
            
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'Connection Successful',
                    'message': 'Successfully connected to AAJJO API.',
                    'type': 'success',
                    'sticky': False,
                }
            }
        except Exception as e:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'Connection Failed',
                    'message': f"Could not connect: {str(e)}",
                    'type': 'danger',
                    'sticky': True,
                }
            }


    def action_sync_now(self):
        self.env['crm.lead'].fetch_aajjo_leads_cron()
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Sync Started',
                'message': 'Lead synchronization triggered in background.',
                'type': 'success',
                'sticky': False,
            }
        }
