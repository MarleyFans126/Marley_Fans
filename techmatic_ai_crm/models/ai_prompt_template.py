# -*- coding: utf-8 -*-
"""Reusable prompt templates.

Admins can edit prompts from the UI without touching code. Each template
has a unique ``key`` referenced by the service layer; missing/disabled
templates fall back to in-code defaults so the assistant keeps working.
"""
from odoo import fields, models


class AiPromptTemplate(models.Model):
    _name = 'techmatic.ai.prompt.template'
    _description = 'AI Prompt Template'
    _order = 'category, name'

    name = fields.Char(required=True)
    key = fields.Char(
        required=True, index=True,
        help='Programmatic identifier referenced by code. '
             'Examples: ``lead.summary``, ``lead.followup``, '
             '``lead.score``, ``assistant.system``.',
    )
    category = fields.Selection(
        selection=[
            ('lead', 'Lead'),
            ('assistant', 'Assistant'),
            ('email', 'Email'),
            ('query', 'NL Query'),
            ('other', 'Other'),
        ],
        default='lead', required=True,
    )
    system_prompt = fields.Text(
        help='Passed as the ``system`` role. Defines the assistant '
             'persona and output contract.',
    )
    user_prompt_template = fields.Text(
        help='Passed as the ``user`` role. Plain text — no templating '
             'engine is used (keeps prompt-injection surface small).',
    )
    active = fields.Boolean(default=True)
    note = fields.Char(help='Internal description / examples.')

    _sql_constraints = [
        ('key_unique', 'unique(key)',
         'Prompt template key must be unique.'),
    ]
