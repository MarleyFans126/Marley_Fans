# -*- coding: utf-8 -*-
import json
import logging
import requests
from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError

_logger = logging.getLogger(__name__)


class WhatsAppService(models.Model):
    """
    Central WhatsApp Cloud API Service Layer.

    This model is the ONLY entry point for all WhatsApp API calls.
    No business logic lives here — only clean API dispatch.
    All future automations must call this service.
    """
    _name = 'whatsapp.service'
    _description = 'WhatsApp Cloud API Service'

    # -------------------------------------------------------------------------
    # Configuration Helpers
    # -------------------------------------------------------------------------
    @api.model
    def _get_config(self):
        """
        Returns a dict with all required API config parameters.
        Raises UserError if WhatsApp is not enabled or config is incomplete.
        """
        ICP = self.env['ir.config_parameter'].sudo()
        enabled = ICP.get_param('whatsapp_core.enabled', 'False') == 'True'
        if not enabled:
            raise UserError(
                _('WhatsApp integration is not enabled. '
                  'Please enable it in Settings → General Settings → WhatsApp.')
            )
        config = {
            'phone_number_id': ICP.get_param('whatsapp_core.phone_number_id', ''),
            'access_token': ICP.get_param('whatsapp_core.access_token', ''),
            'api_version': ICP.get_param('whatsapp_core.api_version', 'v19.0'),
            'business_account_id': ICP.get_param('whatsapp_core.business_account_id', ''),
        }
        missing = [k for k, v in config.items() if not v]
        if missing:
            raise UserError(
                _('WhatsApp configuration is incomplete. '
                  'Missing: %(fields)s. '
                  'Please complete the setup in Settings → General Settings → WhatsApp.',
                  fields=', '.join(missing))
            )
        return config

    @api.model
    def _get_api_url(self, config):
        """Build the WhatsApp messages API endpoint URL."""
        return (
            f"https://graph.facebook.com/{config['api_version']}"
            f"/{config['phone_number_id']}/messages"
        )

    @api.model
    def _get_headers(self, config):
        """Build standard request headers."""
        return {
            'Authorization': f"Bearer {config['access_token']}",
            'Content-Type': 'application/json',
        }

    # -------------------------------------------------------------------------
    # Core API Dispatcher
    # -------------------------------------------------------------------------
    @api.model
    def _dispatch_api_call(self, payload, config=None):
        """
        Core method to dispatch a WhatsApp API call.

        Args:
            payload (dict): The JSON payload to send.
            config (dict, optional): Config dict. Fetched automatically if not provided.

        Returns:
            dict: {
                'success': bool,
                'message_id': str or None,
                'raw_response': dict,
                'error': str or None,
            }
        """
        if config is None:
            config = self._get_config()

        url = self._get_api_url(config)
        headers = self._get_headers(config)

        _logger.debug(
            'WhatsApp API call to %s | Payload: %s',
            url,
            json.dumps(payload, indent=2),
        )

        try:
            response = requests.post(url, json=payload, headers=headers, timeout=30)
            data = response.json()

            if response.status_code == 200 and data.get('messages'):
                msg_id = data['messages'][0].get('id', '')
                _logger.info('WhatsApp message sent successfully. ID: %s', msg_id)
                return {
                    'success': True,
                    'message_id': msg_id,
                    'raw_response': data,
                    'error': None,
                }
            else:
                error_detail = data.get('error', {})
                error_msg = error_detail.get('message', f'HTTP {response.status_code}')
                error_code = error_detail.get('code', '')
                _logger.warning(
                    'WhatsApp API error [%s]: %s | Response: %s',
                    error_code, error_msg, json.dumps(data)
                )
                return {
                    'success': False,
                    'message_id': None,
                    'raw_response': data,
                    'error': f'[{error_code}] {error_msg}',
                }
        except requests.exceptions.Timeout:
            msg = 'WhatsApp API request timed out.'
            _logger.error(msg)
            return {'success': False, 'message_id': None, 'raw_response': {}, 'error': msg}
        except requests.exceptions.ConnectionError as e:
            msg = f'WhatsApp API connection error: {str(e)}'
            _logger.error(msg)
            return {'success': False, 'message_id': None, 'raw_response': {}, 'error': msg}
        except Exception as e:
            msg = f'Unexpected WhatsApp API error: {str(e)}'
            _logger.exception(msg)
            return {'success': False, 'message_id': None, 'raw_response': {}, 'error': msg}

    # -------------------------------------------------------------------------
    # Public API Methods
    # -------------------------------------------------------------------------
    @api.model
    def send_text_message(self, partner, message):
        """
        Send a plain text WhatsApp message to a partner.

        Args:
            partner: res.partner record
            message (str): Plain text message body.

        Returns:
            dict: API result from _dispatch_api_call
        """
        wa_number = self._resolve_partner_number(partner)
        config = self._get_config()

        payload = {
            'messaging_product': 'whatsapp',
            'recipient_type': 'individual',
            'to': wa_number,
            'type': 'text',
            'text': {
                'preview_url': False,
                'body': message,
            },
        }
        result = self._dispatch_api_call(payload, config)
        self._create_log(
            partner=partner,
            direction='outbound',
            message_type='text',
            payload=payload,
            result=result,
            body_preview=message[:200],
        )
        return result

    @api.model
    def send_template_message(self, partner, template_name, language_code=None, variables=None):
        """
        Send a WhatsApp template (HSM) message to a partner.

        Args:
            partner: res.partner record
            template_name (str): Approved template name in Meta Business Manager.
            language_code (str, optional): Template language code.
                If not provided, auto-detected from local whatsapp.template record.
                Falls back to 'en_US' if not found.
            variables (list of str, optional): List of variable values for {{1}}, {{2}}, etc.

        Returns:
            dict: API result from _dispatch_api_call
        """
        wa_number = self._resolve_partner_number(partner)
        config = self._get_config()

        formatted_template_name = template_name.lower().replace(' ', '_')

        # Auto-detect language code from local template record if not provided
        if not language_code:
            if 'whatsapp.template' in self.env:
                local_tmpl = self.env['whatsapp.template'].sudo().search([
                    ('template_name', '=', formatted_template_name),
                    ('meta_status', '=', 'approved'),
                ], limit=1)
                if local_tmpl:
                    language_code = local_tmpl.language_code or 'en_US'
                    _logger.info(
                        "Auto-detected language_code='%s' for template '%s'",
                        language_code, formatted_template_name,
                    )
            if not language_code:
                language_code = 'en_US'

        components = []
        if variables:
            body_params = [{'type': 'text', 'text': str(v)} for v in variables]
            components.append({
                'type': 'body',
                'parameters': body_params,
            })

        payload = {
            'messaging_product': 'whatsapp',
            'recipient_type': 'individual',
            'to': wa_number,
            'type': 'template',
            'template': {
                'name': formatted_template_name,
                'language': {'code': language_code},
            },
        }

        if components:
            payload['template']['components'] = components
        result = self._dispatch_api_call(payload, config)
        self._create_log(
            partner=partner,
            direction='outbound',
            message_type='template',
            payload=payload,
            result=result,
            template_name=template_name,
            body_preview=f'Template: {template_name}',
        )
        return result

    @api.model
    def send_media_message(self, partner, attachment_id, caption=''):
        """
        Send a media file (image / document / PDF) via WhatsApp.

        Args:
            partner: res.partner record
            attachment_id: ir.attachment record ID (int) or record
            caption (str, optional): Optional caption for the media.

        Returns:
            dict: API result from _dispatch_api_call
        """
        wa_number = self._resolve_partner_number(partner)
        config = self._get_config()

        if isinstance(attachment_id, int):
            attachment = self.env['ir.attachment'].browse(attachment_id)
        else:
            attachment = attachment_id

        if not attachment.exists():
            raise UserError(_('Attachment not found.'))

        # Determine media type from mimetype
        mime = attachment.mimetype or ''
        if mime.startswith('image/'):
            media_type = 'image'
        elif mime == 'application/pdf' or mime.startswith('application/'):
            media_type = 'document'
        elif mime.startswith('audio/'):
            media_type = 'audio'
        elif mime.startswith('video/'):
            media_type = 'video'
        else:
            media_type = 'document'

        # Upload media to Meta to get Media ID
        media_id = self._upload_media_to_meta(attachment, config)

        media_payload = {
            'id': media_id,
        }
        if caption and media_type in ('image', 'document', 'video'):
            media_payload['caption'] = caption
        if media_type == 'document':
            media_payload['filename'] = attachment.name

        payload = {
            'messaging_product': 'whatsapp',
            'recipient_type': 'individual',
            'to': wa_number,
            'type': media_type,
            media_type: media_payload,
        }
        result = self._dispatch_api_call(payload, config)
        self._create_log(
            partner=partner,
            direction='outbound',
            message_type='media',
            payload=payload,
            result=result,
            body_preview=f'[{media_type.upper()}] {attachment.name}',
        )
        return result

    # -------------------------------------------------------------------------
    # Internal Helpers
    # -------------------------------------------------------------------------
    @api.model
    def _upload_media_to_meta(self, attachment, config=None):
        if config is None:
            config = self._get_config()

        url = f"https://graph.facebook.com/{config['api_version']}/{config['phone_number_id']}/media"
        headers = {
            'Authorization': f"Bearer {config['access_token']}",
        }
        
        import base64
        file_content = base64.b64decode(attachment.datas)
        files = {
            'file': (attachment.name, file_content, attachment.mimetype)
        }
        data = {
            'messaging_product': 'whatsapp'
        }

        try:
            response = requests.post(url, headers=headers, data=data, files=files, timeout=30)
            result = response.json()
            if response.status_code == 200 and 'id' in result:
                return result['id']
            else:
                _logger.error("Meta Media Upload Failed: %s", result)
                error_msg = result.get('error', {}).get('message', 'Unknown error')
                raise UserError(_("Failed to upload media to WhatsApp: %s", error_msg))
        except UserError:
            raise
        except Exception as e:
            raise UserError(_("Exception while uploading media: %s", str(e)))

    @api.model
    def _resolve_partner_number(self, partner):
        """
        Resolve and validate the WhatsApp number for a partner.
        Checks whatsapp_number, then phone.
        Must be in E.164 format (e.g. +919876543210).
        """
        number = (partner.whatsapp_number or partner.phone or '').strip()
        if not number:
            raise UserError(
                _('Partner "%s" does not have a valid phone or WhatsApp number configured.', partner.name)
            )

        # Basic E.164 normalization: strip spaces/dashes, ensure starts with +
        number = number.replace(' ', '').replace('-', '').replace('(', '').replace(')', '')
        if not number.startswith('+'):
            number = '+' + number
        return number


    @api.model
    def _create_log(self, partner, direction, message_type, payload,
                    result, template_name=None, body_preview=''):
        """
        Create a whatsapp.message.log record for the sent/received message.
        """
        status = 'sent' if result.get('success') else 'failed'
        self.env['whatsapp.message.log'].sudo().create({
            'partner_id': partner.id,
            'direction': direction,
            'message_type': message_type,
            'template_name': template_name or '',
            'payload': json.dumps(payload, indent=2),
            'status': status,
            'api_response': json.dumps(result.get('raw_response', {}), indent=2),
            'wa_message_id': result.get('message_id', ''),
            'body_preview': body_preview,
        })
        # Post to partner chatter
        icon = '✔️' if status == 'sent' else '❌'
        chatter_body = (
            f"<p><strong>📱 WhatsApp {direction.title()} [{message_type.title()}]</strong> {icon}</p>"
            f"<p>{body_preview}</p>"
        )
        if status == 'failed':
            chatter_body += f"<p><em>Error: {result.get('error', 'Unknown')}</em></p>"
        partner.message_post(
            body=chatter_body,
            message_type='comment',
            subtype_xmlid='mail.mt_note',
        )
