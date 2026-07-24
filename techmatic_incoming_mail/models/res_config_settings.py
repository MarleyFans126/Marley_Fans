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
        string='Internal Recipients',
        config_parameter='techmatic_incoming_mail.ops_email',
        help='Fixed mailboxes that receive a copy of every incoming customer '
             'email, on top of the lead\'s assigned salesperson. Separate '
             'several with commas, e.g. '
             'operations@marleyfans.in, sales@marleyfans.in',
    )
    tim_rescan_enabled = fields.Boolean(
        string='Read-Independent Fetch',
        config_parameter='techmatic_incoming_mail.rescan_enabled',
        help='Fetch recent mail regardless of read state, so a message read in '
             'the webmail inbox before Odoo fetches is still imported. Odoo '
             'skips any message it has already imported, so nothing is duplicated.',
    )
    tim_rescan_days = fields.Integer(
        string='Look-back (days)',
        config_parameter='techmatic_incoming_mail.rescan_days',
        help='How many days back the read-independent fetch scans on each run '
             '(1–30). Only genuinely new mail is downloaded; already-imported '
             'mail costs a tiny header check. Default 3.',
    )
