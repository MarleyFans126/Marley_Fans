import logging
from email.utils import parseaddr

from markupsafe import Markup

from odoo import api, fields, models, _
from odoo.tools import email_normalize, email_split

_logger = logging.getLogger(__name__)

# Sender local-parts that mean "automated system mail" — never forwarded.
AUTO_LOCALPARTS = frozenset({
    'mailer-daemon', 'mailerdaemon', 'postmaster', 'no-reply', 'noreply',
    'donotreply', 'do-not-reply', 'bounce', 'bounces', 'notification',
    'notifications', 'automailer', 'auto-reply', 'autoreply',
})

# Fixed internal mailboxes that get a copy of every customer email, on top of
# the lead's salesperson. Comma-separated so more can be added from Settings
# without a code change.
DEFAULT_OPS_EMAIL = 'operations@marleyfans.in,sales@marleyfans.in'


class CrmLead(models.Model):
    _inherit = 'crm.lead'

    incoming_mail_ids = fields.One2many(
        'techmatic.incoming.mail', 'lead_id', string='Incoming Mails')
    incoming_mail_count = fields.Integer(compute='_compute_incoming_mail_count')

    def _compute_incoming_mail_count(self):
        grouped = self.env['techmatic.incoming.mail'].sudo()._read_group(
            [('lead_id', 'in', self.ids)], ['lead_id'], ['__count'])
        counts = {lead.id: count for lead, count in grouped}
        for lead in self:
            lead.incoming_mail_count = counts.get(lead.id, 0)

    def action_view_incoming_mails(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Incoming Mails'),
            'res_model': 'techmatic.incoming.mail',
            'view_mode': 'list,form',
            'domain': [('lead_id', '=', self.id)],
            'context': {'create': False},
            'target': 'current',
        }

    # -------------------------------------------------------------------------
    # CONFIG
    # -------------------------------------------------------------------------
    @api.model
    def _tim_ops_emails(self):
        """Fixed internal mailboxes copied on every customer email, as a list.

        Stored as one comma-separated parameter so the client can add or drop a
        mailbox in Settings without a code change.
        """
        raw = self.env['ir.config_parameter'].sudo().get_param(
            'techmatic_incoming_mail.ops_email', DEFAULT_OPS_EMAIL) or ''
        return [part.strip() for part in raw.replace(';', ',').split(',') if part.strip()]

    @api.model
    def _tim_forward_enabled(self):
        value = self.env['ir.config_parameter'].sudo().get_param(
            'techmatic_incoming_mail.forward_enabled', 'True')
        return str(value).strip().lower() not in ('false', '0', '', 'none')

    # -------------------------------------------------------------------------
    # HELPERS
    # -------------------------------------------------------------------------
    @api.model
    def _tim_normalize_sender(self, email_from):
        """Bare lowercase address from any From form ("Name <A@B.com >" -> a@b.com)."""
        normalized = email_normalize(email_from)
        if not normalized:
            parts = email_split(email_from or '')
            normalized = email_normalize(parts[0]) if parts else False
        return normalized or False

    @api.model
    def _tim_sender_name(self, email_from):
        """Display name out of a From header, if the sender supplied one."""
        name, _addr = parseaddr(email_from or '')
        return (name or '').strip() or False

    @api.model
    def _tim_blocked_addresses(self):
        """Addresses we must never forward TO — forwarding to any of them would
        be re-imported by the gateway and loop (or bounce back at ourselves).

        Covers every mailbox Odoo fetches, the company address, and each alias
        domain's catchall / bounce address.
        """
        blocked = set()
        for server in self.env['fetchmail.server'].sudo().search([]):
            normalized = self._tim_normalize_sender(server.user)
            if normalized:
                blocked.add(normalized)
        for source in (self.env.company.email, self.env.company.catchall_email
                       if 'catchall_email' in self.env.company._fields else None):
            normalized = self._tim_normalize_sender(source)
            if normalized:
                blocked.add(normalized)
        for domain in self.env['mail.alias.domain'].sudo().search([]):
            for addr in (getattr(domain, 'catchall_email', None),
                         getattr(domain, 'bounce_email', None)):
                normalized = self._tim_normalize_sender(addr)
                if normalized:
                    blocked.add(normalized)
        return blocked

    # -------------------------------------------------------------------------
    # 0. IS THIS A GENUINE EXTERNAL CUSTOMER?
    # -------------------------------------------------------------------------
    @api.model
    def _tim_is_external_sender(self, email_from):
        """True only when the sender is a genuine external customer.

        Everything else is blocked from creating (or being captured as) a lead:
        any address on our own mail domain (info@, sales@, sales6@, …), the
        fetched mailbox / catchall / bounce, mailer-daemon / no-reply style
        senders, and internal Odoo users. This is what stops Odoo's own periodic
        digest and the mail our salespeople send out from turning into junk leads
        once a fallback model is set on the incoming server.
        """
        sender = self._tim_normalize_sender(email_from)
        if not sender:
            return False
        localpart, _sep, domain = sender.partition('@')
        if localpart in AUTO_LOCALPARTS:
            return False
        if sender in self._tim_blocked_addresses():
            return False
        # Our own mail domains => internal. Gathered from the alias domains, the
        # company email and the fetched mailbox, so this still holds even if the
        # alias-domain config is ever missing.
        our_domains = {d.name.strip().lower()
                       for d in self.env['mail.alias.domain'].sudo().search([]) if d.name}
        company_email = self.env.company.email or ''
        if '@' in company_email:
            our_domains.add(company_email.rsplit('@', 1)[-1].strip().lower())
        for server in self.env['fetchmail.server'].sudo().search([]):
            if server.user and '@' in server.user:
                our_domains.add(server.user.rsplit('@', 1)[-1].strip().lower())
        if domain and domain in our_domains:
            return False
        # An internal (non-share) Odoo user's address => internal.
        partner = self.env['res.partner'].sudo().search(
            [('email_normalized', '=', sender)], limit=1)
        if partner and partner.user_ids and all(not u.share for u in partner.user_ids):
            return False
        return True

    # -------------------------------------------------------------------------
    # 1. LEAD MATCHING
    # -------------------------------------------------------------------------
    @api.model
    def _tim_find_open_lead_by_email(self, email_from):
        """Most recently updated OPEN lead whose email matches the sender.

        Searches the stored, indexed ``email_normalized`` column, which Odoo
        already keeps lowercased and stripped — so the match is case-insensitive
        and whitespace-tolerant without ever scanning the lead table.

        Won / Lost / archived leads are excluded on purpose: a returning
        customer's new enquiry should become a fresh opportunity rather than
        landing silently in a closed lead nobody is watching. (Lost leads are
        archived by Odoo, so ``active`` covers them; Won ones stay active and
        are excluded via the stage.)
        """
        normalized = self._tim_normalize_sender(email_from)
        if not normalized:
            return self.browse()
        return self.search(
            [('email_normalized', '=', normalized),
             ('active', '=', True),
             ('stage_id.is_won', '=', False)],
            order='write_date desc', limit=1,
        )

    # -------------------------------------------------------------------------
    # 2. LEAD CREATION (unknown sender)
    # -------------------------------------------------------------------------
    @api.model
    def message_new(self, msg_dict, custom_values=None):
        """Create a lead for an unknown sender.

        Core already fills name (from subject), email_from and the author
        partner; we add the contact name and carry the email body into the
        description so the enquiry is readable without opening the chatter.
        """
        custom_values = dict(custom_values or {})
        email_from = msg_dict.get('email_from') or msg_dict.get('from')
        subject = (msg_dict.get('subject') or '').strip()
        custom_values.setdefault(
            'name',
            subject or self._tim_normalize_sender(email_from) or _('Email enquiry'))
        contact_name = self._tim_sender_name(email_from)
        if contact_name:
            custom_values.setdefault('contact_name', contact_name)
        if msg_dict.get('body'):
            custom_values.setdefault('description', msg_dict['body'])

        lead = super().message_new(msg_dict, custom_values=custom_values)
        _logger.info(
            "[INCOMING] no open lead for %s — created lead %s (%s).",
            email_from, lead.id, lead.name,
        )
        # Flag carries through to message_post (the gateway posts on this very
        # recordset) so the audit record can say "New Lead Created".
        return lead.with_context(tim_lead_created=True)

    # -------------------------------------------------------------------------
    # 4. LOOP DETECTION
    # -------------------------------------------------------------------------
    def _tim_is_customer_email(self, message):
        """True only for a genuine inbound customer email worth processing.

        Reuses the same external-sender test used to gate lead creation, plus a
        belt-and-suspenders check on the message author (an internal Odoo user).
        """
        self.ensure_one()
        if not self._tim_is_external_sender(message.email_from):
            _logger.info(
                "[INCOMING] message %s is not from an external customer (%s) — "
                "not processed.", message.id, message.email_from)
            return False

        author = message.author_id
        if author and author.user_ids and all(not user.share for user in author.user_ids):
            _logger.info(
                "[INCOMING] loop guard: message %s authored by internal user %s — "
                "not processed.", message.id, author.name)
            return False

        return True

    # -------------------------------------------------------------------------
    # 6. CHATTER
    # -------------------------------------------------------------------------
    def _tim_promote_subtype(self, message):
        """Show the email as a normal customer exchange in the chatter.

        A mail landing on a *newly created* lead is stamped with the lead's
        creation subtype ("Opportunity Created"), which reads like a system
        notice rather than a customer email. Promote it to Discussions so both
        the matched and created paths look identical to the salesperson.
        """
        comment = self.env.ref('mail.mt_comment', raise_if_not_found=False)
        if comment and message.subtype_id != comment:
            message.sudo().write({'subtype_id': comment.id})

    # -------------------------------------------------------------------------
    # 3. INCOMING MAIL AUDIT RECORD
    # -------------------------------------------------------------------------
    def _tim_create_incoming_record(self, message):
        """Mirror the email into the Incoming Mails audit log. One per message."""
        self.ensure_one()
        Incoming = self.env['techmatic.incoming.mail'].sudo()
        if message.id and Incoming.search_count(
                [('mail_message_id', '=', message.id)], limit=1):
            _logger.info(
                "[INCOMING] message %s already captured for lead %s — not "
                "duplicating.", message.id, self.id)
            return Incoming.browse()

        status = 'created' if self.env.context.get('tim_lead_created') else 'matched'
        attachments = message.attachment_ids
        record = Incoming.create({
            'lead_id': self.id,
            'partner_id': message.author_id.id if message.author_id else False,
            'sender_name': (self._tim_sender_name(message.email_from)
                            or (message.author_id.name if message.author_id else False)),
            'email_from': message.email_from or (
                message.author_id.email if message.author_id else False),
            'subject': message.subject or (
                ('Re: ' + self.name) if self.name else _('Incoming email')),
            'body': message.body,
            'date_received': message.date or fields.Datetime.now(),
            'mail_message_id': message.id or False,
            'message_id': message.message_id or False,
            'processing_status': status,
            'attachment_ids': [(6, 0, attachments.ids)] if attachments else False,
            'is_read': False,
        })
        _logger.info(
            "[INCOMING] lead %s (%s): incoming mail record %s created [%s] with "
            "%d attachment(s).",
            self.id, self.name, record.id, status, len(attachments),
        )
        return record

    # -------------------------------------------------------------------------
    # 5. INTERNAL FORWARD
    # -------------------------------------------------------------------------
    def _tim_forward_recipients(self):
        """Fixed internal mailboxes + assigned and secondary salesperson,
        de-duplicated and with any of our own addresses removed."""
        self.ensure_one()
        blocked = self._tim_blocked_addresses()
        root_user = self.env.ref('base.user_root', raise_if_not_found=False)

        candidates = self._tim_ops_emails()
        if not candidates:
            _logger.warning(
                "[INCOMING] lead %s: no internal mailbox configured.", self.id)

        users = self.user_id
        # The secondary salesperson field is optional (added by another module).
        if 'second_salesperson_id' in self._fields:
            users |= self.second_salesperson_id
        for user in users:
            if not user or user == root_user or user.share:
                continue
            email = user.partner_id.email or user.email
            if email:
                candidates.append(email)
            else:
                _logger.info(
                    "[INCOMING] lead %s: salesperson %s has no email address — "
                    "cannot forward to them.", self.id, user.name)

        seen, recipients = set(), []
        for address in candidates:
            normalized = self._tim_normalize_sender(address)
            if not normalized or normalized in seen:
                continue
            if normalized in blocked:
                _logger.info(
                    "[INCOMING] loop guard: dropping recipient %s — it is one of "
                    "our own fetched/catchall addresses.", address)
                continue
            seen.add(normalized)
            recipients.append(address.strip())
        return recipients

    def _tim_forward(self, message, record=None):
        """Forward the customer email to operations + the salesperson(s)."""
        self.ensure_one()
        if not self._tim_forward_enabled():
            return False
        recipients = self._tim_forward_recipients()
        if not recipients:
            _logger.warning(
                "[INCOMING] lead %s: nothing to forward to (no operations address "
                "and no salesperson email).", self.id)
            return False

        sender = message.email_from or (
            message.author_id.email_formatted if message.author_id else '')
        header = Markup(
            '<div style="background:#f4f4f4;padding:8px 12px;'
            'border-left:3px solid #875A7B;margin-bottom:10px;font-size:13px;">'
            '<strong>Forwarded from CRM lead:</strong> %(lead)s<br/>'
            '<strong>From:</strong> %(sender)s<br/>'
            '<strong>Received:</strong> %(date)s'
            '</div>'
        ) % {
            'lead': self.name or '',
            'sender': sender or _('(unknown sender)'),
            'date': message.date or fields.Datetime.now(),
        }
        subject = message.subject or (_("Customer email — %s") % (self.name or ''))
        if not subject.strip().lower().startswith('fwd'):
            subject = 'Fwd: %s' % subject

        # Copy the attachments so the forward is self-contained: it auto-deletes
        # after sending, and we must not take the customer's originals with it.
        attachment_commands = [
            (0, 0, {'name': att.name, 'datas': att.datas, 'mimetype': att.mimetype})
            for att in message.attachment_ids
        ]

        mail = self.env['mail.mail'].sudo().create({
            'subject': subject,
            'body_html': header + Markup(message.body or ''),
            'email_from': self.env.company.email or (self._tim_ops_emails() or [''])[0],
            'email_to': ', '.join(recipients),
            'auto_delete': True,
            'attachment_ids': attachment_commands or False,
        })
        mail.send()
        _logger.info(
            "[INCOMING] lead %s (%s): email forwarded to %s (%d attachment(s)).",
            self.id, self.name, ', '.join(recipients), len(message.attachment_ids),
        )
        if record:
            record.sudo().forwarded_to = ', '.join(recipients)
        return True

    # -------------------------------------------------------------------------
    # PIPELINE ENTRY POINT
    # -------------------------------------------------------------------------
    def message_post(self, **kwargs):
        message = super().message_post(**kwargs)
        # Only genuine gateway mail is 'email'; our outbound stage mails and the
        # composer post as 'comment'/'notification', so they never come through
        # here — outbound automation is untouched.
        if (kwargs.get('message_type') == 'email'
                and not self.env.context.get('tim_processing')):
            for lead in self:
                try:
                    lead.with_context(tim_processing=True)._tim_process_incoming(message)
                except Exception:
                    _logger.exception(
                        "[INCOMING] processing failed for lead %s (message %s)",
                        lead.id, getattr(message, 'id', None))
        return message

    def _tim_process_incoming(self, message):
        """Chatter -> audit record -> internal forward, for one customer email."""
        self.ensure_one()
        if not message or message.message_type != 'email':
            return
        if not self._tim_is_customer_email(message):
            return
        _logger.info(
            "[INCOMING] lead %s (%s): processing customer email from %s.",
            self.id, self.name, message.email_from)
        self._tim_promote_subtype(message)
        record = self._tim_create_incoming_record(message)
        self._tim_forward(message, record)
