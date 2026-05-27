# -*- coding: utf-8 -*-
"""OpenAI Chat Completions provider.

Uses the public /v1/chat/completions endpoint (compatible with most
OpenAI-compatible gateways such as Azure OpenAI proxies and Together).
"""
import logging

from .ai_provider import AIProvider
from .exceptions import AIProviderError

_logger = logging.getLogger(__name__)

DEFAULT_ENDPOINT = 'https://api.openai.com/v1/chat/completions'


class OpenAIProvider(AIProvider):
    name = 'openai'

    def __init__(self, config):
        super().__init__(config)
        self.endpoint = config.get('endpoint') or DEFAULT_ENDPOINT

    def _chat(self, messages, **kwargs):
        requests = self._require_requests()
        payload = {
            'model': self.model,
            'messages': messages,
            'temperature': kwargs.get('temperature', self.temperature),
            'max_tokens': kwargs.get('max_tokens', self.max_tokens),
        }
        headers = {
            'Authorization': 'Bearer %s' % self.api_key,
            'Content-Type': 'application/json',
        }
        try:
            resp = requests.post(
                self.endpoint, json=payload, headers=headers,
                timeout=self.timeout,
            )
        except requests.RequestException as e:
            raise AIProviderError(
                'OpenAI request failed: %s' % e
            ) from e

        if resp.status_code != 200:
            self._raise_provider(
                'OpenAI HTTP %s' % resp.status_code, response=resp,
            )

        try:
            data = resp.json()
            return data['choices'][0]['message']['content'].strip()
        except (KeyError, IndexError, ValueError) as e:
            self._raise_provider(
                'Malformed OpenAI response: %s' % e, response=resp,
            )
