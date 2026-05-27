# -*- coding: utf-8 -*-
"""Tests for the NL → ORM query wizard."""
import json

from odoo.exceptions import UserError

from .common import AICRMTestCase, patched_provider


class TestQueryWizard(AICRMTestCase):

    def test_empty_question_raises(self):
        wiz = self.env['techmatic.ai.query.wizard'].with_user(
            self.user_sales).create({'question': '   '})
        with self.assertRaises(UserError):
            wiz.action_run()

    def test_valid_spec_runs_and_returns_action(self):
        spec = {
            'model': 'crm.lead',
            'domain': [['probability', '<', 100]],
            'fields': ['name', 'probability'],
            'order': 'date_last_stage_update desc',
            'limit': 10,
        }
        fake = self._new_fake(json.dumps(spec))
        wiz = self.env['techmatic.ai.query.wizard'].with_user(
            self.user_sales).create({'question': 'show open leads'})
        with patched_provider(fake):
            action = wiz.action_run()
        self.assertEqual(action['type'], 'ir.actions.act_window')
        self.assertIn(('id', 'in'), [(d[0], d[1]) for d in action['domain']])
        wiz.invalidate_recordset()
        self.assertEqual(wiz.state, 'done')
        self.assertGreaterEqual(wiz.result_count, 1)

    def test_unsafe_field_raises(self):
        # The wizard rolls back its own state mutation when it raises
        # — the public contract is the UserError, not the state field.
        bad_spec = {
            'model': 'crm.lead',
            'domain': [['nonexistent_field', '=', 1]],
            'limit': 5,
        }
        fake = self._new_fake(json.dumps(bad_spec))
        wiz = self.env['techmatic.ai.query.wizard'].with_user(
            self.user_sales).create({'question': 'evil'})
        with patched_provider(fake):
            with self.assertRaises(UserError):
                wiz.action_run()

    def test_unknown_model_raises(self):
        bad_spec = {'model': 'res.users', 'domain': [], 'limit': 5}
        fake = self._new_fake(json.dumps(bad_spec))
        wiz = self.env['techmatic.ai.query.wizard'].with_user(
            self.user_sales).create({'question': 'dump users'})
        with patched_provider(fake):
            with self.assertRaises(UserError):
                wiz.action_run()
