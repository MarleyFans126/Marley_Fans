from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    tim_forward_enabled = fields.Boolean(
        string='Forward Incoming Customer Emails',
        config_parameter='techmatic_incoming_mail.forward_enabled',
        help='When a customer emails a lead, forward a copy to the operations '
             'mailbox and to the assigned (and secondary) salesperson.',
    )
    tim_ops_email = fields.Char(
        string='Operations Mailbox',
        config_parameter='techmatic_incoming_mail.ops_email',
        help='Fixed address that receives a copy of every incoming customer '
             'email (e.g. operations@marleyfans.in).',
    )
