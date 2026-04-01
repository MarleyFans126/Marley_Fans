from odoo import models, fields


class CrmEmailLog(models.Model):
    _name = 'crm.email.log'
    _description = 'CRM Email Log'
    _order = 'sent_date desc, id desc'
    _rec_name = 'lead_name'

    lead_id = fields.Many2one(
        'crm.lead', string='Lead / Opportunity',
        ondelete='set null', index=True,
    )
    lead_name = fields.Char(string='Lead Name')
    partner_name = fields.Char(string='Contact Name')
    email_to = fields.Char(string='Email To')
    template_used = fields.Char(string='Email Template')
    status = fields.Selection([
        ('queued', 'Queued'),
        ('sent', 'Sent'),
        ('failed', 'Failed'),
    ], string='Status', default='queued', required=True, index=True)
    sent_date = fields.Datetime(string='Sent Date', default=fields.Datetime.now)
    error_message = fields.Text(string='Error Message')
