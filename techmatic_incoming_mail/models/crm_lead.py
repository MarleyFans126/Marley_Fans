import logging

from odoo import models, fields, _, SUPERUSER_ID

_logger = logging.getLogger(__name__)


class CrmLead(models.Model):
    _inherit = 'crm.lead'

    def message_post(self, **kwargs):
        message = super().message_post(**kwargs)
        try:
            self._techmatic_capture_incoming(message)
        except Exception:
            _logger.exception("techmatic_incoming_mail: failed to capture incoming reply")
        return message

    def _techmatic_capture_incoming(self, message):
        """Mirror a genuine INCOMING customer reply into the Incoming Mail
        panel and alert the salesperson.

        Only gateway-received emails are ``message_type == 'email'``; our own
        outgoing stage mails are posted as ``'comment'``, so they're ignored.
        """
        if not message or message.message_type != 'email':
            return
        # Incoming customer replies land with the internal "Note" subtype, which
        # is de-emphasised / hidden in the chatter thread. Promote them to the
        # public "Discussions" (mt_comment) subtype so the reply is clearly
        # visible in the lead's chatter as an incoming email exchange.
        comment = self.env.ref('mail.mt_comment', raise_if_not_found=False)
        if comment and message.subtype_id != comment:
            message.sudo().write({'subtype_id': comment.id})
        Incoming = self.env['techmatic.incoming.mail'].sudo()
        for lead in self:
            # Never capture the same source message twice.
            if message.id and Incoming.search_count(
                    [('mail_message_id', '=', message.id)]):
                continue
            Incoming.create({
                'lead_id': lead.id,
                'partner_id': message.author_id.id if message.author_id else False,
                'email_from': message.email_from or (
                    message.author_id.email if message.author_id else False),
                'subject': message.subject or (
                    ('Re: ' + lead.name) if lead.name else _('Incoming reply')),
                'body': message.body,
                'date_received': message.date or fields.Datetime.now(),
                'mail_message_id': message.id or False,
                'is_read': False,
            })
            # Alert the salesperson in their inbox (skip OdooBot / unassigned).
            user = lead.user_id
            if user and user.id != SUPERUSER_ID and user.partner_id:
                try:
                    lead.message_notify(
                        partner_ids=user.partner_id.ids,
                        subject=_("Customer replied: %s") % (lead.name or ''),
                        body=_("A new email reply was received on this lead. "
                               "Open the Incoming Mails panel or the lead to review."),
                    )
                except Exception:
                    _logger.exception("techmatic_incoming_mail: salesperson notify failed")
