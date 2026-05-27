# -*- coding: utf-8 -*-
"""Persistent AI chat sessions.

Each session belongs to one user and optionally to one CRM lead. The
sidebar OWL panel opens/creates a session per user and appends messages
as the conversation goes.
"""
import logging

from odoo import api, fields, models, _
from odoo.exceptions import AccessError

from ..services.ai_service import AIService
from ..services.exceptions import AIError

_logger = logging.getLogger(__name__)


class AiChatSession(models.Model):
    _name = 'techmatic.ai.chat.session'
    _description = 'AI CRM Chat Session'
    _order = 'write_date desc'
    _rec_name = 'title'

    title = fields.Char(default=lambda self: _('New AI Session'))
    user_id = fields.Many2one(
        'res.users', required=True, default=lambda self: self.env.user,
        ondelete='cascade', index=True,
    )
    lead_id = fields.Many2one(
        'crm.lead', ondelete='set null', index=True,
        help='Optional lead this session is anchored to.',
    )
    message_ids = fields.One2many(
        'techmatic.ai.chat.message', 'session_id',
    )
    message_count = fields.Integer(compute='_compute_message_count')
    last_message_preview = fields.Char(
        compute='_compute_last_preview', store=False,
    )
    active = fields.Boolean(default=True)

    @api.depends('message_ids')
    def _compute_message_count(self):
        for rec in self:
            rec.message_count = len(rec.message_ids)

    @api.depends('message_ids.body', 'message_ids.create_date')
    def _compute_last_preview(self):
        for rec in self:
            last = rec.message_ids.sorted('create_date')[-1:] if rec.message_ids else None
            rec.last_message_preview = (last and (last.body or '')[:120]) or ''

    # ------------------------------------------------------------------
    # Public API used by the controller / OWL panel.
    # ------------------------------------------------------------------
    def _check_owner(self):
        for rec in self:
            if rec.user_id.id != self.env.uid and not self.env.user.has_group(
                    'techmatic_ai_crm.group_techmatic_ai_crm_admin'):
                raise AccessError(_('You can only access your own AI sessions.'))

    def post_user_message(self, body, lead_id=None):
        """Append a user message and immediately produce an assistant reply.

        :returns: the new assistant ``techmatic.ai.chat.message`` record.
        """
        self.ensure_one()
        self._check_owner()
        if lead_id and not self.lead_id:
            self.lead_id = lead_id

        self.env['techmatic.ai.chat.message'].create({
            'session_id': self.id,
            'role': 'user',
            'body': body or '',
        })

        # Reuse the last N messages as the chat history. Stay small to
        # control token cost.
        history = self.message_ids.sorted('create_date')[-12:]
        messages = [{
            'role': 'system',
            'content': self._build_system_prompt(),
        }]
        for m in history:
            messages.append({'role': m.role, 'content': m.body or ''})

        service = AIService(self.env)
        try:
            reply = service.chat(messages)
        except AIError as e:
            reply = _('AI error: %s') % e

        assistant_msg = self.env['techmatic.ai.chat.message'].create({
            'session_id': self.id,
            'role': 'assistant',
            'body': reply,
        })
        if self.title == _('New AI Session') and body:
            self.title = (body[:60] + '…') if len(body) > 60 else body
        return assistant_msg

    def _build_system_prompt(self):
        """Assemble the system prompt — includes optional lead dossier."""
        base = self.env['techmatic.ai.prompt.template'].sudo().search([
            ('key', '=', 'assistant.system'), ('active', '=', True),
        ], limit=1).system_prompt or (
            'You are an AI assistant embedded in Odoo CRM. Help the '
            'salesperson with summaries, follow-ups, scoring, and lead '
            'analysis. Be concise and concrete. Stay in CRM scope.'
        )
        if self.lead_id:
            ctx = AIService(self.env)._build_lead_context(
                self.lead_id, include_history=True,
            )
            return base + '\n\nActive lead context:\n' + ctx
        return base
