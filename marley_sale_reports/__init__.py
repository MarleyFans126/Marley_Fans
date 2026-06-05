from . import models
from . import wizard
from . import controllers


def _post_init_swap_quotation_report(env):
    """
    Replace Odoo's default quotation report in the 'Send by Email' template
    with the Marley custom quotation report.
    The default template has noupdate=1, so we must do this via Python.
    """
    try:
        # Get the default email template used for 'Send Quotation by Email'
        template = env.ref('sale.email_template_edi_sale', raise_if_not_found=False)
        if not template:
            return

        # Get Odoo's default report and Marley's custom report
        default_report = env.ref('sale.action_report_saleorder', raise_if_not_found=False)
        marley_report = env.ref('marley_sale_reports.action_report_marley_quotation', raise_if_not_found=False)

        if not marley_report:
            return

        # Swap: Remove default, add Marley
        if default_report and default_report in template.report_template_ids:
            template.write({
                'report_template_ids': [(3, default_report.id), (4, marley_report.id)]
            })
        elif marley_report not in template.report_template_ids:
            template.write({
                'report_template_ids': [(4, marley_report.id)]
            })

        # Also update the Proforma template
        proforma_template = env.ref('sale.email_template_proforma', raise_if_not_found=False)
        marley_proforma = env.ref('marley_sale_reports.action_report_marley_proforma', raise_if_not_found=False)
        default_proforma = env.ref('sale.action_report_pro_forma_invoice', raise_if_not_found=False)

        if proforma_template and marley_proforma:
            if default_proforma and default_proforma in proforma_template.report_template_ids:
                proforma_template.write({
                    'report_template_ids': [(3, default_proforma.id), (4, marley_proforma.id)]
                })
            elif marley_proforma not in proforma_template.report_template_ids:
                proforma_template.write({
                    'report_template_ids': [(4, marley_proforma.id)]
                })

        # Ensure the Marley proforma report is marked as an invoice report
        # so the Send wizard accepts it as a valid PDF template
        if marley_proforma and not marley_proforma.is_invoice_report:
            marley_proforma.write({'is_invoice_report': True, 'domain': '[]'})

        # ── Set Marley proforma as default PDF template on ALL sales journals ──
        # This is the primary mechanism Odoo uses when opening the Send wizard:
        # journal.invoice_template_pdf_report_id takes priority over system default.
        if marley_proforma:
            sales_journals = env['account.journal'].search([
                ('type', '=', 'sale'),
            ])
            for journal in sales_journals:
                if journal.invoice_template_pdf_report_id != marley_proforma:
                    journal.invoice_template_pdf_report_id = marley_proforma

            # Also clear any cached PDF on draft/unposted invoices so they regenerate
            # with the new template on next send
            try:
                env.cr.execute("SAVEPOINT clear_pdf_cache")
                env.cr.execute("""
                    UPDATE account_move
                    SET invoice_pdf_report_file = NULL
                    WHERE invoice_pdf_report_file IS NOT NULL
                      AND state = 'posted'
                      AND is_move_sent = FALSE
                """)
                env.cr.execute("RELEASE SAVEPOINT clear_pdf_cache")
            except Exception:
                env.cr.execute("ROLLBACK TO SAVEPOINT clear_pdf_cache")

        # ── Set company name and logo to Marley HVLS Fans ────────────
        import base64, os
        company = env['res.company'].search([], limit=1)
        if company:
            company.write({'name': 'Marley HVLS Fans'})
            # Also update the linked partner
            if company.partner_id:
                company.partner_id.write({'name': 'Marley HVLS Fans'})
            # Set the logo from static file
            logo_path = os.path.join(
                os.path.dirname(__file__),
                'static', 'src', 'img', 'marley_logo.png',
            )
            if os.path.isfile(logo_path):
                with open(logo_path, 'rb') as f:
                    logo_data = base64.b64encode(f.read())
                company.write({'logo': logo_data})

    except Exception as e:
        import logging
        logging.getLogger(__name__).warning("Could not swap quotation report template: %s", e)

    # Consolidate sale taxes down to a single flat "GST 18%"
    _post_init_setup_single_gst(env)


def _post_init_setup_single_gst(env):
    """Make 'GST 18%' the only sale tax users can pick.

    * Set it as the company default sale tax (new products inherit it).
    * Archive every OTHER active sale tax (the SGST/CGST/IGST split taxes
      from this module AND the l10n_in '18% GST S' / '18% IGST S'
      variants) so the order-line tax dropdown shows only 'GST 18%'.
    * Disable the auto-apply GST fiscal positions so Odoo stops
      swapping the single tax for the CGST+SGST / IGST split.

    Archiving (active=False) is reversible and preserves history on
    existing documents — it only hides the taxes from new dropdowns.
    NOTE: a single 'GST 18%' line is fine for quotations/proformas but
    is NOT valid for a legal intra-state tax invoice (which requires a
    CGST 9% + SGST 9% split). Re-activate the split taxes if a
    compliant tax invoice is ever needed.
    """
    import logging
    _logger = logging.getLogger(__name__)
    try:
        gst18 = env.ref('marley_sale_reports.gst_sale_18', raise_if_not_found=False)
        if not gst18:
            _logger.warning("[GST] gst_sale_18 not found, skipping consolidation.")
            return

        # 1) Default sale tax on every company
        for company in env['res.company'].search([]):
            gst18_c = gst18.with_company(company)
            if company.account_sale_tax_id != gst18_c:
                company.account_sale_tax_id = gst18_c.id

        # 2) Archive all other active SALE taxes (keep only GST 18%)
        other_sale_taxes = env['account.tax'].search([
            ('type_tax_use', '=', 'sale'),
            ('active', '=', True),
            ('id', '!=', gst18.id),
        ])
        if other_sale_taxes:
            other_sale_taxes.write({'active': False})
            _logger.info(
                "[GST] Archived %d non-GST18 sale tax(es): %s",
                len(other_sale_taxes), other_sale_taxes.mapped('name'),
            )

        # 3) Disable the auto-apply GST fiscal positions
        for xmlid in (
            'marley_sale_reports.fiscal_position_intra_state',
            'marley_sale_reports.fiscal_position_inter_state',
        ):
            fp = env.ref(xmlid, raise_if_not_found=False)
            if fp:
                fp.write({'auto_apply': False, 'active': False})

        _logger.info("[GST] Single 'GST 18%%' sale tax configured as default.")
    except Exception as e:
        _logger.warning("[GST] Could not consolidate sale taxes: %s", e)
