from odoo import models, fields

class CrmLeadLost(models.TransientModel):
    _inherit = 'crm.lead.lost'

    loss_remarks = fields.Text(string="Loss Remarks", required=True)

    def action_lost_reason_apply(self):
        leads = self.env['crm.lead'].browse(self.env.context.get('active_ids'))
        leads.write({'loss_remarks': self.loss_remarks})
        return super(CrmLeadLost, self).action_lost_reason_apply()
