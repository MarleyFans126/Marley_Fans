# -*- coding: utf-8 -*-
"""Tests for AI chat sessions and messages."""
from odoo.exceptions import AccessError

from .common import AICRMTestCase, patched_provider


class TestAiChatSession(AICRMTestCase):

    def test_post_user_message_creates_pair(self):
        session = self.env['techmatic.ai.chat.session'].with_user(
            self.user_sales).create({})
        fake = self._new_fake('Assistant reply text.')
        with patched_provider(fake):
            assistant = session.post_user_message('Hi there', lead_id=self.lead.id)
        session.invalidate_recordset()
        # One user + one assistant message.
        roles = session.message_ids.sorted('create_date').mapped('role')
        self.assertEqual(roles, ['user', 'assistant'])
        self.assertEqual(assistant.body, 'Assistant reply text.')
        # Lead linkage was populated by the call.
        self.assertEqual(session.lead_id, self.lead)

    def test_title_auto_set_from_first_message(self):
        session = self.env['techmatic.ai.chat.session'].with_user(
            self.user_sales).create({})
        original = session.title
        fake = self._new_fake('reply')
        with patched_provider(fake):
            session.post_user_message('summarize my pipeline')
        session.invalidate_recordset()
        self.assertNotEqual(session.title, original)
        self.assertIn('summarize', session.title.lower())

    def test_long_first_message_truncates_title(self):
        session = self.env['techmatic.ai.chat.session'].with_user(
            self.user_sales).create({})
        fake = self._new_fake('reply')
        with patched_provider(fake):
            session.post_user_message('x' * 120)
        session.invalidate_recordset()
        self.assertLessEqual(len(session.title), 65)

    def test_owner_check_blocks_other_user(self):
        sess_user = self.env['techmatic.ai.chat.session'].with_user(
            self.user_sales).create({})
        # A different sales user tries to talk in someone else's session.
        Users = self.env['res.users'].with_context(no_reset_password=True)
        other = Users.create({
            'name': 'Other Sales',
            'login': 'ai_sales_user_2',
            'email': 'ai_sales_user_2@example.com',
            'group_ids': [(4, self.group_user.id)],
        })
        with self.assertRaises(AccessError):
            sess_user.with_user(other).post_user_message('hello')

    def test_message_history_passed_to_provider(self):
        """The 12-most-recent-message window must include the system prompt."""
        session = self.env['techmatic.ai.chat.session'].with_user(
            self.user_sales).create({'lead_id': self.lead.id})
        fake = self._new_fake('reply')
        with patched_provider(fake):
            session.post_user_message('first turn')
            session.post_user_message('second turn')

        # Second call: messages should include the first user + assistant turn.
        second_messages, _ = fake.calls[-1]
        roles = [m['role'] for m in second_messages]
        self.assertEqual(roles[0], 'system')
        self.assertIn('user', roles)
        self.assertIn('assistant', roles)
