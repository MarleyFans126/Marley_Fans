from odoo import models, fields, api


class BusinessCity(models.Model):
    _name = 'business.city'
    _description = 'Business City'
    _rec_name = 'name'
    _order = 'name'

    name = fields.Char(string='City', required=True, index=True)
    state_id = fields.Many2one(
        'res.country.state',
        string='State',
        required=True,
        domain="[('country_id.code', '=', 'IN')]",
        ondelete='restrict',
    )
    active = fields.Boolean(default=True)

    def name_get(self):
        return [(rec.id, f"{rec.name} ({rec.state_id.name})") for rec in self]

    @api.model
    def name_create(self, name):
        """Allow quick-create from lead form — picks state from context."""
        state_id = self.env.context.get('default_state_id')
        if not state_id:
            # Fallback: try to find state from context
            state_id = self.env.context.get('state_id')
        if not state_id:
            # If no state in context, use first Indian state as placeholder
            india = self.env.ref('base.in', raise_if_not_found=False)
            if india:
                state = self.env['res.country.state'].search(
                    [('country_id', '=', india.id)], limit=1
                )
                state_id = state.id if state else False
        if state_id:
            record = self.create({'name': name, 'state_id': state_id})
            return record.name_get()[0]
        return super().name_create(name)
