from odoo import http
from odoo.http import request
import json
import logging

_logger = logging.getLogger(__name__)

class AajjoWebhookController(http.Controller):
    
    @http.route('/api/v1/marley/webhook', type='jsonrpc', auth='public', methods=['POST'], csrf=False)
    def handle_webhook(self, **post):
        try:
            data = request.jsonrequest
            
            # Log Incoming
            request.env['aajjo.api.log'].sudo().create({
                'name': '/api/v1/marley/webhook',
                'request_type': 'POST',
                'request_payload': json.dumps(data),
                'status_code': 200,
                'response_payload': 'Received',
            })

            # Process Lead (Using same logic as cron but single item)
            # Assuming payload matches what cron gets or is wrapped
            lead_data = data.get('data') or data
            if lead_data:
                # Reuse process logic from model
                request.env['crm.lead'].sudo()._process_aajjo_lead(lead_data)

            return {'status': 'success'}
        except Exception as e:
             _logger.exception("Webhook Error")
             return {'status': 'error', 'message': str(e)}
