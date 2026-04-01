from odoo import models, fields, api


class IndiaMARTLog(models.Model):
    _name = 'indiamart.log'
    _description = 'IndiaMART API Log'
    _order = 'create_date desc'

    name = fields.Char(string='Endpoint', default='Fetch Leads')
    request_type = fields.Selection([
        ('GET', 'GET'),
        ('POST', 'POST'),
    ], string='Request Type', default='GET')
    request_url = fields.Char(string='URL')
    request_payload = fields.Text(string='Request Payload')
    response_payload = fields.Text(string='Response Payload')
    status_code = fields.Integer(string='Status Code')
    error_message = fields.Text(string='Error')

    # Stats
    leads_fetched = fields.Integer(string='Leads Fetched', default=0)
    leads_created = fields.Integer(string='Leads Created', default=0)
    leads_skipped_dup = fields.Integer(string='Skipped (Duplicate)', default=0)
    leads_skipped_invalid = fields.Integer(string='Skipped (Invalid)', default=0)

    # Time window sent to API (IST strings for easy debugging)
    api_start_time = fields.Char(string='API Start Time (IST)')
    api_end_time = fields.Char(string='API End Time (IST)')

    # Sync mode
    sync_mode = fields.Selection([
        ('historical', 'Historical Backfill'),
        ('normal', 'Normal Sync'),
        ('manual', 'Manual Fetch'),
    ], string='Sync Mode')
