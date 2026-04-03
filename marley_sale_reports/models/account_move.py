import base64
import logging

from odoo import models, fields, api, _

_logger = logging.getLogger(__name__)

# Default bank details for Marley Fans
_BANK_DEFAULTS = {
    'proforma_bank_name': 'HDFC Bank',
    'proforma_bank_account_number': '50200092737354',
    'proforma_bank_account_type': 'Current Account',
    'proforma_bank_ifsc': 'HDFC0000364',
    'proforma_bank_branch': 'Kukatpally, Hyderabad',
}

# Default commercial terms
_TERM_DEFAULTS = {
    'proforma_warranty': '5 Years warranty on Mechanical items & 1 year OEM warranty on Motors & VFD Drive',
    'proforma_gst_note': '18% Extra',
    'proforma_delivery': '1-2 Weeks from the date of receipt of your technically and commercially clear purchase order.',
    'proforma_payment_terms_text': 'Supply: 100% Advance with Purchase Order\nInstallation: 100% immediately after Installation',
    'proforma_offer_validity': '30 days',
}


class AccountMove(models.Model):
    _inherit = 'account.move'

    # ------------------------------------------------------------------
    # Bank details (shown on Proforma Invoice PDF)
    # ------------------------------------------------------------------
    proforma_bank_name = fields.Char(
        string='Bank Name',
        default=_BANK_DEFAULTS['proforma_bank_name'],
    )
    proforma_bank_account_number = fields.Char(
        string='Bank Account Number',
        default=_BANK_DEFAULTS['proforma_bank_account_number'],
    )
    proforma_bank_account_type = fields.Char(
        string='Account Type',
        default=_BANK_DEFAULTS['proforma_bank_account_type'],
    )
    proforma_bank_ifsc = fields.Char(
        string='IFSC Code',
        default=_BANK_DEFAULTS['proforma_bank_ifsc'],
    )
    proforma_bank_branch = fields.Char(
        string='Bank Branch',
        default=_BANK_DEFAULTS['proforma_bank_branch'],
    )

    # ------------------------------------------------------------------
    # Proforma print options
    # ------------------------------------------------------------------
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
    advance_amount_due = fields.Monetary(
        string='Advance To Be Paid',
        compute='_compute_advance_amount_due',
        store=True,
        currency_field='currency_id',
    )

    @api.depends('advance_payment_percentage', 'amount_total', 'amount_untaxed', 'proforma_with_taxes')
    def _compute_advance_amount_due(self):
        for move in self:
            pct = move.advance_payment_percentage or 0.0
            base = move.amount_total if move.proforma_with_taxes else move.amount_untaxed
            move.advance_amount_due = round(base * pct / 100.0, 2)

    # ------------------------------------------------------------------
    # Commercial terms (shown on Proforma Invoice PDF)
    # ------------------------------------------------------------------
    proforma_warranty = fields.Text(
        string='Warranty',
        default=_TERM_DEFAULTS['proforma_warranty'],
    )
    proforma_gst_note = fields.Char(
        string='GST Note',
        default=_TERM_DEFAULTS['proforma_gst_note'],
    )
    proforma_delivery = fields.Text(
        string='Delivery Terms',
        default=_TERM_DEFAULTS['proforma_delivery'],
    )
    proforma_payment_terms_text = fields.Text(
        string='Payment Terms (Text)',
        default=_TERM_DEFAULTS['proforma_payment_terms_text'],
    )
    proforma_offer_validity = fields.Char(
        string='Offer Validity',
        default=_TERM_DEFAULTS['proforma_offer_validity'],
    )

    # ------------------------------------------------------------------
    # Use Marley invoice template instead of default Odoo
    # ------------------------------------------------------------------
    def _get_name_invoice_report(self):
        return 'marley_sale_reports.report_marley_invoice_document'

    # ------------------------------------------------------------------
    # WhatsApp: Share invoice with client
    # ------------------------------------------------------------------
    def action_open_whatsapp_send_wizard(self):
        """Open the WhatsApp Send Wizard with the proforma invoice PDF pre-attached."""
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

        # ── Generate proforma invoice PDF ──────────────────────────────
        pdf_filename = 'Proforma Invoice - %s.pdf' % self.name

        report = self.env.ref(
            'marley_sale_reports.action_report_marley_proforma',
            raise_if_not_found=False,
        )
        if not report:
            report = self.env.ref('account.account_invoices')

        pdf_content, _content_type = report.sudo()._render_qweb_pdf(
            report.report_name, self.ids,
        )
        pdf_base64 = base64.b64encode(pdf_content).decode('ascii')

        # ── Create wizard record with PDF already attached ───────────
        wizard = self.env['whatsapp.send.wizard'].create({
            'mobile_number': mobile_number,
            'partner_id': partner.id,
            'message_type': 'media',
            'media_file': pdf_base64,
            'media_filename': pdf_filename,
        })

        return {
            'type': 'ir.actions.act_window',
            'name': _('Send Invoice via WhatsApp'),
            'res_model': 'whatsapp.send.wizard',
            'res_id': wizard.id,
            'view_mode': 'form',
            'target': 'new',
        }

    def init(self):
        """Backfill bank and commercial term defaults on existing invoices."""
        all_defaults = {**_BANK_DEFAULTS, **_TERM_DEFAULTS}
        for col, default_val in all_defaults.items():
            self.env.cr.execute(f"""
                UPDATE account_move
                SET {col} = %s
                WHERE {col} IS NULL
            """, (default_val,))
        _logger.info("Backfilled proforma defaults on existing invoices.")
