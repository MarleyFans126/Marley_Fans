# -*- coding: utf-8 -*-
from odoo import api, fields, models, _


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    # -------------------------------------------------------------------------
    # CRM Automation Toggle Switches
    # -------------------------------------------------------------------------
    crm_auto_email_enabled = fields.Boolean(
        string='Auto-Send Email on Opportunity Conversion',
        config_parameter='crm_automation.auto_email_enabled',
        help='Automatically send acknowledgment email when a lead is converted to an opportunity.',
    )
    crm_auto_whatsapp_enabled = fields.Boolean(
        string='Auto-Send WhatsApp on Opportunity Conversion',
        config_parameter='crm_automation.auto_whatsapp_enabled',
        help='Automatically send WhatsApp template message when a lead is converted to an opportunity.',
    )

    # -------------------------------------------------------------------------
    # Qualify Stage Automation Toggles
    # -------------------------------------------------------------------------
    crm_qualify_email_enabled = fields.Boolean(
        string='Auto-Send Email on Qualify Stage',
        config_parameter='crm_automation.qualify_email_enabled',
        help='Automatically send email to client with salesperson details when lead moves to Qualify stage.',
    )
    crm_qualify_whatsapp_enabled = fields.Boolean(
        string='Auto-Send WhatsApp on Qualify Stage',
        config_parameter='crm_automation.qualify_whatsapp_enabled',
        help='Automatically send WhatsApp (lead_qualified_notification) to client with salesperson details when lead moves to Qualify stage.',
    )

    # -------------------------------------------------------------------------
    # Incoming Email Forwarding
    # -------------------------------------------------------------------------
    crm_forward_incoming_email = fields.Boolean(
        string='Forward Incoming Customer Emails',
        config_parameter='crm_automation.forward_incoming_email',
        help='When a customer emails a lead (a reply or a fresh email routed to a lead), '
             'forward a copy to the operations mailbox and to the assigned salesperson.',
    )
    crm_forward_ops_email = fields.Char(
        string='Operations Mailbox',
        config_parameter='crm_automation.forward_ops_email',
        help='Fixed address that always receives a copy of every incoming customer email '
             '(e.g. operations@marleyfans.in).',
    )
