"""Stubs for Enterprise-only fields/methods that the standard mrp.bom form
view (id=2028) still references after the Enterprise mrp_workorder addon
was removed. Without these stubs, view validation fails with
"action_copy_existing_operations is not a valid action on mrp.bom".
"""

from odoo import fields, models


class MrpBom(models.Model):
    _inherit = 'mrp.bom'

    # Field referenced as `invisible="not show_copy_operations_button"` on
    # the "Copy Existing Operations" button. Always False so the button
    # stays hidden in the standard view.
    show_copy_operations_button = fields.Boolean(
        string='Show Copy Operations Button',
        compute='_compute_show_copy_operations_button',
    )

    def _compute_show_copy_operations_button(self):
        for bom in self:
            bom.show_copy_operations_button = False

    def action_copy_existing_operations(self):
        """No-op stub. The button calling this is hidden via the
        `show_copy_operations_button` field above; this method exists so
        view validation passes."""
        return False
