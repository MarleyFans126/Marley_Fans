"""Read-independent IMAP fetch.

Core Odoo fetches only ``(UNSEEN)`` mail. If a human opens the shared mailbox
in webmail before the fetch cron runs, the message is flagged ``\\Seen`` and
Odoo skips it forever — no chatter, no capture, no forward. This has bitten
Marley repeatedly.

Fix: scan a recent time window (``SINCE``) regardless of read state, but first
fetch just the ``Message-ID`` header of the candidates and drop the ones we have
already imported. So we only ever download genuinely-new mail; already-processed
mail costs one tiny header fetch plus one indexed DB query. Odoo's own
Message-ID dedup in ``message_process`` is the safety net underneath.

Everything is wrapped so that ANY failure falls back to the exact core
``(UNSEEN)`` behaviour — mail intake must never break because of this.
"""
import logging
import re
import types
from datetime import datetime, timedelta

from odoo import models
from odoo.addons.mail.models.fetchmail import OdooIMAP4

_logger = logging.getLogger(__name__)

DEFAULT_RESCAN_DAYS = 3
MAX_RESCAN_DAYS = 30

_MSGID_RE = re.compile(rb'Message-ID\s*:\s*(<[^>\r\n]+>)', re.IGNORECASE)
_SEQ_RE = re.compile(rb'^\s*(\d+)\b')


def _parse_header_fetch(data):
    """Map IMAP sequence number -> Message-ID from a batched HEADER.FIELDS fetch.

    ``data`` is imaplib's ``fetch()`` response list, e.g.::

        [(b'1 (BODY[HEADER.FIELDS (MESSAGE-ID)] {40}',
          b'Message-ID: <a@x>\\r\\n\\r\\n'), b')', (b'2 (...', b'Message-ID: <b@y>...'), b')']

    Pure function so it can be unit-tested without a live server.
    """
    out = {}
    for item in data or ():
        if not isinstance(item, (tuple, list)) or len(item) < 2:
            continue
        seq = _SEQ_RE.match(item[0] or b'')
        mid = _MSGID_RE.search(item[1] or b'')
        if seq and mid:
            out[seq.group(1)] = mid.group(1).decode('ascii', 'replace').strip()
    return out


def _rescan_check_unread_messages(self):
    """Recent mail we have NOT imported yet, regardless of \\Seen state.

    Bound onto the live IMAP connection in ``_connect__``. Falls back to the
    core ``(UNSEEN)`` search on any error.
    """
    self.select()
    try:
        since = (datetime.utcnow() - timedelta(days=self._tim_days)).strftime('%d-%b-%Y')
        _typ, data = self.search(None, '(SINCE %s)' % since)
        nums = data[0].split() if data and data[0] else []
        if not nums:
            self._unread_messages = []
            return 0

        # Cheap header-only fetch: get every candidate's Message-ID.
        _typ, hdr = self.fetch(b','.join(nums), '(BODY.PEEK[HEADER.FIELDS (MESSAGE-ID)])')
        msgid_by_seq = _parse_header_fetch(hdr)

        msgids = [m for m in msgid_by_seq.values() if m]
        already = set()
        if msgids:
            rows = self._tim_server.env['mail.message'].sudo().search(
                [('message_id', 'in', msgids)])
            already = set(rows.mapped('message_id'))

        # Keep candidates we have not imported (and any with no parseable
        # Message-ID, to be safe — message_process will dedup those too).
        keep = [num for num in nums
                if msgid_by_seq.get(num) is None or msgid_by_seq[num] not in already]

        # Ascending order: retrieve pops from the end, so the NEWEST mail is
        # processed first and always lands within the fetch batch_limit.
        self._unread_messages = keep
        _logger.info(
            "[INCOMING] read-independent fetch: %d msg(s) in last %dd, %d new to import.",
            len(nums), self._tim_days, len(keep))
        return len(keep)
    except Exception:
        _logger.warning(
            "[INCOMING] read-independent fetch failed; falling back to core UNSEEN.",
            exc_info=True)
        _typ, data = self.search(None, '(UNSEEN)')
        self._unread_messages = data[0].split() if data and data[0] else []
        self._unread_messages.reverse()
        return len(self._unread_messages)


def _rescan_retrieve_unread_messages(self):
    """Yield (seq, raw) newest-first. Unlike core we do NOT clear the \\Seen
    flag — re-scanning read mail is the whole point, and dedup handles it."""
    assert self._unread_messages is not None
    while self._unread_messages:
        num = self._unread_messages.pop()
        _typ, data = self.fetch(num, '(RFC822)')
        yield num, data[0][1]


class FetchmailServer(models.Model):
    _inherit = 'fetchmail.server'

    def _tim_rescan_enabled(self):
        value = self.env['ir.config_parameter'].sudo().get_param(
            'techmatic_incoming_mail.rescan_enabled', 'True')
        return str(value).strip().lower() not in ('false', '0', '', 'none')

    def _tim_rescan_days(self):
        try:
            days = int(self.env['ir.config_parameter'].sudo().get_param(
                'techmatic_incoming_mail.rescan_days', DEFAULT_RESCAN_DAYS))
        except (TypeError, ValueError):
            days = DEFAULT_RESCAN_DAYS
        return max(1, min(days, MAX_RESCAN_DAYS))

    def _connect__(self, allow_archived=False):
        connection = super()._connect__(allow_archived=allow_archived)
        # Only IMAP, only when enabled. Any hiccup leaves the vanilla core
        # connection untouched so fetching keeps working.
        try:
            if (self._get_connection_type() == 'imap'
                    and isinstance(connection, OdooIMAP4)
                    and self._tim_rescan_enabled()):
                connection._tim_server = self
                connection._tim_days = self._tim_rescan_days()
                connection.check_unread_messages = types.MethodType(
                    _rescan_check_unread_messages, connection)
                connection.retrieve_unread_messages = types.MethodType(
                    _rescan_retrieve_unread_messages, connection)
        except Exception:
            _logger.warning(
                "[INCOMING] could not enable read-independent fetch; using core UNSEEN.",
                exc_info=True)
        return connection
