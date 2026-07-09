# -*- coding: utf-8 -*-
"""Re-scan every lead for duplicates.

Duplicate detection previously ran only on create / edit, so leads that already
existed when company-name matching was added were never flagged. Re-run the
check across all leads once so existing duplicates (same phone, email, or
similar company name) light up immediately.
"""
import logging

from odoo import api, SUPERUSER_ID

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    leads = env['crm.lead'].with_context(active_test=False).search([])
    _logger.info("[MIGRATE 1.5.0] Re-scanning %d lead(s) for duplicates…", len(leads))
    # Process in batches so a very large pipeline doesn't build one huge write.
    flagged = 0
    for i in range(0, len(leads), 200):
        batch = leads[i:i + 200]
        batch._check_and_mark_duplicates()
    flagged = env['crm.lead'].search_count([('duplicate_flag', '=', True)])
    _logger.info("[MIGRATE 1.5.0] Duplicate re-scan done. %d lead(s) now flagged.", flagged)
