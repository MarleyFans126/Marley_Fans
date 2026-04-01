from odoo import models, fields, api


class AccountPayment(models.Model):
    _inherit = 'account.payment'

    proforma_invoice_id = fields.Many2one(
        'account.move',
        string='Proforma Invoice',
        domain="[('move_type', '=', 'out_invoice'), ('partner_id', '=', partner_id)]",
        help='Link this cash receipt to a proforma invoice.',
    )
    receipt_reference = fields.Char(
        string='Receipt Reference',
        help='Internal receipt reference number',
    )
