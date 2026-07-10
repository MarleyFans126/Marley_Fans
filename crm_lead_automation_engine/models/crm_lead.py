from odoo import models, fields, api, _
from odoo.exceptions import ValidationError
import base64
import logging
import os
import re

_logger = logging.getLogger(__name__)


class CrmLead(models.Model):
    _inherit = 'crm.lead'

    # -------------------------------------------------------------------------
    # NEW AUTOMATION FIELDS
    # -------------------------------------------------------------------------
    acknowledgment_sent = fields.Boolean(default=False, string="Acknowledgment Sent (New Stage)")
    qualify_email_sent = fields.Boolean(default=False, string="Qualify Email Sent")
    proposition_email_sent = fields.Boolean(default=False, string="Proposition Email Sent")
    won_email_sent = fields.Boolean(default=False, string="Won Email Sent")
    salesperson_notified = fields.Boolean(default=False, string="Salesperson Notified")
    whatsapp_ack_sent = fields.Boolean(default=False, string="WhatsApp Ack Sent")
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

    # Salesperson lock: only Sales Administrators may (re)assign the
    # Salesperson. For everyone else the field is read-only in the form
    # (the server-side auto-assign / propagation is unaffected).
    can_edit_salesperson = fields.Boolean(
        compute='_compute_can_edit_salesperson',
        help='True when the current user may (re)assign the Salesperson.')

    def _compute_can_edit_salesperson(self):
        user = self.env.user
        # "User: All Documents" and "Administrator" may (re)assign ANY lead's
        # Salesperson (Administrator implies All Documents, so this one group
        # check covers both). An "Own Documents Only" user may change it only on
        # their OWN lead (or one that's still unassigned).
        can_edit_any = user.has_group('sales_team.group_sale_salesman_all_leads')
        for lead in self:
            lead.can_edit_salesperson = (
                can_edit_any or not lead.user_id or lead.user_id == user
            )

    # Unified Source Flags (Shared across modules)
    is_indiamart = fields.Boolean(string='Is IndiaMART Lead', default=False, readonly=True)
    is_aajjo = fields.Boolean(string='Is AAJJO Lead', default=False, readonly=True)
    is_manual_lead = fields.Boolean(string='Is Manual Lead', default=True)
    aajjo_lead_id = fields.Char(string='AAJJO Lead ID', readonly=True, copy=False)
    external_lead_id = fields.Char(string="External Lead ID", index=True, copy=False)

    # Project link (stored as Integer to avoid hard dependency on project module)
    linked_project_id = fields.Integer(string='Project ID', readonly=True, copy=False)

    # Lead Source Type (computed from flags)
    lead_source_type = fields.Selection([
        ('indiamart', 'IndiaMART'),
        ('aajjo', 'AAJJO'),
    ], string='Source', compute='_compute_lead_source_type', store=True, default=False)

    lead_source = fields.Char(string='Lead Source', tracking=True)
    inquiry_creation_date = fields.Datetime(string='Inquiry Creation Date', tracking=True)

    @api.depends('is_indiamart', 'is_aajjo', 'is_manual_lead')
    def _compute_lead_source_type(self):
        for lead in self:
            if lead.is_indiamart:
                lead.lead_source_type = 'indiamart'
            elif lead.is_aajjo:
                lead.lead_source_type = 'aajjo'
            else:
                lead.lead_source_type = False

    # Business Location — Cascading: State → City → Area
    business_state_id = fields.Many2one(
        'res.country.state',
        string='Business State',
        domain="[('country_id.code', '=', 'IN')]",
        compute='_compute_business_location_from_partner',
        store=True,
        readonly=False,
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
    business_city = fields.Char(
        string='Business City',
        compute='_compute_business_location_from_partner',
        store=True,
        readonly=False,
        tracking=True,
    )
    business_area = fields.Char(
        string='Business Area',
        tracking=True,
    )
    business_pincode = fields.Char(
        string='Pincode',
        size=6,
        compute='_compute_business_location_from_partner',
        store=True,
        readonly=False,
        tracking=True,
    )

    @api.depends('partner_id', 'partner_id.state_id', 'partner_id.city', 'partner_id.zip')
    def _compute_business_location_from_partner(self):
        """Auto-fill Business State / City / Pincode from the customer.
        Business Area is intentionally NOT computed — it stays a manual entry.
        Fields are readonly=False so users can still type over them.
        """
        for rec in self:
            partner = rec.partner_id
            if partner:
                # Only overwrite when the partner has a value, otherwise keep
                # whatever the user typed in.
                if partner.state_id:
                    rec.business_state_id = partner.state_id
                if partner.city:
                    rec.business_city = partner.city
                if partner.zip:
                    rec.business_pincode = partner.zip

    # @api.onchange('business_state_id')
    # def _onchange_business_state_id(self):
    #     """Clear city and area when state changes."""
    #     self.business_city_id = False
    #     self.business_area_id = False

    # @api.onchange('business_city_id')
    # def _onchange_business_city_id(self):
    #     """Clear area when city changes; auto-set state from city."""
    #     self.business_area_id = False
    #     if self.business_city_id and self.business_city_id.state_id:
    #         self.business_state_id = self.business_city_id.state_id


    @api.onchange('partner_id')
    def _onchange_partner_location(self):
        # State / City / Pincode are now handled by the stored compute
        # `_compute_business_location_from_partner`.
        # business_area remains a manual entry — no auto-fetch from partner.
        return


    # -------------------------------------------------------------------------
    # INIT: Cleanup stale views on module upgrade
    # -------------------------------------------------------------------------
    def init(self):
        """Cleanup stale views referencing fields from uninstalled modules.

        Also force-update the built-in "Personal Leads" record rule so that a
        salesperson whose profile is "Own Documents Only" can also see leads
        where they are the Second Salesperson. The original rule is shipped
        with ``noupdate="1"`` so editing it via XML doesn't stick — we patch
        it in place here.
        """
        # Widen the CRM "Personal Leads" rule to include second_salesperson_id
        try:
            rule = self.env.ref('crm.crm_rule_personal_lead', raise_if_not_found=False)
            if rule and 'second_salesperson_id' in self._fields:
                # Own Documents salespeople see ONLY their own leads and leads
                # where they are the Second Salesperson — not unassigned leads
                # and not other people's.
                new_domain = (
                    "['|', ('user_id', '=', user.id), "
                    "('second_salesperson_id', '=', user.id)]"
                )
                if rule.domain_force != new_domain:
                    rule.sudo().write({
                        'domain_force': new_domain,
                        'name': 'Personal Leads (incl. Second Salesperson)',
                    })
                    _logger.info(
                        "[INIT] Patched crm.crm_rule_personal_lead to include second_salesperson_id."
                    )
        except Exception as e:
            _logger.warning("[INIT] Could not patch Personal Leads rule: %s", e)

        stale_fields = ['l10n_in_gsp']
        for field_name in stale_fields:
            try:
                if field_name in self.env['res.config.settings']._fields:
                    continue
                stale_views = self.env['ir.ui.view'].sudo().search([
                    ('model', '=', 'res.config.settings'),
                    ('arch_db', 'like', field_name),
                ])
                if stale_views:
                    _logger.info("[INIT] Deactivating %d stale view(s) referencing %s", len(stale_views), field_name)
                    stale_views.write({'active': False})
            except Exception as e:
                _logger.warning("[INIT] Could not clean stale views for %s: %s", field_name, e)

        # Clear stale Selection-field values across ALL models.  Leftover values that are
        # not in the current options list crash the web SelectionField renderer:
        #   TypeError: Cannot read properties of undefined (reading '1') at get string
        # Only scan text/varchar columns (selection fields with translate=True become jsonb).
        # Use savepoints so one bad query doesn't abort the whole upgrade transaction.
        try:
            self.env.cr.execute(
                "SELECT table_name, column_name, data_type "
                "FROM information_schema.columns "
                "WHERE table_schema = 'public'"
            )
            db_cols = {}
            for table, col, dtype in self.env.cr.fetchall():
                if dtype in ('character varying', 'text', 'char'):
                    db_cols.setdefault(table, set()).add(col)

            total_cleaned = 0
            for model_name, Model in self.env.registry.items():
                if Model._abstract or Model._transient:
                    continue
                table = Model._table
                table_cols = db_cols.get(table)
                if not table_cols:
                    continue
                model = self.env[model_name].sudo()
                for fname, field in model._fields.items():
                    if field.type != 'selection' or not field.store:
                        continue
                    if fname not in table_cols:
                        continue
                    try:
                        selection = field.get_values(self.env)
                    except Exception:
                        continue
                    if not selection:
                        continue
                    self.env.cr.execute('SAVEPOINT sel_cleanup')
                    try:
                        self.env.cr.execute(
                            'UPDATE "%s" SET "%s" = NULL '
                            'WHERE "%s" IS NOT NULL AND "%s" <> ALL(%%s)'
                            % (table, fname, fname, fname),
                            (list(selection),),
                        )
                        if self.env.cr.rowcount:
                            total_cleaned += self.env.cr.rowcount
                            _logger.info(
                                "[INIT] Cleared %d %s row(s) with stale %s value",
                                self.env.cr.rowcount, table, fname,
                            )
                        self.env.cr.execute('RELEASE SAVEPOINT sel_cleanup')
                    except Exception as inner:
                        self.env.cr.execute('ROLLBACK TO SAVEPOINT sel_cleanup')
                        _logger.warning(
                            "[INIT] Cleanup for %s.%s failed: %s",
                            table, fname, inner,
                        )
            if total_cleaned:
                _logger.info("[INIT] Selection cleanup cleared %d total row(s)", total_cleaned)
        except Exception as e:
            _logger.warning("[INIT] Could not clean stale Selection values: %s", e)

    # -------------------------------------------------------------------------
    # HELPER: Phone Normalization
    # -------------------------------------------------------------------------
    def _normalize_phone_for_search(self, number):
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
        for lead in self:
            lead.duplicate_star = '★' if lead.duplicate_flag else ''
            if lead.duplicate_flag and lead.id:
                try:
                    domain = self._get_duplicate_domain(lead.phone, lead.email_from, lead._lead_company_name())
                    if domain:
                        count_domain = domain + [('id', '!=', lead.id)]
                        lead.duplicate_count = self.search_count(count_domain)
                    else:
                        lead.duplicate_count = 0
                except Exception:
                    lead.duplicate_count = 0
            else:
                lead.duplicate_count = 0

    @api.model
    def _normalize_company_name(self, name):
        """Normalized 'core' of a company name for fuzzy duplicate matching:
        lowercased, parenthetical qualifiers and common legal suffixes removed,
        punctuation stripped, whitespace collapsed. Returns '' when nothing
        meaningful is left. e.g. 'Airserve Engineering (JSW Cement)' and
        'Airserve Engineering Pvt. Ltd.' both reduce to 'airserve engineering'.
        """
        if not name:
            return ''
        s = name.lower()
        # Drop bracketed qualifiers e.g. "(JSW Cement)", "[Unit 2]".
        s = re.sub(r'[\(\[\{][^\)\]\}]*[\)\]\}]', ' ', s)
        # Drop common legal / entity suffixes (keep descriptive words like
        # "engineering" / "industries" so the core stays specific).
        s = re.sub(
            r'\b(private limited|pvt\.?\s*ltd\.?|p\.?\s*ltd\.?|limited|ltd\.?|'
            r'llp|inc\.?|incorporated|corp\.?|corporation|company|co\.?|'
            r'and co|& co)\b',
            ' ', s)
        # Strip punctuation, collapse whitespace.
        s = re.sub(r'[^a-z0-9 ]', ' ', s)
        return re.sub(r'\s+', ' ', s).strip()

    def _lead_company_name(self):
        """Best available company name for duplicate matching: the free-text
        Company Name, else the linked customer's commercial (company) name."""
        self.ensure_one()
        if self.partner_name:
            return self.partner_name
        if self.partner_id:
            return (self.partner_id.commercial_partner_id.name
                    or self.partner_id.name or '')
        return ''

    def _get_duplicate_domain(self, phone, email, company_name=None):
        # Each entry is a sub-domain; the whole thing is OR-ed together.
        clauses = []
        if phone:
            sanitized = re.sub(r'\D', '', str(phone))
            if len(sanitized) >= 10:
                clauses.append([('phone', 'ilike', sanitized[-10:])])
            else:
                clauses.append([('phone', '=ilike', phone.strip())])
        if email:
            clauses.append([('email_from', '=ilike', email.strip())])
        # Company-name similarity: flag leads whose company shares the same
        # normalized core (legal suffixes / parenthetical qualifiers stripped),
        # e.g. "Airserve Engineering" ~ "Airserve Engineering (JSW Cement)".
        # The company can live in the free-text Company Name OR the linked
        # customer, so match either. Only when the core is specific enough
        # (>= 5 chars) to avoid noise.
        core = self._normalize_company_name(company_name)
        if len(core) >= 5:
            clauses.append([
                '|',
                ('partner_name', 'ilike', core),
                ('partner_id.commercial_partner_id.name', 'ilike', core),
            ])
        if not clauses:
            return []
        # OR the sub-domains together (needs N-1 leading '|' operators).
        domain = ['|'] * (len(clauses) - 1)
        for c in clauses:
            domain += c
        return domain

    def _check_and_mark_duplicates(self):
        for lead in self:
            company = lead._lead_company_name()
            if not lead.phone and not lead.email_from and not company:
                continue
            domain = self._get_duplicate_domain(lead.phone, lead.email_from, company)
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
            else:
                if lead.duplicate_flag:
                    lead.duplicate_flag = False

    # -------------------------------------------------------------------------
    # AUTO-CREATE PROJECT (as soon as lead enters pipeline)
    # -------------------------------------------------------------------------
    def _auto_create_project(self, lead):
        """Create a project linked to this lead when it enters the pipeline."""
        if lead.linked_project_id:
            return  # already has a project
        _logger.info(f"[AUTO-PROJECT] Creating project for Lead {lead.id}")
        try:
            if 'project.project' not in self.env:
                _logger.info("[AUTO-PROJECT] project module not installed, skipping.")
                return
            project_vals = {
                'name': lead.name or 'Lead %s' % lead.id,
                'partner_id': lead.partner_id.id if lead.partner_id else False,
                'lead_id': lead.id,
                'site_contact_person': lead.contact_name or '',
                'site_contact_number': lead.phone or '',
            }
            project = self.env['project.project'].sudo().create(project_vals)
            lead.write({'linked_project_id': project.id})
            _logger.info(f"[AUTO-PROJECT] Created Project {project.id} for Lead {lead.id}")
        except Exception as e:
            _logger.error(f"[AUTO-PROJECT] Failed for Lead {lead.id}: {e}")

    # -------------------------------------------------------------------------
    # CREATE OVERRIDE — lightweight only (no email/project here)
    # -------------------------------------------------------------------------
    @api.model_create_multi
    def create(self, vals_list):
        leads = super().create(vals_list)

        for lead in leads:
            try:
                lead._check_and_mark_duplicates()
            except Exception as e:
                _logger.error(f"Lead Creation Duplicate Check Error for {lead.id}: {e}")

            # business_state_id / business_city / business_pincode are
            # populated by the stored compute on partner_id change.
            # business_area remains a manual entry.

        return leads

    # -------------------------------------------------------------------------
    # WRITE OVERRIDE — lightweight only
    # -------------------------------------------------------------------------
    def write(self, vals):
        res = super().write(vals)

        # Duplicate detection on phone / email / company-name change
        if 'phone' in vals or 'email_from' in vals or 'partner_name' in vals:
            self._check_and_mark_duplicates()

        if 'partner_id' in vals:
            for lead in self:
                if lead.partner_id:
                    lead._onchange_partner_location()

        # Propagate salesperson / second-salesperson changes to linked
        # quotations and sale orders so the lead and its quotations stay
        # aligned. Skip cancelled SOs.
        propagate_vals = {}
        so_fields = self.env['sale.order']._fields
        if 'user_id' in vals:
            propagate_vals['user_id'] = vals['user_id']
        # Lead's second_salesperson_id maps to SO's second_user_id (Marley
        # custom field for "Additional Salesperson" on the proforma tab).
        if 'second_salesperson_id' in vals and 'second_user_id' in so_fields:
            propagate_vals['second_user_id'] = vals['second_salesperson_id']
        if propagate_vals:
            for lead in self:
                orders = self.env['sale.order'].sudo().search([
                    ('opportunity_id', '=', lead.id),
                    ('state', '!=', 'cancel'),
                ])
                if orders:
                    orders.write(propagate_vals)

        return res

    # -------------------------------------------------------------------------
    # STAGE EMAIL: Send stage-based email (called from automated action)
    # Emails are sent via message_post so they appear in the chatter.
    # -------------------------------------------------------------------------
    def _send_crm_stage_email(self, template_name, extra_attachment_ids=None):
        """Render a crm.lead mail.template and send it to the customer as a
        plain email (no Odoo "Your Lead <name>" wrapper) while posting the
        same body to the chatter as a comment. Returns True on success.

        Shared by the stage automation (_send_stage_email) and the manual
        "Send Intro Email" button (action_send_intro_email).
        """
        self.ensure_one()
        record = self
        if not record.email_from:
            return False

        # Scope by model so we never pick up a same-named template that
        # belongs to a different model (e.g. a crm.stage / sale.order
        # template that happens to share the display name).
        tmpl = self.env['mail.template'].search([
            ('name', '=', template_name),
            ('model', '=', 'crm.lead'),
        ], limit=1)
        if not tmpl:
            _logger.warning("Stage email template '%s' not found.", template_name)
            return False

        extra_attachment_ids = extra_attachment_ids or []

        # Two-step send so the customer gets a plain email AND the chatter
        # shows the full body:
        #   1. Render the template (subject, body, recipients).
        #   2. Post the same body to the lead chatter as a comment.
        #   3. Create a raw mail.mail linked to that chatter message; the
        #      "Mail: Email Queue Manager" cron flushes it asynchronously
        #      (no inline SMTP blocking the web request).
        try:
            all_attachment_ids = list(tmpl.attachment_ids.ids) + extra_attachment_ids

            rendered = tmpl._generate_template(
                record.ids,
                ('subject', 'body_html', 'email_to', 'email_from',
                 'reply_to'),
            )[record.id]

            subject_v   = rendered.get('subject') or tmpl.subject or ''
            body_v      = rendered.get('body_html') or ''
            email_from_v = (rendered.get('email_from') or
                            tmpl.email_from or self.env.company.email)
            email_to_v  = (rendered.get('email_to') or
                           record.email_from)
            reply_to_v  = rendered.get('reply_to') or tmpl.reply_to

            # CC the customer's other contacts: the commercial (company)
            # partner and its child contacts that have an email, excluding
            # the primary recipient already in email_to. So a company with
            # several people gets the mail to one + CC to the rest.
            cc_emails = []
            if record.partner_id:
                company = record.partner_id.commercial_partner_id or record.partner_id
                related = company | company.child_ids
                primary = (email_to_v or '').strip().lower()
                seen = set()
                for contact in related:
                    addr = (contact.email or '').strip()
                    key = addr.lower()
                    if addr and key != primary and key not in seen:
                        seen.add(key)
                        cc_emails.append(addr)
            email_cc_v = ', '.join(cc_emails)

            mail_vals = {
                'subject':    subject_v,
                'body_html':  body_v,
                'email_from': email_from_v,
                'email_to':   email_to_v,
                'email_cc':   email_cc_v,
                'reply_to':   reply_to_v,
                'auto_delete': False,
                'model':      'crm.lead',
                'res_id':     record.id,
            }
            # Post to chatter FIRST (mt_comment) so it shows immediately.
            # No partner_ids → message_post does not send a mail of its own.
            chatter_msg = record.message_post(
                subject=subject_v,
                body=body_v,
                subtype_xmlid='mail.mt_comment',
                attachment_ids=all_attachment_ids or None,
                message_type='comment',
            )
            # Link the mail to the same chatter message so mail.send() does
            # not create a duplicate chatter entry — attachments appear once.
            mail_vals['mail_message_id'] = chatter_msg.id
            mail = self.env['mail.mail'].sudo().create(mail_vals)
            if all_attachment_ids:
                mail.write({
                    'attachment_ids':
                        [(4, aid) for aid in all_attachment_ids]
                })
        except Exception as e:
            _logger.warning(
                "Failed to send CRM email '%s' for Lead %d: %s",
                template_name, record.id, e,
            )
            return False

        _logger.info(
            "CRM email '%s' sent for Lead %d (%s).",
            template_name, record.id, record.name,
        )
        return True

    def _send_stage_email(self):
        """Send the appropriate stage-based email template for this lead.
        Called from the automated action on create/write of stage_id.
        Project creation is manual — triggered by the "Create Order Booking
        Form" button on the lead form, not by stage changes.
        """
        for record in self:
            stage = record.stage_id
            if not stage or not record.email_from:
                continue

            stage_name = stage.name.strip().lower()
            template_name = False
            flag_field = False

            if stage_name == 'new' and not record.acknowledgment_sent:
                template_name = 'New stage mail'
                flag_field = 'acknowledgment_sent'
            elif stage_name in ('qualify', 'qualified') and not record.qualify_email_sent:
                template_name = 'Qualify stage'
                flag_field = 'qualify_email_sent'
            elif stage_name == 'proposition' and not record.proposition_email_sent:
                if 'order_ids' in record._fields and record.order_ids:
                    template_name = 'Proposition stage'
                    flag_field = 'proposition_email_sent'
            elif stage.is_won and not record.won_email_sent:
                template_name = 'won stage'
                flag_field = 'won_email_sent'

            if not template_name or not flag_field:
                continue

            # Build extra attachments for proposition/won (SO PDF)
            extra_attachment_ids = []
            if flag_field in ('proposition_email_sent', 'won_email_sent') and 'order_ids' in record._fields:
                for so in record.order_ids:
                    try:
                        pdf_content, _ = self.env['ir.actions.report']._render(
                            'sale.report_saleorder', so.ids,
                        )
                        att = self.env['ir.attachment'].create({
                            'name': '%s.pdf' % so.name,
                            'type': 'binary',
                            'datas': base64.b64encode(pdf_content),
                            'res_model': 'crm.lead',
                            'res_id': record.id,
                            'mimetype': 'application/pdf',
                        })
                        extra_attachment_ids.append(att.id)
                    except Exception as e:
                        _logger.warning("Failed to generate SO PDF for %s: %s", so.name, e)

            if record._send_crm_stage_email(template_name, extra_attachment_ids):
                record.write({flag_field: True})

    def action_send_intro_email(self):
        """Manual button: send the New-stage intro (acknowledgment) email to
        the customer now, regardless of the lead's current stage. Pressing it
        again re-sends."""
        sent = 0
        for record in self:
            if record._send_crm_stage_email('New stage mail'):
                record.acknowledgment_sent = True
                sent += 1
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Send Intro Email'),
                'message': (
                    _('Intro email queued for %d lead(s). It appears in the '
                      'chatter now and goes out on the next mail cycle.') % sent
                ) if sent else _(
                    'Nothing sent — the lead has no email address, or the '
                    '"New stage mail" template is missing.'
                ),
                'type': 'success' if sent else 'warning',
                'sticky': False,
            },
        }

    # -------------------------------------------------------------------------
    # DEBUG / UI ACTION METHODS
    # -------------------------------------------------------------------------
    def action_debug_reset_flags(self):
        """ Reset automation flags for testing. """
        self.write({
            'acknowledgment_sent': False,
            'proposition_email_sent': False,
            'won_email_sent': False,
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
        action = self.env['ir.actions.act_window']._for_xml_id('crm.crm_lead_all_leads')
        if not self.env.is_admin():
            return action
        pending_domain = [
            ('stage_id.name', '=ilike', 'new'),
            '|',
            ('is_indiamart', '=', True),
            ('is_aajjo', '=', True),
            ('whatsapp_ack_sent', '=', False)
        ]
        pending_leads = self.search(pending_domain)
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
