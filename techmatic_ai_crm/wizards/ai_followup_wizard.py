# -*- coding: utf-8 -*-
"""Follow-up email generator wizard.

Flow:

1. Open from a lead → AI drafts a follow-up body.
2. User edits the draft inline.
3. ``Send`` logs it as a ``mail.message`` on the lead (and optionally
   emails the partner).
"""
import logging

from odoo import api, fields, models, _
from odoo.exceptions import UserError

from ..services.ai_service import AIService
from ..services.exceptions import AIError

_logger = logging.getLogger(__name__)


class AiFollowupWizard(models.TransientModel):
    _name = 'techmatic.ai.followup.wizard'
    _description = 'AI Follow-Up Email Wizard'

    lead_id = fields.Many2one('crm.lead', required=True, ondelete='cascade')
    instructions = fields.Char(
        help='Optional steering for the AI: "remind them about the demo", '
             '"polite nudge after 2 weeks", etc.',
    )
    # Subject is picked from a short dropdown of the most common
    # follow-up scenarios. Selecting "Custom…" reveals the free-text
    # field below so the user can type their own subject line.
    subject_template = fields.Selection(
        selection=[
            ('followup',     'Follow-up'),
            ('checking_in',  'Checking in'),
            ('demo',         'Demo follow-up'),
            ('quote',        'Quote follow-up'),
            ('proposal',     'Proposal follow-up'),
            ('meeting',      'Meeting request'),
            ('introduction', 'Introduction'),
            ('reminder',     'Friendly reminder'),
            ('custom',       'Custom…'),
        ],
        string='Subject',
        default='followup',
        required=True,
    )
    subject = fields.Char(
        string='Custom subject',
        compute='_compute_subject',
        store=True, readonly=False,
    )
    body = fields.Html()
    state = fields.Selection(
        selection=[('draft', 'Draft'), ('ready', 'Ready')],
        default='draft',
    )
    send_email = fields.Boolean(
        default=False,
        help='If checked AND the lead has a partner email, the wizard '
             'will additionally trigger an outbound email.',
    )

    # Map dropdown codes → the actual email subject line. Keep these
    # in sync with the ``subject_template`` selection labels above.
    _SUBJECT_TEMPLATES = {
        'followup':     'Follow-up',
        'checking_in':  'Checking in',
        'demo':         'Demo follow-up',
        'quote':        'Quote follow-up',
        'proposal':     'Proposal follow-up',
        'meeting':      'Meeting request',
        'introduction': 'Introduction',
        'reminder':     'Friendly reminder',
    }

    @api.depends('subject_template')
    def _compute_subject(self):
        """Auto-fill ``subject`` from the dropdown selection.

        For the ``custom`` option the field stays writable and we don't
        clobber whatever the user typed; otherwise we overwrite with the
        canonical template label so a salesperson can switch options
        freely without orphan text left over.
        """
        for rec in self:
            if rec.subject_template == 'custom':
                # Keep whatever the user already entered. If they just
                # switched to 'custom' for the first time, seed with the
                # current subject (or blank) so the input is editable.
                rec.subject = rec.subject or ''
            else:
                rec.subject = self._SUBJECT_TEMPLATES.get(
                    rec.subject_template, 'Follow-up',
                )

    @api.model_create_multi
    def create(self, vals_list):
        """Pre-fill the AI draft on open so users land on a ready form."""
        records = super().create(vals_list)
        for rec in records:
            if not rec.body and rec.lead_id:
                rec._regenerate()
        return records

    def action_regenerate(self):
        self.ensure_one()
        self._regenerate()
        return {
            'type': 'ir.actions.act_window',
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }

    def _regenerate(self):
        service = AIService(self.env)
        try:
            text = service.generate_followup_email(
                self.lead_id, instructions=self.instructions,
            )
        except AIError as e:
            raise UserError(_('AI error: %s') % e) from e
        # Plain → HTML: preserve paragraphs, escape angle brackets.
        from markupsafe import escape
        html = '<br/>'.join(escape(line) for line in (text or '').splitlines())
        self.body = html
        self.state = 'ready'

    def action_send(self):
        self.ensure_one()
        if not self.body:
            raise UserError(_('Email body is empty.'))
        # Always log to the lead's chatter as a record of the AI draft.
        self.lead_id.message_post(
            body=self.body,
            subject=self.subject or _('AI Follow-up'),
            subtype_xmlid='mail.mt_note',
        )
        if self.send_email and self.lead_id.email_from:
            self.env['mail.mail'].sudo().create({
                'subject': self.subject or _('Follow-up'),
                'body_html': self.body,
                'email_to': self.lead_id.email_from,
                'email_from': (
                    self.lead_id.user_id.email_formatted
                    or self.env.user.email_formatted
                ),
                'model': 'crm.lead',
                'res_id': self.lead_id.id,
            }).send()
        return {'type': 'ir.actions.act_window_close'}
