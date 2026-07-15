# -*- coding: utf-8 -*-
"""Re-scan all leads after switching to EXACT-match duplicate detection.

Company-name matching was fuzzy (normalized core / substring); it's now an
exact match. Re-run the check across all leads so anything that was flagged
only by a fuzzy company match gets un-flagged, and the flags reflect the exact
criteria (mobile / email / exact company name / exact contact person).
"""
import logging

from odoo import api, SUPERUSER_ID

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    leads = env['crm.lead'].with_context(active_test=False).search([])
    _logger.info("[MIGRATE 1.7.0] Re-scanning %d lead(s) with EXACT-match duplicate rules…", len(leads))
    for i in range(0, len(leads), 200):
        leads[i:i + 200]._check_and_mark_duplicates()
    flagged = env['crm.lead'].search_count([('duplicate_flag', '=', True)])
    _logger.info("[MIGRATE 1.7.0] Re-scan done. %d lead(s) now flagged (exact match).", flagged)
