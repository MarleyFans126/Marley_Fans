# -*- coding: utf-8 -*-
"""Domain exceptions for the AI service layer.

These are kept separate from ``odoo.exceptions`` so the service layer
remains decoupled from the Odoo runtime where reasonable; controllers /
models translate them into ``UserError`` / ``ValidationError`` as needed.
"""


class AIError(Exception):
    """Base class for all AI provider / orchestration errors."""


class AIConfigurationError(AIError):
    """Misconfigured provider, missing API key, unknown model, etc."""


class AIProviderError(AIError):
    """Provider returned a non-OK HTTP response or malformed payload."""


class AIRateLimitError(AIError):
    """Local rate limiter (or upstream 429) refused the request."""


class AIUnsafePromptError(AIError):
    """Sanitizer detected a prompt-injection / unsafe input pattern."""


class AIUnsafeQueryError(AIError):
    """Natural-language query translator produced an unsafe domain."""
