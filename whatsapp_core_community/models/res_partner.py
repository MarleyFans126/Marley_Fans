# -*- coding: utf-8 -*-
from odoo import api, fields, models, _


class ResPartner(models.Model):
    _inherit = 'res.partner'

    # -------------------------------------------------------------------------
    # WhatsApp Fields
    # -------------------------------------------------------------------------
    whatsapp_number = fields.Char(
        string='WhatsApp Number',
        help='WhatsApp phone number in E.164 format (e.g. +919876543210).',
    )
    whatsapp_opt_in = fields.Boolean(
        string='WhatsApp Opt-In',
        default=False,
        help='Contact has given consent to receive WhatsApp messages.',
    )
    whatsapp_message_count = fields.Integer(
        string='WhatsApp Messages',
        compute='_compute_whatsapp_message_count',
    )

    # -------------------------------------------------------------------------
    # Computed
    # -------------------------------------------------------------------------
    def _compute_whatsapp_message_count(self):
        for partner in self:
            partner.whatsapp_message_count = self.env['whatsapp.message.log'].search_count([
                ('partner_id', '=', partner.id),
            ])

    # -------------------------------------------------------------------------
    # Smart Button Action
    # -------------------------------------------------------------------------
    def action_open_whatsapp_send_wizard(self):
        """Open the WhatsApp Send Wizard for this partner."""
        self.ensure_one()
        # Fallback to mobile (if exists) or phone
        mobile_number = self.whatsapp_number or getattr(self, 'mobile', False) or self.phone
        
        if not mobile_number:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('WhatsApp Number Missing'),
                    'message': _(
                        'Please set a mobile or phone number for %s before sending a message.',
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
                'default_partner_id': self.id,
                'default_mobile_number': mobile_number,
            },
        }

    def action_open_whatsapp_logs(self):
        """Open WhatsApp message logs for this partner."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('WhatsApp Messages — %s') % self.name,
            'res_model': 'whatsapp.message.log',
            'view_mode': 'list,form',
            'domain': [('partner_id', '=', self.id)],
            'context': {'default_partner_id': self.id},
        }
