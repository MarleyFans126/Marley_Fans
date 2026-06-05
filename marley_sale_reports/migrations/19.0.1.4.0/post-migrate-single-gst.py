"""Migration 19.0.1.4.0 — consolidate sale taxes to a single 'GST 18%'.

The post_init_hook fires only on fresh install, so existing
installations need this migration to run the same consolidation:
make 'GST 18%' the default sale tax and archive all other sale taxes
+ the auto-apply GST fiscal positions.
"""

import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    from odoo import api, SUPERUSER_ID

    env = api.Environment(cr, SUPERUSER_ID, {})

    gst18 = env.ref('marley_sale_reports.gst_sale_18', raise_if_not_found=False)
    if not gst18:
        _logger.warning("[MIGRATE 1.4.0] gst_sale_18 not found, skipping.")
        return

    # 1) Default sale tax on every company
    for company in env['res.company'].search([]):
        gst18_c = gst18.with_company(company)
        if company.account_sale_tax_id != gst18_c:
            company.account_sale_tax_id = gst18_c.id

    # 2) Archive all other active SALE taxes (keep only GST 18%)
    other_sale_taxes = env['account.tax'].search([
        ('type_tax_use', '=', 'sale'),
        ('active', '=', True),
        ('id', '!=', gst18.id),
    ])
    if other_sale_taxes:
        _logger.info(
            "[MIGRATE 1.4.0] Archiving %d non-GST18 sale tax(es): %s",
            len(other_sale_taxes), other_sale_taxes.mapped('name'),
        )
        other_sale_taxes.write({'active': False})

    # 3) Disable the auto-apply GST fiscal positions
    for xmlid in (
        'marley_sale_reports.fiscal_position_intra_state',
        'marley_sale_reports.fiscal_position_inter_state',
    ):
        fp = env.ref(xmlid, raise_if_not_found=False)
        if fp:
            fp.write({'auto_apply': False, 'active': False})

    _logger.info("[MIGRATE 1.4.0] Single 'GST 18%%' sale tax set as default.")
