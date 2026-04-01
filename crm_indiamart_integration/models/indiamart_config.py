from odoo import models, fields, api, _
import logging

_logger = logging.getLogger(__name__)


class IndiaMARTConfig(models.Model):
    _name = 'indiamart.config'
    _description = 'IndiaMART Configuration'

    api_key = fields.Char(string='API Key (glusr_crm_key)')
    api_base_url = fields.Char(
        string='API Base URL',
        default='https://mapi.indiamart.com/wservce/crm/crmListing/v2/',
    )
    is_mock_server = fields.Boolean(string='Use Mock Server', default=False)
    last_sync_datetime = fields.Datetime(string='Last Sync Datetime')
    last_start_time = fields.Datetime(string='Last API Start Time')
    last_end_time = fields.Datetime(string='Last API End Time')
    is_active = fields.Boolean(string='Active', default=True)

    # ── Historical backfill tracking ──
    key_generated_date = fields.Datetime(
        string='Key Generated Date',
        help='Date when the IndiaMART API key was generated. '
             'Historical leads are only available 24 hours after key generation.',
    )
    historical_sync_done = fields.Boolean(
        string='Historical Sync Done',
        default=False,
        help='True once the 365-day historical backfill has completed.',
    )
    historical_sync_cursor = fields.Datetime(
        string='Historical Sync Cursor',
        help='Tracks current position in the historical backfill. '
             'Each cron run advances this by 7 days.',
    )

    def _log_api_error(self, url, status, text):
        self.env['indiamart.log'].sudo().create({
            'name': 'API Error',
            'request_url': url,
            'status_code': status,
            'error_message': text[:1000],
        })

    def _log_error(self, message, op_type):
        self.env['indiamart.log'].sudo().create({
            'name': 'Configuration Error',
            'error_message': message,
            'status_code': 400,
        })
