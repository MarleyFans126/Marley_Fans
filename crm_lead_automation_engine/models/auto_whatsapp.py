from odoo import models
import logging

_logger = logging.getLogger(__name__)


class CrmLeadAutoWhatsApp(models.Model):
    _inherit = 'crm.lead'

    def _auto_send_opportunity_whatsapp(self):
        """Send WhatsApp acknowledgment when a lead is converted to opportunity."""
        for lead in self:
            if lead.whatsapp_ack_sent:
                continue

            # Soft dependency — skip if whatsapp module not installed
            if 'whatsapp.service' not in self.env:
                _logger.info("[AUTO-WA] whatsapp.service not available. Skipping Lead %s.", lead.id)
                return

            # Need a phone number
            phone = lead.phone or getattr(lead, 'mobile', False)
            if not phone:
                _logger.info("[AUTO-WA] Skipped Lead %s — no phone number.", lead.id)
                continue

            # Need a partner for the WhatsApp service
            if not lead.partner_id:
                _logger.info("[AUTO-WA] Skipped Lead %s — no partner linked.", lead.id)
                continue

            contact_name = lead.contact_name or lead.partner_id.name or ''
            variables = [contact_name]

            try:
                self.env['whatsapp.service'].send_template_message(
                    partner=lead.partner_id,
                    template_name='lead_auto_thankyou',
                    variables=variables,
                )
                lead.whatsapp_ack_sent = True
                lead.message_post(
                    body="WhatsApp template 'lead_auto_thankyou' sent automatically.",
                    message_type='comment',
                    subtype_xmlid='mail.mt_note',
                )
                _logger.info("[AUTO-WA] WhatsApp sent for Lead %s", lead.id)
            except Exception as e:
                lead.message_post(
                    body="WhatsApp auto-send failed: %s" % str(e),
                    message_type='comment',
                    subtype_xmlid='mail.mt_note',
                )
                _logger.error("[AUTO-WA] Failed for Lead %s: %s", lead.id, e)
