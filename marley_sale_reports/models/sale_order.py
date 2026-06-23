import base64
import logging

from odoo import models, fields, api, _

_logger = logging.getLogger(__name__)


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    # ------------------------------------------------------------------
    # INIT: widen "Personal Orders" + "Personal Order Lines" record rules
    # so a salesperson with "Own Documents Only" access can also see SOs
    # (and their lines) where they are the Second Salesperson.
    # The originals ship with noupdate=1, so we patch them in place here.
    # ------------------------------------------------------------------
    def init(self):
        if 'second_user_id' not in self._fields:
            return
        # 1) sale.order
        try:
            rule = self.env.ref('sale.sale_order_personal_rule', raise_if_not_found=False)
            if rule:
                new_domain = (
                    "['|', '|', ('user_id', '=', user.id), "
                    "('user_id', '=', False), "
                    "('second_user_id', '=', user.id)]"
                )
                if rule.domain_force != new_domain:
                    rule.sudo().write({
                        'domain_force': new_domain,
                        'name': 'Personal Orders (incl. Second Salesperson)',
                    })
                    _logger.info(
                        "[INIT] Patched sale.sale_order_personal_rule to "
                        "include second_user_id."
                    )
        except Exception as e:
            _logger.warning("[INIT] Could not patch Personal Orders rule: %s", e)

        # 2) sale.order.line — line-level visibility must mirror the parent
        # SO rule, otherwise opening the SO triggers an Access Error on the
        # line cache. salesman_id is related to order_id.user_id, so we
        # match on order_id.user_id / order_id.second_user_id directly.
        try:
            line_rule = self.env.ref(
                'sale.sale_order_line_personal_rule', raise_if_not_found=False
            )
            if line_rule:
                new_line_domain = (
                    "['|', '|', ('salesman_id', '=', user.id), "
                    "('salesman_id', '=', False), "
                    "('order_id.second_user_id', '=', user.id)]"
                )
                if line_rule.domain_force != new_line_domain:
                    line_rule.sudo().write({
                        'domain_force': new_line_domain,
                        'name': 'Personal Order Lines (incl. Second Salesperson)',
                    })
                    _logger.info(
                        "[INIT] Patched sale.sale_order_line_personal_rule "
                        "to include second_user_id."
                    )
        except Exception as e:
            _logger.warning(
                "[INIT] Could not patch Personal Order Lines rule: %s", e
            )

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

    # ------------------------------------------------------------------
    # Terms & Conditions — single text block populated from a chosen draft
    # ------------------------------------------------------------------
    # Replaces the previous per-field structure (warranty / delivery /
    # payment / customer-scope / bank). The salesperson picks a draft
    # from `sale.terms.template` and its body is poured into the standard
    # `note` field (Odoo's "Terms and Conditions"). The legacy structured
    # fields above are retained so existing orders and PDF reports keep
    # rendering — they're just no longer surfaced on the form.
    terms_template_id = fields.Many2one(
        comodel_name='sale.terms.template',
        string='Terms Template',
        domain=[('active', '=', True)],
        help='Pick one of the saved draft templates to insert its full '
             'Terms & Conditions text into the Terms tab below. '
             'Manage drafts under Sales → Configuration → Terms Templates.',
    )

    @api.onchange('terms_template_id')
    def _onchange_terms_template_id(self):
        """Pour the chosen draft's body into the standard `note` field."""
        for order in self:
            if order.terms_template_id:
                order.note = order.terms_template_id.body

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

    # ── Revision tracking (manual) ──────────────────────────────
    revision_number = fields.Integer(
        string='Revision',
        default=0,
        copy=False,
        help='Manually set the revision number for this quotation.',
    )
    last_print_date = fields.Datetime(
        string='Last Printed On',
        readonly=True,
        copy=False,
    )

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
    # GST is FIXED at 18% on every proforma — never variable.
    proforma_amount_untaxed = fields.Monetary(
        string='Proforma Untaxed',
        compute='_compute_proforma_totals',
        store=True,
        currency_field='currency_id',
        help='Sum of the line subtotals that are flagged to print on the '
             'proforma (print_on_proforma). Equals the order untaxed amount '
             'when all lines are selected.',
    )
    proforma_tax_amount = fields.Monetary(
        string='GST 18% Amount',
        compute='_compute_proforma_totals',
        store=True,
        currency_field='currency_id',
        help='Proforma Untaxed × 18%. Shown on the Proforma PDF when '
             '"Print With Taxes" is on; zero otherwise.',
    )
    proforma_amount_total = fields.Monetary(
        string='Proforma Total',
        compute='_compute_proforma_totals',
        store=True,
        currency_field='currency_id',
        help='Proforma Untaxed + GST (18%). This is the grand total printed '
             'on the Proforma Invoice PDF.',
    )

    @api.depends('order_line.price_subtotal', 'order_line.print_on_proforma',
                 'order_line.display_type', 'proforma_with_taxes')
    def _compute_proforma_totals(self):
        # Fixed 18% GST — not configurable per order. Totals sum only the
        # lines selected to print on the proforma.
        GST_RATE = 18.0
        for order in self:
            sel = order.order_line.filtered(
                lambda l: not l.display_type and l.print_on_proforma)
            base = sum(sel.mapped('price_subtotal'))
            tax = round(base * GST_RATE / 100.0, 2) if order.proforma_with_taxes else 0.0
            order.proforma_amount_untaxed = base
            order.proforma_tax_amount = tax
            order.proforma_amount_total = base + tax

    def action_select_proforma_lines(self):
        """Open the popup to choose which product lines print on the proforma."""
        self.ensure_one()
        pre = self.order_line.filtered(
            lambda l: not l.display_type and l.print_on_proforma)
        wizard = self.env['proforma.line.select.wizard'].create({
            'order_id': self.id,
            'line_ids': [(6, 0, pre.ids)],
        })
        return {
            'type': 'ir.actions.act_window',
            'name': 'Select Products for Proforma',
            'res_model': 'proforma.line.select.wizard',
            'res_id': wizard.id,
            'view_mode': 'form',
            'target': 'new',
        }
    proforma_print_terms = fields.Boolean(
        string='Print Terms & Conditions',
        default=True,
        help='If checked, terms, payment schedule, bank details and delivery sections will be printed in the Proforma Invoice PDF.',
    )
    advance_payment_percentage = fields.Float(
        string='Advance Payment %',
        default=0.0,
        help='Percentage of the untaxed (pre-tax) goods value to collect '
             'now (e.g. 70 for 70%).',
    )
    advance_tax_percentage = fields.Float(
        string='Tax % in Advance',
        default=100.0,
        help='Percentage of the total GST to collect now along with the '
             'advance (e.g. 50 = collect half the GST now). 100 = collect '
             'the full GST up-front; 0 = collect no GST in the advance.',
    )
    advance_amount_due = fields.Monetary(
        string='Advance To Be Paid Now',
        compute='_compute_advance_amount_due',
        store=True,
        currency_field='currency_id',
        help='Amount the customer pays now = (Advance % × untaxed goods '
             'value) + (Tax % × total GST).',
    )
    advance_received = fields.Monetary(
        string='Advance Received',
        currency_field='currency_id',
        default=0.0,
        help='Advance amount already received from the client. Deducted from the total on the proforma invoice.',
    )
    balance_due = fields.Monetary(
        string='Balance Due',
        compute='_compute_balance_due',
        store=True,
        currency_field='currency_id',
        help='Total amount minus advance received.',
    )

    @api.depends('advance_payment_percentage', 'proforma_amount_untaxed',
                 'advance_tax_percentage', 'proforma_tax_amount')
    def _compute_advance_amount_due(self):
        for order in self:
            pct = order.advance_payment_percentage or 0.0
            tax_pct = order.advance_tax_percentage or 0.0
            # Advance % applies to the pre-tax (untaxed) goods value of the
            # lines printed on the proforma; Tax % applies to the proforma
            # GST. Only that share is collected now. The two add up to the
            # amount payable now.
            advance_on_goods = round((order.proforma_amount_untaxed or 0.0) * pct / 100.0, 2)
            tax_now = round((order.proforma_tax_amount or 0.0) * tax_pct / 100.0, 2)
            order.advance_amount_due = advance_on_goods + tax_now

    @api.depends('proforma_amount_total', 'advance_received')
    def _compute_balance_due(self):
        for order in self:
            order.balance_due = (order.proforma_amount_total or 0.0) - (order.advance_received or 0.0)

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
