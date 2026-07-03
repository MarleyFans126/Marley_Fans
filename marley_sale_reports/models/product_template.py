from odoo import models, fields


class ProductTemplate(models.Model):
    _inherit = 'product.template'

    warranty_terms = fields.Text(
        string='Warranty Terms',
        help='Warranty text printed on quotations and proforma invoices that contain this product. '
             'Blank by default — only prints when you fill it in.',
    )
    marley_weight = fields.Float(
        string='Weight (kg)',
        digits=(12, 3),
        help='Per-unit weight in kilograms, printed on installation and sale reports.',
    )
