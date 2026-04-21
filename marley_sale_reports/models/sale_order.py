import base64
import logging

from odoo import models, fields, api, _

_logger = logging.getLogger(__name__)


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    # ------------------------------------------------------------------
    # WhatsApp: Share quotation with client
    # ------------------------------------------------------------------

    def action_open_whatsapp_send_wizard(self):
        """Open the WhatsApp Send Wizard with the quotation PDF pre-attached."""
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

        # ── Generate quotation PDF ──────────────────────────────────────
        pdf_filename = 'Quotation - %s.pdf' % self.name

        # Try Marley custom report first, then fall back to standard Odoo
        report = self.env.ref(
            'marley_sale_reports.action_report_marley_quotation',
            raise_if_not_found=False,
        )
        if not report:
            report = self.env.ref('sale.action_report_saleorder')

        pdf_content, _content_type = report.sudo()._render_qweb_pdf(
            report.report_name, self.ids,
        )
        pdf_base64 = base64.b64encode(pdf_content).decode('ascii')

        # ── Create wizard record with PDF already written ─────────────
        wizard = self.env['whatsapp.send.wizard'].create({
            'mobile_number': mobile_number,
            'partner_id': partner.id,
            'message_type': 'media',
            'media_file': pdf_base64,
            'media_filename': pdf_filename,
        })

        return {
            'type': 'ir.actions.act_window',
            'name': _('Send Quotation via WhatsApp'),
            'res_model': 'whatsapp.send.wizard',
            'res_id': wizard.id,
            'view_mode': 'form',
            'target': 'new',
        }

    # ------------------------------------------------------------------
    # Quotation Commercial Terms (as per Marley Fans template)
    # ------------------------------------------------------------------
    warranty_terms = fields.Text(
        string='Warranty Terms',
        compute='_compute_warranty_terms',
        store=True,
        readonly=False,
        help='Auto-fetched from the products in this order (deduplicated). '
             'Can be edited manually to override for this quotation.',
    )

    @api.depends('order_line.product_id', 'order_line.product_id.warranty_terms')
    def _compute_warranty_terms(self):
        for order in self:
            terms = []
            seen = set()
            for line in order.order_line:
                product = line.product_id
                text = (product.warranty_terms or '').strip() if product else ''
                if text and text not in seen:
                    seen.add(text)
                    terms.append(text)
            if terms:
                order.warranty_terms = '\n\n'.join(terms)
            elif not order.warranty_terms:
                order.warranty_terms = (
                    '5 Years warranty on Mechanical items & '
                    '1 year OEM warranty on Motors & VFD Drive'
                )
    delivery_terms = fields.Text(
        string='Delivery Terms',
        default='1-2 Weeks from the date of receipt of your technically and commercially clear purchase order.',
    )
    payment_terms_text = fields.Text(
        string='Payment Terms (Text)',
        default='Supply: 100% Advance with Purchase Order\nInstallation: 100% immediately after Installation',
    )
    offer_validity_days = fields.Integer(
        string='Offer Validity (Days)',
        default=30,
    )
    cover_letter = fields.Text(
        string='Cover Letter',
        default='We thank you very much for your valuable enquiry for HVLS Fans and are pleased to enclose herewith our offer.\n\nWe hope that you will find the above offer in line with your requirements.\nPlease feel free to contact us for any further clarification.\n\nLooking forward to receiving your valuable order.\nAssuring you of our best services at all times.',
    )
    customer_scope = fields.Text(
        string='Customer Scope',
        help='Facilities / responsibilities to be provided by the customer',
    )
    subject_line = fields.Char(
        string='Subject',
        help='Subject line for quotation print (e.g. Supply of Pole mounted HVLS Fan)',
    )
    kind_attn = fields.Char(
        string='Kind Attention',
        help='Contact person name for quotation print',
    )
    bank_name = fields.Char(string='Bank Name', default='HDFC Bank')
    bank_account_number = fields.Char(string='Bank Account Number', default='50200092737354')
    bank_account_type = fields.Char(string='Account Type', default='Current Account')
    bank_ifsc = fields.Char(string='IFSC Code', default='HDFC0000364')
    bank_branch = fields.Char(string='Bank Branch', default='Kukatpally, Hyderabad')

    # ── Financial Year label (Indian FY: April 1 → March 31) ────
    financial_year_label = fields.Char(
        string='Financial Year',
        compute='_compute_financial_year_label',
        store=True,
        help='Indian financial year derived from the order date, e.g. 2026-2027.',
    )

    @api.depends('date_order')
    def _compute_financial_year_label(self):
        for order in self:
            d = order.date_order
            if not d:
                order.financial_year_label = ''
                continue
            start = d.year if d.month >= 4 else d.year - 1
            order.financial_year_label = '%d-%d' % (start, start + 1)

    # ── Revision tracking (incremented on edit after print) ─────
    revision_number = fields.Integer(
        string='Revision',
        default=0,
        readonly=True,
        copy=False,
    )
    last_print_date = fields.Datetime(
        string='Last Printed On',
        readonly=True,
        copy=False,
    )

    _REVISION_IGNORED_FIELDS = {
        'revision_number',
        'last_print_date',
        'message_ids',
        'message_follower_ids',
        'message_partner_ids',
        'access_token',
        'access_warning',
        'activity_ids',
    }

    def write(self, vals):
        bump_candidates = [k for k in vals if k not in self._REVISION_IGNORED_FIELDS]
        res = super().write(vals)
        skip = self.env.context.get('skip_revision_bump')
        if bump_candidates and not skip:
            for order in self:
                new_rev = (order.revision_number or 0) + 1
                order.with_context(skip_revision_bump=True).write({
                    'revision_number': new_rev,
                })
        return res

    # ── Proforma-specific Fields ─────────────────────────────────
    second_user_id = fields.Many2one(
        'res.users', string='Additional Salesperson',
        domain=[('share', '=', False)],
    )
    po_reference_date = fields.Date(string='P.O. Reference Date')
    proforma_date = fields.Date(string='Proforma Invoice Date')

    # ── Proforma Print Options ───────────────────────────────────
    proforma_with_taxes = fields.Boolean(
        string='Print With Taxes',
        default=False,
        help='If checked, taxes will be shown in the Proforma Invoice PDF.',
    )
    proforma_print_terms = fields.Boolean(
        string='Print Terms & Conditions',
        default=True,
        help='If checked, terms, payment schedule, bank details and delivery sections will be printed in the Proforma Invoice PDF.',
    )
    advance_payment_percentage = fields.Float(
        string='Advance Payment %',
        default=0.0,
        help='Enter percentage value (e.g. 70 for 70%).',
    )
    advance_include_taxes = fields.Boolean(
        string='Include Taxes in Advance',
        default=False,
        help='If checked, advance amount is calculated on total (with taxes). Otherwise on untaxed amount.',
    )
    advance_amount_due = fields.Monetary(
        string='Advance To Be Paid',
        compute='_compute_advance_amount_due',
        store=True,
        currency_field='currency_id',
    )

    @api.depends('advance_payment_percentage', 'amount_total', 'amount_untaxed', 'advance_include_taxes')
    def _compute_advance_amount_due(self):
        for order in self:
            pct = order.advance_payment_percentage or 0.0
            base = order.amount_total if order.advance_include_taxes else order.amount_untaxed
            order.advance_amount_due = round(base * pct / 100.0, 2)

    # ── Installation Cost Fields ─────────────────────────────────
    x_installation_cost = fields.Float(string='Installation Cost (per unit)')
    x_installation_qty = fields.Integer(string='Installation Qty', default=0)
    x_installation_total = fields.Float(
        string='Installation Total',
        compute='_compute_installation_total',
        store=True,
    )

    @api.depends('x_installation_cost', 'x_installation_qty')
    def _compute_installation_total(self):
        for order in self:
            order.x_installation_total = order.x_installation_cost * order.x_installation_qty


class SaleOrderLine(models.Model):
    _inherit = 'sale.order.line'

    list_price = fields.Float(
        string='List Price',
        help='Original list price before discount',
    )
    special_discount_price = fields.Float(
        string='Special Discount Price',
        help='Discounted unit price offered to customer',
    )

    @api.onchange('product_id')
    def _onchange_product_set_list_price(self):
        """Auto-fill list_price from product's sales price when product is selected."""
        for line in self:
            if line.product_id and line.product_id.list_price:
                line.list_price = line.product_id.list_price
                if not line.special_discount_price:
                    line.special_discount_price = line.product_id.list_price

    @api.onchange('special_discount_price')
    def _onchange_special_discount_price(self):
        """When special discount price is set, update unit price accordingly."""
        for line in self:
            if line.special_discount_price:
                line.price_unit = line.special_discount_price

    @api.onchange('list_price')
    def _onchange_list_price(self):
        """If special discount price is zero, set it equal to list price."""
        for line in self:
            if line.list_price and not line.special_discount_price:
                line.special_discount_price = line.list_price
                line.price_unit = line.list_price
