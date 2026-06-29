import base64
import logging

from odoo import models, fields, api, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class ProjectTask(models.Model):
    _inherit = 'project.task'

    # ------------------------------------------------------------------
    # Default stage: "Installation"
    # ------------------------------------------------------------------
    @api.model
    def _get_default_stage_id(self):
        """Return the 'Installation' stage as default."""
        stage = self.env.ref(
            'marley_crm_enhancements.project_stage_installation',
            raise_if_not_found=False,
        )
        if stage:
            return stage.id
        return super()._get_default_stage_id() if hasattr(super(), '_get_default_stage_id') else False

    stage_id = fields.Many2one(default=_get_default_stage_id)

    # ------------------------------------------------------------------
    # Default project: the singleton "Installation" project
    # ------------------------------------------------------------------
    @api.model
    def _get_default_installation_project(self):
        Project = self.env['project.project'].sudo()
        project = Project.search([('name', '=', 'Installation')], limit=1)
        if project:
            return project.id
        stage_xmlids = [
            'marley_crm_enhancements.project_stage_installation',
            'marley_crm_enhancements.project_stage_in_progress',
            'marley_crm_enhancements.project_stage_done',
            'marley_crm_enhancements.project_stage_cancelled',
        ]
        stages = []
        for xmlid in stage_xmlids:
            s = self.env.ref(xmlid, raise_if_not_found=False)
            if s:
                stages.append(s.id)
        return Project.create({
            'name': 'Installation',
            'type_ids': [(6, 0, stages)] if stages else False,
        }).id

    project_id = fields.Many2one(default=_get_default_installation_project)

    # Link task directly to the CRM opportunity / lead
    lead_id = fields.Many2one(
        'crm.lead',
        string='Opportunity',
        index=True,
        copy=False,
        help='CRM opportunity this installation task was created for.',
    )

    # ------------------------------------------------------------------
    # Installation Fields
    # ------------------------------------------------------------------
    is_installation = fields.Boolean(string='Installation Task', default=True)

    # Auto-fetched from Sale Order / Invoice / Partner
    inst_sales_rep = fields.Char(string='Sales Representative', compute='_compute_installation_details', store=True, readonly=True)
    inst_installation_date = fields.Date(string='Scheduled Installation Date')
    inst_company_name = fields.Char(string='Company Name', compute='_compute_installation_details', store=True, readonly=False)
    inst_company_address = fields.Text(string='Company Address', compute='_compute_installation_details', store=True, readonly=False)
    inst_gstin = fields.Char(string='GSTIN', compute='_compute_installation_details', store=True, readonly=False)
    inst_site_contact = fields.Char(string='Site Contact Person', compute='_compute_installation_details', store=True, readonly=False)
    inst_site_phone = fields.Char(string='Contact Number', compute='_compute_installation_details', store=True, readonly=False)

    # Transport & Invoice
    inst_models_to_transport = fields.Char(string='Models to Transport', compute='_compute_product_details', store=True, readonly=False)
    inst_transportation_terms = fields.Selection([
        ('paid', 'Paid'),
        ('to_pay', 'To Pay'),
        ('to_be_billed', 'To be Billed'),
    ], string='Transportation Terms', default='paid')
    inst_invoice_value = fields.Float(string='Invoice Value', compute='_compute_derived_amounts', store=True, readonly=True)
    inst_amount_in_words = fields.Char(string='Amount In Words', compute='_compute_amount_words')

    # Installation Site Address (may differ from company address)
    inst_site_address_street = fields.Char(string='Site Address Line 1')
    inst_site_address_street2 = fields.Char(string='Site Address Line 2')
    inst_site_address_city = fields.Char(string='Site City')
    inst_site_address_state_id = fields.Many2one('res.country.state', string='Site State', domain="[('country_id.code', '=', 'IN')]")
    inst_site_address_zip = fields.Char(string='Site Pincode')
    inst_site_gstin = fields.Char(string='Site GSTIN')

    # Advance Received (auto-fetched from payments against invoices)
    inst_advance_received = fields.Float(string='Advance Received', compute='_compute_advance_received', readonly=True)
    inst_balance_amount = fields.Float(string='Balance Amount', compute='_compute_balance_amount', readonly=True)
    # Basic (untaxed) + 18% GST split of the GST-inclusive invoice value (report use)
    inst_basic_value = fields.Float(string='Basic Value', compute='_compute_basic_value', store=True, readonly=False)
    inst_gst_value = fields.Float(string='GST Value', compute='_compute_derived_amounts', store=True, readonly=True)
    inst_payment_terms_text = fields.Text(string='Payment Terms', compute='_compute_payment_terms_text', store=True, readonly=False)

    # Site Specification
    inst_ext_rod_length = fields.Char(string='Ext Rod Length', help='e.g. 500 mm')
    inst_field_height = fields.Char(string='Field Height', help='e.g. 6 MTR')
    inst_electrical_wire = fields.Char(string='Required Electrical Wire', help='e.g. 150 Meter')
    inst_mounting_structure = fields.Selection(
        selection=[
            ('rcc_concrete', 'RCC CONCRETE'),
            ('i_beam', 'I BEAM MOUNTING'),
            ('sandwich', 'SANDWICH MOUNTING'),
            ('other', 'OTHER'),
        ],
        string='Mounting Structure',
    )
    inst_crane_rafter_distance = fields.Char(string='Distance Between Crane Top and Rafter Bottom', help='in mm')
    inst_height_arrangement_scope = fields.Selection(
        selection=[
            ('our_scope', 'Our Scope'),
            ('client_scope', 'Client Scope'),
        ],
        string='Height Arrangement Scope',
        help='Who arranges the height access (scaffolding/lift/JCB).',
    )
    inst_stay_arrangement_scope = fields.Selection(
        selection=[
            ('our_scope', 'Our Scope'),
            ('client_scope', 'Client Scope'),
        ],
        string='Stay Arrangement Scope',
        help='Who arranges stay / accommodation for the installation crew.',
    )

    # Other
    inst_other_info = fields.Text(string='Other Important Information')

    # ── Editable installation product lines (override sale order lines) ──
    installation_line_ids = fields.One2many(
        'project.task.installation.line',
        'task_id',
        string='Installation Lines',
        copy=True,
    )
    inst_total_quantity = fields.Float(
        string='Total Quantity',
        compute='_compute_installation_totals',
        store=False,
    )
    inst_total_weight = fields.Float(
        string='Total Weight',
        compute='_compute_installation_totals',
        store=False,
        digits=(12, 3),
    )
    inst_grand_total = fields.Float(
        string='Grand Total',
        compute='_compute_installation_totals',
        store=False,
        digits='Product Price',
    )

    @api.depends('installation_line_ids.quantity',
                 'installation_line_ids.weight',
                 'installation_line_ids.price_subtotal')
    def _compute_installation_totals(self):
        for task in self:
            task.inst_total_quantity = sum(task.installation_line_ids.mapped('quantity'))
            task.inst_total_weight = sum(task.installation_line_ids.mapped('weight'))
            task.inst_grand_total = sum(task.installation_line_ids.mapped('price_subtotal'))

    def action_fill_installation_lines_from_so(self):
        """Populate installation_line_ids from the related sale order's product lines."""
        for task in self:
            so = task._get_related_sale_order()
            if not so:
                continue
            # Clear existing lines and repopulate
            task.installation_line_ids = [(5, 0, 0)]
            new_lines = []
            for seq, line in enumerate(so.order_line.filtered(
                lambda l: not l.display_type and l.product_id
            ), start=10):
                per_unit_weight = (
                    (getattr(line.product_id, 'marley_weight', 0.0) or 0.0)
                    or (line.product_id.weight or 0.0)
                )
                new_lines.append((0, 0, {
                    'sequence': seq,
                    'product_id': line.product_id.id,
                    'name': line.product_id.name or line.name,
                    'quantity': line.product_uom_qty,
                    'uom_id': line.product_uom_id.id if line.product_uom_id else False,
                    'weight': per_unit_weight * (line.product_uom_qty or 0.0),
                    'unit_price': line.price_unit,
                }))
            if new_lines:
                task.installation_line_ids = new_lines
        return True

    # ------------------------------------------------------------------
    # Auto-fetch: Company Details from Sale Order → Partner / Lead
    # ------------------------------------------------------------------
    @api.depends('is_installation',
                 'sale_order_id', 'sale_order_id.user_id',
                 'sale_order_id.partner_id',
                 'partner_id', 'project_id', 'project_id.partner_id',
                 'project_id.lead_id', 'lead_id',
                 'lead_id.partner_id', 'project_id.lead_id.partner_id',
                 'partner_id.name', 'partner_id.street', 'partner_id.street2',
                 'partner_id.city', 'partner_id.state_id', 'partner_id.zip',
                 'partner_id.vat',
                 'lead_id.partner_name', 'lead_id.contact_name',
                 'lead_id.street', 'lead_id.street2', 'lead_id.city',
                 'lead_id.state_id', 'lead_id.country_id', 'lead_id.zip')
    def _compute_installation_details(self):
        for task in self:
            # Sales Representative — SO salesperson first, then lead's salesperson
            so = task._get_related_sale_order()
            if so and so.user_id:
                task.inst_sales_rep = so.user_id.name
            elif 'lead_id' in task._fields and task.lead_id and task.lead_id.user_id:
                task.inst_sales_rep = task.lead_id.user_id.name
            elif task.project_id and 'lead_id' in task.project_id._fields and task.project_id.lead_id and task.project_id.lead_id.user_id:
                task.inst_sales_rep = task.project_id.lead_id.user_id.name
            else:
                task.inst_sales_rep = ''

            # Company Details — resolved from task.partner_id, the related
            # sale order's partner, the opportunity's partner, or the
            # project's customer.
            lead = False
            if 'lead_id' in task._fields and task.lead_id:
                lead = task.lead_id
            elif task.project_id and 'lead_id' in task.project_id._fields and task.project_id.lead_id:
                lead = task.project_id.lead_id
            partner = (
                task.partner_id
                or (so.partner_id if so else False)
                or (lead.partner_id if lead else False)
                or (task.project_id.partner_id if task.project_id else False)
            )
            # Helper: build a multi-line address from a partner or a lead
            def _build_address(rec):
                if not rec:
                    return ''
                parts = []
                if getattr(rec, 'street', False):
                    parts.append(rec.street)
                if getattr(rec, 'street2', False):
                    parts.append(rec.street2)
                city_line = ''
                if getattr(rec, 'city', False):
                    city_line += rec.city
                state = getattr(rec, 'state_id', False)
                if state:
                    city_line += ' ' + state.name if city_line else state.name
                country = getattr(rec, 'country_id', False)
                if country:
                    city_line += ' (%s)' % country.code if city_line else country.code
                if getattr(rec, 'zip', False):
                    city_line += ' ' + rec.zip if city_line else rec.zip
                if city_line:
                    parts.append(city_line)
                return '\n'.join(parts)

            # These three fields are auto-fetched but user-editable: only fill
            # them when empty so a manual override is never overwritten by a
            # later recompute (same pattern as Site Contact below).
            if partner:
                # Use the COMMERCIAL entity (parent company) for the company
                # name, not the contact person. If `partner` is a contact like
                # "Nithin" under "Anurag Engineering College",
                # commercial_partner_id resolves to the company.
                company = partner.commercial_partner_id or partner
                if not task.inst_company_name:
                    task.inst_company_name = company.name or ''
                if not task.inst_company_address:
                    task.inst_company_address = _build_address(company)
                if not task.inst_gstin:
                    task.inst_gstin = company.vat or partner.vat or ''
            elif lead:
                # Lead is at New / Qualify stage with no partner yet — fetch
                # the address details directly from the lead fields.
                if not task.inst_company_name:
                    task.inst_company_name = (
                        lead.partner_name or lead.contact_name or lead.name or ''
                    )
                if not task.inst_company_address:
                    task.inst_company_address = _build_address(lead)
                if not task.inst_gstin:
                    task.inst_gstin = (
                        getattr(lead, 'x_gstin', False)
                        or getattr(lead, 'vat', False)
                        or ''
                    )
            else:
                task.inst_company_name = task.inst_company_name or ''
                task.inst_company_address = task.inst_company_address or ''
                task.inst_gstin = task.inst_gstin or ''

            # Site Contact — from lead contact or partner. Reuses the `lead`
            # already resolved above (task.lead_id, then project.lead_id).
            if not task.inst_site_contact:
                if lead:
                    task.inst_site_contact = lead.contact_name or (partner.name if partner else '')
                    task.inst_site_phone = lead.phone or (partner.phone if partner else '')
                elif partner:
                    task.inst_site_contact = partner.name or ''
                    task.inst_site_phone = partner.phone or ''
                else:
                    task.inst_site_contact = ''
                    task.inst_site_phone = ''

    def _get_related_sale_order(self):
        """Return the best sale.order for this task: direct link, else via lead."""
        self.ensure_one()
        if self.sale_order_id:
            return self.sale_order_id
        lead = False
        if 'lead_id' in self._fields and self.lead_id:
            lead = self.lead_id
        elif self.project_id and 'lead_id' in self.project_id._fields and self.project_id.lead_id:
            lead = self.project_id.lead_id
        if lead:
            return self.env['sale.order'].sudo().search(
                [('opportunity_id', '=', lead.id)], limit=1,
            )
        return self.env['sale.order']

    # ------------------------------------------------------------------
    # Auto-fetch: Advance received — user-entered on SO, or payments on invoices
    # ------------------------------------------------------------------
    @api.depends('sale_order_id',
                 'sale_order_id.advance_received',
                 'sale_order_id.invoice_ids.amount_residual',
                 'sale_order_id.invoice_ids.payment_state',
                 'project_id.lead_id',
                 'lead_id')
    def _compute_advance_received(self):
        for task in self:
            task.inst_advance_received = 0.0
            if not task.is_installation:
                continue
            so = task._get_related_sale_order()
            if not so:
                continue
            # 1) user-entered advance on the sale order wins
            so_advance = getattr(so, 'advance_received', 0.0) or 0.0
            if so_advance:
                task.inst_advance_received = so_advance
                continue
            # 2) otherwise derive from posted invoices payment state
            invoices = so.invoice_ids.filtered(
                lambda i: i.state == 'posted' and i.move_type == 'out_invoice'
            )
            if invoices:
                task.inst_advance_received = sum(
                    inv.amount_total - inv.amount_residual for inv in invoices
                )

    # ------------------------------------------------------------------
    # Balance = Invoice Value - Advance Received
    # ------------------------------------------------------------------
    @api.depends('inst_invoice_value', 'inst_advance_received')
    def _compute_balance_amount(self):
        for task in self:
            task.inst_balance_amount = (task.inst_invoice_value or 0.0) - (task.inst_advance_received or 0.0)

    @api.depends('inst_basic_value')
    def _compute_derived_amounts(self):
        """GST (18%) and the GST-inclusive Total, derived from the (editable)
        basic value: GST = basic x 0.18, Total = basic x 1.18."""
        for task in self:
            base = task.inst_basic_value or 0.0
            task.inst_gst_value = base * 0.18
            task.inst_invoice_value = base * 1.18

    @api.depends('sale_order_id', 'project_id.lead_id', 'lead_id')
    def _compute_payment_terms_text(self):
        """Payment-schedule text from the related sale order. Editable: only
        auto-filled when empty so a manual override is preserved."""
        for task in self:
            if task.inst_payment_terms_text:
                continue
            so = task._get_related_sale_order() if task.is_installation else False
            if so:
                task.inst_payment_terms_text = getattr(so, 'payment_terms_text', '') or ''

    # ------------------------------------------------------------------
    # Auto-fetch: Product models from Sale Order lines
    # ------------------------------------------------------------------
    @api.depends('sale_order_id', 'project_id.lead_id', 'lead_id')
    def _compute_product_details(self):
        for task in self:
            if not task.is_installation:
                task.inst_models_to_transport = task.inst_models_to_transport or ''
                continue
            so = task._get_related_sale_order()
            if not so:
                task.inst_models_to_transport = task.inst_models_to_transport or ''
                continue
            if not task.inst_models_to_transport:
                lines = so.order_line.filtered(lambda l: not l.display_type and l.product_id)
                product_names = lines.mapped('product_id.name')
                task.inst_models_to_transport = ' | '.join(set(product_names)) if product_names else ''

    # ------------------------------------------------------------------
    # Auto-fetch: Invoice value from Sale Order / Invoice
    # ------------------------------------------------------------------
    @api.depends('sale_order_id',
                 'sale_order_id.amount_untaxed',
                 'installation_line_ids.price_subtotal',
                 'project_id.lead_id',
                 'lead_id')
    def _compute_basic_value(self):
        """Basic (untaxed) amount. When the task has its own product lines it
        mirrors their grand total, updating live as soon as a line changes. With
        no lines it's editable: auto-filled when empty from the quotation's
        untaxed total (or posted invoices), then preserved. GST and Total derive
        from this. Use "Refresh Installation Details" to clear + re-fetch."""
        for task in self:
            if not task.is_installation:
                continue
            if task.installation_line_ids:
                # Product lines present — Basic tracks their untaxed grand total.
                task.inst_basic_value = sum(task.installation_line_ids.mapped('price_subtotal'))
                continue
            if task.inst_basic_value:   # no lines, manually set — preserve
                continue
            so = task._get_related_sale_order()
            if not so:
                continue
            # Posted invoices first, otherwise the SO (proforma) untaxed amount.
            invoices = so.invoice_ids.filtered(
                lambda i: i.state == 'posted' and i.move_type == 'out_invoice'
            )
            if invoices:
                task.inst_basic_value = sum(invoices.mapped('amount_untaxed'))
            else:
                task.inst_basic_value = so.amount_untaxed or 0.0

    # ------------------------------------------------------------------
    # Amount in words
    # ------------------------------------------------------------------
    @api.depends('inst_invoice_value')
    def _compute_amount_words(self):
        for task in self:
            if task.inst_invoice_value:
                try:
                    currency = self.env.company.currency_id
                    task.inst_amount_in_words = currency.amount_to_text(task.inst_invoice_value)
                except Exception:
                    task.inst_amount_in_words = self._num_to_words_indian(task.inst_invoice_value)
            else:
                task.inst_amount_in_words = ''

    @staticmethod
    def _num_to_words_indian(amount):
        """Simple Indian number to words."""
        if not amount:
            return ''
        amount = int(amount)
        ones = ['', 'one', 'two', 'three', 'four', 'five', 'six', 'seven',
                'eight', 'nine', 'ten', 'eleven', 'twelve', 'thirteen',
                'fourteen', 'fifteen', 'sixteen', 'seventeen', 'eighteen', 'nineteen']
        tens = ['', '', 'twenty', 'thirty', 'forty', 'fifty',
                'sixty', 'seventy', 'eighty', 'ninety']

        def two_digits(n):
            if n < 20:
                return ones[n]
            return tens[n // 10] + (' ' + ones[n % 10] if n % 10 else '')

        def three_digits(n):
            if n >= 100:
                return ones[n // 100] + ' hundred' + (' and ' + two_digits(n % 100) if n % 100 else '')
            return two_digits(n)

        parts = []
        if amount >= 10000000:
            parts.append(two_digits(amount // 10000000) + ' crore')
            amount %= 10000000
        if amount >= 100000:
            parts.append(two_digits(amount // 100000) + ' lakh')
            amount %= 100000
        if amount >= 1000:
            parts.append(two_digits(amount // 1000) + ' thousand')
            amount %= 1000
        if amount > 0:
            parts.append(three_digits(amount))

        return ' '.join(parts) + ' only'

    # ------------------------------------------------------------------
    # Button: Refresh Installation Details
    # ------------------------------------------------------------------
    def action_refresh_installation(self):
        """Manually re-fetch installation details from SO/Invoice."""
        self.ensure_one()
        # Clear cached values to force recompute
        self.write({
            'inst_sales_rep': False,
            'inst_company_name': False,
            'inst_company_address': False,
            'inst_gstin': False,
            'inst_site_contact': False,
            'inst_site_phone': False,
            'inst_models_to_transport': False,
            'inst_basic_value': 0.0,
            'inst_payment_terms_text': False,
        })
        self._compute_installation_details()
        self._compute_product_details()
        self._compute_basic_value()
        self._compute_derived_amounts()
        self._compute_payment_terms_text()
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Installation Details Refreshed',
                'message': 'All details have been re-fetched from Sale Order and Invoice.',
                'type': 'success',
                'sticky': False,
            }
        }

    # ------------------------------------------------------------------
    # Send Installation Report via Email
    # ------------------------------------------------------------------
    def action_send_installation_report_email(self):
        """Open email composer with task installation report attached."""
        self.ensure_one()
        template = self.env.ref(
            'marley_crm_enhancements.email_template_task_installation_report',
            raise_if_not_found=False,
        )
        compose_form = self.env.ref('mail.email_compose_message_wizard_form', raise_if_not_found=False)
        ctx = {
            'default_model': 'project.task',
            'default_res_ids': self.ids,
            'default_template_id': template.id if template else False,
            'default_composition_mode': 'comment',
            'default_email_layout_xmlid': 'mail.mail_notification_light',
            'force_email': True,
        }
        return {
            'type': 'ir.actions.act_window',
            'name': _('Send Installation Report'),
            'res_model': 'mail.compose.message',
            'view_mode': 'form',
            'views': [(compose_form.id if compose_form else False, 'form')],
            'target': 'new',
            'context': ctx,
        }

    # ------------------------------------------------------------------
    # Send Installation Report via WhatsApp (uses whatsapp_core_community)
    # ------------------------------------------------------------------
    def action_send_installation_report_whatsapp(self):
        """Open WhatsApp Send Wizard with task installation report PDF pre-attached."""
        self.ensure_one()

        # Guard: whatsapp_core_community must be installed
        if 'whatsapp.send.wizard' not in self.env:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('WhatsApp Not Available'),
                    'message': _('Please install the WhatsApp Core Community module first.'),
                    'type': 'warning',
                    'sticky': False,
                },
            }

        partner = self.partner_id
        mobile_number = (
            getattr(partner, 'whatsapp_number', False)
            or getattr(partner, 'mobile', False)
            or partner.phone
            or self.inst_site_phone
        ) if partner else self.inst_site_phone or False

        if not mobile_number:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Number Missing'),
                    'message': _(
                        'Please set a mobile/WhatsApp number for customer "%s" before sending.',
                        partner.name if partner else self.inst_company_name or 'N/A',
                    ),
                    'type': 'warning',
                    'sticky': False,
                },
            }

        # ── Generate Installation Report PDF ─────────────────────────
        company_name = self.inst_company_name or (partner.name if partner else self.name)
        pdf_filename = 'Installation - %s.pdf' % company_name

        report = self.env.ref(
            'marley_crm_enhancements.action_report_task_installation',
            raise_if_not_found=False,
        )
        if not report:
            raise UserError(_('Installation Report template not found.'))

        pdf_content, _content_type = report.sudo()._render_qweb_pdf(
            report.report_name, self.ids,
        )
        pdf_base64 = base64.b64encode(pdf_content).decode('ascii')

        # ── Create wizard with PDF pre-attached ──────────────────────
        wizard_vals = {
            'mobile_number': mobile_number,
            'message_type': 'media',
            'media_file': pdf_base64,
            'media_filename': pdf_filename,
            'media_caption': 'Installation Report - %s' % company_name,
        }
        if partner:
            wizard_vals['partner_id'] = partner.id

        wizard = self.env['whatsapp.send.wizard'].create(wizard_vals)

        return {
            'type': 'ir.actions.act_window',
            'name': _('Send Installation Report via WhatsApp'),
            'res_model': 'whatsapp.send.wizard',
            'res_id': wizard.id,
            'view_mode': 'form',
            'target': 'new',
        }
