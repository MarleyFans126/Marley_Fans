# -*- coding: utf-8 -*-
"""Pure unit tests for the natural-language query translator."""
import json
from datetime import date, timedelta

from odoo.tests.common import BaseCase

from ..services import query_translator as qt
from ..services.exceptions import AIUnsafeQueryError


class TestQueryTranslator(BaseCase):

    # --- parse_spec ---------------------------------------------------------

    def test_parse_spec_strips_markdown_fences(self):
        raw = '```json\n{"model": "crm.lead", "domain": [], "limit": 5}\n```'
        spec = qt.parse_spec(raw)
        self.assertEqual(spec['model'], 'crm.lead')

    def test_parse_spec_rejects_empty(self):
        with self.assertRaises(AIUnsafeQueryError):
            qt.parse_spec('')

    def test_parse_spec_rejects_non_json(self):
        with self.assertRaises(AIUnsafeQueryError):
            qt.parse_spec('definitely not json')

    # --- validate_spec ------------------------------------------------------

    def test_rejects_unknown_model(self):
        with self.assertRaises(AIUnsafeQueryError):
            qt.validate_spec({'model': 'res.users', 'domain': []})

    def test_rejects_unknown_field(self):
        with self.assertRaises(AIUnsafeQueryError):
            qt.validate_spec({
                'model': 'crm.lead',
                'domain': [['secret_field', '=', 1]],
            })

    def test_rejects_unsafe_operator(self):
        with self.assertRaises(AIUnsafeQueryError):
            qt.validate_spec({
                'model': 'crm.lead',
                'domain': [['name', 'inselect', 'x']],   # not in allow-list
            })

    def test_rejects_oversized_domain(self):
        big = [['name', '=', 'x']] * (qt.MAX_DOMAIN_NODES + 1)
        with self.assertRaises(AIUnsafeQueryError):
            qt.validate_spec({'model': 'crm.lead', 'domain': big})

    def test_rejects_oversized_limit(self):
        with self.assertRaises(AIUnsafeQueryError):
            qt.validate_spec({
                'model': 'crm.lead', 'domain': [],
                'limit': qt.MAX_LIMIT + 1,
            })

    def test_rejects_disallowed_read_field(self):
        with self.assertRaises(AIUnsafeQueryError):
            qt.validate_spec({
                'model': 'crm.lead', 'domain': [],
                'fields': ['secret_field'],
            })

    def test_rejects_disallowed_order_field(self):
        with self.assertRaises(AIUnsafeQueryError):
            qt.validate_spec({
                'model': 'crm.lead', 'domain': [],
                'order': 'secret_field desc',
            })

    def test_accepts_minimal_valid_spec(self):
        out = qt.validate_spec({
            'model': 'crm.lead',
            'domain': [['probability', '<', 100]],
        })
        self.assertEqual(out['model'], 'crm.lead')
        self.assertEqual(out['limit'], 50)
        self.assertIn('order', out)
        self.assertTrue(isinstance(out['fields'], list))

    def test_logical_connectors_allowed(self):
        out = qt.validate_spec({
            'model': 'crm.lead',
            'domain': ['|', ['name', '=', 'a'], ['name', '=', 'b']],
        })
        self.assertEqual(out['domain'][0], '|')

    # --- _materialize_tokens ------------------------------------------------

    def test_today_minus_token_resolves_to_iso_date(self):
        out = qt.validate_spec({
            'model': 'crm.lead',
            'domain': [['date_open', '<', '__TODAY_MINUS_10__']],
        })
        expected = (date.today() - timedelta(days=10)).isoformat()
        self.assertEqual(out['domain'][0][2], expected)

    def test_translator_prompt_includes_question(self):
        msg = qt.build_translator_prompt('Show me hot leads')
        self.assertIn('Show me hot leads', msg)
        self.assertIn('STRICT JSON', msg)
