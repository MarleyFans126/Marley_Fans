"""Portal controller override — make the customer-portal "View Details"
button (and any ?report_type=pdf link) render the Marley Quotation report
instead of Odoo's default `sale.action_report_saleorder`.
"""

from odoo import http
from odoo.exceptions import AccessError, MissingError
from odoo.http import request
from odoo.addons.sale.controllers.portal import CustomerPortal


class MarleyCustomerPortal(CustomerPortal):

    @http.route(['/my/orders/<int:order_id>'], type='http', auth='public', website=True)
    def portal_order_page(
        self,
        order_id,
        report_type=None,
        access_token=None,
        message=False,
        download=False,
        payment_amount=None,
        amount_selection=None,
        **kw,
    ):
        # Only intercept PDF / HTML / TEXT report rendering — fall back to
        # the standard portal page for the regular HTML order view.
        if report_type in ('html', 'pdf', 'text'):
            try:
                order_sudo = self._document_check_access(
                    'sale.order', order_id, access_token=access_token,
                )
            except (AccessError, MissingError):
                return request.redirect('/my')
            return self._show_report(
                model=order_sudo,
                report_type=report_type,
                report_ref='marley_sale_reports.action_report_marley_quotation',
                download=download,
            )
        return super().portal_order_page(
            order_id,
            report_type=report_type,
            access_token=access_token,
            message=message,
            download=download,
            payment_amount=payment_amount,
            amount_selection=amount_selection,
            **kw,
        )
