# -*- coding: utf-8 -*-
"""Stop non-admin users from editing or deleting chatter messages / log notes.

Only administrators (Settings group) can edit a message's content or delete
a message. Automated / system writes (read receipts, starring, notification
status, message creation via message_post, etc.) are NOT affected — only a
genuine content edit ('body' in vals) or a delete is blocked.
"""
from odoo import models, _
from odoo.exceptions import AccessError


class MailMessage(models.Model):
    _inherit = 'mail.message'

    def _marley_is_admin(self):
        return self.env.su or self.env.user.has_group('base.group_system')

    def write(self, vals):
        # Block content edits (the pencil "Edit" on a log note) for non-admins.
        if 'body' in vals and not self._marley_is_admin():
            raise AccessError(_(
                "Editing messages / log notes is restricted to administrators."
            ))
        return super().write(vals)

    def unlink(self):
        if not self._marley_is_admin():
            raise AccessError(_(
                "Deleting messages / log notes is restricted to administrators."
            ))
        return super().unlink()
