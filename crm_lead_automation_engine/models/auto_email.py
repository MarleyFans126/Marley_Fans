from odoo import models, _
import logging

_logger = logging.getLogger(__name__)


class CrmLeadAutoEmail(models.Model):
    _inherit = 'crm.lead'

    def _auto_send_opportunity_email(self):
        """Send acknowledgment email when a lead is converted to opportunity."""
        for lead in self:
            if lead.acknowledgment_sent:
                continue
            if not lead.email_from:
                _logger.info("[AUTO-EMAIL] Skipped Lead %s — no email address.", lead.id)
                continue

            template = self.env.ref(
                'crm_lead_automation_engine.email_template_opportunity_acknowledgment',
                raise_if_not_found=False,
            )
            if not template:
                _logger.warning("[AUTO-EMAIL] Template not found for Lead %s.", lead.id)
                continue

            log_vals = {
                'lead_id': lead.id,
                'lead_name': lead.name or '',
                'partner_name': lead.contact_name or lead.partner_name or '',
                'email_to': lead.email_from,
                'template_used': template.name,
            }

            try:
                template.send_mail(lead.id, force_send=True)
                log_vals['status'] = 'sent'
                lead.acknowledgment_sent = True
                _logger.info("[AUTO-EMAIL] Email sent for Lead %s to %s", lead.id, lead.email_from)
            except Exception as e:
                log_vals['status'] = 'failed'
                log_vals['error_message'] = str(e)
                _logger.error("[AUTO-EMAIL] Failed for Lead %s: %s", lead.id, e)

            self.env['crm.email.log'].sudo().create(log_vals)
