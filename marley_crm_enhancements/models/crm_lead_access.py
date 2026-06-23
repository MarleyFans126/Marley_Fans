# -*- coding: utf-8 -*-
"""Lock down lead editing/deletion for non-admin users.

Business rule (Marley): a regular salesperson may move a lead through the
pipeline (change stage) and create quotations, but may NOT edit the lead's
captured data (company / contact / address / description / etc.) and may
NOT delete a lead. Only administrators (Settings group) can do those.

Implementation notes:
* Only a fixed set of "data" fields is blocked on write. Operational fields
  (stage_id, probability, kanban_state, the *_email_sent flags written by the
  stage-email automation, date_closed, order links, etc.) are left writable,
  so stage changes, quotation creation, and the Won-conversion keep working.
* System / automated writes run as superuser (env.su) or as OdooBot
  (base.group_system) and are never blocked.
"""
from odoo import models, _
from odoo.exceptions import AccessError

# Lead "data" fields a non-admin salesperson must not change.
# (partner_id is intentionally left out so the Won-conversion can still link
#  the customer; add it here if you also want the customer link frozen.)
LOCKED_LEAD_FIELDS = {
    'name', 'partner_name', 'contact_name', 'email_from', 'phone', 'mobile',
    'function', 'title', 'street', 'street2', 'city', 'state_id', 'zip',
    'country_id', 'website', 'description', 'expected_revenue',
    'lead_source', 'lead_source_type', 'second_salesperson_id',
    'business_state_id', 'business_city_id', 'business_area_id',
    'business_city', 'business_area', 'business_pincode',
}


class CrmLead(models.Model):
    _inherit = 'crm.lead'

    def _marley_is_admin(self):
        return self.env.su or self.env.user.has_group('base.group_system')

    def write(self, vals):
        if not self._marley_is_admin():
            blocked = set(vals) & LOCKED_LEAD_FIELDS
            if blocked:
                raise AccessError(_(
                    "You can change the stage and create quotations, but "
                    "editing lead data is restricted to administrators.\n\n"
                    "Blocked fields: %s"
                ) % ", ".join(sorted(blocked)))
        return super().write(vals)

    def unlink(self):
        if not self._marley_is_admin():
            raise AccessError(_(
                "Only administrators can delete leads."
            ))
        return super().unlink()
