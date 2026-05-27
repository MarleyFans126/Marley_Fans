# -*- coding: utf-8 -*-
"""Tests for the ``crm.lead`` AI extensions: buttons, fields, cron."""
import json
from datetime import timedelta

from odoo import fields

from .common import AICRMTestCase, patched_provider


class TestCrmLeadAI(AICRMTestCase):

    def test_action_generate_ai_summary_writes_fields(self):
        fake = self._new_fake('AI summary body.')
        with patched_provider(fake):
            self.lead.with_user(self.user_sales).action_generate_ai_summary()
        self.lead.invalidate_recordset()
        self.assertEqual(self.lead.ai_summary, 'AI summary body.')
        self.assertTrue(self.lead.ai_summary_date)

    def test_action_generate_ai_score_clamps_and_validates(self):
        # Wild model output: score outside range, bogus priority and status.
        bad = json.dumps({
            'score': 250, 'priority': 'Crazy',
            'status': 'Boiling', 'reason': 'x' * 1000,
        })
        fake = self._new_fake(bad)
        with patched_provider(fake):
            self.lead.with_user(self.user_sales).action_generate_ai_score()
        self.lead.invalidate_recordset()
        self.assertEqual(self.lead.ai_score, 100)               # clamped
        self.assertEqual(self.lead.ai_priority, 'Low')          # defaulted
        self.assertEqual(self.lead.ai_status, 'Cold')           # defaulted
        self.assertLessEqual(len(self.lead.ai_score_reason or ''), 255)

    def test_action_open_followup_wizard_returns_action(self):
        action = self.lead.with_user(
            self.user_sales).action_open_followup_wizard()
        self.assertEqual(action['type'], 'ir.actions.act_window')
        self.assertEqual(action['res_model'], 'techmatic.ai.followup.wizard')
        self.assertEqual(action['context']['default_lead_id'], self.lead.id)
        self.assertEqual(action['target'], 'new')

    def test_action_generate_ai_activities_populates_json(self):
        fake = self._new_fake(
            '[{"action":"call","summary":"Ring","due_in_days":2}]'
        )
        with patched_provider(fake):
            self.lead.with_user(
                self.user_sales).action_generate_ai_activities()
        self.lead.invalidate_recordset()
        data = json.loads(self.lead.ai_suggested_actions)
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]['action'], 'call')

    def test_cron_skips_recently_updated_leads(self):
        # Make the lead look "fresh" — cron should not re-score it.
        fake = self._new_fake(
            '{"score": 10, "priority":"Low","status":"Cold","reason":"x"}'
        )
        # Force a high score first to detect a change later.
        self.lead.write({'ai_score': 99, 'ai_priority': 'High',
                         'ai_status': 'Hot'})
        with patched_provider(fake):
            self.env['crm.lead']._cron_score_active_leads(limit=10)
        self.lead.invalidate_recordset()
        # Recent write_date + non-zero score → skipped.
        self.assertEqual(self.lead.ai_score, 99)

    def test_cron_rescores_stale_leads(self):
        # Make the lead's write_date old to force re-scoring.
        old = fields.Datetime.now() - timedelta(days=2)
        self.env.cr.execute(
            "UPDATE crm_lead SET write_date=%s WHERE id=%s",
            (old, self.lead.id),
        )
        self.lead.invalidate_recordset()
        fake = self._new_fake(
            '{"score": 42, "priority":"Medium","status":"Warm","reason":"x"}'
        )
        with patched_provider(fake):
            self.env['crm.lead']._cron_score_active_leads(limit=10)
        self.lead.invalidate_recordset()
        self.assertEqual(self.lead.ai_score, 42)
        self.assertEqual(self.lead.ai_status, 'Warm')

    def test_cron_isolates_failures(self):
        """One bad lead must not poison the whole batch."""
        from ..services.exceptions import AIProviderError

        good = self.env['crm.lead'].create({
            'name': 'Other Lead', 'type': 'opportunity', 'probability': 50.0,
        })
        # Force both leads to be eligible.
        old = fields.Datetime.now() - timedelta(days=2)
        self.env.cr.execute(
            "UPDATE crm_lead SET write_date=%s WHERE id IN %s",
            (old, tuple([self.lead.id, good.id])),
        )

        calls = {'n': 0}

        def flaky_score(self_, lead):
            # ``patch.object`` installs this as an unbound function,
            # which Python re-binds as a method — hence ``self_, lead``.
            calls['n'] += 1
            if calls['n'] == 1:
                raise AIProviderError('upstream 500')
            return {'score': 70, 'priority': 'High',
                    'status': 'Hot', 'reason': 'ok'}

        # Patch the high-level score_lead so we control per-lead results.
        from unittest.mock import patch as _patch
        with _patch(
            'odoo.addons.techmatic_ai_crm.services.ai_service.AIService.score_lead',
            new=flaky_score,
        ):
            self.env['crm.lead']._cron_score_active_leads(limit=10)
        # Exactly one of them got updated.
        updated = self.env['crm.lead'].search([
            ('id', 'in', [self.lead.id, good.id]),
            ('ai_score', '=', 70),
        ])
        self.assertEqual(len(updated), 1)
