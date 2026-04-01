# -*- coding: utf-8 -*-
from odoo import api, fields, models, _


class CrmLead(models.Model):
    _inherit = 'crm.lead'

    def action_open_whatsapp_send_wizard(self):
        """Open the WhatsApp Send Wizard for this lead using phone."""
        self.ensure_one()
        
        # Use mobile (if it exists) or phone
        mobile_number = getattr(self, 'mobile', False) or self.phone
        
        if not mobile_number:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Number Missing'),
                    'message': _(
                        'Please set a mobile number for lead "%s" before sending a message.',
                        self.name,
                    ),
                    'type': 'warning',
                    'sticky': False,
                },
            }

        return {
            'type': 'ir.actions.act_window',
            'name': _('Send WhatsApp Message'),
            'res_model': 'whatsapp.send.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_lead_id': self.id,
                'default_mobile_number': mobile_number,
                'default_partner_id': self.partner_id.id if self.partner_id else False,
            },
        }
