import logging

from odoo import models

_logger = logging.getLogger(__name__)


class MailActivity(models.Model):
    _inherit = 'mail.activity'

    def _marley_mute_lead_activity_notify(self):
        """Whether to mute the 'assigned to you' notification for lead activities.
        Config: marley_crm_enhancements.mute_lead_activity_assign_notify
        (default True). Flip to False in Technical > Parameters to restore the
        standard Odoo behaviour without a code change."""
        value = self.env['ir.config_parameter'].sudo().get_param(
            'marley_crm_enhancements.mute_lead_activity_assign_notify', 'True')
        return str(value).strip().lower() not in ('false', '0', '', 'none')

    def action_notify(self):
        """Suppress the "<activity>: <summary> assigned to you" notification for
        activities on CRM leads / opportunities.

        Assigning an activity on a lead should not email or inbox-ping the
        assignee (per client request). Activities on every other model still
        notify exactly as standard. The assignee is still subscribed to the lead
        and their activity counter still updates — only the assignment message
        is muted.
        """
        target = self
        if self._marley_mute_lead_activity_notify():
            target = self.filtered(lambda act: act.res_model != 'crm.lead')
            muted = self - target
            if muted:
                _logger.info(
                    "[MARLEY] muted 'assigned to you' notification for %d lead "
                    "activity(ies).", len(muted))
        return super(MailActivity, target).action_notify()
