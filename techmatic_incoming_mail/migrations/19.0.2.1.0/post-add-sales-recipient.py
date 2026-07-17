# -*- coding: utf-8 -*-
"""Add sales@marleyfans.in to the incoming-mail forward recipients.

The parameter is seeded with noupdate=1 so a client edit is never clobbered on
upgrade — which also means already-deployed databases keep the old
single-address value. Append the new mailbox here instead, preserving whatever
else is configured.
"""
import logging

from odoo import api, SUPERUSER_ID

_logger = logging.getLogger(__name__)

PARAM = 'techmatic_incoming_mail.ops_email'
NEW_RECIPIENT = 'sales@marleyfans.in'


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    config = env['ir.config_parameter'].sudo()
    raw = config.get_param(PARAM, '') or ''
    current = [part.strip() for part in raw.replace(';', ',').split(',') if part.strip()]

    if any(addr.lower() == NEW_RECIPIENT for addr in current):
        _logger.info("[MIGRATE 2.1.0] %s already forwards to %s — nothing to do.",
                     PARAM, NEW_RECIPIENT)
        return

    current.append(NEW_RECIPIENT)
    config.set_param(PARAM, ', '.join(current))
    _logger.info("[MIGRATE 2.1.0] incoming mail now forwards to: %s",
                 ', '.join(current))
