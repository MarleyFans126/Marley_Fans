# -*- coding: utf-8 -*-
"""Group gating and record-rule tests."""
from odoo.exceptions import AccessError, UserError

from .common import AICRMTestCase, patched_provider


class TestSecurity(AICRMTestCase):

    def test_outsider_cannot_use_ai_buttons(self):
        # An outsider with no AI group must be blocked by ``_check_ai_user``.
        with self.assertRaises(UserError):
            self.lead.with_user(self.user_outsider).action_generate_ai_summary()

    def test_sales_user_can_use_ai_buttons(self):
        fake = self._new_fake('Summary text.')
        with patched_provider(fake):
            self.lead.with_user(self.user_sales).action_generate_ai_summary()
        self.lead.invalidate_recordset()
        self.assertEqual(self.lead.ai_summary, 'Summary text.')

    def test_admin_can_use_ai_buttons(self):
        fake = self._new_fake('Admin summary.')
        with patched_provider(fake):
            self.lead.with_user(self.user_admin).action_generate_ai_summary()
        self.lead.invalidate_recordset()
        self.assertEqual(self.lead.ai_summary, 'Admin summary.')

    def test_sales_user_blocked_from_settings_save(self):
        # Give the sales user just enough power to OPEN settings (the
        # standard Odoo ``base.group_system``), but NOT our AI admin
        # group. ``_check_admin`` must still slam the door.
        sys_user = self.user_sales.copy({
            'login': 'ai_sales_sys',
            'email': 'ai_sales_sys@example.com',
            'group_ids': [
                (4, self.group_user.id),
                (4, self.env.ref('base.group_system').id),
            ],
        })
        Settings = self.env['res.config.settings'].with_user(sys_user)
        cfg = Settings.create({})
        with self.assertRaises(AccessError):
            cfg.set_values()

    def test_admin_can_save_settings(self):
        Settings = self.env['res.config.settings'].with_user(self.user_admin)
        cfg = Settings.create({})
        # Should NOT raise.
        cfg.set_values()

    def test_session_record_rule_isolates_users(self):
        """User A cannot read user B's chat sessions through the ORM."""
        # User-sales creates their own session.
        own = self.env['techmatic.ai.chat.session'].with_user(
            self.user_sales).create({})

        # Build a second sales user.
        Users = self.env['res.users'].with_context(no_reset_password=True)
        other_user = Users.create({
            'name': 'Second Sales',
            'login': 'ai_sales_user_x',
            'email': 'ai_sales_user_x@example.com',
            'group_ids': [(4, self.group_user.id)],
        })
        sessions_visible_to_other = self.env[
            'techmatic.ai.chat.session'
        ].with_user(other_user).search([('id', '=', own.id)])
        self.assertFalse(sessions_visible_to_other,
                         msg='Record rule should hide other users\' sessions.')

    def test_admin_can_see_all_sessions(self):
        own = self.env['techmatic.ai.chat.session'].with_user(
            self.user_sales).create({})
        visible = self.env[
            'techmatic.ai.chat.session'
        ].with_user(self.user_admin).search([('id', '=', own.id)])
        self.assertTrue(visible)
