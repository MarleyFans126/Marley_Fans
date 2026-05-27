# -*- coding: utf-8 -*-
"""Tests for Flavor-3 auto follow-up emails.

Verifies every guardrail in isolation:
  * Master switch off → no sends.
  * Per-user opt-in off → no sends for that user.
  * AI score above threshold → skipped.
  * Recently active lead → skipped.
  * Tagged lead → skipped.
  * Daily per-user cap → enforced.
  * 14-day cooldown → enforced.
  * Successful run → audit log + chatter post + mail.mail dispatch.
"""
from datetime import timedelta

from odoo import fields

from .common import AICRMTestCase, patched_provider


class TestAutoFollowup(AICRMTestCase):

    def _enable_master(self, **overrides):
        """Flip the master switch and write guardrail values."""
        ICP = self.env['ir.config_parameter'].sudo()
        ICP.set_param('techmatic_ai_crm.auto_followup_enabled', 'True')
        ICP.set_param('techmatic_ai_crm.auto_followup_max_score',
                      str(overrides.get('max_score', 30)))
        ICP.set_param('techmatic_ai_crm.auto_followup_inactive_days',
                      str(overrides.get('inactive_days', 7)))
        ICP.set_param('techmatic_ai_crm.auto_followup_per_user_cap',
                      str(overrides.get('per_user_cap', 5)))
        ICP.set_param('techmatic_ai_crm.auto_followup_skip_tags',
                      overrides.get('skip_tags',
                                    'vip,manual-only,do-not-contact'))

    def _make_eligible_lead(self, owner=None, score=20):
        """Build a lead that passes every guardrail by default."""
        owner = owner or self.user_sales
        owner.techmatic_ai_auto_followup_optin = True
        Lead = self.env['crm.lead']
        lead = Lead.with_user(owner).create({
            'name': 'Cold Lead Ltd',
            'type': 'opportunity',
            'email_from': 'cold@example.com',
            'probability': 20,
            'ai_score': score,
            'ai_status': 'Cold',
        })
        # Flush pending ORM writes BEFORE the raw UPDATE — otherwise
        # the cache flush at the next ORM op will overwrite our
        # backdated write_date with ``now`` from cache.
        self.env.flush_all()
        old = fields.Datetime.now() - timedelta(days=30)
        self.env.cr.execute(
            "UPDATE crm_lead SET write_date=%s WHERE id=%s",
            (old, lead.id),
        )
        # ``invalidate_all`` wipes the entire ORM cache (not just this
        # record) — needed when callers create multiple leads in a row,
        # since each subsequent create() would otherwise flush stale
        # write_dates back over our backdates.
        self.env.invalidate_all()
        return lead

    # ------------------------------------------------------------------
    def test_master_switch_off_skips_everything(self):
        self.env['ir.config_parameter'].sudo().set_param(
            'techmatic_ai_crm.auto_followup_enabled', 'False',
        )
        lead = self._make_eligible_lead()
        fake = self._new_fake('reply body')
        with patched_provider(fake):
            self.env['crm.lead']._cron_auto_send_followups()
        # No provider call, no log entry.
        self.assertEqual(len(fake.calls), 0)
        Log = self.env['techmatic.ai.auto.followup.log'].sudo()
        self.assertFalse(Log.search([('lead_id', '=', lead.id)]))

    def test_user_optin_required(self):
        self._enable_master()
        lead = self._make_eligible_lead()
        # Revoke opt-in after lead creation.
        self.user_sales.techmatic_ai_auto_followup_optin = False
        fake = self._new_fake('reply body')
        with patched_provider(fake):
            self.env['crm.lead']._cron_auto_send_followups()
        Log = self.env['techmatic.ai.auto.followup.log'].sudo()
        self.assertFalse(Log.search([('lead_id', '=', lead.id)]))

    def test_high_score_lead_skipped(self):
        self._enable_master(max_score=30)
        lead = self._make_eligible_lead(score=60)
        fake = self._new_fake('reply body')
        with patched_provider(fake):
            self.env['crm.lead']._cron_auto_send_followups()
        Log = self.env['techmatic.ai.auto.followup.log'].sudo()
        self.assertFalse(Log.search([('lead_id', '=', lead.id)]))

    def test_recently_active_lead_skipped(self):
        self._enable_master(inactive_days=7)
        lead = self._make_eligible_lead()
        # Touch the lead so write_date is "now".
        lead.write({'description': 'just touched'})
        fake = self._new_fake('reply body')
        with patched_provider(fake):
            self.env['crm.lead']._cron_auto_send_followups()
        Log = self.env['techmatic.ai.auto.followup.log'].sudo()
        self.assertFalse(Log.search([('lead_id', '=', lead.id)]))

    def test_tagged_lead_skipped(self):
        self._enable_master(skip_tags='vip,manual-only')
        lead = self._make_eligible_lead()
        Tag = self.env['crm.tag']
        vip_tag = Tag.create({'name': 'VIP'})
        lead.tag_ids = [(4, vip_tag.id)]
        fake = self._new_fake('reply body')
        with patched_provider(fake):
            self.env['crm.lead']._cron_auto_send_followups()
        Log = self.env['techmatic.ai.auto.followup.log'].sudo()
        self.assertFalse(Log.search([('lead_id', '=', lead.id)]))

    def test_per_user_cap_enforced(self):
        self._enable_master(per_user_cap=2)
        # Create 5 eligible leads — cap should limit sends to 2.
        leads = self.env['crm.lead']
        for i in range(5):
            leads += self._make_eligible_lead()
        fake = self._new_fake(*['reply body'] * 5)
        with patched_provider(fake):
            self.env['crm.lead']._cron_auto_send_followups()
        Log = self.env['techmatic.ai.auto.followup.log'].sudo()
        sent = Log.search([
            ('user_id', '=', self.user_sales.id),
            ('success', '=', True),
        ])
        self.assertEqual(len(sent), 2)

    def test_cooldown_blocks_resend(self):
        self._enable_master()
        lead = self._make_eligible_lead()
        # Pre-seed a successful log entry from yesterday.
        Log = self.env['techmatic.ai.auto.followup.log'].sudo()
        Log.create({
            'lead_id': lead.id,
            'user_id': self.user_sales.id,
            'email_to': lead.email_from,
            'subject': 'old send',
            'sent_at': fields.Datetime.now() - timedelta(days=1),
            'success': True,
        })
        fake = self._new_fake('reply body')
        with patched_provider(fake):
            self.env['crm.lead']._cron_auto_send_followups()
        # No new send — only the pre-seeded log remains.
        self.assertEqual(
            Log.search_count([('lead_id', '=', lead.id)]), 1,
        )

    def test_successful_send_logs_audit_and_posts_chatter(self):
        self._enable_master()
        lead = self._make_eligible_lead()
        before_msgs = self.env['mail.message'].search_count([
            ('model', '=', 'crm.lead'), ('res_id', '=', lead.id),
        ])
        fake = self._new_fake('Friendly follow-up body.')
        with patched_provider(fake):
            self.env['crm.lead']._cron_auto_send_followups()

        Log = self.env['techmatic.ai.auto.followup.log'].sudo()
        log_rec = Log.search([('lead_id', '=', lead.id)], limit=1)
        self.assertTrue(log_rec)
        # Mail dispatched (mail.mail row exists for this lead).
        mail = self.env['mail.mail'].sudo().search([
            ('model', '=', 'crm.lead'), ('res_id', '=', lead.id),
        ], limit=1)
        self.assertTrue(mail)
        self.assertEqual(mail.email_to, lead.email_from)
        # Lead chatter has a new entry.
        after_msgs = self.env['mail.message'].search_count([
            ('model', '=', 'crm.lead'), ('res_id', '=', lead.id),
        ])
        self.assertGreater(after_msgs, before_msgs)
        # Score + inactivity snapshot stored.
        self.assertEqual(log_rec.score_at_send, 20)
        self.assertGreaterEqual(log_rec.days_inactive_at_send, 7)

    def test_unscored_lead_never_sent(self):
        """``ai_score == 0`` (never scored) should be skipped — the cron
        only acts on leads that have been deliberately characterized."""
        self._enable_master()
        lead = self._make_eligible_lead(score=0)
        fake = self._new_fake('reply')
        with patched_provider(fake):
            self.env['crm.lead']._cron_auto_send_followups()
        Log = self.env['techmatic.ai.auto.followup.log'].sudo()
        self.assertFalse(Log.search([('lead_id', '=', lead.id)]))

    def test_lead_without_email_skipped(self):
        self._enable_master()
        lead = self._make_eligible_lead()
        # Remove the email — should now be skipped at the domain level.
        lead.email_from = False
        fake = self._new_fake('reply')
        with patched_provider(fake):
            self.env['crm.lead']._cron_auto_send_followups()
        Log = self.env['techmatic.ai.auto.followup.log'].sudo()
        self.assertFalse(Log.search([('lead_id', '=', lead.id)]))
