# -*- coding: utf-8 -*-
import logging
from odoo import models, fields, api, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class LeadMergeWizard(models.TransientModel):
    _name = 'x.lead.merge.wizard'
    _description = 'Lead Merge Wizard'

    x_lead_original_id = fields.Many2one(
        'crm.lead', string='Original Lead', required=True, readonly=True)
    x_lead_duplicate_id = fields.Many2one(
        'crm.lead', string='Duplicate Lead', required=True, readonly=True)

    currency_id = fields.Many2one('res.currency', default=lambda self: self.env.company.currency_id)

    # Display fields from Original
    x_orig_contact = fields.Char(related='x_lead_original_id.contact_name', string='Contact (Original)', readonly=True)
    x_orig_email = fields.Char(related='x_lead_original_id.email_from', string='Email (Original)', readonly=True)
    x_orig_mobile = fields.Char(related='x_lead_original_id.phone', string='Phone (Original)', readonly=True)
    x_orig_revenue = fields.Monetary(related='x_lead_original_id.expected_revenue', string='Revenue (Original)', readonly=True, currency_field='currency_id')
    x_orig_description = fields.Html(related='x_lead_original_id.description', string='Description (Original)', readonly=True)
    x_orig_source = fields.Char(related='x_lead_original_id.source_id.name', string='Source (Original)', readonly=True)

    # Display fields from Duplicate
    x_dup_contact = fields.Char(related='x_lead_duplicate_id.contact_name', string='Contact (Duplicate)', readonly=True)
    x_dup_email = fields.Char(related='x_lead_duplicate_id.email_from', string='Email (Duplicate)', readonly=True)
    x_dup_mobile = fields.Char(related='x_lead_duplicate_id.phone', string='Phone (Duplicate)', readonly=True)
    x_dup_revenue = fields.Monetary(related='x_lead_duplicate_id.expected_revenue', string='Revenue (Duplicate)', readonly=True, currency_field='currency_id')
    x_dup_description = fields.Html(related='x_lead_duplicate_id.description', string='Description (Duplicate)', readonly=True)
    x_dup_source = fields.Char(related='x_lead_duplicate_id.source_id.name', string='Source (Duplicate)', readonly=True)

    # User's choice: which one to keep
    x_keep_lead = fields.Selection([
        ('original', 'Keep Original Lead'),
        ('duplicate', 'Keep Duplicate Lead'),
    ], string='Lead to Keep', required=True, default='original')

    def action_merge_leads(self):
        """Merge duplicate into primary: move messages, activities, archive loser."""
        self.ensure_one()

        original = self.x_lead_original_id
        duplicate = self.x_lead_duplicate_id

        if not original or not duplicate:
            raise UserError(_('Both leads must be set to perform merge.'))

        if original.id == duplicate.id:
            raise UserError(_('Cannot merge a lead with itself.'))

        # Determine primary (keep) and secondary (archive)
        if self.x_keep_lead == 'original':
            primary = original
            secondary = duplicate
        else:
            primary = duplicate
            secondary = original

        _logger.info(
            '[MERGE] Merging Lead %s into Lead %s (keeping %s)',
            secondary.id, primary.id, primary.id)

        # 1. Move mail.message records from secondary to primary
        messages = self.env['mail.message'].sudo().search([
            ('res_id', '=', secondary.id),
            ('model', '=', 'crm.lead'),
        ])
        if messages:
            messages.write({'res_id': primary.id})
            _logger.info('[MERGE] Moved %d messages from Lead %s to Lead %s',
                         len(messages), secondary.id, primary.id)

        # 2. Move mail.activity records from secondary to primary
        activities = self.env['mail.activity'].sudo().search([
            ('res_id', '=', secondary.id),
            ('res_model', '=', 'crm.lead'),
        ])
        if activities:
            activities.write({'res_id': primary.id})
            _logger.info('[MERGE] Moved %d activities from Lead %s to Lead %s',
                         len(activities), secondary.id, primary.id)

        # 3. Merge key fields: if primary is missing data, take from secondary
        merge_fields = [
            'email_from', 'phone', 'contact_name',
            'partner_name', 'expected_revenue', 'description',
        ]
        update_vals = {}
        for f in merge_fields:
            primary_val = getattr(primary, f, False)
            secondary_val = getattr(secondary, f, False)
            if not primary_val and secondary_val:
                update_vals[f] = secondary_val

        # Take higher expected revenue
        if (secondary.expected_revenue or 0) > (primary.expected_revenue or 0):
            update_vals['expected_revenue'] = secondary.expected_revenue

        if update_vals:
            primary.write(update_vals)

        # 4. Archive the secondary lead (NEVER delete)
        secondary.write({'active': False})

        # 5. Clear duplicate flags on primary
        try:
            primary.write({
                'x_duplicate_of': False,
            })
            if hasattr(primary, 'duplicate_flag'):
                primary.write({'duplicate_flag': False})
        except Exception:
            pass

        # 6. Log merge in chatter on primary
        primary.message_post(
            body=_(
                'Lead merged: Lead #%s (%s) was merged into this lead. '
                'Messages, activities, and missing data transferred. '
                'The duplicate lead has been archived.'
            ) % (secondary.id, secondary.name or 'Unnamed'),
            message_type='comment',
            subtype_xmlid='mail.mt_note',
        )

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Leads Merged Successfully'),
                'message': _('Lead #%s merged into Lead #%s. Duplicate archived.') % (
                    secondary.id, primary.id),
                'type': 'success',
                'sticky': False,
                'next': {'type': 'ir.actions.act_window_close'},
            },
        }
