# -*- coding: utf-8 -*-
from odoo import models, fields


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    x_enable_auto_enrichment = fields.Boolean(
        string='Enable Auto Lead Enrichment',
        config_parameter='lead_intelligence.enable_auto_enrichment',
        default=True,
        help='Automatically enrich leads from GSTIN on creation.',
    )
    x_gst_api_url = fields.Char(
        string='GST API URL',
        config_parameter='lead_intelligence.gst_api_url',
        default='https://sheet.gstzen.in/api/v1/gstin',
        help='Base URL for GST lookup API.',
    )
    x_gst_api_key = fields.Char(
        string='GST API Key',
        config_parameter='lead_intelligence.gst_api_key',
        help='API key for GST lookup (if required).',
    )
