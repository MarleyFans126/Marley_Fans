# -*- coding: utf-8 -*-
"""Abstract AI provider contract.

Each concrete provider (OpenAI, Gemini, future local LLMs) implements
``_chat`` — the single transport-level method that turns a list of
messages into a string completion. All higher-level helpers
(``summarize``, ``generate_email``, ``score_lead``) are defined here so
behavior stays consistent across providers.
"""
import abc
import json
import logging

from .exceptions import AIConfigurationError, AIProviderError
from .prompt_sanitizer import sanitize

_logger = logging.getLogger(__name__)


class AIProvider(abc.ABC):
    """Base class. Subclass and implement ``_chat``.

    :param dict config: provider config dict — must contain at minimum
        ``api_key``, ``model``, ``temperature``, ``max_tokens``,
        ``timeout``.
    """

    name = 'base'

    def __init__(self, config):
        if not config:
            raise AIConfigurationError('AI provider config missing.')
        if not config.get('api_key'):
            raise AIConfigurationError(
                'API key not configured. Set it under CRM ➜ Configuration ➜ Settings.'
            )
        if not config.get('model'):
            raise AIConfigurationError('AI model not configured.')
        self.api_key = config['api_key']
        self.model = config['model']
        self.temperature = float(config.get('temperature', 0.4))
        self.max_tokens = int(config.get('max_tokens', 800))
        self.timeout = int(config.get('timeout', 30))

    # ---------------------------------------------------------------------
    # Transport — implemented per provider.
    # ---------------------------------------------------------------------
    @abc.abstractmethod
    def _chat(self, messages, **kwargs):
        """Return the assistant text for the given chat ``messages``.

        :param list messages: ``[{'role': 'system'|'user'|'assistant',
            'content': str}, ...]``
        :rtype: str
        """
        raise NotImplementedError

    # ---------------------------------------------------------------------
    # Public high-level API — same across providers.
    # ---------------------------------------------------------------------
    def generate_response(self, user_prompt, system_prompt=None, **kwargs):
        """Single-turn convenience wrapper around ``_chat``."""
        system_prompt = system_prompt or (
            'You are a helpful CRM assistant for an Odoo 19 deployment. '
            'Answer concisely and stay strictly within the CRM context.'
        )
        messages = [
            {'role': 'system', 'content': sanitize(system_prompt, max_chars=4000)},
            {'role': 'user', 'content': sanitize(user_prompt)},
        ]
        return self._chat(messages, **kwargs)

    def chat(self, messages, **kwargs):
        """Multi-turn chat. Caller owns sanitization of stored history."""
        # Even with stored history, defensively sanitize every turn —
        # cheap and protects against poisoned past messages.
        clean = [
            {'role': m['role'], 'content': sanitize(m['content'])}
            for m in messages if m.get('content')
        ]
        return self._chat(clean, **kwargs)

    def summarize(self, context_text, instructions=None):
        sys_p = (
            'You produce concise, business-grade CRM lead summaries. '
            'Output sections: Summary, Customer Intent, Urgency '
            '(Low/Medium/High), Risk Level (Low/Medium/High), '
            'Recommended Next Action. Keep each section to 1-2 lines.'
        )
        user_p = (instructions + '\n\n' if instructions else '') + \
                 'Lead context:\n' + context_text
        return self.generate_response(user_p, system_prompt=sys_p)

    def generate_email(self, context_text, tone='professional'):
        sys_p = (
            'You draft polished sales follow-up emails. Return ONLY the '
            'email body — no preamble, no markdown fences. Tone: %s.'
        ) % tone
        return self.generate_response(context_text, system_prompt=sys_p)

    def score_lead(self, context_text):
        """Ask the model for a structured scoring blob.

        Returns a dict with ``score`` (0-100), ``priority``
        (Low/Medium/High), ``status`` (Hot/Warm/Cold), and ``reason``.
        """
        sys_p = (
            'You score CRM leads. Respond with STRICT JSON only — no '
            'commentary, no markdown. Schema: '
            '{"score": <int 0-100>, "priority": "Low|Medium|High", '
            '"status": "Hot|Warm|Cold", "reason": "<short sentence>"}'
        )
        raw = self.generate_response(context_text, system_prompt=sys_p)
        return self._parse_json_blob(raw, default={
            'score': 0, 'priority': 'Low', 'status': 'Cold',
            'reason': 'Unable to parse model response.',
        })

    # ---------------------------------------------------------------------
    # Helpers.
    # ---------------------------------------------------------------------
    @staticmethod
    def _parse_json_blob(text, default=None):
        """Best-effort JSON extraction.

        Models sometimes wrap JSON in ```json fences``` or add stray
        prose. We strip fences, locate the first ``{...}`` block, and
        fall back to ``default`` on any failure.
        """
        if not text:
            return default
        cleaned = text.strip()
        if cleaned.startswith('```'):
            # Drop the opening fence (possibly ```json) and the trailer.
            cleaned = cleaned.split('\n', 1)[-1]
            if cleaned.endswith('```'):
                cleaned = cleaned[:-3]
        start = cleaned.find('{')
        end = cleaned.rfind('}')
        if start == -1 or end == -1 or end < start:
            _logger.warning('AI JSON response had no object: %r', text[:200])
            return default
        try:
            return json.loads(cleaned[start:end + 1])
        except (ValueError, json.JSONDecodeError) as e:
            _logger.warning('AI JSON parse failed: %s — payload: %r', e, text[:200])
            return default

    def _require_requests(self):
        """Import ``requests`` lazily so install doesn't require it."""
        try:
            import requests  # noqa: WPS433
            return requests
        except ImportError as e:
            raise AIConfigurationError(
                'The `requests` Python package is required for the AI '
                'provider. Install it with: pip install requests'
            ) from e

    def _raise_provider(self, msg, response=None):
        """Uniform provider-error raising with logging."""
        body = None
        if response is not None:
            try:
                body = response.text[:500]
            except Exception:  # noqa: BLE001 — last-resort log
                body = '<unreadable>'
        _logger.error('Provider %s error: %s | body=%s', self.name, msg, body)
        raise AIProviderError(msg)
