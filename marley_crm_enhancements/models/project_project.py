import base64
import logging

from odoo import models, fields, api, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class ProjectProject(models.Model):
    _inherit = 'project.project'

    def init(self):
        """Drop old invoice_number varchar column so Odoo can recreate it as Many2one integer."""
        self.env.cr.execute("""
            SELECT data_type FROM information_schema.columns
            WHERE table_name = 'project_project' AND column_name = 'invoice_number'
        """)
        row = self.env.cr.fetchone()
        if row and row[0] in ('character varying', 'text'):
            _logger.info("[PROJECT] Dropping old invoice_number varchar column for Many2one migration.")
            self.env.cr.execute("ALTER TABLE project_project DROP COLUMN invoice_number")

    @api.model_create_multi
    def create(self, vals_list):
        """Auto-assign Installation stages to newly created projects."""
        projects = super().create(vals_list)
        stage_ids = [
            self.env.ref('marley_crm_enhancements.project_stage_installation', raise_if_not_found=False),
            self.env.ref('marley_crm_enhancements.project_stage_in_progress', raise_if_not_found=False),
            self.env.ref('marley_crm_enhancements.project_stage_done', raise_if_not_found=False),
            self.env.ref('marley_crm_enhancements.project_stage_cancelled', raise_if_not_found=False),
        ]
        valid_stages = [s for s in stage_ids if s]
        if valid_stages:
            for project in projects:
                # Add stages to the project if they aren't already there
                existing = project.type_ids.ids
                to_add = [s.id for s in valid_stages if s.id not in existing]
                if to_add:
                    project.write({'type_ids': [(4, sid) for sid in to_add]})
        return projects

    # ------------------------------------------------------------------
    # Installation Details
    # ------------------------------------------------------------------
    installation_date = fields.Date(string='Scheduled Installation Date')
    site_contact_person = fields.Char(string='Site Contact Person')
    site_contact_number = fields.Char(string='Contact Number')

    # Transport / Invoice
    models_to_transport = fields.Char(string='Models to Transport', compute='_compute_models_to_transport', store=True, readonly=False)
    transportation_terms = fields.Selection([
        ('paid', 'Paid'),
        ('to_pay', 'To Pay'),
        ('to_be_billed', 'To be Billed'),
    ], string='Transportation Terms', default='paid')
    invoice_id = fields.Many2one('account.move', string='Invoice Number',
                                 domain="[('move_type', '=', 'out_invoice'), ('state', '=', 'posted')]",
                                 copy=False)
    invoice_value = fields.Float(string='Invoice Value', compute='_compute_invoice_value', store=True, readonly=False)
    amount_in_words = fields.Char(string='Amount In Words', compute='_compute_amount_in_words', store=True)

    # Installation Site Address (may differ from company address)
    site_address_street = fields.Char(string='Site Address Line 1')
    site_address_street2 = fields.Char(string='Site Address Line 2')
    site_address_city = fields.Char(string='Site City')
    site_address_state_id = fields.Many2one('res.country.state', string='Site State', domain="[('country_id.code', '=', 'IN')]")
    site_address_zip = fields.Char(string='Site Pincode')

    # Advance Received (auto-fetched from payments against invoices)
    advance_received = fields.Float(string='Advance Received', compute='_compute_advance_received', store=True, readonly=False)
    balance_amount = fields.Float(string='Balance Amount', compute='_compute_balance_amount', store=True)

    # Site Specification
    ext_rod_length = fields.Char(string='Ext Rod Length')
    field_height = fields.Char(string='Field Height')
    required_electrical_wire = fields.Char(string='Required Electrical Wire')
    mounting_structure = fields.Char(string='Mounting Structure')
    crane_rafter_distance = fields.Char(string='Distance Between Crane Top and Rafter Bottom')

    # Other
    other_important_info = fields.Text(string='Other Important Information')

    # Link to CRM lead (reverse of crm_lead.project_id)
    lead_id = fields.Many2one('crm.lead', string='Source Lead', readonly=True, copy=False)

    # Linked Sale Orders for product lines
    sale_order_ids = fields.Many2many(
        'sale.order',
        string='Sale Orders',
        compute='_compute_sale_order_ids',
        store=False,
    )

    @api.depends('lead_id')
    def _compute_sale_order_ids(self):
        for project in self:
            if project.lead_id:
                project.sale_order_ids = self.env['sale.order'].search([
                    ('opportunity_id', '=', project.lead_id.id)
                ])
            else:
                project.sale_order_ids = False

    # ------------------------------------------------------------------
    # Auto-fetch: Models to transport from Sale Order lines
    # ------------------------------------------------------------------
    @api.depends('lead_id')
    def _compute_models_to_transport(self):
        for rec in self:
            if not rec.models_to_transport and rec.lead_id:
                orders = self.env['sale.order'].search([
                    ('opportunity_id', '=', rec.lead_id.id)
                ])
                if orders:
                    lines = orders.mapped('order_line').filtered(
                        lambda l: not l.display_type and l.product_id
                    )
                    product_names = lines.mapped('product_id.name')
                    rec.models_to_transport = ' | '.join(set(product_names)) if product_names else ''
                else:
                    rec.models_to_transport = ''
            elif not rec.models_to_transport:
                rec.models_to_transport = ''

    # ------------------------------------------------------------------
    # Auto-fetch details when invoice is selected
    # ------------------------------------------------------------------
    @api.onchange('invoice_id')
    def _onchange_invoice_id(self):
        """When an invoice is selected, auto-fill contact person, contact number, and invoice value."""
        if self.invoice_id:
            inv = self.invoice_id
            # Auto-fetch invoice value
            self.invoice_value = inv.amount_total
            # Auto-fetch site contact person from invoice partner
            partner = inv.partner_shipping_id or inv.partner_id
            if partner:
                self.site_contact_person = partner.name or ''
                self.site_contact_number = partner.phone or partner.mobile or ''

    # ------------------------------------------------------------------
    # Auto-compute: Invoice value from selected invoice
    # ------------------------------------------------------------------
    @api.depends('invoice_id')
    def _compute_invoice_value(self):
        for rec in self:
            if rec.invoice_id:
                rec.invoice_value = rec.invoice_id.amount_total
            elif not rec.invoice_value:
                rec.invoice_value = 0.0

    @api.depends('invoice_id', 'lead_id', 'sale_order_ids')
    def _compute_advance_received(self):
        for rec in self:
            # If a specific invoice is selected, use its payment data
            if rec.invoice_id:
                inv = rec.invoice_id
                rec.advance_received = inv.amount_total - inv.amount_residual
            elif rec.lead_id:
                orders = self.env['sale.order'].search([
                    ('opportunity_id', '=', rec.lead_id.id)
                ])
                invoices = orders.mapped('invoice_ids').filtered(
                    lambda i: i.state == 'posted' and i.move_type == 'out_invoice'
                )
                if invoices:
                    rec.advance_received = sum(
                        inv.amount_total - inv.amount_residual for inv in invoices
                    )
                else:
                    rec.advance_received = rec.advance_received or 0.0
            else:
                rec.advance_received = rec.advance_received or 0.0

    @api.depends('invoice_value', 'advance_received')
    def _compute_balance_amount(self):
        for rec in self:
            rec.balance_amount = (rec.invoice_value or 0.0) - (rec.advance_received or 0.0)

    @api.depends('invoice_value')
    def _compute_amount_in_words(self):
        for rec in self:
            if rec.invoice_value:
                try:
                    rec.amount_in_words = rec.currency_id.amount_to_text(rec.invoice_value) if hasattr(rec, 'currency_id') and rec.currency_id else self._num_to_words_indian(rec.invoice_value)
                except Exception:
                    rec.amount_in_words = self._num_to_words_indian(rec.invoice_value)
            else:
                rec.amount_in_words = ''

    @staticmethod
    def _num_to_words_indian(amount):
        """Simple Indian number to words converter."""
        if not amount:
            return ''
        amount = int(amount)
        ones = ['', 'one', 'two', 'three', 'four', 'five', 'six', 'seven',
                'eight', 'nine', 'ten', 'eleven', 'twelve', 'thirteen',
                'fourteen', 'fifteen', 'sixteen', 'seventeen', 'eighteen', 'nineteen']
        tens = ['', '', 'twenty', 'thirty', 'forty', 'fifty',
                'sixty', 'seventy', 'eighty', 'ninety']

        if amount == 0:
            return 'zero'

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
    # Send Installation Report via Email
    # ------------------------------------------------------------------
    def action_send_installation_report_email(self):
        """Open email composer with installation report attached."""
        self.ensure_one()
        template = self.env.ref(
            'marley_crm_enhancements.email_template_installation_report',
            raise_if_not_found=False,
        )
        compose_form = self.env.ref('mail.email_compose_message_wizard_form', raise_if_not_found=False)
        ctx = {
            'default_model': 'project.project',
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
        """Open WhatsApp Send Wizard with installation report PDF pre-attached."""
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
        ) if partner else False

        if not mobile_number:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Number Missing'),
                    'message': _(
                        'Please set a mobile/WhatsApp number for customer "%s" before sending.',
                        partner.name if partner else 'N/A',
                    ),
                    'type': 'warning',
                    'sticky': False,
                },
            }

        # ── Generate Installation Report PDF ─────────────────────────
        pdf_filename = 'Installation - %s.pdf' % (partner.name or self.name)

        report = self.env.ref(
            'marley_crm_enhancements.action_report_installation',
            raise_if_not_found=False,
        )
        if not report:
            raise UserError(_('Installation Report template not found.'))

        pdf_content, _content_type = report.sudo()._render_qweb_pdf(
            report.report_name, self.ids,
        )
        pdf_base64 = base64.b64encode(pdf_content).decode('ascii')

        # ── Create wizard with PDF pre-attached ──────────────────────
        wizard = self.env['whatsapp.send.wizard'].create({
            'mobile_number': mobile_number,
            'partner_id': partner.id,
            'message_type': 'media',
            'media_file': pdf_base64,
            'media_filename': pdf_filename,
            'media_caption': 'Installation Report - %s' % (partner.name or self.name),
        })

        return {
            'type': 'ir.actions.act_window',
            'name': _('Send Installation Report via WhatsApp'),
            'res_model': 'whatsapp.send.wizard',
            'res_id': wizard.id,
            'view_mode': 'form',
            'target': 'new',
        }
