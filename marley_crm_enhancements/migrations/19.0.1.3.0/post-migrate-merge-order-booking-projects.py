# -*- coding: utf-8 -*-
"""Merge duplicate Order Booking container projects into one.

On some databases the container ended up split — e.g. the original
"Installation" project was renamed to "Order Booking" in the UI while the
button created a fresh "Order Booking Form". Invoke the (now self-consolidating)
getter once so any "Installation" / "Order Booking" projects are folded into the
single canonical "Order Booking Form": their tasks and stages are moved over and
the emptied legacy projects archived.
"""
import logging

from odoo import api, SUPERUSER_ID

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    before = env['project.project'].search(
        [('name', 'in', ['Installation', 'Order Booking'])]
    )
    names = before.mapped('name')
    canonical = env['crm.lead']._get_installation_project()
    if names:
        _logger.info(
            "[MIGRATE 1.3.0] Folded legacy project(s) %s into %r (now %d task(s)).",
            names, canonical.name,
            env['project.task'].search_count([('project_id', '=', canonical.id)]),
        )
