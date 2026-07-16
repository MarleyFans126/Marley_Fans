# -*- coding: utf-8 -*-
"""Re-scan every lead after removing contact-person-name from duplicate matching.

Duplicates are now matched only on mobile / email / company name. Leads that
were previously flagged solely because they shared a contact person name must
be re-evaluated (and un-flagged where they no longer match anything else).
"""
import logging

from odoo import api, SUPERUSER_ID

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    leads = env['crm.lead'].with_context(active_test=False).search([])
    _logger.info("[MIGRATE 1.8.0] Re-scanning %d lead(s) (contact name no longer matched)…", len(leads))
    for i in range(0, len(leads), 200):
        leads[i:i + 200]._check_and_mark_duplicates()
    flagged = env['crm.lead'].search_count([('duplicate_flag', '=', True)])
    _logger.info("[MIGRATE 1.8.0] Duplicate re-scan done. %d lead(s) now flagged.", flagged)
