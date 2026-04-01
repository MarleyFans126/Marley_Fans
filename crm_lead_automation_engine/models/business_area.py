from odoo import models, fields, api


class BusinessArea(models.Model):
    _name = 'business.area'
    _description = 'Business Area (Locality)'
    _rec_name = 'name'
    _order = 'name'

    name = fields.Char(string='Area / Locality', required=True, index=True)
    city_id = fields.Many2one(
        'business.city',
        string='City',
        required=True,
        ondelete='restrict',
    )
    state_id = fields.Many2one(
        related='city_id.state_id',
        string='State',
        store=True,
        readonly=True,
    )
    active = fields.Boolean(default=True)

    def name_get(self):
        return [(rec.id, f"{rec.name}, {rec.city_id.name}") for rec in self]

    @api.model
    def name_create(self, name):
        """Allow quick-create from lead form — picks city from context."""
        city_id = self.env.context.get('default_city_id')
        if not city_id:
            city_id = self.env.context.get('city_id')
        if city_id:
            record = self.create({'name': name, 'city_id': city_id})
            return record.name_get()[0]
        return super().name_create(name)
