from . import models
from . import wizard


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
            env.cr.execute("""
                UPDATE account_move
                SET invoice_pdf_report_file = NULL
                WHERE invoice_pdf_report_file IS NOT NULL
                  AND state = 'posted'
                  AND is_move_sent = FALSE
            """)

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
