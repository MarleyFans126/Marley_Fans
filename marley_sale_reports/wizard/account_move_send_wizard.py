from odoo import api, models
import logging

_logger = logging.getLogger(__name__)


class AccountMoveSendWizard(models.TransientModel):
    _inherit = 'account.move.send.wizard'

    @api.depends('move_id')
    def _compute_pdf_report_id(self):
        """Force Marley Proforma Invoice as the default PDF report for invoices."""
        marley_report = self.env.ref(
            'marley_sale_reports.action_report_marley_proforma',
            raise_if_not_found=False,
        )
        for wizard in self:
            if marley_report and wizard.move_id.is_sale_document(include_receipts=True):
                wizard.pdf_report_id = marley_report
            else:
                wizard.pdf_report_id = self._get_default_pdf_report_id(wizard.move_id)
