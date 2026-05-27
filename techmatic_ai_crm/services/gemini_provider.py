# -*- coding: utf-8 -*-
"""Google Gemini provider (generativelanguage REST API).

Uses ``v1beta/models/<model>:generateContent`` with the ``contents``
schema. We translate the OpenAI-style ``messages`` list into Gemini's
``role`` / ``parts`` representation in one place — every higher-level
helper in :class:`AIProvider` continues to work.
"""
import logging

from .ai_provider import AIProvider
from .exceptions import AIProviderError

_logger = logging.getLogger(__name__)

DEFAULT_ENDPOINT = 'https://generativelanguage.googleapis.com/v1beta'


class GeminiProvider(AIProvider):
    name = 'gemini'

    def __init__(self, config):
        super().__init__(config)
        self.endpoint = config.get('endpoint') or DEFAULT_ENDPOINT

    def _chat(self, messages, **kwargs):
        requests = self._require_requests()
        contents, system_instruction = self._to_gemini_contents(messages)

        url = '%s/models/%s:generateContent?key=%s' % (
            self.endpoint.rstrip('/'), self.model, self.api_key,
        )
        payload = {
            'contents': contents,
            'generationConfig': {
                'temperature': kwargs.get('temperature', self.temperature),
                'maxOutputTokens': kwargs.get('max_tokens', self.max_tokens),
            },
        }
        if system_instruction:
            payload['systemInstruction'] = {
                'parts': [{'text': system_instruction}],
            }

        try:
            resp = requests.post(
                url, json=payload,
                headers={'Content-Type': 'application/json'},
                timeout=self.timeout,
            )
        except requests.RequestException as e:
            raise AIProviderError('Gemini request failed: %s' % e) from e

        if resp.status_code != 200:
            self._raise_provider(
                'Gemini HTTP %s' % resp.status_code, response=resp,
            )

        try:
            data = resp.json()
            candidates = data.get('candidates') or []
            if not candidates:
                # Hit a safety filter or empty completion.
                reason = data.get('promptFeedback', {}).get('blockReason')
                self._raise_provider(
                    'Gemini returned no candidates (reason=%s)' % reason,
                    response=resp,
                )
            parts = candidates[0]['content']['parts']
            return ''.join(p.get('text', '') for p in parts).strip()
        except (KeyError, IndexError, ValueError) as e:
            self._raise_provider(
                'Malformed Gemini response: %s' % e, response=resp,
            )

    @staticmethod
    def _to_gemini_contents(messages):
        """OpenAI-style messages → Gemini ``contents`` + system instruction.

        Gemini distinguishes ``user`` and ``model`` roles, and accepts a
        separate top-level ``systemInstruction``. We collect every
        ``system`` message into one instruction blob and translate the
        rest accordingly.
        """
        system_blobs = []
        contents = []
        for m in messages:
            role = m.get('role')
            text = m.get('content') or ''
            if role == 'system':
                system_blobs.append(text)
            elif role == 'assistant':
                contents.append({'role': 'model', 'parts': [{'text': text}]})
            else:  # 'user' or anything else → treat as user
                contents.append({'role': 'user', 'parts': [{'text': text}]})
        return contents, '\n\n'.join(system_blobs) if system_blobs else None
