# -*- coding: utf-8 -*-
import logging
import requests
from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError

_logger = logging.getLogger(__name__)


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    # -------------------------------------------------------------------------
    # WhatsApp Configuration Fields
    # -------------------------------------------------------------------------
    whatsapp_enabled = fields.Boolean(
        string='Enable WhatsApp',
        config_parameter='whatsapp_core.enabled',
        help='Enable WhatsApp Cloud API integration.',
    )
    whatsapp_business_account_id = fields.Char(
        string='Business Account ID',
        config_parameter='whatsapp_core.business_account_id',
        help='Your WhatsApp Business Account ID from Meta Business Manager.',
    )
    whatsapp_phone_number_id = fields.Char(
        string='Phone Number ID',
        config_parameter='whatsapp_core.phone_number_id',
        help='The Phone Number ID associated with your WhatsApp Business Account.',
    )
    whatsapp_access_token = fields.Char(
        string='Permanent Access Token',
        config_parameter='whatsapp_core.access_token',
        help='Permanent access token from Meta Developer Portal. Keep this secret.',
    )
    whatsapp_webhook_verify_token = fields.Char(
        string='Webhook Verify Token',
        config_parameter='whatsapp_core.webhook_verify_token',
        help='A secret string you define. Used to verify webhook requests from Meta.',
    )
    whatsapp_app_id = fields.Char(
        string='App ID',
        config_parameter='whatsapp_core.app_id',
        help='Your WhatsApp Meta App ID (optional).',
    )
    whatsapp_app_secret = fields.Char(
        string='App Secret',
        config_parameter='whatsapp_core.app_secret',
        help='Your Meta App Secret used for webhook signature validation.',
    )
    whatsapp_api_version = fields.Char(
        string='API Version',
        config_parameter='whatsapp_core.api_version',
        default='v19.0',
        help='Meta Graph API version (e.g. v19.0).',
    )
    whatsapp_connection_status = fields.Selection(
        selection=[
            ('not_tested', 'Not Tested'),
            ('connected', 'Connected'),
            ('failed', 'Connection Failed'),
        ],
        string='Connection Status',
        config_parameter='whatsapp_core.connection_status',
        default='not_tested',
        readonly=True,
    )

    # -------------------------------------------------------------------------
    # Default Get / Set
    # -------------------------------------------------------------------------
    @api.model
    def get_values(self):
        res = super().get_values()
        ICP = self.env['ir.config_parameter'].sudo()
        res.update({
            'whatsapp_enabled': ICP.get_param('whatsapp_core.enabled', 'False') == 'True',
            'whatsapp_business_account_id': ICP.get_param('whatsapp_core.business_account_id', ''),
            'whatsapp_phone_number_id': ICP.get_param('whatsapp_core.phone_number_id', ''),
            'whatsapp_access_token': ICP.get_param('whatsapp_core.access_token', ''),
            'whatsapp_webhook_verify_token': ICP.get_param('whatsapp_core.webhook_verify_token', ''),
            'whatsapp_app_id': ICP.get_param('whatsapp_core.app_id', ''),
            'whatsapp_app_secret': ICP.get_param('whatsapp_core.app_secret', ''),
            'whatsapp_api_version': ICP.get_param('whatsapp_core.api_version', 'v19.0'),
            'whatsapp_connection_status': ICP.get_param('whatsapp_core.connection_status', 'not_tested'),
        })
        return res

    def set_values(self):
        super().set_values()
        ICP = self.env['ir.config_parameter'].sudo()
        ICP.set_param('whatsapp_core.enabled', str(self.whatsapp_enabled))
        ICP.set_param('whatsapp_core.business_account_id', self.whatsapp_business_account_id or '')
        ICP.set_param('whatsapp_core.phone_number_id', self.whatsapp_phone_number_id or '')
        ICP.set_param('whatsapp_core.access_token', self.whatsapp_access_token or '')
        ICP.set_param('whatsapp_core.webhook_verify_token', self.whatsapp_webhook_verify_token or '')
        ICP.set_param('whatsapp_core.app_id', self.whatsapp_app_id or '')
        ICP.set_param('whatsapp_core.app_secret', self.whatsapp_app_secret or '')
        ICP.set_param('whatsapp_core.api_version', self.whatsapp_api_version or 'v19.0')

    # -------------------------------------------------------------------------
    # Test Connection Button
    # -------------------------------------------------------------------------
    def action_whatsapp_test_connection(self):
        """Test the WhatsApp Cloud API connection by calling the phone number endpoint."""
        self.ensure_one()
        self._validate_config_fields()

        phone_number_id = self.whatsapp_phone_number_id
        access_token = self.whatsapp_access_token
        api_version = self.whatsapp_api_version or 'v19.0'

        url = f'https://graph.facebook.com/{api_version}/{phone_number_id}'
        headers = {
            'Authorization': f'Bearer {access_token}',
            'Content-Type': 'application/json',
        }

        try:
            response = requests.get(url, headers=headers, timeout=15)
            data = response.json()

            if response.status_code == 200 and data.get('id'):
                # Success — persist the connected status
                self.env['ir.config_parameter'].sudo().set_param(
                    'whatsapp_core.connection_status', 'connected'
                )
                display_name = data.get('display_phone_number', phone_number_id)
                verified_name = data.get('verified_name', '')
                return self._show_success_notification(
                    title=_('Connection Successful ✔'),
                    message=_(
                        'WhatsApp Business Account connected!\n'
                        'Phone: %(phone)s\n'
                        'Business Name: %(name)s',
                        phone=display_name,
                        name=verified_name,
                    ),
                )
            else:
                error_msg = data.get('error', {}).get('message', _('Unknown error from Meta API'))
                self.env['ir.config_parameter'].sudo().set_param(
                    'whatsapp_core.connection_status', 'failed'
                )
                raise UserError(
                    _('Connection Failed!\n\nMeta API Error: %(error)s', error=error_msg)
                )
        except requests.exceptions.Timeout:
            self.env['ir.config_parameter'].sudo().set_param(
                'whatsapp_core.connection_status', 'failed'
            )
            raise UserError(_('Connection timed out. Check your internet connection and try again.'))
        except requests.exceptions.ConnectionError:
            self.env['ir.config_parameter'].sudo().set_param(
                'whatsapp_core.connection_status', 'failed'
            )
            raise UserError(_('Unable to reach Meta API. Check network connectivity.'))
        except UserError:
            raise
        except Exception as e:
            _logger.exception('WhatsApp connection test failed')
            self.env['ir.config_parameter'].sudo().set_param(
                'whatsapp_core.connection_status', 'failed'
            )
            raise UserError(_('Unexpected error: %(error)s', error=str(e)))

    # -------------------------------------------------------------------------
    # Validate Credentials Button
    # -------------------------------------------------------------------------
    def action_whatsapp_validate_credentials(self):
        """Validate credentials by fetching the Business Account details."""
        self.ensure_one()
        self._validate_config_fields()

        business_account_id = self.whatsapp_business_account_id
        access_token = self.whatsapp_access_token
        api_version = self.whatsapp_api_version or 'v19.0'

        url = f'https://graph.facebook.com/{api_version}/{business_account_id}'
        params = {
            'fields': 'id,name,currency,timezone_id,message_template_namespace',
            'access_token': access_token,
        }

        try:
            response = requests.get(url, params=params, timeout=15)
            data = response.json()

            if response.status_code == 200 and data.get('id'):
                account_name = data.get('name', 'N/A')
                return self._show_success_notification(
                    title=_('Credentials Valid ✔'),
                    message=_(
                        'WhatsApp Business Account validated!\n'
                        'Account Name: %(name)s\n'
                        'Account ID: %(id)s',
                        name=account_name,
                        id=data.get('id', ''),
                    ),
                )
            else:
                error_msg = data.get('error', {}).get('message', _('Invalid credentials'))
                raise UserError(
                    _('Credential Validation Failed!\n\nError: %(error)s', error=error_msg)
                )
        except requests.exceptions.Timeout:
            raise UserError(_('Validation timed out. Check your internet connection.'))
        except requests.exceptions.ConnectionError:
            raise UserError(_('Unable to reach Meta API. Check network connectivity.'))
        except UserError:
            raise
        except Exception as e:
            _logger.exception('WhatsApp credential validation failed')
            raise UserError(_('Unexpected error: %(error)s', error=str(e)))

    # -------------------------------------------------------------------------
    # Helpers
    # -------------------------------------------------------------------------
    def _validate_config_fields(self):
        """Ensure all required configuration fields are filled."""
        missing = []
        if not self.whatsapp_phone_number_id:
            missing.append(_('Phone Number ID'))
        if not self.whatsapp_access_token:
            missing.append(_('Permanent Access Token'))
        if not self.whatsapp_business_account_id:
            missing.append(_('Business Account ID'))
        if missing:
            raise ValidationError(
                _('Please fill in the following required fields:\n• %(fields)s',
                  fields='\n• '.join(missing))
            )

    def _show_success_notification(self, title, message):
        """Return a clean notification action."""
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': title,
                'message': message,
                'type': 'success',
                'sticky': True,
                'next': {'type': 'ir.actions.act_window_close'},
            },
        }
