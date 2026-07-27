import logging

from odoo import api, models

_logger = logging.getLogger(__name__)


class MailThread(models.AbstractModel):
    _inherit = 'mail.thread'

    @api.model
    def message_route(self, message, message_dict, model=None, thread_id=None,
                      custom_values=None):
        """Point a would-be NEW crm.lead route at the sender's existing open lead.

        The standard gateway threads replies by Message-ID, but a *fresh* email
        from a customer who already has a lead would open a second one. When the
        sender has an open lead we rewrite the route's thread_id to it, so the
        gateway takes its ``message_update`` branch and the mail lands in that
        lead's chatter instead of creating a duplicate.

        Rewriting the route (rather than returning an existing record from
        ``message_new``) matters: on the create branch the gateway stamps the
        message with ``_creation_subtype()`` ("Opportunity Created"), which would
        make a customer email look like a lead-creation notice. On the update
        branch the subtype falls through to the normal mt_comment logic.

        Only routes that would CREATE (no thread_id) are touched, so reply
        threading and every non-CRM alias behave exactly as before.
        """
        routes = super().message_route(
            message, message_dict, model=model, thread_id=thread_id,
            custom_values=custom_values,
        )
        if not routes:
            return routes

        email_from = message_dict.get('email_from')
        Lead = self.env['crm.lead']
        rerouted = []
        for route in routes:
            try:
                r_model, r_thread_id, r_custom, r_user_id, r_alias = route
            except (TypeError, ValueError):
                # Unexpected route shape — leave it exactly as the core built it.
                rerouted.append(route)
                continue
            if r_model == 'crm.lead' and not r_thread_id:
                # This route would CREATE a lead. Per policy we NEVER create a
                # lead from incoming mail: if the sender's email already belongs
                # to a lead, attach the mail to that lead's chatter; otherwise
                # drop it entirely (no lead, no bounce). This keeps the pipeline
                # free of junk — Odoo digests, staff-sent mail, newsletters,
                # first-time senders — and lets sales create leads deliberately.
                lead = Lead._tim_find_lead_by_email(email_from)
                if lead:
                    _logger.info(
                        "[INCOMING] sender %s matched existing lead %s (%s) — "
                        "attaching mail to its log.", email_from, lead.id, lead.name)
                    route = (r_model, lead.id, r_custom, r_user_id, r_alias)
                else:
                    _logger.info(
                        "[INCOMING] sender %s has no existing lead — mail dropped "
                        "(no new lead created).", email_from)
                    continue  # drop this route; nothing is created
            rerouted.append(route)
        return rerouted
