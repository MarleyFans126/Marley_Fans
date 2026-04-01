# -*- coding: utf-8 -*-
import json
import logging

from odoo import http, _
from odoo.http import request

_logger = logging.getLogger(__name__)


class WhatsAppWebhookController(http.Controller):
    """
    WhatsApp Cloud API Webhook Controller.

    Handles:
      - GET  /whatsapp/webhook  → Webhook verification (Meta handshake)
      - POST /whatsapp/webhook  → Inbound message processing
    """

    WEBHOOK_PATH = '/whatsapp/webhook'

    # =========================================================================
    # GET — Webhook Verification (Meta handshake)
    # =========================================================================
    @http.route(WEBHOOK_PATH, type='http', auth='public', methods=['GET'], csrf=False)
    def whatsapp_webhook_verify(self, **kwargs):
        """
        Handle Meta's webhook verification challenge.
        Meta sends:
          hub.mode=subscribe, hub.challenge=<random>, hub.verify_token=<your_token>
        We must respond with hub.challenge if the verify_token matches.
        """
        mode = kwargs.get('hub.mode')
        challenge = kwargs.get('hub.challenge')
        verify_token = kwargs.get('hub.verify_token')

        ICP = request.env['ir.config_parameter'].sudo()
        stored_token = ICP.get_param('whatsapp_core.webhook_verify_token', '')

        if mode == 'subscribe' and verify_token == stored_token:
            _logger.info('WhatsApp webhook verified successfully.')
            return request.make_response(
                challenge,
                headers=[('Content-Type', 'text/plain')],
            )
        else:
            _logger.warning(
                'WhatsApp webhook verification failed. '
                'mode=%s verify_token=%s expected=%s',
                mode, verify_token, stored_token,
            )
            return request.make_response(
                'Verification failed',
                status=403,
                headers=[('Content-Type', 'text/plain')],
            )

    # =========================================================================
    # POST — Inbound Message Handler
    # =========================================================================
    @http.route(WEBHOOK_PATH, type='http', auth='public', methods=['POST'], csrf=False)
    def whatsapp_webhook_inbound(self, **kwargs):
        """
        Process inbound WhatsApp messages pushed by Meta.

        Payload structure (WhatsApp Cloud API):
        {
          "object": "whatsapp_business_account",
          "entry": [{
            "id": "<WABA_ID>",
            "changes": [{
              "value": {
                "messaging_product": "whatsapp",
                "contacts": [{"profile": {"name": "..."}, "wa_id": "..."}],
                "messages": [{
                  "from": "<phone_number>",
                  "id": "wamid...",
                  "type": "text",
                  "text": {"body": "..."},
                  "timestamp": "..."
                }]
              },
              "field": "messages"
            }]
          }]
        }
        """
        try:
            raw_body = request.httprequest.get_data(as_text=True)
            _logger.debug('WhatsApp inbound webhook received: %s', raw_body[:1000])

            try:
                payload = json.loads(raw_body)
            except json.JSONDecodeError:
                _logger.error('WhatsApp webhook: invalid JSON body')
                return request.make_response('Bad Request', status=400)

            if payload.get('object') != 'whatsapp_business_account':
                _logger.debug('Webhook payload is not for whatsapp_business_account, ignoring.')
                return request.make_response('OK', status=200)

            for entry in payload.get('entry', []):
                for change in entry.get('changes', []):
                    if change.get('field') != 'messages':
                        continue
                    value = change.get('value', {})
                    self._process_inbound_messages(value, raw_body)

            return request.make_response('OK', status=200)

        except Exception:
            _logger.exception('Unhandled error in WhatsApp webhook')
            # Always respond 200 to Meta to prevent retries
            return request.make_response('OK', status=200)

    # =========================================================================
    # Internal Helpers
    # =========================================================================
    def _process_inbound_messages(self, value, raw_payload):
        """Process a single 'value' block from the webhook entry."""
        messages = value.get('messages', [])
        contacts = value.get('contacts', [])

        # Build phone → name map from contacts
        contact_map = {c.get('wa_id', ''): c.get('profile', {}).get('name', '') for c in contacts}

        for msg in messages:
            try:
                self._handle_single_message(msg, contact_map, raw_payload)
            except Exception:
                _logger.exception('Error handling inbound WhatsApp message: %s', msg)

    def _handle_single_message(self, msg, contact_map, raw_payload):
        """Handle a single inbound message object."""
        from_number = msg.get('from', '')
        wa_message_id = msg.get('id', '')
        msg_type = msg.get('type', 'unknown')
        sender_name = contact_map.get(from_number, from_number)

        # Extract message body
        body_preview = self._extract_body(msg, msg_type)

        # Format number as E.164
        full_number = f'+{from_number}' if not from_number.startswith('+') else from_number

        env = request.env(user=request.env.ref('base.user_root').id)

        # Try to find partner by WhatsApp number
        partner = env['res.partner'].sudo().search(
            [('whatsapp_number', '=', full_number)], limit=1
        )
        if not partner:
            # Try mobile / phone fallback
            partner = env['res.partner'].sudo().search(
                [
                    '|',
                    ('mobile', '=', full_number),
                    ('phone', '=', full_number),
                ],
                limit=1,
            )

        if not partner:
            # Create a new basic contact
            _logger.info(
                'WhatsApp: No partner found for %s. Creating new contact.', full_number
            )
            partner = env['res.partner'].sudo().create({
                'name': sender_name or full_number,
                'mobile': full_number,
                'whatsapp_number': full_number,
            })
            _logger.info('WhatsApp: Created new partner %s (id=%s)', partner.name, partner.id)

        # Check for duplicate message (idempotency)
        existing = env['whatsapp.message.log'].sudo().search(
            [('wa_message_id', '=', wa_message_id)], limit=1
        )
        if existing:
            _logger.debug('WhatsApp: Message %s already logged, skipping.', wa_message_id)
            return

        # Create message log
        env['whatsapp.message.log'].sudo().create({
            'partner_id': partner.id,
            'direction': 'inbound',
            'message_type': msg_type if msg_type in ('text', 'template', 'media') else 'unknown',
            'body_preview': body_preview,
            'payload': json.dumps(msg, indent=2),
            'status': 'received',
            'api_response': raw_payload[:5000],
            'wa_message_id': wa_message_id,
            'from_number': full_number,
        })

        # Post inbound message to chatter
        partner.message_post(
            body=(
                f'<p><strong>📱 WhatsApp Inbound ↙</strong></p>'
                f'<p><strong>From:</strong> {sender_name} ({full_number})</p>'
                f'<p><strong>Message:</strong> {body_preview}</p>'
            ),
            message_type='comment',
            subtype_xmlid='mail.mt_note',
        )
        _logger.info(
            'WhatsApp inbound: logged message from %s (partner: %s)',
            full_number, partner.name,
        )

    @staticmethod
    def _extract_body(msg, msg_type):
        """Extract a human-readable preview from an inbound message payload."""
        if msg_type == 'text':
            return msg.get('text', {}).get('body', '[text]')
        elif msg_type == 'image':
            caption = msg.get('image', {}).get('caption', '')
            return f'[IMAGE] {caption}' if caption else '[IMAGE]'
        elif msg_type == 'document':
            name = msg.get('document', {}).get('filename', 'document')
            return f'[DOCUMENT] {name}'
        elif msg_type == 'audio':
            return '[AUDIO]'
        elif msg_type == 'video':
            caption = msg.get('video', {}).get('caption', '')
            return f'[VIDEO] {caption}' if caption else '[VIDEO]'
        elif msg_type == 'location':
            loc = msg.get('location', {})
            return f'[LOCATION] {loc.get("name", "")} ({loc.get("latitude", "")},{loc.get("longitude", "")})'
        elif msg_type == 'interactive':
            interactive = msg.get('interactive', {})
            itype = interactive.get('type', '')
            if itype == 'button_reply':
                return f'[BUTTON] {interactive.get("button_reply", {}).get("title", "")}'
            elif itype == 'list_reply':
                return f'[LIST] {interactive.get("list_reply", {}).get("title", "")}'
        elif msg_type == 'sticker':
            return '[STICKER]'
        return f'[{msg_type.upper()}]'
