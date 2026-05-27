# -*- coding: utf-8 -*-
"""Single turn in an AI chat session."""
from odoo import fields, models


class AiChatMessage(models.Model):
    _name = 'techmatic.ai.chat.message'
    _description = 'AI CRM Chat Message'
    _order = 'create_date asc, id asc'

    session_id = fields.Many2one(
        'techmatic.ai.chat.session', required=True, ondelete='cascade',
        index=True,
    )
    role = fields.Selection(
        selection=[
            ('user', 'User'),
            ('assistant', 'Assistant'),
            ('system', 'System'),
        ],
        required=True,
    )
    body = fields.Text(required=True)
