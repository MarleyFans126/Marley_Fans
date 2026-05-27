# -*- coding: utf-8 -*-
"""Integration tests for ``AIService`` (config, context, provider dispatch)."""
import json

from .common import AICRMTestCase, patched_provider

from ..services.ai_service import AIService
from ..services.exceptions import AIConfigurationError


class TestAIService(AICRMTestCase):

    def test_get_config_reads_icp(self):
        svc = AIService(self.env)
        cfg = svc.get_config()
        self.assertEqual(cfg['provider'], 'openai')
        self.assertEqual(cfg['model'], 'fake-model')
        self.assertTrue(cfg['enabled'])

    def test_is_enabled_requires_api_key(self):
        svc = AIService(self.env)
        self.assertTrue(svc.is_enabled())
        self.ICP.set_param('techmatic_ai_crm.api_key', '')
        self.assertFalse(svc.is_enabled())

    def test_provider_raises_without_api_key(self):
        self.ICP.set_param('techmatic_ai_crm.api_key', '')
        # Re-enable but with no key — provider must still build, but the
        # OpenAI subclass should refuse on missing key.
        self.ICP.set_param('techmatic_ai_crm.enabled', 'True')
        svc = AIService(self.env)
        with self.assertRaises(AIConfigurationError):
            svc.provider()

    def test_provider_raises_when_disabled(self):
        self.ICP.set_param('techmatic_ai_crm.enabled', 'False')
        svc = AIService(self.env)
        with self.assertRaises(AIConfigurationError):
            svc.provider()

    def test_build_lead_context_includes_key_fields(self):
        svc = AIService(self.env)
        ctx = svc._build_lead_context(self.lead)
        self.assertIn('Test AI Lead', ctx)
        self.assertIn('lead@example.com', ctx)
        self.assertIn('200 units urgent', ctx)
        self.assertIn('75000', ctx)

    def test_summarize_lead_uses_provider(self):
        fake = self._new_fake('A concise summary text.')
        with patched_provider(fake):
            text = AIService(self.env).summarize_lead(self.lead)
        self.assertEqual(text, 'A concise summary text.')
        # Provider was called exactly once with system + user roles.
        self.assertEqual(len(fake.calls), 1)
        messages, _ = fake.calls[0]
        self.assertEqual(messages[0]['role'], 'system')
        self.assertEqual(messages[1]['role'], 'user')

    def test_score_lead_parses_json(self):
        payload = json.dumps({
            'score': 87, 'priority': 'High', 'status': 'Hot',
            'reason': 'Urgent customer, high revenue.',
        })
        fake = self._new_fake(payload)
        with patched_provider(fake):
            score = AIService(self.env).score_lead(self.lead)
        self.assertEqual(score['score'], 87)
        self.assertEqual(score['status'], 'Hot')
        self.assertEqual(score['priority'], 'High')

    def test_score_lead_recovers_from_bad_json(self):
        fake = self._new_fake('this is not JSON at all')
        with patched_provider(fake):
            score = AIService(self.env).score_lead(self.lead)
        # Falls back to the documented default.
        self.assertEqual(score['score'], 0)
        self.assertEqual(score['status'], 'Cold')

    def test_score_lead_strips_markdown_fences(self):
        fenced = '```json\n{"score": 42, "priority": "Medium", ' \
                 '"status": "Warm", "reason": "ok"}\n```'
        fake = self._new_fake(fenced)
        with patched_provider(fake):
            score = AIService(self.env).score_lead(self.lead)
        self.assertEqual(score['score'], 42)
        self.assertEqual(score['status'], 'Warm')

    def test_suggest_activities_parses_list(self):
        fake = self._new_fake(
            '[{"action": "call", "summary": "Ring back", "due_in_days": 1}]'
        )
        with patched_provider(fake):
            items = AIService(self.env).suggest_activities(self.lead)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]['action'], 'call')

    def test_suggest_activities_returns_empty_on_garbage(self):
        fake = self._new_fake('not a list')
        with patched_provider(fake):
            items = AIService(self.env).suggest_activities(self.lead)
        self.assertEqual(items, [])

    def test_test_connection_success_shape(self):
        fake = self._new_fake('OK')
        with patched_provider(fake):
            out = AIService(self.env).test_connection()
        self.assertTrue(out['success'])

    def test_test_connection_handles_error(self):
        from ..services.exceptions import AIProviderError

        class BoomProvider(type(self._new_fake())):
            def _chat(self, messages, **kw):
                raise AIProviderError('boom')

        boom = BoomProvider()
        with patched_provider(boom):
            out = AIService(self.env).test_connection()
        self.assertFalse(out['success'])
        self.assertIn('boom', out['message'])
