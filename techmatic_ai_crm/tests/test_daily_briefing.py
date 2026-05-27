# -*- coding: utf-8 -*-
"""Tests for the AI daily briefing feature."""
from datetime import date, timedelta

from odoo import fields
from odoo.exceptions import AccessError

from .common import AICRMTestCase, patched_provider


class TestDailyBriefing(AICRMTestCase):

    def _seed_pipeline(self, owner):
        """Build a small mixed pipeline for ``owner`` covering every
        category the composer cares about."""
        Lead = self.env['crm.lead'].with_user(owner)
        # Hot / high probability
        hot = Lead.create({
            'name': 'Acme Corp', 'type': 'opportunity',
            'probability': 90, 'expected_revenue': 50000,
            'ai_status': 'Hot',
        })
        # Closing soon
        closing = Lead.create({
            'name': 'Globex Industries', 'type': 'opportunity',
            'probability': 65, 'expected_revenue': 25000,
        })
        # New lead (created just now)
        new_l = Lead.create({
            'name': 'Stark Enterprises', 'type': 'opportunity',
            'probability': 30, 'expected_revenue': 15000,
        })
        # Cold lead — backdate date_last_stage_update via raw SQL.
        # Must flush_all() BEFORE the UPDATE so the next ORM op can't
        # overwrite our backdated value from cached pending writes; and
        # invalidate_all() AFTER so all readers re-fetch from DB.
        cold = Lead.create({
            'name': 'Wayne Industries', 'type': 'opportunity',
            'probability': 40, 'expected_revenue': 10000,
        })
        self.env.flush_all()
        old = fields.Datetime.now() - timedelta(days=20)
        self.env.cr.execute(
            "UPDATE crm_lead SET date_last_stage_update=%s WHERE id=%s",
            (old, cold.id),
        )
        self.env.invalidate_all()
        return hot + closing + new_l + cold

    # ------------------------------------------------------------------
    def test_compose_briefing_returns_html_and_count(self):
        from ..services.ai_service import AIService
        # ``setUpClass`` already seeded one lead for user_sales; we add 4
        # more below — composer counts every open opportunity assigned
        # to the user.
        Lead = self.env['crm.lead'].sudo()
        baseline_count = Lead.search_count([
            ('user_id', '=', self.user_sales.id),
            ('active', '=', True),
            ('probability', '<', 100),
            ('probability', '>', 0),
        ])
        seeded = self._seed_pipeline(self.user_sales)

        fake = self._new_fake('<h3>Today\'s focus</h3><p>Hot leads first.</p>')
        with patched_provider(fake):
            result = AIService(self.env).compose_daily_briefing(self.user_sales)

        body = result['body_html']
        self.assertTrue(body, 'Body should not be empty')
        self.assertTrue(
            '<h3>' in body or '<p>' in body,
            msg='Body should contain HTML tags, got: %r' % body[:80],
        )
        self.assertEqual(result['lead_count'], baseline_count + len(seeded))

    def test_compose_briefing_with_empty_pipeline(self):
        from ..services.ai_service import AIService
        # The shared lead from setUpClass belongs to self.user_sales —
        # use a fresh user with zero leads.
        Users = self.env['res.users'].with_context(no_reset_password=True)
        empty_user = Users.create({
            'name': 'Empty Pipeline User',
            'login': 'empty_pipe',
            'email': 'empty_pipe@example.com',
            'group_ids': [(4, self.group_user.id)],
        })
        # No provider call should be made when there are no leads.
        fake = self._new_fake()
        with patched_provider(fake):
            result = AIService(self.env).compose_daily_briefing(empty_user)
        self.assertEqual(result['lead_count'], 0)
        self.assertEqual(len(fake.calls), 0,
                         msg='Empty pipeline → no provider call')

    def test_compose_briefing_categorizes_in_python(self):
        """The LLM should receive a categorized snapshot, NOT raw rows —
        we verify by inspecting the prompt that was sent."""
        from ..services.ai_service import AIService
        self._seed_pipeline(self.user_sales)
        fake = self._new_fake('<p>briefing</p>')
        with patched_provider(fake):
            AIService(self.env).compose_daily_briefing(self.user_sales)
        # First call: messages = [system, user]
        messages, _kw = fake.calls[0]
        user_prompt = messages[1]['content']
        # The prompt should mention category headers.
        self.assertIn('Hot', user_prompt)
        self.assertIn('Closing Soon', user_prompt)
        # Lead names should be referenced.
        self.assertIn('Acme Corp', user_prompt)
        # The Cold category header is present even though the cold
        # lead's stage date was just backdated.
        self.assertIn('Cold', user_prompt)

    def test_action_generate_my_briefing_creates_record(self):
        Briefing = self.env['techmatic.ai.daily.briefing']
        self._seed_pipeline(self.user_sales)
        fake = self._new_fake('<h3>Day plan</h3>')
        with patched_provider(fake):
            action = Briefing.with_user(
                self.user_sales).action_generate_my_briefing()
        self.assertEqual(action['type'], 'ir.actions.act_window')
        b = Briefing.with_user(self.user_sales).browse(action['res_id'])
        self.assertEqual(b.state, 'generated')
        self.assertEqual(b.user_id, self.user_sales)
        self.assertEqual(b.briefing_date, fields.Date.context_today(b))
        self.assertTrue(b.body_html)

    def test_action_generate_my_briefing_is_idempotent_per_day(self):
        """Calling it twice in the same day updates the existing row,
        does not create a duplicate (sql_constraint enforces this)."""
        Briefing = self.env['techmatic.ai.daily.briefing']
        self._seed_pipeline(self.user_sales)
        fake = self._new_fake('<p>v1</p>', '<p>v2</p>')
        with patched_provider(fake):
            a1 = Briefing.with_user(
                self.user_sales).action_generate_my_briefing()
            a2 = Briefing.with_user(
                self.user_sales).action_generate_my_briefing()
        self.assertEqual(a1['res_id'], a2['res_id'])
        b = Briefing.with_user(self.user_sales).browse(a1['res_id'])
        b.invalidate_recordset()
        self.assertIn('v2', b.body_html)

    def test_action_regenerate_owner_only(self):
        Briefing = self.env['techmatic.ai.daily.briefing']
        self._seed_pipeline(self.user_sales)
        fake = self._new_fake('<p>first</p>')
        with patched_provider(fake):
            action = Briefing.with_user(
                self.user_sales).action_generate_my_briefing()
        # Build a second sales user — they shouldn't be able to
        # regenerate someone else's briefing.
        Users = self.env['res.users'].with_context(no_reset_password=True)
        other = Users.create({
            'name': 'Other Sales',
            'login': 'briefing_other',
            'email': 'briefing_other@example.com',
            'group_ids': [(4, self.group_user.id)],
        })
        # The record rule already hides the other user's briefing from
        # ``other`` — ``browse`` returns an empty recordset on read.
        visible = Briefing.with_user(other).search([('id', '=', action['res_id'])])
        self.assertFalse(visible, 'Record rule should hide other-user briefings.')

    def test_cron_skips_users_already_briefed(self):
        Briefing = self.env['techmatic.ai.daily.briefing']
        self._seed_pipeline(self.user_sales)
        today = fields.Date.context_today(Briefing)
        # Seed a "generated" briefing for today.
        Briefing.create({
            'user_id': self.user_sales.id,
            'briefing_date': today,
            'title': 'pre-existing',
            'body_html': '<p>existing</p>',
            'state': 'generated',
            'lead_count': 4,
        })
        fake = self._new_fake('<p>new</p>')
        with patched_provider(fake):
            Briefing._cron_generate_daily_briefings()
        # No additional briefing should have been created for today.
        count_today = Briefing.search_count([
            ('user_id', '=', self.user_sales.id),
            ('briefing_date', '=', today),
        ])
        self.assertEqual(count_today, 1)

    def test_cron_records_failure_per_user(self):
        from ..services.exceptions import AIProviderError

        Briefing = self.env['techmatic.ai.daily.briefing']
        self._seed_pipeline(self.user_sales)

        class _Boom(type(self._new_fake())):
            def _chat(self_inner, messages, **kw):
                raise AIProviderError('upstream 500')

        with patched_provider(_Boom()):
            Briefing._cron_generate_daily_briefings()

        failed = Briefing.search([
            ('user_id', '=', self.user_sales.id),
            ('state', '=', 'failed'),
        ], limit=1)
        self.assertTrue(failed)
        self.assertIn('upstream', failed.error_message or '')
