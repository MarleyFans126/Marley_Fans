# -*- coding: utf-8 -*-
"""Lead deletion lockdown for non-admin users.

Business rule (Marley): a regular salesperson may freely EDIT leads (and
change stage, create quotations), but may NOT DELETE a lead. Only
administrators (Settings group) can delete.

Editing lead data is intentionally NOT restricted. Log-note / message
editing & deletion is restricted separately in mail_message_access.py.

System / automated deletions run as superuser (env.su) or as OdooBot
(base.group_system) and are never blocked.
"""
from odoo import models, _
from odoo.exceptions import AccessError


class CrmLead(models.Model):
    _inherit = 'crm.lead'

    def _marley_is_admin(self):
        return self.env.su or self.env.user.has_group('base.group_system')

    def unlink(self):
        if not self._marley_is_admin():
            raise AccessError(_(
                "Only administrators can delete leads."
            ))
        return super().unlink()
