"""Incoming-mail health watchdog.

Every failure mode we have hit is *silent*: mail simply stops arriving and
nobody notices until a customer asks why they got no reply. This watchdog runs
hourly and turns any breakage into an email alert, so problems are caught in
hours instead of by accident.

It only DETECTS and ALERTS — it never changes configuration on its own.
"""
import logging
from datetime import timedelta

from markupsafe import Markup

from odoo import api, fields, models, _

_logger = logging.getLogger(__name__)


class FetchmailServer(models.Model):
    _inherit = 'fetchmail.server'

    @api.model
    def _tim_health_enabled(self):
        value = self.env['ir.config_parameter'].sudo().get_param(
            'techmatic_incoming_mail.health_enabled', 'True')
        return str(value).strip().lower() not in ('false', '0', '', 'none')

    @api.model
    def _tim_health_int_param(self, key, default):
        try:
            return max(1, int(self.env['ir.config_parameter'].sudo().get_param(key, default)))
        except (TypeError, ValueError):
            return default

    @api.model
    def _tim_health_check(self):
        """Human-readable list of problems with the incoming-mail pipeline.
        Empty list means healthy. Safe to call from anywhere (read-only)."""
        problems = []
        Server = self.env['fetchmail.server'].sudo()
        servers = Server.search([('server_type', '!=', 'local')])
        active = servers.filtered('active')

        if not active:
            problems.append(_("No active incoming mail server is configured — "
                              "no customer email is being fetched at all."))

        stale = timedelta(hours=self._tim_health_int_param(
            'techmatic_incoming_mail.health_stale_hours', 2))
        now = fields.Datetime.now()
        for server in active:
            if server.state != 'done':
                problems.append(_(
                    "Incoming server '%(name)s' is not connected (status: %(state)s) — "
                    "mail is not being fetched. Re-check the mailbox login.",
                    name=server.name, state=server.state))
                continue
            if server.error_message:
                problems.append(_(
                    "Incoming server '%(name)s' reported an error: %(err)s",
                    name=server.name, err=server.error_message))
            if server.date and (now - server.date) > stale:
                problems.append(_(
                    "Incoming server '%(name)s' last fetched at %(when)s — the fetch "
                    "job looks stalled.", name=server.name, when=server.date))
            if not server.object_id:
                problems.append(_(
                    "Incoming server '%(name)s' has no fallback model set — fresh "
                    "customer emails may be dropped instead of creating a lead.",
                    name=server.name))

        if not self.env['mail.alias.domain'].sudo().search_count([]):
            problems.append(_("No alias domain is configured — fresh customer "
                              "emails cannot be turned into leads."))

        return problems

    @api.model
    def _tim_cron_health_check(self):
        """Cron entry point: check and alert (throttled). Never raises."""
        try:
            if not self._tim_health_enabled():
                return
            problems = self._tim_health_check()
            if not problems:
                _logger.info("[INCOMING] mail health watchdog: pipeline OK.")
                return
            _logger.critical("[INCOMING] MAIL HEALTH ALERT:\n - %s",
                             "\n - ".join(problems))
            self._tim_send_health_alert(problems)
        except Exception:
            _logger.exception("[INCOMING] mail health watchdog failed to run")

    def _tim_alert_recipients(self):
        """Who to warn: explicit alert address, else the forwarding mailboxes,
        else every system administrator who has an email."""
        ICP = self.env['ir.config_parameter'].sudo()
        raw = (ICP.get_param('techmatic_incoming_mail.health_alert_email')
               or ICP.get_param('techmatic_incoming_mail.ops_email') or '')
        recipients = [p.strip() for p in raw.replace(';', ',').split(',') if p.strip()]
        if recipients:
            return recipients
        admins = self.env.ref('base.group_system').sudo().users.filtered('email')
        return list({user.email for user in admins if user.email})

    def _tim_send_health_alert(self, problems):
        ICP = self.env['ir.config_parameter'].sudo()
        # Throttle so a lasting outage does not send one email per hour.
        throttle = self._tim_health_int_param(
            'techmatic_incoming_mail.health_throttle_hours', 6)
        now = fields.Datetime.now()
        last = ICP.get_param('techmatic_incoming_mail.health_last_alert')
        if last:
            try:
                if (now - fields.Datetime.to_datetime(last)) < timedelta(hours=throttle):
                    return
            except Exception:
                pass

        recipients = self._tim_alert_recipients()
        if not recipients:
            _logger.warning("[INCOMING] health alert has no recipient; only logged.")
            return

        body = Markup(
            "<p>The incoming-email pipeline needs attention:</p><ul>%s</ul>"
            "<p>Customer emails may not be reaching the CRM until this is resolved.</p>"
        ) % Markup("").join(Markup("<li>%s</li>") % p for p in problems)

        self.env['mail.mail'].sudo().create({
            'subject': _("[Marley CRM] Incoming email pipeline needs attention"),
            'body_html': body,
            'email_from': self.env.company.email or recipients[0],
            'email_to': ', '.join(recipients),
            'auto_delete': True,
        }).send()
        ICP.set_param('techmatic_incoming_mail.health_last_alert',
                      fields.Datetime.to_string(now))
        _logger.info("[INCOMING] mail health alert sent to %s", ', '.join(recipients))
