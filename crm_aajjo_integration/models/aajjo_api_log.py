from odoo import models, fields, api

class AajjoApiLog(models.Model):
    _name = 'aajjo.api.log'
    _description = 'AAJJO API Log'
    _order = 'create_date desc'

    name = fields.Char(string='Endpoint', required=True)
    request_type = fields.Selection([
        ('GET', 'GET'),
        ('POST', 'POST'),
        ('PUT', 'PUT'),
        ('PATCH', 'PATCH'),
        ('DELETE', 'DELETE')
    ], string='Request Type', required=True)
    request_payload = fields.Text(string='Request Payload')
    response_payload = fields.Text(string='Response Payload')
    status_code = fields.Integer(string='Status Code')
    error_message = fields.Text(string='Error')
    log_date = fields.Datetime(string='Log Date', default=fields.Datetime.now)
