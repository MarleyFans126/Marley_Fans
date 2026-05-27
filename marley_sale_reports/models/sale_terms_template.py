# -*- coding: utf-8 -*-
"""Reusable Sale Order Terms & Conditions templates.

A `sale.terms.template` record is a named, free-form text block (warranty,
delivery, payment, bank, customer-scope, etc. all merged into a single
narrative). On a sale.order, the user picks one of these templates via the
`terms_template_id` selector and its body is poured into the standard
`note` field — no individual structured fields, no per-section edits.

Multiple templates act as "drafts" the salesperson can choose between
(e.g. Standard, Express, Installation Included, OEM, etc.).
"""

from odoo import models, fields


class SaleTermsTemplate(models.Model):
    _name = 'sale.terms.template'
    _description = 'Sale Order Terms & Conditions Draft'
    _order = 'sequence, name'

    name = fields.Char(
        string='Template Name',
        required=True,
        help='Short label shown in the salesperson selector '
             '(e.g. "Standard", "Express", "OEM Customers").',
    )
    sequence = fields.Integer(
        string='Sequence',
        default=10,
        help='Display order in the selector dropdown.',
    )
    body = fields.Html(
        string='Terms & Conditions Body',
        required=True,
        sanitize=True,
        sanitize_overridable=True,
        help='Rich-text T&C block (bold, underline, bullets, colors). '
             'Inserted verbatim into the sale order "Terms and Conditions" '
             '(note) field when this template is selected. Use the toolbar '
             'or keyboard shortcuts: Ctrl+B = bold, Ctrl+I = italic, '
             'Ctrl+U = underline.',
    )
    active = fields.Boolean(
        string='Active',
        default=True,
        help='Uncheck to hide a template from the selector without '
             'deleting it (preserves history).',
    )
