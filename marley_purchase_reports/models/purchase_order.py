from odoo import api, fields, models


# Default text shown in the PDF when the buyer hasn't customised the section.
_DEFAULT_TAXES_TEXT = (
    "GST shall be applicable on above quoted price. Any change in tax "
    "structure or any statutory levies introduced by the appropriate "
    "Government at the time of shipment will be borne as per actual."
)
_DEFAULT_PAYMENT_TEXT = "As per agreed terms."
_DEFAULT_DELIVERY_TEXT = ""


class PurchaseOrder(models.Model):
    _inherit = 'purchase.order'

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

    # ── Editable PDF sections (override the boilerplate per-PO) ─────────
    # All three are Html so users can paste rich-text. Fall back to defaults
    # when empty.
    marley_taxes_text = fields.Html(
        string='Taxes & Duties (PDF)',
        default=lambda self: _DEFAULT_TAXES_TEXT,
        help="Text shown under TAXES & DUTIES on the printed Purchase Order. "
             "Edit per PO if the standard boilerplate doesn't apply.",
    )
    marley_payment_text = fields.Html(
        string='Payment Terms (PDF)',
        default=lambda self: _DEFAULT_PAYMENT_TEXT,
        help="Text shown under PAYMENT TERMS on the printed Purchase Order. "
             "Overrides the standard Payment Term name when set.",
    )
    marley_delivery_text = fields.Html(
        string='Delivery Terms (PDF)',
        default=lambda self: _DEFAULT_DELIVERY_TEXT,
        help="Free-text Delivery Terms shown on the printed Purchase Order. "
             "When blank the PDF falls back to Incoterm + Expected Arrival.",
    )

    # ── Purchase Representative (shown on the printed PO) ───────────────
    # Defaults to the standard Buyer (`user_id`) so the field is always
    # populated; override per-PO when the contact-facing rep differs from
    # the system buyer.
    purchase_representative_id = fields.Many2one(
        'res.users',
        string='Purchase Representative',
        domain="[('share', '=', False)]",
        compute='_compute_purchase_representative_id',
        store=True,
        readonly=False,
        tracking=True,
        help="Person printed under 'Purchase Representative' on the PDF. "
             "Defaults to the Buyer; change when a different colleague is "
             "the vendor's day-to-day contact.",
    )

    @api.depends('user_id')
    def _compute_purchase_representative_id(self):
        for order in self:
            if not order.purchase_representative_id and order.user_id:
                order.purchase_representative_id = order.user_id
