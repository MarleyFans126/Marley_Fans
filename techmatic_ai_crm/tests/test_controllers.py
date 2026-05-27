# -*- coding: utf-8 -*-
"""HTTP controller tests for the OWL panel endpoints.

Uses :class:`HttpCase` so the routes get exercised through werkzeug,
which catches issues a pure ORM test would miss (envelope shape,
status codes, CSRF, group gating in the request context).
"""
import json
from unittest.mock import patch

from odoo.tests import HttpCase, tagged

from ..services import ai_service as ai_service_mod
from .common import FakeProvider


@tagged('post_install', '-at_install')
class TestAiController(HttpCase):

    def setUp(self):
        super().setUp()
        ICP = self.env['ir.config_parameter'].sudo()
        ICP.set_param('techmatic_ai_crm.enabled', 'True')
        ICP.set_param('techmatic_ai_crm.api_key', 'sk-test')
        ICP.set_param('techmatic_ai_crm.model', 'fake-model')
        ICP.set_param('techmatic_ai_crm.provider', 'openai')

        Users = self.env['res.users'].with_context(no_reset_password=True)
        self.user_ai = Users.create({
            'name': 'HTTP AI User',
            'login': 'http_ai_user',
            'password': 'http_ai_user',
            'email': 'http_ai_user@example.com',
            'group_ids': [
                (4, self.env.ref(
                    'techmatic_ai_crm.group_techmatic_ai_crm_user').id),
            ],
        })
        self.user_outsider = Users.create({
            'name': 'HTTP Outsider',
            'login': 'http_outsider',
            'password': 'http_outsider',
            'email': 'http_outsider@example.com',
            'group_ids': [(4, self.env.ref('base.group_user').id)],
        })

    def _json(self, route, params=None):
        return self.url_open(
            route,
            data=json.dumps({'jsonrpc': '2.0', 'method': 'call',
                             'params': params or {}}),
            headers={'Content-Type': 'application/json'},
        )

    def test_status_requires_ai_user_group(self):
        self.authenticate('http_outsider', 'http_outsider')
        resp = self._json('/techmatic_ai_crm/status')
        body = resp.json()['result']
        self.assertFalse(body['ok'])
        self.assertIn('AI assistant access required', body['error'])

    def test_status_ok_for_ai_user(self):
        self.authenticate('http_ai_user', 'http_ai_user')
        resp = self._json('/techmatic_ai_crm/status')
        body = resp.json()['result']
        self.assertTrue(body['ok'])
        self.assertTrue(body['enabled'])

    def test_session_round_trip(self):
        """get_or_create → send → expect 2 messages back."""
        self.authenticate('http_ai_user', 'http_ai_user')
        fake = FakeProvider().queue('Assistant http reply.')

        with patch.object(
                ai_service_mod.AIService, 'provider',
                lambda self: fake,
        ):
            resp = self._json('/techmatic_ai_crm/session/get_or_create')
            body = resp.json()['result']
            self.assertTrue(body['ok'])
            session_id = body['session_id']

            resp = self._json('/techmatic_ai_crm/session/send', {
                'session_id': session_id,
                'body': 'hello bot',
            })
            body = resp.json()['result']
            self.assertTrue(body['ok'])
            roles = [m['role'] for m in body['messages']]
            self.assertIn('user', roles)
            self.assertIn('assistant', roles)

    def test_send_empty_body_returns_error(self):
        self.authenticate('http_ai_user', 'http_ai_user')
        # First create a session so we have an id to send to.
        resp = self._json('/techmatic_ai_crm/session/get_or_create')
        session_id = resp.json()['result']['session_id']
        resp = self._json('/techmatic_ai_crm/session/send', {
            'session_id': session_id, 'body': '   ',
        })
        body = resp.json()['result']
        self.assertFalse(body['ok'])
        self.assertIn('Empty message', body['error'])

    def test_lead_quick_action_unknown_action(self):
        self.authenticate('http_ai_user', 'http_ai_user')
        lead = self.env['crm.lead'].with_user(self.user_ai).create({
            'name': 'HTTP Test Lead', 'type': 'opportunity',
        })
        resp = self._json('/techmatic_ai_crm/lead/quick_action', {
            'lead_id': lead.id, 'action': 'definitely_bogus',
        })
        body = resp.json()['result']
        self.assertFalse(body['ok'])
        self.assertIn('Unknown action', body['error'])

    def test_lead_quick_action_summarize(self):
        self.authenticate('http_ai_user', 'http_ai_user')
        lead = self.env['crm.lead'].with_user(self.user_ai).create({
            'name': 'HTTP Summary Lead', 'type': 'opportunity',
            'description': 'A short description.',
        })
        fake = FakeProvider().queue('HTTP summary result.')
        with patch.object(
                ai_service_mod.AIService, 'provider',
                lambda self: fake,
        ):
            resp = self._json('/techmatic_ai_crm/lead/quick_action', {
                'lead_id': lead.id, 'action': 'summarize',
            })
        body = resp.json()['result']
        self.assertTrue(body['ok'])
        self.assertEqual(body['result'], 'HTTP summary result.')
