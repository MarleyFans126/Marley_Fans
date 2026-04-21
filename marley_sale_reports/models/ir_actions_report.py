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

    def _marley_stamp_print(self, report_ref, res_ids):
        """Stamp last_print_date on sale.order records when a Marley report runs."""
        _logger.info("Marley stamp: called with report_ref=%s res_ids=%s", report_ref, res_ids)
        if not res_ids:
            _logger.info("Marley stamp: no res_ids, skipping")
            return
        try:
            report = self._get_report(report_ref)
        except Exception as e:
            _logger.warning("Marley stamp: could not resolve report %s: %s", report_ref, e)
            return
        if not report:
            _logger.info("Marley stamp: report is None for ref=%s", report_ref)
            return
        _logger.info(
            "Marley stamp: resolved report_name=%s model=%s",
            report.report_name, report.model,
        )
        if report.model != 'sale.order':
            return
        if report.report_name not in MARLEY_SALE_REPORT_NAMES:
            return
        try:
            orders = self.env['sale.order'].sudo().browse(res_ids).exists()
            if orders:
                orders.with_context(skip_revision_bump=True).write({
                    'last_print_date': fields.Datetime.now(),
                })
                _logger.info(
                    "Marley stamp: STAMPED last_print_date on sale.order ids=%s via %s",
                    orders.ids, report.report_name,
                )
        except Exception as e:
            _logger.warning("Marley stamp: could not stamp last_print_date: %s", e)

    def _render_qweb_pdf(self, report_ref, res_ids=None, data=None):
        result = super()._render_qweb_pdf(report_ref=report_ref, res_ids=res_ids, data=data)
        self._marley_stamp_print(report_ref, res_ids)
        return result

    def _pre_render_qweb_pdf(self, report_ref, res_ids=None, data=None):
        result = super()._pre_render_qweb_pdf(report_ref=report_ref, res_ids=res_ids, data=data)
        self._marley_stamp_print(report_ref, res_ids)
        return result

    def _render_qweb_html(self, report_ref, docids, data=None):
        result = super()._render_qweb_html(report_ref, docids, data=data)
        self._marley_stamp_print(report_ref, docids)
        return result
