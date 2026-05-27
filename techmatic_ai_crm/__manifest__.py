# -*- coding: utf-8 -*-
{
    'name': 'Techmatic AI CRM Assistant',
    'version': '19.0.1.0.0',
    'summary': 'AI-powered CRM assistant: lead summarization, scoring, follow-ups, '
               'and natural-language CRM queries (OpenAI / Gemini).',
    'description': """
Techmatic AI CRM Assistant
==========================

Brings an enterprise-grade AI layer into Odoo CRM:

* Configurable AI provider (OpenAI / Gemini) with secure key storage
* Lead AI summarization, AI scoring (Hot / Warm / Cold), follow-up generation
* Activity suggestions on every lead
* Floating OWL assistant panel for natural-language CRM queries
* Modular service layer (easy to plug in WhatsApp / Email / Voice / Local LLMs)
""",
    'category': 'Sales/CRM',
    'author': 'Techmatic Systems',
    'website': 'https://www.techmaticsys.com',
    'license': 'LGPL-3',
    'maintainer': 'Techmatic Odoo Team',
    'support': 'info@techmaticsys.com',
    'depends': [
        'base',
        'web',
        'mail',
        'crm',
        'sales_team',
    ],
    'external_dependencies': {
        # Both libs are optional at install-time; missing ones raise a clean
        # UserError only when the matching provider is actually used.
        'python': ['requests'],
    },
    'data': [
        'security/techmatic_ai_crm_security.xml',
        'security/ir.model.access.csv',
        'data/ir_config_parameter_data.xml',
        'data/ai_prompt_template_data.xml',
        'data/ir_cron_data.xml',
        'views/res_config_settings_views.xml',
        'views/crm_lead_views.xml',
        'views/ai_chat_session_views.xml',
        'views/ai_prompt_template_views.xml',
        'views/ai_daily_briefing_views.xml',
        'views/ai_auto_followup_log_views.xml',
        'views/res_users_views.xml',
        'wizards/ai_followup_wizard_views.xml',
        'wizards/ai_query_wizard_views.xml',
        'views/menus.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'techmatic_ai_crm/static/src/components/**/*.js',
            'techmatic_ai_crm/static/src/components/**/*.xml',
            'techmatic_ai_crm/static/src/components/**/*.scss',
            'techmatic_ai_crm/static/src/services/**/*.js',
        ],
    },
    'installable': True,
    'application': True,
    'auto_install': False,
}
