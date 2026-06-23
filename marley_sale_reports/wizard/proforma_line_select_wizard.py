# -*- coding: utf-8 -*-
from odoo import models, fields


class ProformaLineSelectWizard(models.TransientModel):
    _name = 'proforma.line.select.wizard'
    _description = 'Select Order Lines to Print on Proforma'

    order_id = fields.Many2one(
        'sale.order', string='Order', required=True, ondelete='cascade')
    line_ids = fields.Many2many(
        'sale.order.line',
        string='Products on Proforma',
        domain="[('order_id', '=', order_id), ('display_type', '=', False)]",
        help='Ticked products appear on the Proforma Invoice PDF.',
    )

    def action_apply(self):
        """Write the print_on_proforma flag onto the order's product lines."""
        self.ensure_one()
        product_lines = self.order_id.order_line.filtered(
            lambda l: not l.display_type)
        selected = self.line_ids
        for line in product_lines:
            line.print_on_proforma = line in selected
        return {'type': 'ir.actions.act_window_close'}
