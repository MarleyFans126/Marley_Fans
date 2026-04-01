from odoo import models, fields, api, _
from odoo.exceptions import ValidationError
import base64
import logging
import os
import re

_logger = logging.getLogger(__name__)

# ── Marley introduction email content ──
_MARLEY_EMAIL_SUBJECT = (
    "Introduction \u2013 Marley Enterprises | One of India\u2019s Leading "
    "HVLS Fan Manufacturers"
)

_MARLEY_EMAIL_BODY = """\
<div style="margin:0; padding:0; font-family:Arial, sans-serif; font-size:13px; color:#333;">
<p>Dear Sir/Ma'am,</p>

<p>
Greetings from <strong>Marley Enterprises!</strong>
</p>

<p>
We are pleased to introduce ourselves as <strong>one of India's leading manufacturers
of HVLS (High Volume Low Speed) fans</strong>, proudly serving a wide range of industries
across the country.
</p>

<p>At Marley, we are committed to delivering <strong>innovative air circulation solutions</strong> that combine:</p>
<ul>
    <li>Superior engineering and build quality</li>
    <li>Energy-efficient performance</li>
    <li>Customizable designs to suit diverse industrial and commercial needs</li>
</ul>

<p>Our product range is designed to offer <strong>maximum airflow with minimum energy consumption</strong>, making us the preferred choice for:</p>
<ul>
    <li>Warehouses &amp; Logistics Hubs</li>
    <li>Manufacturing &amp; Assembly Plants</li>
    <li>Commercial Spaces &amp; Showrooms</li>
    <li>Dairy Farms &amp; Agricultural Facilities</li>
    <li>Airports, Railway Stations &amp; Public Infrastructure</li>
</ul>

<p><strong>Why Marley HVLS Fans?</strong></p>
<ul>
    <li>Made in India with globally benchmarked standards</li>
    <li>Pan-India installation and after-sales support</li>
    <li>Trusted by 500+ clients across 20+ industries</li>
    <li>5-year warranty on mechanical parts</li>
</ul>

<p>
We would love the opportunity to discuss how our HVLS fans can add value to your facility.
Please find attached our <strong>Latest Brochure</strong> and <strong>Client List</strong>
for your reference.
</p>

<p>
Looking forward to connecting with you.
</p>

<p>
Warm regards,<br/>
<strong>Team Marley Enterprises</strong><br/>
<a href="https://www.marleyfan.com">www.marleyfan.com</a>
</p>
</div>"""

class CrmLead(models.Model):
    _inherit = 'crm.lead'

    # -------------------------------------------------------------------------
    # NEW AUTOMATION FIELDS
    # -------------------------------------------------------------------------
    acknowledgment_sent = fields.Boolean(default=False, string="Acknowledgment Sent")
    salesperson_notified = fields.Boolean(default=False, string="Salesperson Notified")
    whatsapp_ack_sent = fields.Boolean(default=False, string="WhatsApp Ack Sent")
    qualify_email_sent = fields.Boolean(default=False, string="Qualify Email Sent")
    qualify_whatsapp_sent = fields.Boolean(default=False, string="Qualify WhatsApp Sent")
    
    # Duplicate Logic Fields
    duplicate_flag = fields.Boolean(string='Duplicate Lead', default=False, index=True)
    is_duplicate = fields.Boolean(string='Is Duplicate (Legacy)', related='duplicate_flag', readonly=True, store=True)
    duplicate_count = fields.Integer(string='Duplicate Count', compute='_compute_duplicate_info')
    duplicate_star = fields.Char(string=' ', compute='_compute_duplicate_info', help="Displays ★ if duplicate")

    # Loss Logic Fields
    loss_reason_id = fields.Many2one('crm.lost.reason', string='Loss Reason')
    loss_remarks = fields.Text(string='Loss Remarks')
    
    # Fields moved from crm_aajjo_integration that are needed for general automation display
    second_salesperson_id = fields.Many2one('res.users', string='Second SalesPerson', domain=[('share', '=', False)])
    
    # Unified Source Flags (Shared across modules)
    is_indiamart = fields.Boolean(string='Is IndiaMART Lead', default=False, readonly=True)
    is_aajjo = fields.Boolean(string='Is AAJJO Lead', default=False, readonly=True)
    aajjo_lead_id = fields.Char(string='AAJJO Lead ID', readonly=True, copy=False)
    external_lead_id = fields.Char(string="External Lead ID", index=True, copy=False)

    # Lead Source Type (computed from flags)
    lead_source_type = fields.Selection([
        ('indiamart', 'IndiaMART'),
        ('aajjo', 'AAJJO'),
        ('manual', 'Manual'),
    ], string='Source', compute='_compute_lead_source_type', store=True)

    @api.depends('is_indiamart', 'is_aajjo')
    def _compute_lead_source_type(self):
        for lead in self:
            if lead.is_indiamart:
                lead.lead_source_type = 'indiamart'
            elif lead.is_aajjo:
                lead.lead_source_type = 'aajjo'
            else:
                lead.lead_source_type = 'manual'

    # Business Location — Cascading: State → City → Area
    business_state_id = fields.Many2one(
        'res.country.state',
        string='Business State',
        domain="[('country_id.code', '=', 'IN')]",
        tracking=True,
    )
    business_city_id = fields.Many2one(
        'business.city',
        string='Business City',
        domain="[('state_id', '=', business_state_id)]",
        tracking=True,
    )
    business_area_id = fields.Many2one(
        'business.area',
        string='Business Area',
        domain="[('city_id', '=', business_city_id)]",
        tracking=True,
    )
    business_pincode = fields.Char(string='Pincode', size=6, tracking=True)

    @api.onchange('business_state_id')
    def _onchange_business_state_id(self):
        """Clear city and area when state changes."""
        self.business_city_id = False
        self.business_area_id = False

    @api.onchange('business_city_id')
    def _onchange_business_city_id(self):
        """Clear area when city changes; auto-set state from city."""
        self.business_area_id = False
        if self.business_city_id and self.business_city_id.state_id:
            self.business_state_id = self.business_city_id.state_id

    # -------------------------------------------------------------------------
    # INIT: Update acknowledgment email template on module upgrade
    # -------------------------------------------------------------------------
    def init(self):
        """Replace the default acknowledgment email with Marley intro + PDF attachments."""
        template = self.env.ref(
            'crm_lead_automation_engine.email_template_lead_acknowledgment',
            raise_if_not_found=False,
        )
        if not template:
            return

        # Skip if already updated
        if 'Marley Enterprises' in (template.subject or ''):
            return

        # ── Create / find PDF attachments ──
        attachment_dir = os.path.join(
            os.path.dirname(os.path.dirname(__file__)),
            'static', 'attachments',
        )
        pdf_files = [
            ('Latest Brochure - 2026.pdf', 'Latest_Brochure_2026.pdf'),
            ('Marley Client List.pdf', 'Marley_Client_List.pdf'),
        ]
        attachment_ids = []
        for display_name, filename in pdf_files:
            filepath = os.path.join(attachment_dir, filename)
            if not os.path.isfile(filepath):
                _logger.warning("PDF not found: %s", filepath)
                continue

            existing = self.env['ir.attachment'].search([
                ('name', '=', display_name),
                ('res_model', '=', 'mail.template'),
                ('res_id', '=', template.id),
            ], limit=1)
            if existing:
                attachment_ids.append(existing.id)
            else:
                with open(filepath, 'rb') as f:
                    data = base64.b64encode(f.read())
                att = self.env['ir.attachment'].create({
                    'name': display_name,
                    'type': 'binary',
                    'datas': data,
                    'res_model': 'mail.template',
                    'res_id': template.id,
                    'mimetype': 'application/pdf',
                })
                attachment_ids.append(att.id)

        vals = {
            'name': 'Marley Introduction Email (New Stage)',
            'subject': _MARLEY_EMAIL_SUBJECT,
            'body_html': _MARLEY_EMAIL_BODY,
        }
        if attachment_ids:
            vals['attachment_ids'] = [(6, 0, attachment_ids)]

        template.write(vals)
        _logger.info(
            "Updated acknowledgment template → Marley introduction email "
            "with %d attachments.", len(attachment_ids),
        )

    # -------------------------------------------------------------------------
    # HELPER: Phone Normalization
    # -------------------------------------------------------------------------
    def _normalize_phone_for_search(self, number):
        """ 
        Strip non-numeric characters to improve matching. 
        Only keep digits.
        """
        if not number:
            return False
        sanitized = re.sub(r'\D', '', str(number))
        if len(sanitized) > 10:
             return sanitized[-10:]
        return sanitized

    # -------------------------------------------------------------------------
    # DUPLICATE DETECTION LOGIC
    # -------------------------------------------------------------------------
    @api.depends('duplicate_flag')
    def _compute_duplicate_info(self):
        """
        Compute the visual star indicator and duplicate count.
        """
        for lead in self:
            lead.duplicate_star = '★' if lead.duplicate_flag else ''
            if lead.duplicate_flag and lead.id:
                try:
                    domain = self._get_duplicate_domain(lead.phone, lead.email_from)
                    if domain:
                        count_domain = domain + [('id', '!=', lead.id)]
                        lead.duplicate_count = self.search_count(count_domain)
                    else:
                        lead.duplicate_count = 0
                except Exception:
                    lead.duplicate_count = 0
            else:
                lead.duplicate_count = 0

    def _get_duplicate_domain(self, phone, email):
        """ Return domain for finding duplicates based on phone OR email """
        domain = []
        
        if phone:
            sanitized = re.sub(r'\D', '', str(phone))
            if len(sanitized) >= 10:
                search_term = sanitized[-10:] 
                domain.append(('phone', 'ilike', search_term))
            else:
                domain.append(('phone', '=ilike', phone.strip()))

        if email:
            domain.append(('email_from', '=ilike', email.strip()))
        
        if not domain:
            return []
        
        if len(domain) > 1:
            return ['|'] + domain
        return domain

    def _check_and_mark_duplicates(self):
        """ 
        Check if current lead is a duplicate. 
        If yes, mark it AND the existing matches as duplicate.
        """
        for lead in self:
            if not lead.phone and not lead.email_from:
                continue

            domain = self._get_duplicate_domain(lead.phone, lead.email_from)
            if not domain:
                continue

            search_domain = domain + [('id', '!=', lead.id)]
            duplicates = self.search(search_domain)
            
            if duplicates:
                _logger.info(f"Duplicate found for Lead {lead.id}: {len(duplicates)} matches.")
                
                if not lead.duplicate_flag:
                    lead.duplicate_flag = True
                
                leads_to_flag = duplicates.filtered(lambda l: not l.duplicate_flag)
                if leads_to_flag:
                    leads_to_flag.write({'duplicate_flag': True})
                    _logger.info(f"Marked {len(leads_to_flag)} existing leads as duplicates of {lead.id}")
            
            else:
                if lead.duplicate_flag:
                    lead.duplicate_flag = False

    # -------------------------------------------------------------------------
    # AUTOMATION SERVICE HELPERS (previously in abstract mixin)
    # -------------------------------------------------------------------------
    def _auto_send_acknowledgment(self, lead):
        """ Send acknowledgment email + WhatsApp on lead creation (New stage) """
        ICP = self.env['ir.config_parameter'].sudo()

        # --- EMAIL ---
        auto_email = ICP.get_param('crm_automation.auto_email_enabled', 'False') == 'True'

        # Support native template attached to stage (new state)
        stage_template = False
        if lead.stage_id and 'mail_template_id' in lead.stage_id._fields and lead.stage_id.mail_template_id:
            stage_template = lead.stage_id.mail_template_id
        elif lead.stage_id and 'template_id' in lead.stage_id._fields and lead.stage_id.template_id:
            stage_template = lead.stage_id.template_id

        if stage_template and lead.email_from:
            try:
                stage_template.send_mail(lead.id, force_send=True)
                lead.acknowledgment_sent = True

                self.env['crm.email.log'].sudo().create({
                    'lead_id': lead.id,
                    'lead_name': lead.name or '',
                    'partner_name': lead.contact_name or lead.partner_name or '',
                    'email_to': lead.email_from,
                    'template_used': stage_template.name,
                    'status': 'sent',
                })
                _logger.info(f"[AUTO-NEW] Stage template sent for Lead {lead.id}")
            except Exception as e:
                self.env['crm.email.log'].sudo().create({
                    'lead_id': lead.id,
                    'lead_name': lead.name or '',
                    'partner_name': lead.contact_name or lead.partner_name or '',
                    'email_to': lead.email_from,
                    'template_used': getattr(stage_template, 'name', 'Stage Template'),
                    'status': 'failed',
                    'error_message': str(e),
                })
                _logger.error(f"[AUTO-NEW] Stage template failed for Lead {lead.id}: {e}")

        elif auto_email and lead.email_from:
            try:
                template = self.env.ref(
                    'crm_lead_automation_engine.email_template_lead_acknowledgment',
                    raise_if_not_found=False,
                )
                if template:
                    template.send_mail(lead.id, force_send=True)
                    lead.acknowledgment_sent = True

                    self.env['crm.email.log'].sudo().create({
                        'lead_id': lead.id,
                        'lead_name': lead.name or '',
                        'partner_name': lead.contact_name or lead.partner_name or '',
                        'email_to': lead.email_from,
                        'template_used': template.name,
                        'status': 'sent',
                    })
                    _logger.info(f"[AUTO-NEW] Acknowledgment email sent for Lead {lead.id} to {lead.email_from}")
                else:
                    _logger.warning(f"[AUTO-NEW] Acknowledgment email template not found for Lead {lead.id}")
            except Exception as e:
                self.env['crm.email.log'].sudo().create({
                    'lead_id': lead.id,
                    'lead_name': lead.name or '',
                    'partner_name': lead.contact_name or lead.partner_name or '',
                    'email_to': lead.email_from,
                    'template_used': 'Lead Acknowledgment Email',
                    'status': 'failed',
                    'error_message': str(e),
                })
                _logger.error(f"[AUTO-NEW] Acknowledgment email failed for Lead {lead.id}: {e}")
        else:
            if not auto_email:
                _logger.info(f"[AUTO-NEW] Auto email disabled in settings. Skipped Lead {lead.id}")

        # --- WHATSAPP ---
        auto_wa = ICP.get_param('crm_automation.auto_whatsapp_enabled', 'False') == 'True'
        if auto_wa and not lead.whatsapp_ack_sent:
            phone = lead.phone or getattr(lead, 'mobile', False)
            if phone and lead.partner_id:
                try:
                    if 'whatsapp.service' in self.env:
                        contact_name = lead.contact_name or lead.partner_id.name or ''
                        self.env['whatsapp.service'].send_template_message(
                            partner=lead.partner_id,
                            template_name='lead_auto_thankyou',
                            variables=[contact_name],
                        )
                        lead.whatsapp_ack_sent = True
                        lead.message_post(
                            body="WhatsApp 'lead_auto_thankyou' sent automatically on lead creation.",
                            message_type='comment',
                            subtype_xmlid='mail.mt_note',
                        )
                        _logger.info(f"[AUTO-NEW] WhatsApp sent for Lead {lead.id}")
                except Exception as e:
                    lead.message_post(
                        body=f"WhatsApp auto-send failed on creation: {e}",
                        message_type='comment',
                        subtype_xmlid='mail.mt_note',
                    )
                    _logger.error(f"[AUTO-NEW] WhatsApp failed for Lead {lead.id}: {e}")
            else:
                _logger.info(f"[AUTO-NEW] No phone/partner for WhatsApp. Skipped Lead {lead.id}")
        elif not auto_wa:
            _logger.info(f"[AUTO-NEW] Auto WhatsApp disabled in settings. Skipped Lead {lead.id}")

    def _auto_on_qualify(self, lead):
        """ Handle stage change to Qualify — send email + WhatsApp to client """
        _logger.info(f"[AUTO] Lead {lead.id} moved to Qualify stage.")
        ICP = self.env['ir.config_parameter'].sudo()

        # Post internal note
        if not lead.salesperson_notified and lead.user_id:
            try:
                lead.message_post(
                    body=f"Lead qualified and assigned to {lead.user_id.name}.",
                    message_type='comment',
                    subtype_xmlid='mail.mt_note',
                )
                lead.salesperson_notified = True
                _logger.info(f"[AUTO] Salesperson notified for Lead {lead.id}")
            except Exception as e:
                _logger.error(f"[AUTO] Error notifying salesperson for {lead.id}: {e}")

        # --- EMAIL: Send Qualify notification to client ---
        if not lead.qualify_email_sent and lead.email_from:
            auto_qualify_email = ICP.get_param('crm_automation.qualify_email_enabled', 'False') == 'True'
            if auto_qualify_email:
                try:
                    template = self.env.ref(
                        'crm_lead_automation_engine.email_template_lead_qualified',
                        raise_if_not_found=False,
                    )
                    if template:
                        template.send_mail(lead.id, force_send=True)
                        lead.qualify_email_sent = True

                        # Log the email
                        self.env['crm.email.log'].sudo().create({
                            'lead_id': lead.id,
                            'lead_name': lead.name or '',
                            'partner_name': lead.contact_name or lead.partner_name or '',
                            'email_to': lead.email_from,
                            'template_used': template.name,
                            'status': 'sent',
                        })
                        _logger.info(f"[AUTO-QUALIFY] Email sent for Lead {lead.id} to {lead.email_from}")
                    else:
                        _logger.warning(f"[AUTO-QUALIFY] Email template not found for Lead {lead.id}")
                except Exception as e:
                    self.env['crm.email.log'].sudo().create({
                        'lead_id': lead.id,
                        'lead_name': lead.name or '',
                        'partner_name': lead.contact_name or lead.partner_name or '',
                        'email_to': lead.email_from,
                        'template_used': 'Lead Qualified Notification',
                        'status': 'failed',
                        'error_message': str(e),
                    })
                    _logger.error(f"[AUTO-QUALIFY] Email failed for Lead {lead.id}: {e}")
            else:
                _logger.info(f"[AUTO-QUALIFY] Qualify email disabled in settings. Skipped Lead {lead.id}")

        # --- WHATSAPP: Send Qualify notification to client ---
        if not lead.qualify_whatsapp_sent:
            auto_qualify_wa = ICP.get_param('crm_automation.qualify_whatsapp_enabled', 'False') == 'True'
            if auto_qualify_wa:
                phone = lead.phone or getattr(lead, 'mobile', False)
                if phone and lead.partner_id:
                    try:
                        if 'whatsapp.service' in self.env:
                            contact_name = lead.contact_name or lead.partner_id.name or ''
                            sp_name = lead.user_id.name if lead.user_id else 'N/A'
                            sp_phone = lead.user_id.partner_id.phone if lead.user_id and lead.user_id.partner_id else 'N/A'
                            sp_email = lead.user_id.email if lead.user_id else 'N/A'

                            variables = [contact_name, sp_name, sp_phone, sp_email]
                            self.env['whatsapp.service'].send_template_message(
                                partner=lead.partner_id,
                                template_name='lead_qualified_notification',
                                variables=variables,
                            )
                            lead.qualify_whatsapp_sent = True
                            lead.message_post(
                                body=f"WhatsApp 'lead_qualified_notification' sent to client. "
                                     f"Salesperson: {sp_name}, Phone: {sp_phone}, Email: {sp_email}",
                                message_type='comment',
                                subtype_xmlid='mail.mt_note',
                            )
                            _logger.info(f"[AUTO-QUALIFY] WhatsApp sent for Lead {lead.id}")
                        else:
                            _logger.info(f"[AUTO-QUALIFY] whatsapp.service not available. Skipped Lead {lead.id}")
                    except Exception as e:
                        lead.message_post(
                            body=f"WhatsApp qualify notification failed: {e}",
                            message_type='comment',
                            subtype_xmlid='mail.mt_note',
                        )
                        _logger.error(f"[AUTO-QUALIFY] WhatsApp failed for Lead {lead.id}: {e}")
                else:
                    _logger.info(f"[AUTO-QUALIFY] No phone/partner for WhatsApp. Skipped Lead {lead.id}")
            else:
                _logger.info(f"[AUTO-QUALIFY] Qualify WhatsApp disabled in settings. Skipped Lead {lead.id}")

    def _auto_on_won(self, lead):
        """ Handle Won lead — delegates to marley_crm_enhancements conversion """
        _logger.info(f"[AUTO] Lead {lead.id} marked as Won.")
        try:
            if hasattr(lead, 'action_convert_to_won'):
                lead.action_convert_to_won()
        except Exception as e:
            _logger.error(f"[AUTO] Won conversion error for Lead {lead.id}: {e}")

    # -------------------------------------------------------------------------
    # CREATE OVERRIDE
    # -------------------------------------------------------------------------
    @api.model_create_multi
    def create(self, vals_list):
        leads = super().create(vals_list)

        for lead in leads:
            try:
                lead._check_and_mark_duplicates()
            except Exception as e:
                _logger.error(f"Lead Creation Duplicate Check Error for {lead.id}: {e}")

            # Auto-send acknowledgment for both pipeline opportunities and reporting leads
            try:
                stage_name = lead.stage_id.name.strip().lower() if lead.stage_id else 'new'
                if stage_name == 'new' and not lead.acknowledgment_sent and not lead.duplicate_flag:
                    _logger.info(f"[AUTO] Triggering New stage acknowledgment for Lead {lead.id}")
                    self._auto_send_acknowledgment(lead)
            except Exception as e:
                _logger.error(f"[AUTO] New stage auto-send error for Lead {lead.id}: {e}")

        return leads

    # -------------------------------------------------------------------------
    # WRITE OVERRIDE
    # -------------------------------------------------------------------------
    def write(self, vals):
        res = super().write(vals)

        if 'phone' in vals or 'email_from' in vals:
            self._check_and_mark_duplicates()

        # Stage change automation — ONLY for pipeline opportunities
        if 'stage_id' in vals:
            for rec in self:
                try:
                    if rec.type != 'opportunity':
                        _logger.info(f"[AUTO] Skipping stage automation for non-pipeline lead {rec.id} (type={rec.type})")
                        continue

                    new_stage = rec.stage_id
                    new_name = new_stage.name.strip().lower() if new_stage else ''

                    if new_name == 'new' and not rec.acknowledgment_sent:
                        self._auto_send_acknowledgment(rec)

                    if new_name in ['qualified', 'qualify']:
                        self._auto_on_qualify(rec)

                    if new_stage.is_won:
                        self._auto_on_won(rec)

                except Exception as e:
                    _logger.error(f"[AUTO] Stage change error for Lead {rec.id}: {e}")

        # When lead is converted to opportunity (enters pipeline) — use COMMON templates
        if vals.get('type') == 'opportunity':
            for rec in self:
                try:
                    stage_name = rec.stage_id.name.strip().lower() if rec.stage_id else 'new'
                    if stage_name == 'new' and not rec.acknowledgment_sent and not rec.duplicate_flag:
                        _logger.info(f"[AUTO] Lead {rec.id} converted to opportunity in New stage — triggering acknowledgment")
                        self._auto_send_acknowledgment(rec)
                    else:
                        _logger.info(f"[AUTO] Lead {rec.id} converted to opportunity — ack already sent or not in New stage")
                except Exception as e:
                    _logger.error(f"[AUTO] Opportunity conversion auto-send error for Lead {rec.id}: {e}")

        return res

    # -------------------------------------------------------------------------
    # DEBUG / UI ACTION METHODS
    # -------------------------------------------------------------------------
    def action_debug_send_acknowledgment(self):
        for lead in self:
            lead._auto_send_acknowledgment(lead)
        return True

    def action_debug_reset_flags(self):
        """ Reset automation flags for testing. """
        self.write({
            'acknowledgment_sent': False,
            'salesperson_notified': False,
            'duplicate_flag': False,
            'qualify_email_sent': False,
            'qualify_whatsapp_sent': False,
        })
        return True

    def action_manual_duplicate_check(self):
        """ Allow user to force duplicate check from UI """
        for lead in self:
             lead._check_and_mark_duplicates()
        
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Duplicate Check Complete',
                'message': 'Checked lead for duplicates. See flag status.',
                'type': 'success',
                'sticky': False,
            }
        }

    @api.model
    def action_open_leads_with_whatsapp_check(self):
        # 1. Base CRM action
        action = self.env['ir.actions.act_window']._for_xml_id('crm.crm_lead_all_leads')

        # 2. Only admin gets the wizard
        if not self.env.is_admin():
            return action

        # 3. Check for pending leads
        pending_domain = [
            ('stage_id.name', '=ilike', 'new'),
            '|',
            ('is_indiamart', '=', True),
            ('is_aajjo', '=', True),
            ('whatsapp_ack_sent', '=', False)
        ]
        pending_leads = self.search(pending_domain)

        # 4. If pending, return wizard action instead, passing the leads
        if pending_leads:
            return {
                'type': 'ir.actions.act_window',
                'name': 'Pending WhatsApp Approvals',
                'res_model': 'lead.whatsapp.bulk.approve.wizard',
                'view_mode': 'form',
                'target': 'new',
                'context': {
                    'default_lead_ids': [(6, 0, pending_leads.ids)]
                }
            }

        return action

