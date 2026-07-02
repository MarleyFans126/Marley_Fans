from odoo import api, fields, models


class TechmaticIncomingMail(models.Model):
    _name = 'techmatic.incoming.mail'
    _description = 'Incoming Mail (Customer Reply)'
    _order = 'date_received desc, id desc'
    _rec_name = 'subject'

    lead_id = fields.Many2one(
        'crm.lead', string='Lead / Opportunity',
        ondelete='cascade', index=True, required=True,
    )
    partner_id = fields.Many2one('res.partner', string='From Contact')
    email_from = fields.Char(string='From Email', index=True)
    subject = fields.Char(string='Subject')
    body = fields.Html(string='Message', sanitize=True, sanitize_style=True)
    date_received = fields.Datetime(
        string='Received On', default=fields.Datetime.now, index=True)
    is_read = fields.Boolean(string='Read', default=False, index=True)
    # Salesperson who owns the lead — for filtering "my replies" and alerts.
    user_id = fields.Many2one(
        'res.users', string='Salesperson',
        related='lead_id.user_id', store=True, index=True)
    company_name = fields.Char(
        string='Company', related='lead_id.partner_id.commercial_partner_id.name',
        store=True)
    stage_id = fields.Many2one(
        'crm.stage', string='Lead Stage', related='lead_id.stage_id', store=True)
    mail_message_id = fields.Many2one(
        'mail.message', string='Source Message', ondelete='cascade', index=True)

    def action_mark_read(self):
        self.write({'is_read': True})

    def action_mark_unread(self):
        self.write({'is_read': False})

    def action_open_lead(self):
        """Open the related lead and mark the reply read."""
        self.ensure_one()
        self.is_read = True
        return {
            'type': 'ir.actions.act_window',
            'name': self.lead_id.name or 'Lead',
            'res_model': 'crm.lead',
            'res_id': self.lead_id.id,
            'view_mode': 'form',
            'target': 'current',
        }
