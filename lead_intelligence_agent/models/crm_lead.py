# -*- coding: utf-8 -*-
import json
import logging
import requests
from datetime import timedelta

from odoo import models, fields, api, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class CrmLeadIntelligence(models.Model):
    _inherit = 'crm.lead'

    # =====================================================================
    # ENRICHMENT FIELDS
    # =====================================================================
    x_gstin = fields.Char('GSTIN', size=15, tracking=True)
    x_company_legal_name = fields.Char('Legal Name (GST)', readonly=True)
    x_gst_status = fields.Selection([
        ('active', 'Active'),
        ('cancelled', 'Cancelled'),
        ('suspended', 'Suspended'),
    ], string='GST Status', readonly=True)
    x_business_type = fields.Char('Business Type (GST)', readonly=True)
    x_gst_address = fields.Text('Registered Address (GST)', readonly=True)
    x_enriched = fields.Boolean('Enriched', default=False)
    x_enrichment_date = fields.Datetime('Last Enriched On')

    # =====================================================================
    # SCORING FIELDS
    # =====================================================================
    x_lead_score = fields.Integer(
        'Lead Score',
        compute='_compute_lead_score',
        store=True,
        help='Weighted score 0-100 based on multiple criteria')
    x_lead_grade = fields.Selection([
        ('a', 'A'), ('b', 'B'), ('c', 'C'), ('d', 'D'),
    ], string='Lead Grade',
        compute='_compute_lead_score',
        store=True,
        help='A: 80-100, B: 60-79, C: 40-59, D: 0-39')
    x_score_breakdown = fields.Text(
        'Score Breakdown',
        help='JSON showing per-criteria scores for transparency')

    # =====================================================================
    # DUPLICATE ENHANCEMENT
    # =====================================================================
    x_duplicate_of = fields.Many2one(
        'crm.lead', string='Duplicate Of',
        help='Reference to the original lead this is a duplicate of')

    # =====================================================================
    # ENRICHMENT LOGIC
    # =====================================================================
    def action_enrich_lead(self):
        """Public method: Enrich lead from GSTIN via GST API.
        Called from button and from create override."""
        ICP = self.env['ir.config_parameter'].sudo()
        enabled = ICP.get_param('lead_intelligence.enable_auto_enrichment', 'True')
        if enabled != 'True':
            _logger.info('[ENRICH] Auto-enrichment disabled in settings.')
            return

        api_url = ICP.get_param(
            'lead_intelligence.gst_api_url',
            'https://sheet.gstzen.in/api/v1/gstin')
        api_key = ICP.get_param('lead_intelligence.gst_api_key', '')

        for lead in self:
            gstin = (lead.x_gstin or '').strip().upper()
            if not gstin or len(gstin) != 15:
                _logger.info('[ENRICH] Skipping Lead %s — no valid GSTIN.', lead.id)
                continue

            # Rate limit: check company-level last API call timestamp
            company = lead.company_id or self.env.company
            last_call = company.x_last_api_call if hasattr(company, 'x_last_api_call') and company.x_last_api_call else False
            now = fields.Datetime.now()
            if last_call and (now - last_call).total_seconds() < 6:
                _logger.info('[ENRICH] Rate-limited. Skipping Lead %s.', lead.id)
                continue

            # Update rate-limit timestamp
            try:
                company.sudo().write({'x_last_api_call': now})
            except Exception:
                pass  # Field may not exist if res.company not extended yet

            # Call GST API
            url = f"{api_url}/{gstin}"
            headers = {}
            if api_key:
                headers['Authorization'] = f'Bearer {api_key}'

            try:
                resp = requests.get(url, headers=headers, timeout=10)
                if resp.status_code == 200:
                    data = resp.json()
                    self._process_gst_response(lead, data)
                else:
                    _logger.warning(
                        '[ENRICH] GST API returned %s for GSTIN %s (Lead %s)',
                        resp.status_code, gstin, lead.id)
            except requests.exceptions.Timeout:
                _logger.warning('[ENRICH] GST API timeout for GSTIN %s (Lead %s)', gstin, lead.id)
            except requests.exceptions.ConnectionError:
                _logger.warning('[ENRICH] GST API connection error for GSTIN %s (Lead %s)', gstin, lead.id)
            except Exception as e:
                _logger.warning('[ENRICH] GST API error for Lead %s: %s', lead.id, e)

    def _process_gst_response(self, lead, data):
        """Parse GST API response and update lead fields."""
        try:
            vals = {
                'x_enriched': True,
                'x_enrichment_date': fields.Datetime.now(),
            }

            # Legal name
            legal_name = data.get('lgnm') or data.get('tradeNam') or data.get('legal_name', '')
            if legal_name:
                vals['x_company_legal_name'] = legal_name

            # GST Status
            status_raw = (data.get('sts') or data.get('status') or '').lower()
            if 'active' in status_raw:
                vals['x_gst_status'] = 'active'
            elif 'cancel' in status_raw:
                vals['x_gst_status'] = 'cancelled'
            elif 'suspend' in status_raw:
                vals['x_gst_status'] = 'suspended'

            # Business type
            biz_type = data.get('ctb') or data.get('constitution_of_business', '')
            if biz_type:
                vals['x_business_type'] = biz_type

            # Address
            addr_parts = []
            pradr = data.get('pradr', {})
            if isinstance(pradr, dict):
                addr = pradr.get('addr', {})
                if isinstance(addr, dict):
                    for key in ['bno', 'flno', 'bnm', 'st', 'loc', 'dst', 'stcd', 'pncd']:
                        v = addr.get(key, '')
                        if v:
                            addr_parts.append(str(v))
            if addr_parts:
                vals['x_gst_address'] = ', '.join(addr_parts)

            lead.write(vals)

            lead.message_post(
                body=f"Lead enriched via GST lookup. Legal Name: {legal_name or 'N/A'}, "
                     f"Status: {vals.get('x_gst_status', 'N/A')}",
                message_type='comment',
                subtype_xmlid='mail.mt_note',
            )
            _logger.info('[ENRICH] Successfully enriched Lead %s from GSTIN %s', lead.id, lead.x_gstin)

        except Exception as e:
            _logger.warning('[ENRICH] Error processing GST response for Lead %s: %s', lead.id, e)

    # =====================================================================
    # LEAD SCORING ENGINE
    # =====================================================================
    @api.depends(
        'source_id', 'email_from', 'phone', 'x_gstin',
        'expected_revenue', 'message_ids',
    )
    def _compute_lead_score(self):
        """Compute weighted lead score (0-100) and grade."""
        config = self.env['x.lead.scoring.config']._get_config()
        city_tiers = self.env['x.city.tier'].search([])

        # Build city lookup: lowercase city name -> tier value
        city_map = {}
        for ct in city_tiers:
            city_map[ct.name.strip().lower()] = ct.tier

        for lead in self:
            scores = {}

            # 1. Source Quality
            scores['source_quality'] = self._score_source_quality(lead, config)

            # 2. Contact Completeness
            scores['contact_completeness'] = self._score_contact_completeness(lead, config)

            # 3. Geographic Match
            scores['geographic_match'] = self._score_geographic_match(lead, config, city_map)

            # 4. Estimated Deal Size
            scores['deal_size'] = self._score_deal_size(lead, config)

            # 5. Engagement Speed
            scores['engagement_speed'] = self._score_engagement_speed(lead, config)

            # 6. Duplicate Flag
            scores['duplicate_flag'] = self._score_duplicate_flag(lead, config)

            total = sum(scores.values())
            total = max(0, min(100, total))

            # Grade
            if total >= 80:
                grade = 'a'
            elif total >= 60:
                grade = 'b'
            elif total >= 40:
                grade = 'c'
            else:
                grade = 'd'

            lead.x_lead_score = total
            lead.x_lead_grade = grade
            lead.x_score_breakdown = json.dumps(scores, indent=2)

    def _score_source_quality(self, lead, config):
        """Score based on lead source."""
        weight = config.weight_source_quality
        source_name = (lead.source_id.name or '').lower() if lead.source_id else ''

        if 'indiamart' in source_name:
            ratio = 15 / 20
        elif 'aajjo' in source_name:
            ratio = 12 / 20
        elif 'website' in source_name or 'web' in source_name:
            ratio = 10 / 20
        else:
            ratio = 5 / 20

        return round(weight * ratio)

    def _score_contact_completeness(self, lead, config):
        """Score based on contact info completeness."""
        weight = config.weight_contact_completeness
        points = 0
        max_points = 15

        if lead.email_from:
            points += 5
        if lead.phone:
            points += 5
        if lead.x_gstin:
            points += 5

        return round(weight * (points / max_points))

    def _score_geographic_match(self, lead, config, city_map):
        """Score based on city tier matching."""
        weight = config.weight_geographic_match
        business_area = ''

        # Safely get x_business_area — may exist from another module
        try:
            business_area = (lead.x_business_area or '').strip().lower()
        except Exception:
            business_area = ''

        if not business_area:
            return round(weight * (3 / 15))

        # Try partial match against city names
        matched_tier = None
        for city_name, tier in city_map.items():
            if city_name in business_area or business_area in city_name:
                matched_tier = tier
                break

        if matched_tier == 'tier_1':
            ratio = 15 / 15
        elif matched_tier == 'tier_2':
            ratio = 10 / 15
        elif matched_tier == 'tier_3':
            ratio = 5 / 15
        else:
            ratio = 3 / 15

        return round(weight * ratio)

    def _score_deal_size(self, lead, config):
        """Score based on expected revenue."""
        weight = config.weight_deal_size
        rev = lead.expected_revenue or 0

        if rev > 500000:
            ratio = 20 / 20
        elif rev >= 100000:
            ratio = 15 / 20
        elif rev >= 50000:
            ratio = 10 / 20
        else:
            ratio = 5 / 20

        return round(weight * ratio)

    def _score_engagement_speed(self, lead, config):
        """Score based on first message response time after lead creation."""
        weight = config.weight_engagement_speed

        if not lead.create_date:
            return 0

        # Find first mail.message after creation (excluding automated/system)
        first_msg = self.env['mail.message'].sudo().search([
            ('res_id', '=', lead.id),
            ('model', '=', 'crm.lead'),
            ('message_type', 'in', ['comment', 'email']),
            ('date', '>', lead.create_date),
        ], order='date asc', limit=1)

        if not first_msg:
            return 0

        delta = first_msg.date - lead.create_date
        hours = delta.total_seconds() / 3600

        if hours <= 1:
            ratio = 15 / 15
        elif hours <= 4:
            ratio = 10 / 15
        elif hours <= 24:
            ratio = 5 / 15
        else:
            ratio = 0

        return round(weight * ratio)

    def _score_duplicate_flag(self, lead, config):
        """Score: full weight if NOT a duplicate, 0 if duplicate."""
        weight = config.weight_duplicate_flag

        is_dup = False
        try:
            is_dup = bool(lead.duplicate_flag) if hasattr(lead, 'duplicate_flag') else False
        except Exception:
            pass

        return weight if not is_dup else 0

    # =====================================================================
    # ENHANCED DUPLICATE DETECTION
    # =====================================================================
    def _find_and_link_duplicate(self):
        """After duplicate detection, link x_duplicate_of to the original."""
        for lead in self:
            is_dup = False
            try:
                is_dup = bool(lead.duplicate_flag) if hasattr(lead, 'duplicate_flag') else False
            except Exception:
                pass

            if not is_dup:
                if lead.x_duplicate_of:
                    lead.x_duplicate_of = False
                continue

            # Find the original (oldest non-self lead with same phone/email)
            domain = []
            if lead.phone:
                domain.append(('phone', 'ilike', lead.phone[-10:]))
            if lead.email_from:
                if domain:
                    domain = ['|'] + domain + [('email_from', '=ilike', lead.email_from)]
                else:
                    domain = [('email_from', '=ilike', lead.email_from)]

            if domain:
                domain += [('id', '!=', lead.id)]
                original = self.search(domain, order='create_date asc', limit=1)
                if original:
                    lead.x_duplicate_of = original.id

    # =====================================================================
    # CREATE / WRITE OVERRIDES
    # =====================================================================
    @api.model_create_multi
    def create(self, vals_list):
        leads = super().create(vals_list)

        for lead in leads:
            # Trigger enrichment if GSTIN provided
            try:
                if lead.x_gstin:
                    lead.action_enrich_lead()
            except Exception as e:
                _logger.warning('[INTELLIGENCE] Enrichment on create failed for Lead %s: %s', lead.id, e)

            # Link duplicate reference
            try:
                lead._find_and_link_duplicate()
            except Exception as e:
                _logger.warning('[INTELLIGENCE] Duplicate link failed for Lead %s: %s', lead.id, e)

        return leads

    def write(self, vals):
        res = super().write(vals)

        # Re-enrich if GSTIN changed
        if 'x_gstin' in vals:
            for lead in self:
                try:
                    if lead.x_gstin:
                        lead.action_enrich_lead()
                except Exception as e:
                    _logger.warning('[INTELLIGENCE] Enrichment on write failed for Lead %s: %s', lead.id, e)

        # Update duplicate link if phone/email changed
        if 'phone' in vals or 'email_from' in vals or 'duplicate_flag' in vals:
            try:
                self._find_and_link_duplicate()
            except Exception:
                pass

        return res

    # =====================================================================
    # ACTION: Open Merge Wizard
    # =====================================================================
    def action_open_merge_wizard(self):
        """Open lead merge wizard for this duplicate lead."""
        self.ensure_one()
        if not self.x_duplicate_of:
            raise UserError(_('No duplicate reference found. Cannot merge.'))

        return {
            'type': 'ir.actions.act_window',
            'name': _('Merge Leads'),
            'res_model': 'x.lead.merge.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_x_lead_duplicate_id': self.id,
                'default_x_lead_original_id': self.x_duplicate_of.id,
            },
        }

    # =====================================================================
    # ACTION: Recompute Scores (manual)
    # =====================================================================
    def action_recompute_score(self):
        """Manual button to recompute lead score."""
        self._compute_lead_score()
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Score Updated'),
                'message': _('Lead score recalculated: %s (Grade %s)') % (
                    self.x_lead_score, (self.x_lead_grade or '').upper()),
                'type': 'success',
                'sticky': False,
            },
        }


class ResCompanyIntelligence(models.Model):
    _inherit = 'res.company'

    x_last_api_call = fields.Datetime('Last GST API Call', help='Rate-limit tracker')
