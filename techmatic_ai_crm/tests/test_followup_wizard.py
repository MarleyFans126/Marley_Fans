# -*- coding: utf-8 -*-
"""Tests for the AI follow-up email wizard."""
from odoo.exceptions import UserError

from .common import AICRMTestCase, patched_provider


class TestFollowupWizard(AICRMTestCase):

    def _open_wizard(self, body='Hello,\nFollow-up draft body.\n— sales'):
        fake = self._new_fake(body)
        with patched_provider(fake):
            wiz = self.env['techmatic.ai.followup.wizard'].with_user(
                self.user_sales).create({'lead_id': self.lead.id})
        return wiz

    def test_create_prefills_body(self):
        wiz = self._open_wizard()
        self.assertTrue(wiz.body)
        self.assertEqual(wiz.state, 'ready')

    def test_action_send_logs_to_chatter(self):
        wiz = self._open_wizard()
        before = self.env['mail.message'].search_count([
            ('model', '=', 'crm.lead'), ('res_id', '=', self.lead.id),
        ])
        result = wiz.action_send()
        after = self.env['mail.message'].search_count([
            ('model', '=', 'crm.lead'), ('res_id', '=', self.lead.id),
        ])
        self.assertGreater(after, before)
        self.assertEqual(result['type'], 'ir.actions.act_window_close')

    def test_action_send_refuses_empty(self):
        wiz = self._open_wizard(body='')
        wiz.body = ''
        with self.assertRaises(UserError):
            wiz.action_send()

    def test_send_email_flag_creates_mail(self):
        # Lead must have an outbound email for the mail.mail row to be made.
        wiz = self._open_wizard()
        wiz.send_email = True
        wiz.action_send()
        mail = self.env['mail.mail'].sudo().search([
            ('model', '=', 'crm.lead'), ('res_id', '=', self.lead.id),
        ], limit=1)
        self.assertTrue(mail)
        self.assertEqual(mail.email_to, self.lead.email_from)

    def test_regenerate_replaces_body(self):
        wiz = self._open_wizard(body='draft v1')
        first = wiz.body
        # The next call should pull a different canned response.
        fake = self._new_fake('completely new draft v2')
        with patched_provider(fake):
            wiz.action_regenerate()
        self.assertNotEqual(wiz.body, first)
        self.assertIn('v2', wiz.body)
