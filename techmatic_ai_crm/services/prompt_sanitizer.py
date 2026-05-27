# -*- coding: utf-8 -*-
"""Prompt sanitization utilities.

Goal: keep the system-prompt boundary intact and strip the easiest
prompt-injection vectors before any user-controlled text reaches the
provider.

This is defense in depth, not a silver bullet. Providers themselves are
the final authority — we only enforce hygiene we can guarantee locally.
"""
import re
import logging

from .exceptions import AIUnsafePromptError

_logger = logging.getLogger(__name__)

# Patterns we strip outright. These commonly appear in injection attempts
# trying to dissolve the system prompt or impersonate the operator.
_BANNED_PATTERNS = [
    re.compile(r'(?i)ignore (all|previous|above) instructions'),
    re.compile(r'(?i)disregard (all|previous|above) (instructions|prompts)'),
    re.compile(r'(?i)you are now [a-z ]{0,40}(dan|jailbroken|unfiltered)'),
    re.compile(r'(?i)system\s*:\s*'),
    re.compile(r'(?i)</?(system|assistant|user)>'),
    re.compile(r'(?i)reveal (the )?(system )?prompt'),
]

# Control characters (except tab/newline) → drop. Reduces invisible
# Unicode-tag smuggling attacks.
_CTRL_CHARS = re.compile(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]')

# Hard caps so a runaway lead description can't blow our token budget
# or DoS the provider.
DEFAULT_MAX_INPUT_CHARS = 12000


def sanitize(text, max_chars=DEFAULT_MAX_INPUT_CHARS, raise_on_block=False):
    """Return a sanitized copy of ``text`` safe to embed in a prompt.

    :param str text: untrusted user / record content
    :param int max_chars: hard truncation cap
    :param bool raise_on_block: if True, raise ``AIUnsafePromptError``
        instead of silently stripping injection patterns. Use this on
        the natural-language query endpoint where intent matters.
    :returns: cleaned text (never None)
    """
    if not text:
        return ''
    if not isinstance(text, str):
        text = str(text)

    cleaned = _CTRL_CHARS.sub('', text)

    blocked = False
    for pat in _BANNED_PATTERNS:
        if pat.search(cleaned):
            blocked = True
            cleaned = pat.sub('[redacted]', cleaned)

    if blocked:
        _logger.warning('Prompt sanitizer redacted injection-like pattern.')
        if raise_on_block:
            raise AIUnsafePromptError(
                'Input contains patterns that look like prompt injection.'
            )

    if len(cleaned) > max_chars:
        cleaned = cleaned[:max_chars] + '\n...[truncated]'

    return cleaned.strip()


def sanitize_record_text(record, fields):
    """Concatenate selected ``fields`` from ``record`` into a single
    sanitized blob suitable for system-prompt context injection.
    """
    parts = []
    for fname in fields:
        val = record[fname] if fname in record._fields else False
        if not val:
            continue
        if hasattr(val, 'ids'):  # recordset → display name list
            val = ', '.join(val.mapped('display_name'))
        parts.append('%s: %s' % (fname, val))
    return sanitize('\n'.join(parts))
