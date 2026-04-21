from odoo import models, fields


class ProductTemplate(models.Model):
    _inherit = 'product.template'

    warranty_terms = fields.Text(
        string='Warranty Terms',
        help='Warranty text printed on quotations and proforma invoices that contain this product.',
        default='5 Years warranty on Mechanical items & 1 year OEM warranty on Motors & VFD Drive',
    )
