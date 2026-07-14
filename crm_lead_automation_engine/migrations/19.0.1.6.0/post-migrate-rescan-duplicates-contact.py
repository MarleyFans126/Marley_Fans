# -*- coding: utf-8 -*-
"""Re-scan every lead for duplicates after adding contact-person-name matching.

Duplicate detection now also matches on the contact person's name. Existing
leads were flagged under the old criteria (phone / email / company), so re-run
the check across all leads once to surface any same-contact-person duplicates.
"""
import logging

from odoo import api, SUPERUSER_ID

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    leads = env['crm.lead'].with_context(active_test=False).search([])
    _logger.info("[MIGRATE 1.6.0] Re-scanning %d lead(s) for duplicates (incl. contact name)…", len(leads))
    for i in range(0, len(leads), 200):
        leads[i:i + 200]._check_and_mark_duplicates()
    flagged = env['crm.lead'].search_count([('duplicate_flag', '=', True)])
    _logger.info("[MIGRATE 1.6.0] Duplicate re-scan done. %d lead(s) now flagged.", flagged)
