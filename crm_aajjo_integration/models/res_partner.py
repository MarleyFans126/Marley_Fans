from odoo import models, api

class ResPartner(models.Model):
    _inherit = 'res.partner'

    def action_open_mail_composer(self):
        """ Opens the mail composer for this partner """
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Compose Email',
            'res_model': 'mail.compose.message',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_composition_mode': 'comment',
                'default_model': 'res.partner',
                'default_res_ids': [self.id],
                'default_partner_ids': [self.id],
                'force_email': True,
            }
        }
