from markupsafe import Markup

from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


class CrmLeadLost(models.TransientModel):
    _inherit = 'crm.lead.lost'

    # Make loss reason mandatory
    lost_reason_id = fields.Many2one(
        'crm.lost.reason', 'Lost Reason', required=True,
    )

    # Add mandatory loss remarks text field
    loss_remarks = fields.Text(
        string='Loss Remarks',
        required=True,
        help='Provide detailed remarks on why this lead was lost.',
    )

    def action_lost_reason_apply(self):
        """Override to store loss_remarks on the lead(s) before marking lost."""
        self.ensure_one()

        if not self.lost_reason_id:
            raise ValidationError(_('Please select a Loss Reason.'))
        if not self.loss_remarks or not self.loss_remarks.strip():
            raise ValidationError(_('Please provide Loss Remarks before marking as lost.'))

        # Store loss fields on the lead records AND log them to the chatter so
        # the reason + remarks are visible in the timeline forever (not only in
        # the form field, which hides when empty).
        for lead in self.lead_ids:
            lead.write({
                'loss_reason_id': self.lost_reason_id.id,
                'loss_remarks': self.loss_remarks,
            })
            lead.message_post(body=Markup(
                "<b>Lead marked Lost</b><br/>"
                "<b>Loss Reason:</b> %s<br/>"
                "<b>Loss Remarks:</b> %s"
            ) % (self.lost_reason_id.name or '', self.loss_remarks or ''))

        return super().action_lost_reason_apply()
