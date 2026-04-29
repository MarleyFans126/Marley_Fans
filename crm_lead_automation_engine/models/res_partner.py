from odoo import models, fields


class ResPartner(models.Model):
    _inherit = 'res.partner'

    business_area = fields.Char(
        string='Business Area',
        help='Locality / area in which this contact operates. '
             'Auto-fetched into the CRM lead when this contact is set as the lead\'s customer.',
    )
