from odoo import models, fields, api, _

class LeadWhatsappBulkApproveWizard(models.TransientModel):
    _name = 'lead.whatsapp.bulk.approve.wizard'
    _description = 'Bulk Approve WhatsApp Wizard'

    lead_ids = fields.Many2many('crm.lead', string='Leads')
    count = fields.Integer(string='Count', compute='_compute_count')
    preview_text = fields.Text(string='Preview Text', default='Template: lead_auto_thankyou')

    @api.depends('lead_ids')
    def _compute_count(self):
        for rec in self:
            rec.count = len(rec.lead_ids)

    def action_approve_and_send(self):
        for lead in self.lead_ids:
            if not lead.phone and not lead.mobile:
                lead.message_post(body="WhatsApp not sent via wizard: Mobile/Phone missing.")
                continue

            try:
                # Variables: {{1}} -> lead.contact_name or lead.name
                val = lead.contact_name or lead.name or ''
                self.env['whatsapp.service'].send_template_message(
                    partner=lead.partner_id,
                    template_name='lead_auto_thankyou',
                    variables=[val]
                )
                lead.whatsapp_ack_sent = True
                lead.message_post(body="WhatsApp acknowledgment sent via approval wizard.")
            except Exception as e:
                lead.message_post(body=f"WhatsApp sending failed via wizard: {str(e)}")

        # Return the original CRM action
        return self.env['ir.actions.act_window']._for_xml_id('crm.crm_lead_all_leads')

    def action_cancel(self):
        return self.env['ir.actions.act_window']._for_xml_id('crm.crm_lead_all_leads')
