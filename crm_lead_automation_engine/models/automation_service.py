from odoo import models, api, fields, _
import logging

_logger = logging.getLogger(__name__)

class CrmAutomationService(models.AbstractModel):
    _name = 'crm.automation.service'
    _description = 'CRM Automation Service'

    def _auto_send_acknowledgment(self, lead):
        """ Send acknowledgment email on lead creation """
        # EMAIL AUTOMATION DISABLED — re-enable by removing the return below
        _logger.info(f"[AUTO] _auto_send_acknowledgment SKIPPED (disabled) for Lead {lead.id}")
        lead.acknowledgment_sent = True
        return

    def _auto_on_qualify(self, lead):
        """ Automation when stage moves to Qualify """
        # EMAIL AUTOMATION DISABLED — re-enable by restoring the original method
        _logger.info(f"[AUTO] _auto_on_qualify SKIPPED (disabled) for Lead {lead.id}")
        lead.salesperson_notified = True
        return

    def _auto_on_won(self, lead):
        """ Automation when lead is Won """
        _logger.info(f"[AUTO] Lead {lead.id} Won Logic Triggered")
        # 1. Convert to Customer (if not already)
        if not lead.partner_id and lead.contact_name:
             lead.handle_partner_assignment() # or custom logic
        
        # 2. Create Sales Order (Placeholder - complex without product)
        # 3. Create Project (Placeholder)
        # 4. Internal Notification
        lead.message_post(body="Lead Won! Automation steps executed (mock).")

    def _auto_check_lost_reason(self, lead):
        """ Check mandatory lost reason """
        if not lead.loss_reason_id or not lead.loss_remarks:
            # Note: This raises validation error, preventing the write if not handled.
            # However, often Stage change happens, then Reason is set. 
            # If we enforce strictness, user must set reason FIRST or use wizard.
            pass # We'll enforce this via required=True in view or specific write check logic

    def _handle_new_lead_whatsapp(self, lead):
        """ Trigger WhatsApp template for API leads created in New stage """
        _logger.info(f"[WHATSAPP_TRIGGER] Checking lead {lead.id}")

        # API lead check
        source = getattr(lead, 'source_api', False)
        is_api_lead = (
            source in ['indiamart', 'aajjo']
            or getattr(lead, 'is_indiamart', False)
            or getattr(lead, 'is_aajjo', False)
        )

        if not is_api_lead:
            _logger.info("[WHATSAPP_TRIGGER] Not an API lead. Skipping.")
            return

        _logger.info(f"[WHATSAPP_TRIGGER] Lead source detected: {source}")

        # Stage check
        if not lead.stage_id:
            return

        _logger.info(f"[WHATSAPP_TRIGGER] Lead stage: {lead.stage_id.name}")

        if lead.stage_id.name.strip().lower() != 'new':
            return

        # Mobile validation
        if not lead.mobile:
            lead.message_post(body="WhatsApp not sent: Mobile missing.")
            return

        # Template validation
        template = self.env['whatsapp.template'].sudo().search([
            ('template_name', '=', 'test'),
            ('meta_status', '=', 'approved')
        ], limit=1)

        if not template:
            lead.message_post(body="WhatsApp not sent: Template not approved.")
            return

        variables = [
            lead.contact_name or "",
            lead.name or "",
            lead.user_id.name if lead.user_id else ""
        ]

        try:
            self.env['whatsapp.service'].send_template_message(
                partner=lead.partner_id,
                template_name="test",
                variables=variables
            )
            lead.message_post(body="WhatsApp template 'test' sent successfully.")
        except Exception as e:
            lead.message_post(body=f"WhatsApp failed: {str(e)}")


