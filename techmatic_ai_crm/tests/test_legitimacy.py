# -*- coding: utf-8 -*-
"""Tests for lead-legitimacy research.

Two layers covered:
1. Pure Python heuristics (no Odoo / no LLM) — deterministic.
2. Integration through the auto-process cron + orchestrator gate.
"""
import json

from odoo.tests.common import BaseCase

from .common import AICRMTestCase, patched_provider
from ..services import legitimacy


# ---------------------------------------------------------------------------
# Layer 1: pure heuristics
# ---------------------------------------------------------------------------
class TestLegitimacyHeuristics(BaseCase):

    def _fake_lead(self, **overrides):
        """A tiny stand-in for crm.lead — heuristics only touch the
        fields listed below."""
        class _L(object):
            pass
        L = _L()
        L.email_from = overrides.get('email_from', 'jane@acme.com')
        L.phone = overrides.get('phone', '+1 555 1234')
        L.mobile = overrides.get('mobile', '')
        L.partner_name = overrides.get('partner_name', 'Acme Corp')
        L.partner_id = overrides.get('partner_id', None)
        L.country_id = overrides.get('country_id', _stub_country('US'))
        L.description = overrides.get(
            'description',
            'Looking to evaluate your widget line for our 50-unit '
            'procurement in Q1.',
        )
        L.name = overrides.get('name', 'Acme inquiry')
        return L

    def test_disposable_email_is_spam(self):
        lead = self._fake_lead(email_from='throwaway@mailinator.com')
        sigs = legitimacy.collect_signals(lead)
        self.assertIn('disposable_email_provider', sigs['red_flags'])
        verdict, _score, _reason = legitimacy.heuristic_verdict(sigs)
        self.assertEqual(verdict, 'spam')

    def test_malformed_email_is_spam(self):
        lead = self._fake_lead(email_from='not-an-email')
        sigs = legitimacy.collect_signals(lead)
        self.assertIn('malformed_email', sigs['red_flags'])
        verdict, _, _ = legitimacy.heuristic_verdict(sigs)
        self.assertEqual(verdict, 'spam')

    def test_corporate_email_with_full_data_is_trusted(self):
        lead = self._fake_lead(
            email_from='john.smith@acme.com',
            partner_name='Acme',
        )
        sigs = legitimacy.collect_signals(lead)
        self.assertIn('corporate_email_domain', sigs['green_flags'])
        # Email domain matches company name → bonus signal
        self.assertIn('email_domain_matches_company', sigs['green_flags'])
        verdict, score, _ = legitimacy.heuristic_verdict(sigs)
        self.assertIn(verdict, ('trusted', 'verified'))
        self.assertGreaterEqual(score, 70)

    def test_gmail_with_complete_data_is_verified(self):
        lead = self._fake_lead(email_from='jane.smith@gmail.com')
        sigs = legitimacy.collect_signals(lead)
        self.assertIn('free_email_provider', sigs['yellow_flags'])
        # No red flags — should land at 'verified' or 'suspicious' but
        # not 'spam'.
        verdict, _, _ = legitimacy.heuristic_verdict(sigs)
        self.assertIn(verdict, ('verified', 'suspicious'))

    def test_missing_data_is_suspicious(self):
        lead = self._fake_lead(
            email_from='someone@randomdomain.com',
            phone='', partner_name='',
            country_id=None,
            description='hi',
        )
        sigs = legitimacy.collect_signals(lead)
        # Most key fields missing
        self.assertGreaterEqual(len(sigs['yellow_flags']), 3)
        verdict, _, _ = legitimacy.heuristic_verdict(sigs)
        self.assertEqual(verdict, 'suspicious')

    def test_generic_description_flagged(self):
        lead = self._fake_lead(
            description='Just curious — interested in your services.',
        )
        sigs = legitimacy.collect_signals(lead)
        self.assertIn('generic_template_language', sigs['yellow_flags'])

    def test_no_email_is_spam(self):
        lead = self._fake_lead(email_from='')
        sigs = legitimacy.collect_signals(lead)
        self.assertIn('no_email_address', sigs['red_flags'])
        verdict, _, _ = legitimacy.heuristic_verdict(sigs)
        self.assertEqual(verdict, 'spam')


def _stub_country(name):
    """Minimal Country stand-in for the heuristics helper."""
    class _C(object):
        pass
    c = _C()
    c.name = name
    return c


# ---------------------------------------------------------------------------
# Layer 2: integration via auto-process cron
# ---------------------------------------------------------------------------
class TestLegitimacyIntegration(AICRMTestCase):

    def _make_pending(self, **kw):
        defaults = dict(
            name='Pending Lead',
            type='opportunity',
            probability=30,
            expected_revenue=5000,
            user_id=self.user_sales.id,
        )
        defaults.update(kw)
        return self.env['crm.lead'].create(defaults)

    def test_auto_process_populates_legitimacy_fields(self):
        # Lead with a corporate domain → heuristic shortcuts to non-spam,
        # but the LLM still gets called. Stub the LLM response.
        lead = self._make_pending(
            email_from='alex@acme.com',
            partner_name='Acme Corp',
            description='Need 100 units of widget X for Q1 procurement.',
        )
        legitimacy_payload = json.dumps({
            'verdict': 'verified', 'score': 78,
            'notes': 'Corporate domain, specific intent.',
        })
        # Then the auto-process cron also calls summarize/score/suggest,
        # so we need 4 responses queued total.
        fake = self._new_fake(
            legitimacy_payload,
            'Lead summary text.',
            '{"score": 70, "priority":"High","status":"Hot","reason":"ok"}',
            '[]',
        )
        with patched_provider(fake):
            self.env['crm.lead']._cron_process_pending_ai_leads()
        lead.invalidate_recordset()

        self.assertEqual(lead.ai_legitimacy_verdict, 'verified')
        self.assertEqual(lead.ai_legitimacy_score, 78)
        self.assertTrue(lead.ai_legitimacy_notes)
        self.assertTrue(lead.ai_legitimacy_signals)
        self.assertTrue(lead.ai_legitimacy_checked_at)

    def test_disposable_email_shortcuts_to_spam(self):
        """No LLM call needed for disposable-email leads."""
        lead = self._make_pending(email_from='temp@mailinator.com')
        # Even though we queue zero responses for legitimacy, the
        # cron will still call score/suggest/etc. Queue 3 for those.
        fake = self._new_fake(
            'summary',
            '{"score": 5, "priority":"Low","status":"Cold","reason":"x"}',
            '[]',
        )
        with patched_provider(fake):
            self.env['crm.lead']._cron_process_pending_ai_leads()
        lead.invalidate_recordset()

        self.assertEqual(lead.ai_legitimacy_verdict, 'spam')
        # The LLM was NOT called for legitimacy (the heuristic shortcut
        # fired) — so only summarize + score + suggest used responses.
        self.assertEqual(len(fake.calls), 3)

    def test_orchestrator_skips_suspicious_lead(self):
        # Enable orchestrator with a low min_score so the only thing
        # that could block outreach is the legitimacy gate.
        ICP = self.env['ir.config_parameter'].sudo()
        ICP.set_param('techmatic_ai_crm.orchestrator_enabled', 'True')
        ICP.set_param('techmatic_ai_crm.orchestrator_min_score', '0')
        self.user_sales.techmatic_ai_auto_followup_optin = True

        lead = self._make_pending(
            email_from='cust@example.com',
            ai_score=80,
            ai_status='Hot',
            ai_auto_processed=True,
            ai_legitimacy_verdict='suspicious',
            ai_legitimacy_score=20,
            ai_legitimacy_notes='Incomplete data.',
        )

        fake = self._new_fake('should not be called')
        with patched_provider(fake):
            self.env['crm.lead']._cron_run_ai_orchestrator()
        lead.invalidate_recordset()

        # Lead should be handed off, NOT contacted.
        self.assertTrue(lead.ai_handed_off)
        self.assertFalse(lead.ai_outreach_initialized)
        self.assertEqual(len(fake.calls), 0,
                         msg='AI must not be called for flagged leads')
        self.assertIn('suspicious', lead.ai_handoff_reason)

    def test_orchestrator_skips_spam_lead(self):
        ICP = self.env['ir.config_parameter'].sudo()
        ICP.set_param('techmatic_ai_crm.orchestrator_enabled', 'True')
        ICP.set_param('techmatic_ai_crm.orchestrator_min_score', '0')
        self.user_sales.techmatic_ai_auto_followup_optin = True

        lead = self._make_pending(
            email_from='temp@mailinator.com',
            ai_score=10,
            ai_auto_processed=True,
            ai_legitimacy_verdict='spam',
            ai_legitimacy_score=5,
            ai_legitimacy_notes='Disposable email.',
        )
        fake = self._new_fake('should not be called')
        with patched_provider(fake):
            self.env['crm.lead']._cron_run_ai_orchestrator()
        lead.invalidate_recordset()
        self.assertTrue(lead.ai_handed_off)
        self.assertEqual(len(fake.calls), 0)

    def test_orchestrator_proceeds_for_trusted_lead(self):
        ICP = self.env['ir.config_parameter'].sudo()
        ICP.set_param('techmatic_ai_crm.orchestrator_enabled', 'True')
        ICP.set_param('techmatic_ai_crm.orchestrator_min_score', '0')
        self.user_sales.techmatic_ai_auto_followup_optin = True

        lead = self._make_pending(
            email_from='alex@acme.com',
            ai_score=80,
            ai_status='Hot',
            ai_auto_processed=True,
            ai_legitimacy_verdict='trusted',
            ai_legitimacy_score=92,
        )

        outreach = json.dumps({
            'should_send': True,
            'subject': 'Quick question',
            'body_html': '<p>Hi Alex…</p>',
            'reason': 'Strong context',
        })
        with patched_provider(self._new_fake(outreach)):
            self.env['crm.lead']._cron_run_ai_orchestrator()
        lead.invalidate_recordset()

        # Trusted lead → outreach should fire normally.
        self.assertTrue(lead.ai_outreach_initialized)
        self.assertFalse(lead.ai_handed_off)
