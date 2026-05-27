# -*- coding: utf-8 -*-
"""AI service layer.

Loaded BEFORE ``models`` so the registry can import provider classes
during ORM bootstrapping. Adding a new provider only requires:

1. Subclass ``AIProvider`` in ``services/<name>_provider.py``.
2. Register it in ``AIService.PROVIDERS``.
"""
from . import exceptions
from . import prompt_sanitizer
from . import rate_limiter
from . import ai_provider
from . import openai_provider
from . import gemini_provider
from . import claude_provider
from . import legitimacy
from . import web_research
from . import ai_service
from . import query_translator
