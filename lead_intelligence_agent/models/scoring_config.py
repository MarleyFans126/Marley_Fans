# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import ValidationError


class LeadScoringConfig(models.Model):
    _name = 'x.lead.scoring.config'
    _description = 'Lead Scoring Weight Configuration'
    _rec_name = 'display_name'

    # ── Weights (must sum to 100) ─────────────────────────────────
    weight_source_quality = fields.Integer(
        string='Source Quality Weight', default=20,
        help='Weight for lead source (IndiaMart, Aajjo, Website, Manual)')
    weight_contact_completeness = fields.Integer(
        string='Contact Completeness Weight', default=15,
        help='Weight for having email, mobile, GSTIN')
    weight_geographic_match = fields.Integer(
        string='Geographic Match Weight', default=15,
        help='Weight for city tier matching')
    weight_deal_size = fields.Integer(
        string='Estimated Deal Size Weight', default=20,
        help='Weight for expected revenue thresholds')
    weight_engagement_speed = fields.Integer(
        string='Engagement Speed Weight', default=15,
        help='Weight for first response time after lead creation')
    weight_duplicate_flag = fields.Integer(
        string='Duplicate Flag Weight', default=15,
        help='Weight for non-duplicate leads')

    def _compute_display_name(self):
        for rec in self:
            rec.display_name = 'Lead Scoring Weights Configuration'

    @api.constrains(
        'weight_source_quality', 'weight_contact_completeness',
        'weight_geographic_match', 'weight_deal_size',
        'weight_engagement_speed', 'weight_duplicate_flag')
    def _check_weights_sum(self):
        for rec in self:
            total = (
                rec.weight_source_quality +
                rec.weight_contact_completeness +
                rec.weight_geographic_match +
                rec.weight_deal_size +
                rec.weight_engagement_speed +
                rec.weight_duplicate_flag
            )
            if total != 100:
                raise ValidationError(
                    _('All scoring weights must sum to exactly 100. '
                      'Current total: %d') % total)

    @api.model
    def _get_config(self):
        """Return the singleton config record, creating if needed."""
        config = self.search([], limit=1)
        if not config:
            config = self.create({})
        return config
