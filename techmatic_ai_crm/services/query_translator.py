# -*- coding: utf-8 -*-
"""Natural-language → safe Odoo ORM domain translator.

The CRM Query Assistant lets users type questions like
*"show leads inactive for 10 days"*. We pass the prompt to the LLM and
ask for a STRICT JSON spec describing a read-only ``crm.lead`` query.
The translator then:

* Validates the spec against an allow-list of fields, operators, and
  ordering keys.
* Refuses anything other than ``crm.lead`` (extendable via
  ``ALLOWED_MODELS``).
* Refuses unsafe ops (write/unlink/exec/SQL) outright.

This keeps the ORM the single source of truth and prevents the model
from inventing arbitrary database mutations.
"""
import json
import logging
from datetime import date, timedelta

from .exceptions import AIUnsafeQueryError

_logger = logging.getLogger(__name__)


ALLOWED_MODELS = {'crm.lead'}

ALLOWED_FIELDS = {
    'crm.lead': {
        'name', 'partner_name', 'partner_id', 'email_from', 'phone',
        'stage_id', 'type', 'probability', 'expected_revenue',
        'date_deadline', 'date_open', 'date_closed', 'date_last_stage_update',
        'create_date', 'write_date', 'user_id', 'team_id', 'country_id',
        'tag_ids', 'source_id', 'priority', 'active', 'won_status',
        'ai_score', 'ai_priority', 'ai_status',
    },
}

ALLOWED_OPERATORS = {
    '=', '!=', '>', '>=', '<', '<=', 'in', 'not in',
    'like', 'ilike', 'not ilike', 'child_of', '=?',
}

ALLOWED_ORDER_DIRS = {'asc', 'desc'}

MAX_LIMIT = 200
MAX_DOMAIN_NODES = 30


def build_translator_prompt(user_question):
    """System prompt instructing the LLM to emit a strict JSON spec.

    Kept narrow on purpose — fewer degrees of freedom = fewer ways to
    produce an unsafe spec.
    """
    return (
        'You translate a sales user\'s English question into a STRICT '
        'JSON spec for an Odoo ``crm.lead`` search. NEVER suggest '
        'writes/updates/deletes. JSON schema:\n'
        '{\n'
        '  "model": "crm.lead",\n'
        '  "domain": [<list of triples [field, op, value]>],\n'
        '  "fields": [<field names to show>],\n'
        '  "order": "<field asc|desc>",\n'
        '  "limit": <int 1-200>\n'
        '}\n'
        'Use only these operators: =, !=, >, >=, <, <=, in, not in, '
        'like, ilike, not ilike. For relative dates use ISO strings — '
        'today is computed server-side, you may use the literal token '
        '"__TODAY_MINUS_<N>__" inside a value to mean today minus N '
        'days. Output JSON only, no prose, no markdown.\n\n'
        'Question: ' + (user_question or '')
    )


def parse_spec(raw):
    """Parse the LLM's JSON response. Returns ``dict`` or raises."""
    if not raw:
        raise AIUnsafeQueryError('Empty query spec from AI.')
    text = raw.strip()
    if text.startswith('```'):
        text = text.split('\n', 1)[-1]
        if text.endswith('```'):
            text = text[:-3]
    start, end = text.find('{'), text.rfind('}')
    if start == -1 or end == -1:
        raise AIUnsafeQueryError('AI did not return a JSON object.')
    try:
        return json.loads(text[start:end + 1])
    except ValueError as e:
        raise AIUnsafeQueryError('Malformed JSON from AI: %s' % e) from e


def validate_spec(spec):
    """Strictly validate ``spec``; raise ``AIUnsafeQueryError`` if bad."""
    if not isinstance(spec, dict):
        raise AIUnsafeQueryError('Spec must be a JSON object.')

    model = spec.get('model')
    if model not in ALLOWED_MODELS:
        raise AIUnsafeQueryError('Model %r is not allowed.' % model)

    allowed = ALLOWED_FIELDS[model]
    domain = spec.get('domain') or []
    if not isinstance(domain, list):
        raise AIUnsafeQueryError('"domain" must be a list.')
    if len(domain) > MAX_DOMAIN_NODES:
        raise AIUnsafeQueryError('Domain too large.')
    for node in domain:
        # Logical connectors are fine.
        if isinstance(node, str) and node in ('&', '|', '!'):
            continue
        if not (isinstance(node, (list, tuple)) and len(node) == 3):
            raise AIUnsafeQueryError('Bad domain node: %r' % (node,))
        field, op, _value = node
        if field not in allowed:
            raise AIUnsafeQueryError('Field %r not allowed.' % field)
        if op not in ALLOWED_OPERATORS:
            raise AIUnsafeQueryError('Operator %r not allowed.' % op)

    fields_ = spec.get('fields') or [
        'name', 'partner_id', 'stage_id', 'expected_revenue',
        'user_id', 'date_last_stage_update',
    ]
    for f in fields_:
        if f not in allowed:
            raise AIUnsafeQueryError('Read field %r not allowed.' % f)

    order = spec.get('order') or 'date_last_stage_update desc'
    parts = order.strip().split()
    if not parts or parts[0] not in allowed:
        raise AIUnsafeQueryError('Order field %r not allowed.' % parts)
    if len(parts) > 1 and parts[1].lower() not in ALLOWED_ORDER_DIRS:
        raise AIUnsafeQueryError('Order direction %r not allowed.' % parts[1])

    try:
        limit = int(spec.get('limit') or 50)
    except (TypeError, ValueError):
        raise AIUnsafeQueryError('Bad limit.')
    if limit < 1 or limit > MAX_LIMIT:
        raise AIUnsafeQueryError('Limit out of range.')

    return {
        'model': model,
        'domain': _materialize_tokens(domain),
        'fields': list(fields_),
        'order': order,
        'limit': limit,
    }


def _materialize_tokens(domain):
    """Replace ``__TODAY_MINUS_<N>__`` tokens with real ISO dates.

    Uses naive ``date.today()`` rather than ``fields.Date.context_today``
    because the translator runs without a record context. CRM users
    accept day-level precision; sub-day TZ skew isn't worth a stub.
    """
    today = date.today()
    out = []
    for node in domain:
        if isinstance(node, str):
            out.append(node)
            continue
        field, op, value = node
        if isinstance(value, str) and value.startswith('__TODAY_MINUS_') \
                and value.endswith('__'):
            try:
                days = int(value[len('__TODAY_MINUS_'):-2])
                value = (today - timedelta(days=days)).isoformat()
            except ValueError:
                pass
        out.append([field, op, value])
    return out
