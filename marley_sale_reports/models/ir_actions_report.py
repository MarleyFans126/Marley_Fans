import logging

from odoo import models, fields

_logger = logging.getLogger(__name__)

# Reports whose rendering counts as "printing the quotation/proforma"
MARLEY_SALE_REPORT_NAMES = {
    'marley_sale_reports.report_marley_quotation',
    'marley_sale_reports.report_marley_sale_proforma',
}


class IrActionsReport(models.Model):
    _inherit = 'ir.actions.report'

    def _render_qweb_pdf(self, report_ref, res_ids=None, data=None):
        result = super()._render_qweb_pdf(report_ref=report_ref, res_ids=res_ids, data=data)
        try:
            report = self._get_report(report_ref)
            if (
                report
                and report.report_name in MARLEY_SALE_REPORT_NAMES
                and report.model == 'sale.order'
                and res_ids
            ):
                orders = self.env['sale.order'].sudo().browse(res_ids).exists()
                if orders:
                    orders.with_context(skip_revision_bump=True).write({
                        'last_print_date': fields.Datetime.now(),
                    })
        except Exception as e:
            _logger.warning("Could not stamp last_print_date on sale.order: %s", e)
        return result
