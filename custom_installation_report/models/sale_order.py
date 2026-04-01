from odoo import models, fields, api


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    # ---- Installation Details ----
    x_scheduled_installation_date = fields.Date(string="Scheduled Installation Date")
    x_site_contact_person = fields.Char(string="Site Contact Person")
    x_site_contact_number = fields.Char(string="Site Contact Number")

    # ---- Transport / Model Terms ----
    x_models_to_transport = fields.Char(string="Models to Transport")
    x_transportation_terms = fields.Selection([
        ('paid', 'Paid'),
        ('to_pay', 'To Pay'),
        ('foc', 'FOC'),
    ], string="Transportation Terms", default='paid')
    x_amount_in_words = fields.Char(string="Amount in Words", compute='_compute_amount_in_words', store=True)

    # ---- Site Specifications ----
    x_ext_rod_length = fields.Char(string="Ext Rod Length")
    x_field_height = fields.Char(string="Field Height")
    x_required_electrical_wire = fields.Char(string="Required Electrical Wire")
    x_mounting_structure = fields.Char(string="Mounting Structure")
    x_crane_rafter_distance = fields.Char(string="Distance Between Crane Top and Rafter Bottom")
    x_other_important_info = fields.Text(string="Other Important Information")

    # ---- Totals ----
    x_total_box_qty = fields.Float(string="Total Box Qty", compute='_compute_box_totals', store=True)
    x_total_weight = fields.Float(string="Total Weight (kg)", compute='_compute_box_totals', store=True)
    x_product_total_qty = fields.Float(string="Product Total Qty", compute='_compute_box_totals', store=True)

    @api.depends('order_line.x_box_qty', 'order_line.x_weight_per_unit')
    def _compute_box_totals(self):
        for order in self:
            total_box = sum(order.order_line.mapped('x_box_qty'))
            total_weight = sum(
                line.x_box_qty * line.x_weight_per_unit
                for line in order.order_line
            )
            total_product = sum(order.order_line.mapped('x_box_qty'))
            order.x_total_box_qty = total_box
            order.x_total_weight = total_weight
            order.x_product_total_qty = total_product

    @api.depends('amount_total')
    def _compute_amount_in_words(self):
        for order in self:
            order.x_amount_in_words = order.currency_id.amount_to_text(order.amount_total) if order.currency_id else ''


class SaleOrderLine(models.Model):
    _inherit = 'sale.order.line'

    x_box_dimension = fields.Char(string="Box Dimension")
    x_box_qty = fields.Float(string="Box Qty", default=0.0)
    x_weight_per_unit = fields.Float(string="Weight/Unit (kg)", default=0.0)
