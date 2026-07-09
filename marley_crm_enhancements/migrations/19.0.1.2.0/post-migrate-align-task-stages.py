# -*- coding: utf-8 -*-
"""Align stale task-stage names to the intended 6-stage workflow.

The stage records ship with noupdate="1" (so UI renames persist), which means
the intended workflow names were never applied to databases seeded under the
old defaults. That left the first stage still called "Installation" — which is
what a new Order Booking Form task landed in. This one-time migration renames
the stages to the approved workflow. Because it runs only on this version bump,
any later UI rename is still preserved.

    New -> Commercial Cleared -> Dispatched -> Delivered
        -> Installation Completed -> Warranty Stage
"""
import logging

from odoo import api, SUPERUSER_ID

_logger = logging.getLogger(__name__)

INTENDED = {
    'project_stage_installation': 'New',
    'project_stage_in_progress': 'Commercial Cleared',
    'project_stage_cancelled': 'Dispatched',
    'project_stage_done': 'Delivered',
    'project_stage_installation_completed': 'Installation Completed',
    'project_stage_warranty': 'Warranty Stage',
}


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    for xmlid, name in INTENDED.items():
        stage = env.ref('marley_crm_enhancements.%s' % xmlid, raise_if_not_found=False)
        if stage and stage.name != name:
            old = stage.name
            stage.name = name
            _logger.info("[MIGRATE 1.2.0] Task stage %s: %r -> %r", xmlid, old, name)
