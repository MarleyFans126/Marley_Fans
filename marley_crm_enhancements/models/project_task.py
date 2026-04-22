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
    inst_sales_rep = fields.Char(string='Sales Representative', compute='_compute_installation_details', readonly=True)
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
    inst_invoice_value = fields.Float(string='Invoice Value', compute='_compute_invoice_details', readonly=True)
    inst_amount_in_words = fields.Char(string='Amount In Words', compute='_compute_amount_words')

    # Installation Site Address (may differ from company address)
    inst_site_address_street = fields.Char(string='Site Address Line 1')
    inst_site_address_street2 = fields.Char(string='Site Address Line 2')
    inst_site_address_city = fields.Char(string='Site City')
    inst_site_address_state_id = fields.Many2one('res.country.state', string='Site State', domain="[('country_id.code', '=', 'IN')]")
    inst_site_address_zip = fields.Char(string='Site Pincode')

    # Advance Received (auto-fetched from payments against invoices)
    inst_advance_received = fields.Float(string='Advance Received', compute='_compute_advance_received', readonly=True)
    inst_balance_amount = fields.Float(string='Balance Amount', compute='_compute_balance_amount', readonly=True)

    # Site Specification
    inst_ext_rod_length = fields.Char(string='Ext Rod Length', help='e.g. 500 mm')
    inst_field_height = fields.Char(string='Field Height', help='e.g. 6 MTR')
    inst_electrical_wire = fields.Char(string='Required Electrical Wire', help='e.g. 150 Meter')
    inst_mounting_structure = fields.Char(string='Mounting Structure', help='e.g. PEB, RCC')
    inst_crane_rafter_distance = fields.Char(string='Distance Between Crane Top and Rafter Bottom', help='in mm')

    # Other
    inst_other_info = fields.Text(string='Other Important Information')

    # ------------------------------------------------------------------
    # Auto-fetch: Company Details from Sale Order → Partner / Lead
    # ------------------------------------------------------------------
    @api.depends('sale_order_id', 'sale_order_id.user_id',
                 'partner_id', 'project_id.lead_id', 'lead_id')
    def _compute_installation_details(self):
        for task in self:
            if not task.is_installation:
                task.inst_sales_rep = task.inst_sales_rep or ''
                task.inst_company_name = task.inst_company_name or ''
                task.inst_company_address = task.inst_company_address or ''
                task.inst_gstin = task.inst_gstin or ''
                task.inst_site_contact = task.inst_site_contact or ''
                task.inst_site_phone = task.inst_site_phone or ''
                continue

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

            # Company Details — from partner (customer)
            partner = task.partner_id or (task.sale_order_id.partner_id if task.sale_order_id else False)
            if partner and not task.inst_company_name:
                task.inst_company_name = partner.name or ''

                # Build address
                addr_parts = []
                if partner.street:
                    addr_parts.append(partner.street)
                if partner.street2:
                    addr_parts.append(partner.street2)
                city_line = ''
                if partner.city:
                    city_line += partner.city
                if partner.state_id:
                    city_line += ' ' + partner.state_id.name if city_line else partner.state_id.name
                if partner.country_id:
                    city_line += ' (%s)' % partner.country_id.code if city_line else partner.country_id.code
                if partner.zip:
                    city_line += ' ' + partner.zip if city_line else partner.zip
                if city_line:
                    addr_parts.append(city_line)
                task.inst_company_address = '\n'.join(addr_parts) if addr_parts else ''

                # GSTIN
                task.inst_gstin = partner.vat or ''
            elif not partner:
                task.inst_company_name = task.inst_company_name or ''
                task.inst_company_address = task.inst_company_address or ''
                task.inst_gstin = task.inst_gstin or ''

            # Site Contact — from lead contact or partner
            if not task.inst_site_contact:
                lead = task.project_id.lead_id if task.project_id and hasattr(task.project_id, 'lead_id') else False
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
                 'sale_order_id.amount_total',
                 'project_id.lead_id',
                 'lead_id')
    def _compute_invoice_details(self):
        for task in self:
            task.inst_invoice_value = 0.0
            if not task.is_installation:
                continue
            so = task._get_related_sale_order()
            if not so:
                continue
            # Posted invoices totals first, otherwise SO total (proforma amount)
            invoices = so.invoice_ids.filtered(
                lambda i: i.state == 'posted' and i.move_type == 'out_invoice'
            )
            if invoices:
                task.inst_invoice_value = sum(invoices.mapped('amount_total'))
            else:
                task.inst_invoice_value = so.amount_total or 0.0

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
            'inst_invoice_value': 0.0,
        })
        self._compute_installation_details()
        self._compute_product_details()
        self._compute_invoice_details()
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
