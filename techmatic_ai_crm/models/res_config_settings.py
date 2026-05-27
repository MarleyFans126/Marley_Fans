# -*- coding: utf-8 -*-
"""CRM Settings extension: AI Provider, model, keys, rate limit."""
import logging

from odoo import api, fields, models, _
from odoo.exceptions import AccessError, UserError

from ..services.ai_service import AIService, CONFIG_KEYS, DEFAULTS

_logger = logging.getLogger(__name__)


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    techmatic_ai_enabled = fields.Boolean(
        string='Enable AI CRM Assistant',
        config_parameter=CONFIG_KEYS['enabled'],
        default=True,
    )
    techmatic_ai_provider = fields.Selection(
        selection=[
            ('openai', 'OpenAI'),
            ('gemini', 'Google Gemini'),
            ('claude', 'Anthropic Claude'),
        ],
        string='AI Provider',
        config_parameter=CONFIG_KEYS['provider'],
        default=DEFAULTS['provider'],
    )
    techmatic_ai_api_key = fields.Char(
        string='API Key',
        config_parameter=CONFIG_KEYS['api_key'],
        help='Stored encrypted-at-rest only if the Postgres instance is '
             'configured to do so. Treat as a secret.',
    )
    techmatic_ai_model = fields.Char(
        string='Model',
        config_parameter=CONFIG_KEYS['model'],
        default=DEFAULTS['model'],
        help='Examples:\n'
             '• OpenAI:   gpt-4o-mini, gpt-4o\n'
             '• Gemini:   gemini-1.5-flash, gemini-1.5-pro\n'
             '• Claude:   claude-opus-4-7 (recommended), claude-sonnet-4-6, '
             'claude-haiku-4-5',
    )
    techmatic_ai_temperature = fields.Float(
        string='Temperature',
        config_parameter=CONFIG_KEYS['temperature'],
        default=float(DEFAULTS['temperature']),
    )
    techmatic_ai_max_tokens = fields.Integer(
        string='Max Tokens',
        config_parameter=CONFIG_KEYS['max_tokens'],
        default=int(DEFAULTS['max_tokens']),
    )
    techmatic_ai_timeout = fields.Integer(
        string='Timeout (s)',
        config_parameter=CONFIG_KEYS['timeout'],
        default=int(DEFAULTS['timeout']),
    )
    techmatic_ai_rate_limit = fields.Integer(
        string='Rate Limit (calls/min/user)',
        config_parameter=CONFIG_KEYS['rate_limit'],
        default=int(DEFAULTS['rate_limit']),
    )
    techmatic_ai_endpoint = fields.Char(
        string='Custom Endpoint',
        config_parameter=CONFIG_KEYS['endpoint'],
        help='Leave empty to use the provider default. Useful for Azure '
             'OpenAI proxies or self-hosted Ollama-compatible gateways.',
    )

    # ----- Auto-process new leads (background, no human action needed)
    techmatic_ai_auto_process_enabled = fields.Boolean(
        string='Auto-Process New Leads',
        config_parameter=CONFIG_KEYS['auto_process_enabled'],
        default=True,
        help='When ON, a background cron automatically runs AI summary, '
             'scoring, and activity suggestions for every new lead that '
             'enters the pipeline. Sales reps see results immediately '
             'without clicking any buttons. The cron schedule is set '
             'under Settings > Technical > Scheduled Actions > AI CRM: '
             'Auto-Process Pending Leads. Default: ON.',
    )
    techmatic_ai_auto_process_batch_size = fields.Integer(
        string='Auto-Process Batch Size',
        config_parameter=CONFIG_KEYS['auto_process_batch_size'],
        default=20,
        help='Max number of leads the auto-process cron handles per '
             'run. Tune higher for bulk-import scenarios, lower to '
             'bound API costs per minute. Capped at 100.',
    )

    # ----- AI Orchestrator (the full agent: outreach + reply loop) --
    techmatic_ai_orchestrator_enabled = fields.Boolean(
        string='Enable AI Orchestrator',
        config_parameter=CONFIG_KEYS['orchestrator_enabled'],
        default=False,
        help='HIGH-RISK. When ON, the AI orchestrator runs the full '
             'lead lifecycle: after a lead is scored, it sends the '
             'initial outreach, watches for customer replies, and '
             'responds — without any human click. Each customer-facing '
             'email goes out under the salesperson\'s name. Per-user '
             'opt-in is also required.',
    )
    techmatic_ai_orchestrator_min_score = fields.Integer(
        string='Orchestrator: Min Score for Outreach',
        config_parameter=CONFIG_KEYS['orchestrator_min_score'],
        default=50,
        help='The orchestrator only sends an initial outreach if the '
             'lead\'s AI score is at or above this. Default 50.',
    )
    techmatic_ai_orchestrator_max_exchanges = fields.Integer(
        string='Orchestrator: Max Exchanges per Lead',
        config_parameter=CONFIG_KEYS['orchestrator_max_exchanges'],
        default=3,
        help='After this many round-trips, AI hands the conversation '
             'off to the salesperson. Default 3. Capped at 10.',
    )
    techmatic_ai_orchestrator_skip_keywords = fields.Char(
        string='Orchestrator: Skip Keywords',
        config_parameter=CONFIG_KEYS['orchestrator_skip_keywords'],
        default='out of office,vacation,auto-reply,auto reply,autoreply,'
                'do not reply,donotreply,no-reply,noreply,unsubscribe,'
                'bounce,mailer-daemon',
        help='Comma-separated. If an inbound message contains any of '
             'these strings, AI immediately hands the lead off — '
             'protects against auto-reply loops and unsubscribe storms.',
    )

    # ----- Auto follow-up (Flavor 3) ----------------------------------
    techmatic_ai_auto_followup_enabled = fields.Boolean(
        string='Enable Auto Follow-Up Emails',
        config_parameter=CONFIG_KEYS['auto_followup_enabled'],
        default=False,
        help='HIGH-RISK FEATURE. When ON, a daily cron generates and '
             'AUTOMATICALLY SENDS follow-up emails to cold leads with '
             'no human review. Use the guardrails below to bound the '
             'blast radius. Per-user opt-in is also required.',
    )
    techmatic_ai_auto_followup_max_score = fields.Integer(
        string='Auto Follow-Up: Max AI Score',
        config_parameter=CONFIG_KEYS['auto_followup_max_score'],
        default=30,
        help='Leads with AI score above this are SKIPPED. Default 30 = '
             'only cold leads. Setting this above 50 is not recommended.',
    )
    techmatic_ai_auto_followup_inactive_days = fields.Integer(
        string='Auto Follow-Up: Inactivity Threshold (days)',
        config_parameter=CONFIG_KEYS['auto_followup_inactive_days'],
        default=7,
        help='Leads modified within the last N days are SKIPPED — '
             'a salesperson is already working them.',
    )
    techmatic_ai_auto_followup_per_user_cap = fields.Integer(
        string='Auto Follow-Up: Max Emails / User / Day',
        config_parameter=CONFIG_KEYS['auto_followup_per_user_cap'],
        default=5,
        help='Hard cap on how many leads each salesperson\'s pipeline '
             'can auto-email per day. Stops a misconfigured cron from '
             'spamming the customer base.',
    )
    techmatic_ai_auto_followup_skip_tags = fields.Char(
        string='Auto Follow-Up: Skip Tags',
        config_parameter=CONFIG_KEYS['auto_followup_skip_tags'],
        default='vip,manual-only,do-not-contact',
        help='Comma-separated tag names. Any lead with one of these '
             'tags is SKIPPED. Defaults: vip, manual-only, '
             'do-not-contact.',
    )

    def _check_admin(self):
        """Settings page is already group-gated, but defense in depth."""
        if not self.env.user.has_group(
                'techmatic_ai_crm.group_techmatic_ai_crm_admin'):
            raise AccessError(_(
                'Only AI CRM Administrators can change these settings.'
            ))

    def set_values(self):
        self._check_admin()
        return super().set_values()

    def action_test_ai_connection(self):
        """Used by the ``Test Connection`` button on the settings form."""
        self.ensure_one()
        self._check_admin()
        # Persist the current form values before testing so the service
        # reads the freshly entered API key.
        self.set_values()
        result = AIService(self.env).test_connection()
        if result.get('success'):
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('AI Connection OK'),
                    'message': _('Provider responded: %s') % result['message'],
                    'type': 'success',
                    'sticky': False,
                },
            }
        raise UserError(_(
            'AI connection test failed:\n%s'
        ) % result.get('message') or _('Unknown error'))
