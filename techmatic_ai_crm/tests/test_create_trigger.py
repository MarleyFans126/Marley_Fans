# -*- coding: utf-8 -*-
"""Tests for the create-time auto-process trigger.

When a new lead is created, ``crm.lead.create()`` should nudge the
auto-process cron via ``_trigger()`` so the AI work runs on the next
cron heartbeat (usually within 60s) instead of waiting for the next
scheduled interval.
"""
from unittest.mock import patch

from .common import AICRMTestCase


class TestCreateTriggersCron(AICRMTestCase):

    def _cron(self):
        return self.env.ref('techmatic_ai_crm.cron_auto_process_leads')

    def test_create_triggers_cron_when_active(self):
        """An active cron should receive a ``_trigger()`` call when a
        lead is created with ``ai_auto_processed`` defaulting False."""
        # Make sure the cron is active for this test.
        self._cron().active = True
        with patch.object(
                type(self._cron()), '_trigger', autospec=True
        ) as mock_trigger:
            self.env['crm.lead'].create({
                'name': 'Fresh Lead',
                'type': 'opportunity',
                'email_from': 'new@example.com',
                'probability': 30,
            })
        self.assertTrue(
            mock_trigger.called,
            msg='cron._trigger() should fire after lead creation.',
        )

    def test_create_does_not_trigger_when_cron_inactive(self):
        """A disabled cron should NOT be poked — wastes a row in
        ir_cron_trigger and creates noise in deployments that have
        intentionally turned off auto-processing."""
        self._cron().active = False
        with patch.object(
                type(self._cron()), '_trigger', autospec=True
        ) as mock_trigger:
            self.env['crm.lead'].create({
                'name': 'No-Trigger Lead',
                'type': 'opportunity',
                'email_from': 'nope@example.com',
            })
        self.assertFalse(
            mock_trigger.called,
            msg='Inactive cron should not be triggered.',
        )

    def test_create_does_not_trigger_when_already_processed(self):
        """If the create payload already has ``ai_auto_processed=True``
        (typical for tests / bulk imports of pre-enriched leads), we
        shouldn't waste a cron tick."""
        self._cron().active = True
        with patch.object(
                type(self._cron()), '_trigger', autospec=True
        ) as mock_trigger:
            self.env['crm.lead'].create({
                'name': 'Pre-Enriched Lead',
                'type': 'opportunity',
                'ai_auto_processed': True,
            })
        self.assertFalse(
            mock_trigger.called,
            msg='Pre-processed lead should not poke the cron.',
        )

    def test_bulk_create_triggers_once(self):
        """``create([vals1, vals2, vals3])`` should trigger the cron
        ONCE, not three times — the cron is a batch processor anyway."""
        self._cron().active = True
        with patch.object(
                type(self._cron()), '_trigger', autospec=True
        ) as mock_trigger:
            self.env['crm.lead'].create([
                {'name': 'A', 'type': 'opportunity'},
                {'name': 'B', 'type': 'opportunity'},
                {'name': 'C', 'type': 'opportunity'},
            ])
        # Exactly one trigger call regardless of batch size.
        self.assertEqual(mock_trigger.call_count, 1)

    def test_create_failure_does_not_break_lead(self):
        """If ``_trigger()`` raises (cron table corrupted, registry
        signal issue, etc.) the lead creation must still succeed —
        AI enrichment is best-effort, never a blocker."""
        self._cron().active = True
        with patch.object(
                type(self._cron()), '_trigger', autospec=True,
                side_effect=RuntimeError('cron table angry'),
        ):
            lead = self.env['crm.lead'].create({
                'name': 'Resilient Lead',
                'type': 'opportunity',
            })
        # Lead exists and is in the pending queue for the regular
        # cron tick to pick up.
        self.assertTrue(lead.id)
        self.assertFalse(lead.ai_auto_processed)
