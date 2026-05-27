# -*- coding: utf-8 -*-
"""res.users extension — per-user opt-in for AI auto follow-ups.

Auto follow-up is a **two-gate** feature:

1. Admin enables the master switch in CRM Settings.
2. Each salesperson explicitly opts in via their Preferences page.

The cron skips users who haven't opted in even if the master switch
is on. This avoids the "my boss turned this on for the whole org and
now my leads are getting weird emails I didn't write" failure mode.
"""
from odoo import fields, models


class ResUsers(models.Model):
    _inherit = 'res.users'

    techmatic_ai_auto_followup_optin = fields.Boolean(
        string='AI Auto Follow-Up Opt-In',
        default=False,
        help='When checked, the AI cron may automatically send follow-up '
             'emails to YOUR cold leads (subject to admin guardrails and '
             'the per-user daily cap). When unchecked, no email is sent '
             'on your behalf without your manual click. Default: off.',
    )

    @property
    def SELF_READABLE_FIELDS(self):
        """Allow the user to read their own opt-in flag without admin
        privileges (Odoo whitelists self-readable user fields)."""
        return super().SELF_READABLE_FIELDS + ['techmatic_ai_auto_followup_optin']

    @property
    def SELF_WRITEABLE_FIELDS(self):
        """Allow the user to toggle their own opt-in flag — admin
        approval isn't required for opting OUT, and we want the
        flag to be discoverable by salespeople in Preferences."""
        return super().SELF_WRITEABLE_FIELDS + ['techmatic_ai_auto_followup_optin']
