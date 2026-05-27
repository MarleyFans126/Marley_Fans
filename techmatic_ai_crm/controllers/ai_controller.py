# -*- coding: utf-8 -*-
"""HTTP controllers used by the OWL assistant panel.

Every endpoint:

* Requires an authenticated user (``auth='user'``).
* Enforces the ``group_techmatic_ai_crm_user`` group.
* Never returns the API key or provider config.
* Returns a uniform ``{ok: bool, ...}`` envelope so the OWL component
  has a single shape to deal with.
"""
import logging

from odoo import fields, http, _
from odoo.exceptions import AccessError
from odoo.http import request

from ..services.ai_service import AIService
from ..services.exceptions import AIError

_logger = logging.getLogger(__name__)


def _require_ai_user():
    user = request.env.user
    if not user.has_group('techmatic_ai_crm.group_techmatic_ai_crm_user'):
        raise AccessError(_('AI assistant access required.'))


def _envelope_ok(**data):
    out = {'ok': True}
    out.update(data)
    return out


def _envelope_err(msg):
    return {'ok': False, 'error': msg}


class AiController(http.Controller):

    @http.route(
        '/techmatic_ai_crm/status',
        type='jsonrpc', auth='user', methods=['POST'], csrf=False,
    )
    def status(self):
        """Cheap check the panel calls on mount."""
        try:
            _require_ai_user()
        except AccessError as e:
            return _envelope_err(str(e))
        svc = AIService(request.env)
        return _envelope_ok(enabled=svc.is_enabled())

    @http.route(
        '/techmatic_ai_crm/session/get_or_create',
        type='jsonrpc', auth='user', methods=['POST'], csrf=False,
    )
    def get_or_create_session(self, lead_id=None):
        """Find or create the user's currently active session."""
        try:
            _require_ai_user()
        except AccessError as e:
            return _envelope_err(str(e))
        Session = request.env['techmatic.ai.chat.session']
        domain = [('user_id', '=', request.env.uid), ('active', '=', True)]
        if lead_id:
            domain.append(('lead_id', '=', int(lead_id)))
        session = Session.search(domain, order='write_date desc', limit=1)
        if not session:
            session = Session.create({
                'user_id': request.env.uid,
                'lead_id': int(lead_id) if lead_id else False,
            })
        return _envelope_ok(
            session_id=session.id,
            title=session.title,
            messages=self._dump_messages(session),
        )

    @http.route(
        '/techmatic_ai_crm/session/send',
        type='jsonrpc', auth='user', methods=['POST'], csrf=False,
    )
    def send(self, session_id, body, lead_id=None):
        try:
            _require_ai_user()
        except AccessError as e:
            return _envelope_err(str(e))
        if not body or not str(body).strip():
            return _envelope_err(_('Empty message.'))
        Session = request.env['techmatic.ai.chat.session']
        session = Session.browse(int(session_id)).exists()
        if not session:
            return _envelope_err(_('Session not found.'))
        try:
            session.post_user_message(body, lead_id=lead_id and int(lead_id))
        except AIError as e:
            return _envelope_err(str(e))
        return _envelope_ok(messages=self._dump_messages(session))

    @http.route(
        '/techmatic_ai_crm/session/new',
        type='jsonrpc', auth='user', methods=['POST'], csrf=False,
    )
    def new_session(self, lead_id=None):
        try:
            _require_ai_user()
        except AccessError as e:
            return _envelope_err(str(e))
        session = request.env['techmatic.ai.chat.session'].create({
            'user_id': request.env.uid,
            'lead_id': int(lead_id) if lead_id else False,
        })
        return _envelope_ok(
            session_id=session.id,
            title=session.title,
            messages=[],
        )

    @http.route(
        '/techmatic_ai_crm/lead/quick_action',
        type='jsonrpc', auth='user', methods=['POST'], csrf=False,
    )
    def lead_quick_action(self, lead_id, action):
        """Endpoint for the panel's quick-action buttons.

        ``action`` ∈ {summarize, score, suggest_activities}.
        """
        try:
            _require_ai_user()
        except AccessError as e:
            return _envelope_err(str(e))

        lead = request.env['crm.lead'].browse(int(lead_id)).exists()
        if not lead:
            return _envelope_err(_('Lead not found.'))

        svc = AIService(request.env)
        try:
            if action == 'summarize':
                text = svc.summarize_lead(lead)
                lead.write({
                    'ai_summary': text,
                    'ai_summary_date': fields.Datetime.now(),
                })
                return _envelope_ok(result=text)
            if action == 'score':
                score = svc.score_lead(lead)
                return _envelope_ok(result=score)
            if action == 'suggest_activities':
                return _envelope_ok(result=svc.suggest_activities(lead))
        except AIError as e:
            return _envelope_err(str(e))
        return _envelope_err(_('Unknown action: %s') % action)

    # ------------------------------------------------------------------
    @staticmethod
    def _dump_messages(session):
        return [{
            'id': m.id,
            'role': m.role,
            'body': m.body or '',
            'date': m.create_date and m.create_date.isoformat() or '',
        } for m in session.message_ids.sorted('create_date')]
