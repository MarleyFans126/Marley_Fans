# -*- coding: utf-8 -*-
from odoo import models, fields


class SaleOrderLine(models.Model):
    _inherit = 'sale.order.line'

    print_on_proforma = fields.Boolean(
        string='Print on Proforma',
        default=True,
        help="If unchecked, this line is hidden from the Proforma Invoice PDF "
             "and excluded from the proforma totals. The order still keeps "
             "the line. Set via the 'Select Proforma Products' button.",
    )
