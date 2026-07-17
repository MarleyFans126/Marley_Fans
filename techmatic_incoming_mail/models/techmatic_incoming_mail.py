from odoo import api, fields, models


class TechmaticIncomingMail(models.Model):
    _name = 'techmatic.incoming.mail'
    _description = 'Incoming Mail (Customer Email)'
    _order = 'date_received desc, id desc'
    _rec_name = 'subject'

    lead_id = fields.Many2one(
        'crm.lead', string='Lead / Opportunity',
        ondelete='cascade', index=True, required=True,
    )
    lead_name = fields.Char(
        string='Lead Name', related='lead_id.name', store=True)
    partner_id = fields.Many2one('res.partner', string='From Contact')
    sender_name = fields.Char(string='Sender Name')
    email_from = fields.Char(string='Sender Email', index=True)
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
    message_id = fields.Char(
        string='Message-ID', index=True,
        help="RFC Message-ID of the original email, when the sender supplied one.")
    processing_status = fields.Selection(
        [('matched', 'Matched Lead'),
         ('created', 'New Lead Created')],
        string='Processing Status', index=True, default='matched',
        help="Whether this email landed on an existing lead or caused a new one "
             "to be created.")
    attachment_ids = fields.Many2many(
        'ir.attachment', 'techmatic_incoming_mail_attachment_rel',
        'mail_id', 'attachment_id', string='Attachments')
    attachment_count = fields.Integer(
        string='Attachments', compute='_compute_attachment_count')
    forwarded_to = fields.Char(
        string='Forwarded To',
        help="Internal recipients this email was forwarded to. Empty means it "
             "was not forwarded (forwarding disabled, or no valid recipient).")

    @api.depends('attachment_ids')
    def _compute_attachment_count(self):
        for record in self:
            record.attachment_count = len(record.attachment_ids)

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
