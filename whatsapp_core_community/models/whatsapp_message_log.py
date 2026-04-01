# -*- coding: utf-8 -*-
from odoo import api, fields, models, _


class WhatsAppMessageLog(models.Model):
    """
    WhatsApp Message Log — records every inbound and outbound WhatsApp message.
    """
    _name = 'whatsapp.message.log'
    _description = 'WhatsApp Message Log'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'create_date desc'
    _rec_name = 'partner_id'

    # -------------------------------------------------------------------------
    # Fields
    # -------------------------------------------------------------------------
    partner_id = fields.Many2one(
        'res.partner',
        string='Contact',
        ondelete='set null',
        index=True,
    )
    direction = fields.Selection(
        selection=[
            ('outbound', 'Outbound'),
            ('inbound', 'Inbound'),
        ],
        string='Direction',
        required=True,
        default='outbound',
        index=True,
    )
    message_type = fields.Selection(
        selection=[
            ('text', 'Text'),
            ('template', 'Template'),
            ('media', 'Media / Document'),
            ('unknown', 'Unknown'),
        ],
        string='Message Type',
        required=True,
        default='text',
    )
    template_name = fields.Char(
        string='Template Name',
    )
    body_preview = fields.Text(
        string='Message Preview',
        help='Short preview of the message content.',
    )
    payload = fields.Text(
        string='API Payload (JSON)',
        help='Full JSON payload sent/received via the WhatsApp Cloud API.',
    )
    status = fields.Selection(
        selection=[
            ('sent', 'Sent'),
            ('failed', 'Failed'),
            ('received', 'Received'),
            ('pending', 'Pending'),
        ],
        string='Status',
        required=True,
        default='pending',
        index=True,
    )
    api_response = fields.Text(
        string='API Response (JSON)',
        help='Raw API response from Meta WhatsApp Cloud API.',
    )
    wa_message_id = fields.Char(
        string='WhatsApp Message ID',
        index=True,
        help='Unique message ID assigned by WhatsApp (wamid.).',
    )
    from_number = fields.Char(
        string='From Number',
        help='Sender phone number (for inbound messages).',
    )
    timestamp = fields.Datetime(
        string='Timestamp',
        default=fields.Datetime.now,
        index=True,
    )
    error_message = fields.Char(
        string='Error Detail',
        help='Error message if the send failed.',
    )


    # -------------------------------------------------------------------------
    # Action: Open Partner
    # -------------------------------------------------------------------------
    def action_open_partner(self):
        self.ensure_one()
        if not self.partner_id:
            return False
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'res.partner',
            'res_id': self.partner_id.id,
            'view_mode': 'form',
            'target': 'current',
        }
