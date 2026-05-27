# -*- coding: utf-8 -*-
"""Audit trail for AI auto-sent follow-up emails.

Every email the auto-send cron emits — successful or failed — produces
one row here. This is the **only** evidence salespeople and admins have
that the bot acted on their behalf, so it's critical for trust,
compliance, debugging, and reverse-engineering "wait, did we email
this customer last week?" questions.

Never delete rows from this log. Admins can archive instead.
"""
from odoo import fields, models


class AiAutoFollowupLog(models.Model):
    _name = 'techmatic.ai.auto.followup.log'
    _description = 'AI Auto Follow-Up Audit Log'
    _order = 'sent_at desc, id desc'
    _rec_name = 'subject'

    # ``cascade`` rather than ``set null`` because both fields are
    # required — Odoo rejects ``required + set null``. Deleting a lead
    # or user therefore removes that lead/user's audit history; for
    # long-term retention, run a separate archiver before deletion.
    lead_id = fields.Many2one(
        'crm.lead', required=True, ondelete='cascade', index=True,
    )
    user_id = fields.Many2one(
        'res.users', required=True, ondelete='cascade', index=True,
        help='Salesperson on whose behalf the email was sent.',
    )
    partner_id = fields.Many2one(
        'res.partner', ondelete='set null',
        help='Customer who received the email — may be empty if the '
             'lead used a free-text email_from.',
    )
    email_to = fields.Char(required=True)
    subject = fields.Char(required=True)
    body_html = fields.Html(readonly=True, sanitize=True)
    sent_at = fields.Datetime(
        required=True, default=fields.Datetime.now, index=True,
    )
    success = fields.Boolean(default=False, tracking=True)
    error_message = fields.Char()
    # Snapshot the guardrail values at send time so we can later answer
    # "what was the policy when this email went out?" without time-
    # travel queries against ir.config_parameter.
    score_at_send = fields.Integer(help='AI score at the moment of send.')
    days_inactive_at_send = fields.Integer(
        help='How many days inactive the lead was when the cron picked '
             'it up.',
    )

    # ----- Trigger metadata -------------------------------------------
    # 'cold_chase'    — proactive cron, periodic outreach to stale leads
    # 'inbound_reply' — reactive cron, automatic response to a customer
    #                   email arriving in the lead's chatter
    trigger_type = fields.Selection(
        selection=[
            ('cold_chase', 'Cold Chase'),
            ('initial_outreach', 'Initial Outreach'),
            ('inbound_reply', 'Inbound Reply'),
        ],
        default='cold_chase', required=True,
        help='Which AI workflow caused this email to go out.',
    )
    triggered_by_message_id = fields.Many2one(
        'mail.message', ondelete='set null',
        help='For inbound replies, the customer message that triggered '
             'our automated answer. Used by the inbound cron as the '
             '"have we already replied to this?" dedup key.',
    )
