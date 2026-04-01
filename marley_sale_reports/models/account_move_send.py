from odoo import models, api, Command
import logging

_logger = logging.getLogger(__name__)


class AccountMoveSend(models.AbstractModel):
    _inherit = 'account.move.send'

    def init(self):
        """Ensure the Marley proforma report is flagged as an invoice report
        and wire up GST fiscal position tax mappings."""
        super().init()

        # ── Mark Marley proforma report as invoice report ────────────
        try:
            report = self.env.ref(
                'marley_sale_reports.action_report_marley_proforma',
                raise_if_not_found=False,
            )
            if report and not report.is_invoice_report:
                report.write({'is_invoice_report': True, 'domain': '[]'})
                _logger.info("Marked Marley proforma report as is_invoice_report=True")
        except Exception as e:
            _logger.warning("Could not update Marley proforma report flags: %s", e)

        # ── Set Marley proforma as default on all sales journals ──────
        try:
            if report:
                sales_journals = self.env['account.journal'].search([
                    ('type', '=', 'sale'),
                ])
                for journal in sales_journals:
                    if journal.invoice_template_pdf_report_id != report:
                        journal.write({'invoice_template_pdf_report_id': report.id})
                        _logger.info("Set Marley proforma as default on journal: %s", journal.name)
        except Exception as e:
            _logger.warning("Could not set journal default report: %s", e)

        # ── Wire up GST fiscal position tax mappings ─────────────────
        try:
            self._setup_gst_fiscal_mappings()
        except Exception as e:
            _logger.warning("Could not setup GST fiscal mappings: %s", e)

    def _setup_gst_fiscal_mappings(self):
        """Set original_tax_ids and fiscal_position_ids for GST taxes."""
        ref = self.env.ref

        # Sale taxes
        sgst_sale = ref('marley_sale_reports.sgst_sale_9', raise_if_not_found=False)
        cgst_sale = ref('marley_sale_reports.cgst_sale_9', raise_if_not_found=False)
        igst_sale = ref('marley_sale_reports.igst_sale_18', raise_if_not_found=False)

        # Purchase taxes
        sgst_purchase = ref('marley_sale_reports.sgst_purchase_9', raise_if_not_found=False)
        cgst_purchase = ref('marley_sale_reports.cgst_purchase_9', raise_if_not_found=False)
        igst_purchase = ref('marley_sale_reports.igst_purchase_18', raise_if_not_found=False)

        # Fiscal positions
        fp_intra = ref('marley_sale_reports.fiscal_position_intra_state', raise_if_not_found=False)
        fp_inter = ref('marley_sale_reports.fiscal_position_inter_state', raise_if_not_found=False)

        if not all([sgst_sale, cgst_sale, igst_sale, sgst_purchase, cgst_purchase, igst_purchase, fp_intra, fp_inter]):
            _logger.warning("GST taxes or fiscal positions not found, skipping mapping.")
            return

        # ── Intra-State: SGST + CGST replace IGST ───────────────────
        # SGST Sale 9% replaces IGST Sale 18% (in intra-state context)
        if igst_sale not in sgst_sale.original_tax_ids:
            sgst_sale.write({'original_tax_ids': [Command.link(igst_sale.id)]})
        if igst_sale not in cgst_sale.original_tax_ids:
            cgst_sale.write({'original_tax_ids': [Command.link(igst_sale.id)]})

        # SGST Purchase 9% replaces IGST Purchase 18%
        if igst_purchase not in sgst_purchase.original_tax_ids:
            sgst_purchase.write({'original_tax_ids': [Command.link(igst_purchase.id)]})
        if igst_purchase not in cgst_purchase.original_tax_ids:
            cgst_purchase.write({'original_tax_ids': [Command.link(igst_purchase.id)]})

        # Add SGST+CGST to Intra-State fiscal position
        intra_taxes = sgst_sale | cgst_sale | sgst_purchase | cgst_purchase
        for tax in intra_taxes:
            if fp_intra not in tax.fiscal_position_ids:
                tax.write({'fiscal_position_ids': [Command.link(fp_intra.id)]})

        # ── Inter-State: IGST replaces SGST + CGST ──────────────────
        # IGST Sale 18% replaces SGST Sale 9% and CGST Sale 9%
        for src_tax in (sgst_sale, cgst_sale):
            if src_tax not in igst_sale.original_tax_ids:
                igst_sale.write({'original_tax_ids': [Command.link(src_tax.id)]})

        for src_tax in (sgst_purchase, cgst_purchase):
            if src_tax not in igst_purchase.original_tax_ids:
                igst_purchase.write({'original_tax_ids': [Command.link(src_tax.id)]})

        # Add IGST to Inter-State fiscal position
        inter_taxes = igst_sale | igst_purchase
        for tax in inter_taxes:
            if fp_inter not in tax.fiscal_position_ids:
                tax.write({'fiscal_position_ids': [Command.link(fp_inter.id)]})

        _logger.info("GST fiscal position tax mappings configured successfully.")

    @api.model
    def _get_default_pdf_report_id(self, move):
        """Always use Marley Proforma Invoice layout as the default for invoices."""
        marley_report = self.env.ref(
            'marley_sale_reports.action_report_marley_proforma',
            raise_if_not_found=False,
        )
        if marley_report:
            return marley_report
        return super()._get_default_pdf_report_id(move)
