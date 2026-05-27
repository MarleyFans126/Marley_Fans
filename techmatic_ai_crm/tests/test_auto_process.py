# -*- coding: utf-8 -*-
"""Tests for the auto-process-on-pipeline-entry cron.

Verifies:
  * Cron processes pending leads end-to-end (summary + score + activities).
  * Master switch off → cron is a no-op.
  * Manual button runs set ``ai_auto_processed=True`` so the cron skips them.
  * Already-processed leads are not re-run.
  * Per-lead failure does not poison the batch.
  * Batch size knob is respected.
"""
import json

from odoo import fields

from .common import AICRMTestCase, patched_provider


class TestAutoProcessCron(AICRMTestCase):

    def _make_pending_lead(self, name='Pending Lead'):
        # Owned by user_sales so the CRM record rule lets them read it
        # when the manual-button tests run ``with_user(self.user_sales)``.
        return self.env['crm.lead'].create({
            'name': name,
            'type': 'opportunity',
            'probability': 30,
            'expected_revenue': 5000,
            'description': 'Customer interested in widgets.',
            'user_id': self.user_sales.id,
        })

    def test_cron_processes_pending_lead_end_to_end(self):
        lead = self._make_pending_lead()
        # Brand-new lead → cron has not run yet.
        self.assertFalse(lead.ai_auto_processed)
        self.assertFalse(lead.ai_summary)
        self.assertEqual(lead.ai_score, 0)

        # Provider returns: summary text, then scoring JSON, then
        # activity-suggestion JSON array — in that order, matching the
        # cron's call sequence.
        fake = self._new_fake(
            'Auto-generated summary.',
            json.dumps({
                'score': 72, 'priority': 'High',
                'status': 'Hot', 'reason': 'Hot signals',
            }),
            json.dumps([
                {'action': 'call', 'summary': 'Ring back',
                 'due_in_days': 1},
            ]),
        )
        with patched_provider(fake):
            self.env['crm.lead']._cron_process_pending_ai_leads()
        lead.invalidate_recordset()

        self.assertTrue(lead.ai_auto_processed)
        self.assertEqual(lead.ai_summary, 'Auto-generated summary.')
        self.assertEqual(lead.ai_score, 72)
        self.assertEqual(lead.ai_status, 'Hot')
        self.assertEqual(lead.ai_priority, 'High')
        actions = json.loads(lead.ai_suggested_actions or '[]')
        self.assertEqual(len(actions), 1)
        self.assertEqual(actions[0]['action'], 'call')

    def test_already_processed_lead_skipped(self):
        lead = self._make_pending_lead()
        lead.ai_auto_processed = True   # pretend cron ran already
        lead.ai_summary = 'OLD'

        fake = self._new_fake()  # nothing queued
        with patched_provider(fake):
            self.env['crm.lead']._cron_process_pending_ai_leads()
        # Provider was not called.
        self.assertEqual(len(fake.calls), 0)
        lead.invalidate_recordset()
        self.assertEqual(lead.ai_summary, 'OLD')

    def test_master_switch_off_skips_cron(self):
        self.env['ir.config_parameter'].sudo().set_param(
            'techmatic_ai_crm.auto_process_enabled', 'False',
        )
        lead = self._make_pending_lead()
        fake = self._new_fake('should not be used')
        with patched_provider(fake):
            self.env['crm.lead']._cron_process_pending_ai_leads()
        # No provider call, lead untouched.
        self.assertEqual(len(fake.calls), 0)
        self.assertFalse(lead.ai_auto_processed)

    def test_manual_summary_marks_processed(self):
        lead = self._make_pending_lead()
        fake = self._new_fake('Manual summary text.')
        with patched_provider(fake):
            lead.with_user(self.user_sales).action_generate_ai_summary()
        lead.invalidate_recordset()
        # Manual button has marked the lead processed — so the auto
        # cron won't re-touch it.
        self.assertTrue(lead.ai_auto_processed)

    def test_manual_score_marks_processed(self):
        lead = self._make_pending_lead()
        fake = self._new_fake(
            '{"score": 50, "priority":"Medium","status":"Warm","reason":"x"}'
        )
        with patched_provider(fake):
            lead.with_user(self.user_sales).action_generate_ai_score()
        lead.invalidate_recordset()
        self.assertTrue(lead.ai_auto_processed)

    def test_manual_activities_marks_processed(self):
        lead = self._make_pending_lead()
        fake = self._new_fake('[{"action":"call","summary":"x","due_in_days":1}]')
        with patched_provider(fake):
            lead.with_user(self.user_sales).action_generate_ai_activities()
        lead.invalidate_recordset()
        self.assertTrue(lead.ai_auto_processed)

    def test_one_lead_failure_does_not_poison_batch(self):
        """If lead A fails during scoring, lead B should still get
        processed in the same cron run."""
        from ..services.exceptions import AIProviderError

        lead_a = self._make_pending_lead('A')
        lead_b = self._make_pending_lead('B')

        # Set up provider so lead A's score call raises, but everything
        # else returns valid JSON. The cron call order per lead is:
        # summary, score, activities. Two leads × 3 calls = 6 expected.
        # Make the 2nd call (lead A's score) raise.
        from unittest.mock import patch

        from ..services import ai_service as ai_service_mod

        call_count = {'n': 0}
        original_score = ai_service_mod.AIService.score_lead

        def flaky_score(self_inner, lead_inner):
            call_count['n'] += 1
            if call_count['n'] == 1:
                raise AIProviderError('upstream 500')
            return {'score': 80, 'priority': 'High',
                    'status': 'Hot', 'reason': 'ok'}

        fake = self._new_fake(
            'sum A', 'sum B',  # summaries always succeed
            '[]', '[]',         # activity calls always succeed
        )
        # Patch score_lead specifically.
        with patched_provider(fake), patch.object(
                ai_service_mod.AIService, 'score_lead', new=flaky_score,
        ):
            self.env['crm.lead']._cron_process_pending_ai_leads()

        lead_a.invalidate_recordset()
        lead_b.invalidate_recordset()
        # Lead A: scoring failed → should NOT be marked processed
        #         (so the next cron tick retries it).
        self.assertFalse(lead_a.ai_auto_processed)
        # Lead B: succeeded → marked processed.
        self.assertTrue(lead_b.ai_auto_processed)
        self.assertEqual(lead_b.ai_score, 80)

    def test_batch_size_caps_processing(self):
        ICP = self.env['ir.config_parameter'].sudo()
        ICP.set_param('techmatic_ai_crm.auto_process_batch_size', '2')

        # 4 pending leads, cap = 2 → first two get processed, last
        # two stay pending for the next run.
        leads = self.env['crm.lead']
        for i in range(4):
            leads += self._make_pending_lead('Pending %s' % i)

        # Queue 6 fake responses (2 leads × 3 calls). After 2 leads,
        # the cron stops.
        fake = self._new_fake(
            'sum 1', '{"score": 10, "priority":"Low","status":"Cold","reason":"x"}', '[]',
            'sum 2', '{"score": 20, "priority":"Low","status":"Cold","reason":"x"}', '[]',
        )
        with patched_provider(fake):
            self.env['crm.lead']._cron_process_pending_ai_leads()

        leads.invalidate_recordset()
        processed = leads.filtered(lambda l: l.ai_auto_processed)
        self.assertEqual(len(processed), 2)
