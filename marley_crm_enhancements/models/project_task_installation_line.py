from odoo import models, fields, api


class ProjectTaskInstallationLine(models.Model):
    _name = 'project.task.installation.line'
    _description = 'Installation Task Product Line'
    _order = 'sequence, id'

    task_id = fields.Many2one(
        'project.task',
        string='Task',
        required=True,
        ondelete='cascade',
        index=True,
    )
    sequence = fields.Integer(default=10)
    product_id = fields.Many2one(
        'product.product',
        string='Product',
        ondelete='restrict',
    )
    name = fields.Char(string='Description')
    quantity = fields.Float(string='Quantity', default=1.0, digits='Product Unit of Measure')
    uom_id = fields.Many2one('uom.uom', string='Unit')
    weight = fields.Float(
        string='Weight (kg)',
        digits=(12, 3),
        help='Per-line total weight in kilograms. Defaults from the product when selected.',
    )
    unit_price = fields.Float(string='Unit Price', digits='Product Price')
    price_subtotal = fields.Float(
        string='Total Price',
        compute='_compute_price_subtotal',
        store=True,
        digits='Product Price',
    )
    currency_id = fields.Many2one(
        related='task_id.company_id.currency_id',
        store=False,
    )

    @api.depends('quantity', 'unit_price')
    def _compute_price_subtotal(self):
        for line in self:
            line.price_subtotal = (line.quantity or 0.0) * (line.unit_price or 0.0)

    @api.onchange('product_id')
    def _onchange_product_id(self):
        if not self.product_id:
            return
        self.name = self.product_id.name
        self.unit_price = self.product_id.list_price or 0.0
        # Prefer the custom Marley weight, else standard Odoo weight
        self.weight = (
            (getattr(self.product_id, 'marley_weight', 0.0) or 0.0)
            or (self.product_id.weight or 0.0)
        ) * (self.quantity or 1.0)
        if hasattr(self.product_id, 'uom_id'):
            self.uom_id = self.product_id.uom_id

    @api.onchange('product_id', 'quantity')
    def _onchange_weight(self):
        # Re-scale weight when quantity changes if product has a weight
        if self.product_id:
            per_unit = (
                (getattr(self.product_id, 'marley_weight', 0.0) or 0.0)
                or (self.product_id.weight or 0.0)
            )
            if per_unit:
                self.weight = per_unit * (self.quantity or 0.0)
