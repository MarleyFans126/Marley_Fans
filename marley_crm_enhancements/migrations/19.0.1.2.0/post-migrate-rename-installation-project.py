# -*- coding: utf-8 -*-
"""Rename the singleton container project 'Installation' -> 'Order Booking Form'.

The "Create Order Booking Form" button files its tasks under one shared
project. It used to be named 'Installation', which is what the user still saw
after the report/button were renamed. Rename it in place so every existing
task keeps its home and simply shows under the new project name.
"""
import logging

from odoo import api, SUPERUSER_ID

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    projects = env['project.project'].search([('name', '=', 'Installation')])
    if projects:
        projects.write({'name': 'Order Booking Form'})
        _logger.info(
            "[MIGRATE 1.2.0] Renamed %d 'Installation' project(s) to "
            "'Order Booking Form'.", len(projects),
        )
