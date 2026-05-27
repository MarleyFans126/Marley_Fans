# -*- coding: utf-8 -*-
"""Tests for the Anthropic Claude provider.

We don't hit the real Claude API — we stub the ``anthropic`` SDK to
verify parameter shaping (system-prompt hoisting, Opus-4.7 sampling-param
removal, cache_control attachment, streaming threshold) and to confirm
the provider is registered with the orchestrator.
"""
import sys
import types
from unittest.mock import MagicMock, patch

from odoo.tests.common import BaseCase, TransactionCase

from ..services.ai_service import AIService
from ..services.claude_provider import ClaudeProvider
from ..services.exceptions import AIConfigurationError, AIProviderError


# ---------------------------------------------------------------------------
# Fake ``anthropic`` SDK — minimal surface so the provider can run offline.
# ---------------------------------------------------------------------------
def _make_fake_anthropic(capture):
    """Build a fake ``anthropic`` module that records the call args.

    ``capture`` is a mutable dict the test reads after the call.
    """
    fake_mod = types.ModuleType('anthropic')

    class _APIError(Exception):
        pass

    class _APIConnectionError(_APIError):
        pass

    class _APIStatusError(_APIError):
        status_code = 500
        message = ''

    fake_mod.APIError = _APIError
    fake_mod.APIConnectionError = _APIConnectionError
    fake_mod.APIStatusError = _APIStatusError

    # response.content[0].type == 'text', .text == '...'
    def _make_response(text='reply text'):
        block = MagicMock()
        block.type = 'text'
        block.text = text
        resp = MagicMock()
        resp.content = [block]
        return resp

    class _Messages(object):
        def create(self, **kwargs):
            capture['create_kwargs'] = kwargs
            return _make_response(capture.get('next_text', 'fake reply'))

        def stream(self, **kwargs):
            capture['stream_kwargs'] = kwargs

            class _Ctx(object):
                def __enter__(self_inner):
                    return self_inner
                def __exit__(self_inner, *a):
                    return False
                def get_final_message(self_inner):
                    return _make_response(capture.get('next_text', 'fake reply'))
            return _Ctx()

    class _Anthropic(object):
        def __init__(self, api_key=None, timeout=None, **_kw):
            capture['ctor'] = {'api_key': api_key, 'timeout': timeout}
            self.messages = _Messages()

    fake_mod.Anthropic = _Anthropic
    return fake_mod


# ---------------------------------------------------------------------------
# Pure unit tests (no DB needed).
# ---------------------------------------------------------------------------
class TestClaudeProviderUnit(BaseCase):

    def _make_provider(self, model='claude-opus-4-7'):
        return ClaudeProvider({
            'api_key': 'sk-ant-test',
            'model': model,
            'temperature': 0.5,
            'max_tokens': 800,
            'timeout': 30,
        })

    def _patch_anthropic(self, capture):
        fake = _make_fake_anthropic(capture)
        return patch.dict(sys.modules, {'anthropic': fake})

    def test_opus_47_omits_temperature(self):
        cap = {}
        p = self._make_provider('claude-opus-4-7')
        with self._patch_anthropic(cap):
            out = p._chat([
                {'role': 'system', 'content': 'be brief'},
                {'role': 'user', 'content': 'hi'},
            ])
        self.assertEqual(out, 'fake reply')
        self.assertNotIn('temperature', cap['create_kwargs'])

    def test_other_models_pass_temperature(self):
        cap = {}
        p = self._make_provider('claude-sonnet-4-6')
        with self._patch_anthropic(cap):
            p._chat([{'role': 'user', 'content': 'hi'}])
        self.assertIn('temperature', cap['create_kwargs'])
        self.assertEqual(cap['create_kwargs']['temperature'], 0.5)

    def test_system_messages_are_hoisted(self):
        cap = {}
        p = self._make_provider()
        with self._patch_anthropic(cap):
            p._chat([
                {'role': 'system', 'content': 'sys A'},
                {'role': 'system', 'content': 'sys B'},
                {'role': 'user', 'content': 'question'},
            ])
        kw = cap['create_kwargs']
        # Top-level ``system`` carries both system messages joined.
        self.assertIn('sys A', kw['system'])
        self.assertIn('sys B', kw['system'])
        # ``messages`` only contains the user turn.
        self.assertEqual(kw['messages'], [{'role': 'user', 'content': 'question'}])

    def test_cache_control_attached_by_default(self):
        cap = {}
        p = self._make_provider()
        with self._patch_anthropic(cap):
            p._chat([{'role': 'user', 'content': 'hi'}])
        self.assertEqual(
            cap['create_kwargs']['cache_control'], {'type': 'ephemeral'},
        )

    def test_streaming_kicks_in_above_threshold(self):
        cap = {}
        p = self._make_provider()
        with self._patch_anthropic(cap):
            p._chat([{'role': 'user', 'content': 'hi'}], max_tokens=32000)
        self.assertIn('stream_kwargs', cap)
        self.assertNotIn('create_kwargs', cap)

    def test_blocking_call_below_threshold(self):
        cap = {}
        p = self._make_provider()
        with self._patch_anthropic(cap):
            p._chat([{'role': 'user', 'content': 'hi'}], max_tokens=4000)
        self.assertIn('create_kwargs', cap)
        self.assertNotIn('stream_kwargs', cap)

    def test_missing_anthropic_raises_clean_error(self):
        # Force the import to fail by injecting a None into sys.modules.
        p = self._make_provider()
        with patch.dict(sys.modules, {'anthropic': None}):
            with self.assertRaises(AIConfigurationError) as cm:
                p._chat([{'role': 'user', 'content': 'hi'}])
        self.assertIn('pip install anthropic', str(cm.exception))

    def test_connection_error_wraps_as_provider_error(self):
        cap = {}
        fake = _make_fake_anthropic(cap)

        # Make .create raise a fake APIConnectionError.
        def boom(**kwargs):
            raise fake.APIConnectionError('network down')

        with patch.dict(sys.modules, {'anthropic': fake}):
            p = self._make_provider()
            # Swap the Messages.create after construction.
            with patch.object(
                fake.Anthropic, '__init__', lambda self, **kw: setattr(
                    self, 'messages', type('M', (), {
                        'create': staticmethod(boom),
                        'stream': staticmethod(lambda **kw: None),
                    })()
                )
            ):
                with self.assertRaises(AIProviderError):
                    p._chat([{'role': 'user', 'content': 'hi'}])

    def test_extract_text_skips_thinking_blocks(self):
        thinking = MagicMock()
        thinking.type = 'thinking'
        thinking.text = 'INTERNAL REASONING — should not leak'
        text = MagicMock()
        text.type = 'text'
        text.text = 'visible answer'
        resp = MagicMock()
        resp.content = [thinking, text]
        out = ClaudeProvider._extract_text(resp)
        self.assertEqual(out, 'visible answer')
        self.assertNotIn('INTERNAL', out)


# ---------------------------------------------------------------------------
# Orchestrator wiring — needs a DB so we can read ir.config_parameter.
# ---------------------------------------------------------------------------
class TestClaudeProviderRegistered(TransactionCase):

    def test_claude_is_in_providers_map(self):
        self.assertIn('claude', AIService.PROVIDERS)
        self.assertIs(AIService.PROVIDERS['claude'], ClaudeProvider)

    def test_service_dispatches_to_claude(self):
        ICP = self.env['ir.config_parameter'].sudo()
        ICP.set_param('techmatic_ai_crm.enabled', 'True')
        ICP.set_param('techmatic_ai_crm.provider', 'claude')
        ICP.set_param('techmatic_ai_crm.api_key', 'sk-ant-test')
        ICP.set_param('techmatic_ai_crm.model', 'claude-opus-4-7')

        cap = {}
        with patch.dict(sys.modules, {'anthropic': _make_fake_anthropic(cap)}):
            svc = AIService(self.env)
            provider = svc.provider()
            self.assertIsInstance(provider, ClaudeProvider)
