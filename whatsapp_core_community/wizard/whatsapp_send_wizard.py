# -*- coding: utf-8 -*-
import json
import logging
from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError

_logger = logging.getLogger(__name__)


class WhatsAppSendWizard(models.TransientModel):
    """
    Wizard to compose and send a manual WhatsApp message.
    """
    _name = 'whatsapp.send.wizard'
    _description = 'Send WhatsApp Message Wizard'

    partner_id = fields.Many2one(
        'res.partner',
        string='Contact',
        required=False, # Make optional for leads
        ondelete='cascade',
    )
    
    lead_id = fields.Many2one(
        'crm.lead',
        string='Lead',
        required=False,
        ondelete='cascade',
    )
    
    mobile_number = fields.Char(
        string='Mobile Number',
        readonly=True,
    )
    
    whatsapp_enabled = fields.Boolean(
        compute='_compute_whatsapp_enabled'
    )

    def _compute_whatsapp_enabled(self):
        enabled = self.env['ir.config_parameter'].sudo().get_param('whatsapp_core.enabled', 'False') == 'True'
        for wizard in self:
            wizard.whatsapp_enabled = enabled


    message_type = fields.Selection(
        selection=[
            ('text', 'Text Message'),
            ('template', 'Template (HSM)'),
            ('media', 'Media / Document'),
        ],
        string='Message Type',
        default='text',
        required=True,
    )

    # Text message fields
    text_body = fields.Text(string='Message Text')

    # Template fields
    template_id = fields.Many2one('whatsapp.template', string='Template', domain=[('meta_status', '=', 'approved')])
    template_preview = fields.Text(related='template_id.body_text', string='Preview', readonly=True)
    variable_count = fields.Integer(related='template_id.variable_count', readonly=True)
    
    has_approved_templates = fields.Boolean(compute='_compute_has_approved_templates')

    def _compute_has_approved_templates(self):
        approved_count = self.env['whatsapp.template'].search_count([('meta_status', '=', 'approved')])
        for wizard in self:
            wizard.has_approved_templates = approved_count > 0

    variable_1 = fields.Char(string='Variable 1')
    variable_2 = fields.Char(string='Variable 2')
    variable_3 = fields.Char(string='Variable 3')
    variable_4 = fields.Char(string='Variable 4')
    variable_5 = fields.Char(string='Variable 5')
    variable_6 = fields.Char(string='Variable 6')
    variable_7 = fields.Char(string='Variable 7')
    variable_8 = fields.Char(string='Variable 8')
    variable_9 = fields.Char(string='Variable 9')
    variable_10 = fields.Char(string='Variable 10')

    # Media fields
    media_file = fields.Binary(string='Upload File', attachment=False)
    media_filename = fields.Char(string='Filename')
    media_caption = fields.Char(string='Caption')

    # -------------------------------------------------------------------------
    # Actions
    # -------------------------------------------------------------------------
    def action_send_whatsapp(self):
        """Dispatch the WhatsApp message via the service layer."""
        self.ensure_one()

        if not self.mobile_number:
            raise ValidationError(_('No WhatsApp number provided.'))

        service = self.env['whatsapp.service']
        result = None

        # Create temporary partner if missing for logging purposes 
        # (or modify service to handle raw numbers - we'll keep partner for now 
        # but the crm lead usually has a partner_id or we use a guest partner)
        
        target_partner = self.partner_id
        if not target_partner:
            # Fallback logic for leads without partners:
            # For now, the service expects a partner. 
            # In a real scenario, we might want to log to the lead itself 
            # but the logs are partner-centric in this module.
             raise UserError(_("Sending messages to leads without a Contact (Partner) is currently being improved. Please link a contact first."))

        try:
            if self.message_type == 'text':
                self._validate_text()
                result = service.send_text_message(
                    partner=target_partner,
                    message=self.text_body,
                )

            elif self.message_type == 'template':
                self._validate_template()
                
                if self.template_id.meta_status != 'approved':
                    raise UserError(_("You can only send approved templates. This template is currently: %s") % self.template_id.meta_status.capitalize())

                variables = self._collect_variables()
                lang_code = self.template_id.language_code.strip() if self.template_id.language_code else 'en_US'
                result = service.send_template_message(
                    partner=target_partner,
                    template_name=self.template_id.template_name.strip(),
                    language_code=lang_code,
                    variables=variables,
                )

            elif self.message_type == 'media':
                self._validate_media()
                
                attachment = self.env['ir.attachment'].create({
                    'name': self.media_filename,
                    'type': 'binary',
                    'datas': self.media_file,
                    'res_model': 'whatsapp.message.log', 
                    'res_id': 0,
                })

                result = service.send_media_message(
                    partner=target_partner,
                    attachment_id=attachment,
                    caption=self.media_caption or '',
                )

            if result and result.get('success'):
                return {
                    'type': 'ir.actions.client',
                    'tag': 'display_notification',
                    'params': {
                        'title': _('WhatsApp Message Sent ✔'),
                        'message': _(
                            'Message sent successfully to %(name)s.',
                            name=target_partner.name,
                        ),
                        'type': 'success',
                        'sticky': False,
                        'next': {'type': 'ir.actions.act_window_close'},
                    },
                }
            else:
                error = result.get('error', _('Unknown error')) if result else _('No response')
                raise UserError(_('WhatsApp send failed: %(error)s', error=error))

        except (ValidationError, UserError):
            raise
        except Exception as e:
            raise UserError(_('Unexpected error while sending WhatsApp: %(error)s', error=str(e)))

    # -------------------------------------------------------------------------
    # Validation Helpers
    # -------------------------------------------------------------------------
    def _validate_text(self):
        if not self.text_body:
            raise ValidationError(_('Message body cannot be empty.'))

    def _validate_template(self):
        if not self.template_id:
            raise ValidationError(_('Template is required.'))

    def _validate_media(self):
        if not self.media_file:
            raise ValidationError(_('Please attach a file for media message.'))
        if len(self.media_file) > 20 * 1024 * 1024:
            raise ValidationError(_('Media file exceeds 15MB limit.'))

    def _collect_variables(self):
        vars_list = []
        for i in range(1, (self.variable_count or 0) + 1):
            val = getattr(self, f'variable_{i}', False)
            vars_list.append(val or '')
        return vars_list
