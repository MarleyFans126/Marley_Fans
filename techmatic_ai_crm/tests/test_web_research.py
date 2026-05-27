# -*- coding: utf-8 -*-
"""Tests for company web research.

Layered:
1. Pure-Python primitives (no Odoo, no network): domain_from_email,
   _is_safe_ip, extract_text.
2. SSRF guard: fetch attempts against private IPs raise.
3. Integration through the auto-process cron: writes fields, posts
   chatter, with the HTTP layer mocked.
"""
from unittest.mock import patch, MagicMock

from odoo.tests.common import BaseCase

from .common import AICRMTestCase, patched_provider
from ..services import web_research


# ---------------------------------------------------------------------------
# Layer 1 — pure primitives
# ---------------------------------------------------------------------------
class TestWebResearchPrimitives(BaseCase):

    def test_domain_from_email_corporate(self):
        self.assertEqual(
            web_research.domain_from_email('alex@anvil-corp.com'),
            'anvil-corp.com',
        )

    def test_domain_from_email_skips_gmail(self):
        self.assertIsNone(
            web_research.domain_from_email('someone@gmail.com'),
        )

    def test_domain_from_email_skips_disposable(self):
        self.assertIsNone(
            web_research.domain_from_email('x@mailinator.com'),
        )

    def test_domain_from_email_skips_malformed(self):
        self.assertIsNone(web_research.domain_from_email('not-an-email'))
        self.assertIsNone(web_research.domain_from_email(''))
        self.assertIsNone(web_research.domain_from_email(None))

    def test_domain_from_email_lowercases_and_strips(self):
        self.assertEqual(
            web_research.domain_from_email('  Alex@Anvil-Corp.Com  '),
            'anvil-corp.com',
        )

    def test_is_safe_ip_blocks_loopback(self):
        self.assertFalse(web_research._is_safe_ip('127.0.0.1'))
        self.assertFalse(web_research._is_safe_ip('::1'))

    def test_is_safe_ip_blocks_private(self):
        for ip in ('10.0.0.1', '172.16.0.1', '192.168.1.1'):
            self.assertFalse(web_research._is_safe_ip(ip), msg=ip)

    def test_is_safe_ip_blocks_link_local_metadata(self):
        # AWS metadata endpoint
        self.assertFalse(web_research._is_safe_ip('169.254.169.254'))

    def test_is_safe_ip_allows_public(self):
        for ip in ('8.8.8.8', '1.1.1.1'):
            self.assertTrue(web_research._is_safe_ip(ip), msg=ip)

    def test_extract_text_strips_scripts(self):
        html = (
            '<html><head><script>evil()</script><style>body{x}</style>'
            '</head><body><h1>Acme Corp</h1><p>We make widgets.</p>'
            '</body></html>'
        )
        text = web_research.extract_text(html)
        self.assertIn('Acme Corp', text)
        self.assertIn('We make widgets.', text)
        self.assertNotIn('evil()', text)
        self.assertNotIn('body{x}', text)

    def test_extract_text_decodes_entities(self):
        html = '<p>Acme &amp; Co.&nbsp;Ltd</p>'
        text = web_research.extract_text(html)
        self.assertIn('Acme & Co.', text)


# ---------------------------------------------------------------------------
# Layer 2 — SSRF guard
# ---------------------------------------------------------------------------
class TestWebResearchSsrfGuard(BaseCase):

    def test_resolve_safely_refuses_private(self):
        with patch('socket.gethostbyname', return_value='10.0.0.5'):
            with self.assertRaises(RuntimeError) as cm:
                web_research._resolve_safely('internal.host')
        self.assertIn('non-public', str(cm.exception))

    def test_resolve_safely_refuses_loopback(self):
        with patch('socket.gethostbyname', return_value='127.0.0.1'):
            with self.assertRaises(RuntimeError):
                web_research._resolve_safely('localhost')

    def test_resolve_safely_refuses_metadata_endpoint(self):
        with patch('socket.gethostbyname', return_value='169.254.169.254'):
            with self.assertRaises(RuntimeError):
                web_research._resolve_safely('attacker.com')

    def test_resolve_safely_allows_public(self):
        with patch('socket.gethostbyname', return_value='8.8.8.8'):
            # Should not raise
            web_research._resolve_safely('example.com')

    def test_fetch_homepage_refuses_private_target(self):
        """End-to-end: a domain that resolves private should fail."""
        with patch('socket.gethostbyname', return_value='10.0.0.1'):
            with self.assertRaises(RuntimeError):
                web_research.fetch_homepage('internal-app.local')


# ---------------------------------------------------------------------------
# Layer 3 — integration via auto-process cron
# ---------------------------------------------------------------------------
class TestWebResearchIntegration(AICRMTestCase):

    def _make_lead(self, **kw):
        defaults = dict(
            name='Web Research Lead',
            type='opportunity',
            probability=30,
            user_id=self.user_sales.id,
        )
        defaults.update(kw)
        return self.env['crm.lead'].create(defaults)

    def _mock_homepage(self, html, final_url='https://acmecorp.com/'):
        """Build a mock for ``web_research.fetch_homepage`` returning
        a fixed response — bypasses the real network entirely."""
        def fake_fetch(domain):
            return final_url, html
        return patch.object(web_research, 'fetch_homepage', side_effect=fake_fetch)

    def test_auto_process_runs_web_research_for_corporate_lead(self):
        lead = self._make_lead(
            email_from='cto@acmecorp.com',
            description='Need procurement for Q1.',
        )
        # Fake provider responses needed in order:
        #   legitimacy (LLM, since not disposable),
        #   web research (LLM summary),
        #   summarize, score, suggest
        import json as _json
        fake = self._new_fake(
            _json.dumps({'verdict': 'verified', 'score': 70,
                         'notes': 'Corporate email.'}),
            'Acme Corp builds industrial widgets — 40 employees in Pune.',
            'Lead summary.',
            '{"score": 60, "priority":"Medium","status":"Warm","reason":"ok"}',
            '[]',
        )
        html = (
            '<html><body><h1>Acme Corp</h1>'
            '<p>We build industrial widgets for the manufacturing sector. '
            'Founded 2010 in Pune. 40 employees.</p></body></html>'
        )
        with patched_provider(fake), self._mock_homepage(html):
            self.env['crm.lead']._cron_process_pending_ai_leads()
        lead.invalidate_recordset()

        self.assertEqual(lead.ai_company_research_status, 'completed')
        self.assertEqual(lead.ai_company_website, 'https://acmecorp.com/')
        self.assertIn('widgets', lead.ai_company_summary.lower())
        self.assertTrue(lead.ai_company_research_date)

    def test_auto_process_skips_web_for_gmail_lead(self):
        lead = self._make_lead(email_from='alice@gmail.com')
        # No web call expected. Provide responses for legitimacy LLM +
        # summary + score + activities. Legitimacy passes because gmail
        # isn't disposable.
        import json as _json
        fake = self._new_fake(
            _json.dumps({'verdict': 'verified', 'score': 60,
                         'notes': 'Public domain but OK.'}),
            'summary', '{"score": 50, "priority":"Medium","status":"Warm","reason":"x"}',
            '[]',
        )
        # No mock needed — fetch_homepage should never be called.
        with patched_provider(fake):
            with patch.object(web_research, 'fetch_homepage') as mock_fetch:
                self.env['crm.lead']._cron_process_pending_ai_leads()
                mock_fetch.assert_not_called()
        lead.invalidate_recordset()
        self.assertEqual(lead.ai_company_research_status, 'skipped')
        self.assertFalse(lead.ai_company_summary)
        self.assertIn('Free', lead.ai_company_research_reason or '')

    def test_auto_process_handles_network_failure_gracefully(self):
        lead = self._make_lead(email_from='alex@unreachable-corp.com')
        import json as _json
        # Legitimacy + (no web brief LLM because fetch fails before LLM)
        # + summary + score + activities = 4 LLM calls expected.
        fake = self._new_fake(
            _json.dumps({'verdict': 'verified', 'score': 65,
                         'notes': 'Corporate.'}),
            'summary',
            '{"score": 50, "priority":"Medium","status":"Warm","reason":"x"}',
            '[]',
        )
        def boom(domain):
            raise RuntimeError('Connection timed out')
        with patched_provider(fake), \
                patch.object(web_research, 'fetch_homepage', side_effect=boom):
            self.env['crm.lead']._cron_process_pending_ai_leads()
        lead.invalidate_recordset()
        # Failure recorded, but the rest of the auto-process pipeline
        # still completed.
        self.assertEqual(lead.ai_company_research_status, 'failed')
        self.assertIn('Connection timed out',
                      lead.ai_company_research_reason or '')
        # Score and summary still got written.
        self.assertEqual(lead.ai_score, 50)
        self.assertTrue(lead.ai_summary)

    def test_auto_process_handles_thin_content(self):
        """Site returns text under the 50-char threshold → status=failed."""
        lead = self._make_lead(email_from='hello@thinco.com')
        import json as _json
        fake = self._new_fake(
            _json.dumps({'verdict': 'verified', 'score': 60,
                         'notes': 'OK.'}),
            'summary',
            '{"score": 50, "priority":"Medium","status":"Warm","reason":"x"}',
            '[]',
        )
        # Almost-empty homepage (post-strip).
        with patched_provider(fake), \
                self._mock_homepage('<html><body>Hi</body></html>'):
            self.env['crm.lead']._cron_process_pending_ai_leads()
        lead.invalidate_recordset()
        self.assertEqual(lead.ai_company_research_status, 'failed')
        self.assertIn('no usable text', lead.ai_company_research_reason or '')
