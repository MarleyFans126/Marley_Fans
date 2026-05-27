# -*- coding: utf-8 -*-
"""Tests for the AI Orchestrator (the full agent loop).

State machine covered:
    score < min     → no outreach
    score >= min    → STEP 1: initial outreach sent
    outreach sent + customer replies + within max → STEP 2: AI reply
    >= max exchanges                              → handoff, no more sends
    inbound matches skip keyword (out of office)  → immediate handoff
    AI returns should_send=False                  → handoff with reason
"""
import json

from odoo import fields

from .common import AICRMTestCase, patched_provider


class TestOrchestrator(AICRMTestCase):

    def _enable(self, **overrides):
        ICP = self.env['ir.config_parameter'].sudo()
        ICP.set_param('techmatic_ai_crm.orchestrator_enabled', 'True')
        ICP.set_param('techmatic_ai_crm.orchestrator_min_score',
                      str(overrides.get('min_score', 50)))
        ICP.set_param('techmatic_ai_crm.orchestrator_max_exchanges',
                      str(overrides.get('max_exchanges', 3)))
        ICP.set_param('techmatic_ai_crm.orchestrator_skip_keywords',
                      overrides.get('skip_keywords',
                                    'out of office,unsubscribe,no-reply'))

    def _make_ready_lead(self, score=70):
        """Build a lead that's already been scored and is ready for the
        orchestrator's first step (initial outreach)."""
        self.user_sales.techmatic_ai_auto_followup_optin = True
        lead = self.env['crm.lead'].create({
            'name': 'Orchestrator Test Lead',
            'type': 'opportunity',
            'email_from': 'cust@example.com',
            'probability': 30,
            'ai_score': score,
            'ai_status': 'Hot' if score >= 70 else 'Warm',
            'ai_auto_processed': True,
            'user_id': self.user_sales.id,
        })
        return lead

    # ------------------------------------------------------------------
    # STEP 1 — initial outreach
    # ------------------------------------------------------------------
    def test_master_switch_off_skips_everything(self):
        self.env['ir.config_parameter'].sudo().set_param(
            'techmatic_ai_crm.orchestrator_enabled', 'False')
        lead = self._make_ready_lead()
        fake = self._new_fake()
        with patched_provider(fake):
            self.env['crm.lead']._cron_run_ai_orchestrator()
        # No provider call, no state change.
        self.assertEqual(len(fake.calls), 0)
        self.assertFalse(lead.ai_outreach_initialized)

    def test_low_score_lead_skipped(self):
        self._enable(min_score=50)
        lead = self._make_ready_lead(score=30)
        fake = self._new_fake()
        with patched_provider(fake):
            self.env['crm.lead']._cron_run_ai_orchestrator()
        self.assertEqual(len(fake.calls), 0)
        self.assertFalse(lead.ai_outreach_initialized)

    def test_initial_outreach_sent_for_qualifying_lead(self):
        self._enable()
        lead = self._make_ready_lead(score=80)
        payload = json.dumps({
            'should_send': True,
            'subject': 'Quick question about your interest',
            'body_html': '<p>Hi, saw you reached out — one quick question?</p>',
            'reason': 'Lead context strong',
        })
        fake = self._new_fake(payload)
        with patched_provider(fake):
            self.env['crm.lead']._cron_run_ai_orchestrator()
        lead.invalidate_recordset()
        self.assertTrue(lead.ai_outreach_initialized)
        self.assertEqual(lead.ai_outreach_count, 1)
        self.assertTrue(lead.ai_last_outbound_at)
        # Audit row with initial_outreach trigger.
        Log = self.env['techmatic.ai.auto.followup.log'].sudo()
        log_row = Log.search([
            ('lead_id', '=', lead.id),
            ('trigger_type', '=', 'initial_outreach'),
        ], limit=1)
        self.assertTrue(log_row)
        self.assertTrue(log_row.success)

    def test_ai_declines_outreach_triggers_handoff(self):
        self._enable()
        lead = self._make_ready_lead()
        payload = json.dumps({
            'should_send': False,
            'subject': '', 'body_html': '',
            'reason': 'Lead description is empty',
        })
        fake = self._new_fake(payload)
        with patched_provider(fake):
            self.env['crm.lead']._cron_run_ai_orchestrator()
        lead.invalidate_recordset()
        self.assertFalse(lead.ai_outreach_initialized)
        self.assertTrue(lead.ai_handed_off)
        self.assertIn('Lead description is empty', lead.ai_handoff_reason)

    def test_user_optin_required(self):
        self._enable()
        lead = self._make_ready_lead()
        # Revoke opt-in.
        self.user_sales.techmatic_ai_auto_followup_optin = False
        fake = self._new_fake('should not be called')
        with patched_provider(fake):
            self.env['crm.lead']._cron_run_ai_orchestrator()
        self.assertEqual(len(fake.calls), 0)
        self.assertFalse(lead.ai_outreach_initialized)

    # ------------------------------------------------------------------
    # STEP 2 — inbound reply
    # ------------------------------------------------------------------
    def _simulate_customer_reply(self, lead, body='Tell me more please.'):
        """Post an inbound email from a customer partner."""
        Partner = self.env['res.partner']
        cust = Partner.search([('email', '=', lead.email_from)], limit=1)
        if not cust:
            cust = Partner.sudo().create({
                'name': 'Customer Person',
                'email': lead.email_from,
            })
        # Ensure ``user_ids`` is empty so the orchestrator's filter
        # ``not author_id.user_ids`` treats this as an external sender.
        return lead.sudo().message_post(
            body=body,
            author_id=cust.id,
            message_type='email',
            subtype_xmlid='mail.mt_comment',
        )

    def test_ai_replies_to_customer_message(self):
        self._enable()
        lead = self._make_ready_lead()
        # Walk lead through initial outreach.
        outreach = json.dumps({
            'should_send': True, 'subject': 'Hi',
            'body_html': '<p>Initial outreach.</p>',
            'reason': 'ok',
        })
        with patched_provider(self._new_fake(outreach)):
            self.env['crm.lead']._cron_run_ai_orchestrator()
        lead.invalidate_recordset()
        self.assertTrue(lead.ai_outreach_initialized)

        # Customer replies.
        self._simulate_customer_reply(lead, 'Interested — when can we chat?')
        # AI generates a reply.
        reply = json.dumps({
            'should_send': True,
            'body_html': '<p>Great — Tuesday works.</p>',
            'reason': 'Simple scheduling',
        })
        with patched_provider(self._new_fake(reply)):
            self.env['crm.lead']._cron_run_ai_orchestrator()
        lead.invalidate_recordset()

        # Counters bumped, audit row created with inbound_reply trigger.
        self.assertEqual(lead.ai_outreach_count, 2)
        self.assertEqual(lead.ai_inbound_count, 1)
        Log = self.env['techmatic.ai.auto.followup.log'].sudo()
        inbound_logs = Log.search([
            ('lead_id', '=', lead.id),
            ('trigger_type', '=', 'inbound_reply'),
            ('success', '=', True),
        ])
        self.assertEqual(len(inbound_logs), 1)

    def test_skip_keyword_triggers_handoff(self):
        self._enable(skip_keywords='out of office')
        lead = self._make_ready_lead()
        with patched_provider(self._new_fake(json.dumps({
            'should_send': True, 'subject': 'Hi',
            'body_html': '<p>Initial.</p>', 'reason': 'ok',
        }))):
            self.env['crm.lead']._cron_run_ai_orchestrator()
        # Customer auto-reply: out of office.
        self._simulate_customer_reply(
            lead, 'I am out of office until next Monday — please retry.'
        )
        # The reply step should NOT call AI, just hand off.
        fake = self._new_fake('should not be invoked')
        with patched_provider(fake):
            self.env['crm.lead']._cron_run_ai_orchestrator()
        lead.invalidate_recordset()
        self.assertTrue(lead.ai_handed_off)
        self.assertEqual(len(fake.calls), 0)

    def test_max_exchanges_caps_loop(self):
        self._enable(max_exchanges=2)
        lead = self._make_ready_lead()
        # Pre-set state as if we've already done 2 exchanges.
        lead.write({
            'ai_outreach_initialized': True,
            'ai_outreach_count': 2,
            'ai_inbound_count': 2,
            'ai_last_outbound_at': fields.Datetime.now(),
        })
        self._simulate_customer_reply(lead, 'One more thing...')
        fake = self._new_fake('should not be called')
        with patched_provider(fake):
            self.env['crm.lead']._cron_run_ai_orchestrator()
        lead.invalidate_recordset()
        # Should hand off, NOT send another reply.
        self.assertTrue(lead.ai_handed_off)
        self.assertEqual(len(fake.calls), 0)
        self.assertIn('max', lead.ai_handoff_reason.lower())

    def test_dedupe_does_not_double_reply(self):
        self._enable()
        lead = self._make_ready_lead()
        # Initial outreach.
        with patched_provider(self._new_fake(json.dumps({
            'should_send': True, 'subject': 'Hi',
            'body_html': '<p>Initial.</p>', 'reason': 'ok',
        }))):
            self.env['crm.lead']._cron_run_ai_orchestrator()
        # ONE customer reply.
        self._simulate_customer_reply(lead, 'Hi back.')
        # First cron run after the reply: AI responds.
        with patched_provider(self._new_fake(json.dumps({
            'should_send': True,
            'body_html': '<p>Thanks.</p>',
            'reason': 'simple',
        }))):
            self.env['crm.lead']._cron_run_ai_orchestrator()
        # Second cron run with NO new customer reply: should be a no-op.
        fake = self._new_fake('should not be called')
        with patched_provider(fake):
            self.env['crm.lead']._cron_run_ai_orchestrator()
        # AI must NOT have been called the second time.
        self.assertEqual(len(fake.calls), 0)
        lead.invalidate_recordset()
        # Counters reflect a single round trip on top of initial outreach.
        self.assertEqual(lead.ai_outreach_count, 2)
        self.assertEqual(lead.ai_inbound_count, 1)
