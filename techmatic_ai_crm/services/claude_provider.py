# -*- coding: utf-8 -*-
"""Anthropic Claude provider.

Uses the official ``anthropic`` Python SDK. The SDK is imported lazily
so admins who pick OpenAI or Gemini don't have to install it.

Model selection drives parameter shaping:

* **Opus 4.7** removed top-level sampling params (``temperature``,
  ``top_p``, ``top_k``) — sending them returns a 400. We omit them.
* **Adaptive thinking** (``thinking: {type: "adaptive"}``) is omitted
  by default to keep behavior consistent with the other providers and
  to avoid the cost/latency overhead of reasoning on simple summary
  tasks. Admins can enable it later by extending this class.
* **Streaming** is used automatically when ``max_tokens > 16000`` so we
  don't hit the SDK's HTTP-timeout guard. Below that we use the simpler
  blocking call.

Defaults follow Anthropic's current recommendations (cutoff: 2026-04).
"""
import logging

from .ai_provider import AIProvider
from .exceptions import AIConfigurationError, AIProviderError

_logger = logging.getLogger(__name__)


# Top-level sampling params are removed on Opus 4.7 — sending them 400s.
# Keep this prefix list narrow; new model IDs go in via settings without
# code changes.
_NO_SAMPLING_PARAMS = (
    'claude-opus-4-7',
)

# Threshold beyond which we switch to streaming — the Anthropic SDK
# raises ``ValueError`` on non-streaming requests it predicts will run
# past ~10 minutes, which roughly correlates with max_tokens > 16K.
_STREAM_THRESHOLD = 16000


class ClaudeProvider(AIProvider):
    name = 'claude'

    def _require_anthropic(self):
        """Lazy import — keep ``anthropic`` an optional dependency."""
        try:
            import anthropic
            return anthropic
        except ImportError as e:
            raise AIConfigurationError(
                'The `anthropic` Python package is required for the '
                'Claude provider. Install it in the Odoo virtualenv: '
                'pip install anthropic'
            ) from e

    def _chat(self, messages, **kwargs):
        anthropic = self._require_anthropic()
        client = anthropic.Anthropic(
            api_key=self.api_key, timeout=self.timeout,
        )

        # Claude's API takes the system prompt as a top-level field, not
        # as a message. Hoist every ``system`` role out of the chat
        # history and concatenate.
        system_parts = []
        chat = []
        for m in messages:
            role = m.get('role')
            content = m.get('content') or ''
            if not content:
                continue
            if role == 'system':
                system_parts.append(content)
            elif role == 'assistant':
                chat.append({'role': 'assistant', 'content': content})
            else:
                chat.append({'role': 'user', 'content': content})

        if not chat:
            # Claude requires at least one non-system message.
            chat.append({'role': 'user', 'content': '(no input)'})

        max_tokens = int(kwargs.get('max_tokens', self.max_tokens))
        params = {
            'model': self.model,
            'max_tokens': max_tokens,
            'messages': chat,
        }
        if system_parts:
            params['system'] = '\n\n'.join(system_parts)

        # Auto-cache the largest stable prefix (typically the system
        # prompt). The API silently no-ops if the prefix is below the
        # minimum cacheable size — zero cost when it doesn't trigger,
        # ~90% input-token discount when it does.
        params['cache_control'] = {'type': 'ephemeral'}

        # Opus 4.7 removed top-level sampling params; sending them 400s.
        if not self._is_no_sampling_model(self.model):
            params['temperature'] = float(
                kwargs.get('temperature', self.temperature)
            )

        try:
            if max_tokens > _STREAM_THRESHOLD:
                with client.messages.stream(**params) as stream:
                    response = stream.get_final_message()
            else:
                response = client.messages.create(**params)
        except anthropic.APIConnectionError as e:
            raise AIProviderError(
                'Claude connection error: %s' % e
            ) from e
        except anthropic.APIStatusError as e:
            # Typed exceptions: BadRequest, Auth, RateLimit, Overloaded
            # all subclass APIStatusError. ``e.message`` is sanitized.
            self._raise_provider(
                'Claude HTTP %s: %s' % (e.status_code, e.message),
            )

        return self._extract_text(response)

    # ------------------------------------------------------------------
    @staticmethod
    def _is_no_sampling_model(model_id):
        m = (model_id or '').lower()
        return any(m.startswith(prefix) for prefix in _NO_SAMPLING_PARAMS)

    @staticmethod
    def _extract_text(response):
        """Return the concatenated text of every ``text`` content block.

        Claude responses can include ``thinking`` blocks ahead of the
        final ``text`` blocks. We drop thinking (it's the model's
        internal reasoning, not part of the answer) and concatenate the
        text. ``response.content`` is a Pydantic list — access by
        attribute, not by key.
        """
        if not response or not response.content:
            return ''
        parts = []
        for block in response.content:
            btype = getattr(block, 'type', None)
            if btype == 'text':
                parts.append(getattr(block, 'text', '') or '')
        return ''.join(parts).strip()
