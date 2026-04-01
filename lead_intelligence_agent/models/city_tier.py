# -*- coding: utf-8 -*-
from odoo import models, fields


class CityTier(models.Model):
    _name = 'x.city.tier'
    _description = 'City Tier Master Data'
    _order = 'tier, name'

    name = fields.Char(string='City Name', required=True, index=True)
    state = fields.Char(string='State')
    tier = fields.Selection([
        ('tier_1', 'Tier 1'),
        ('tier_2', 'Tier 2'),
        ('tier_3', 'Tier 3'),
    ], string='Tier', required=True, default='tier_3')

    _sql_constraints = [
        ('unique_city_name', 'UNIQUE(name)', 'City name must be unique!'),
    ]
