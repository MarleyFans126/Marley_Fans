from odoo import models

class SaleOrder(models.Model):
    _inherit = 'sale.order'
    
    # Placeholder if we need specific fields or logic on SO creation via the button
    # The requirement: "Convert to Customer -> Create Sales Order -> Create Project" on Won.
    # This logic is in CRM Lead.
    pass
