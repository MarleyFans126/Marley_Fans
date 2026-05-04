from odoo import api, fields, models


class PurchaseOrder(models.Model):
    _inherit = 'purchase.order'

    # ── Financial Year label (Indian FY: April 1 → March 31) ────
    financial_year_label = fields.Char(
        string='Financial Year',
        compute='_compute_financial_year_label',
        store=True,
        help='Indian financial year derived from the order date, e.g. 2026-2027.',
    )

    @api.depends('date_order')
    def _compute_financial_year_label(self):
        for order in self:
            d = order.date_order
            if not d:
                order.financial_year_label = ''
                continue
            start = d.year if d.month >= 4 else d.year - 1
            order.financial_year_label = '%d-%d' % (start, start + 1)
