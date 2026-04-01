# -*- coding: utf-8 -*-
{
    'name': 'WhatsApp Core Community',
    'version': '19.0.1.0.0',
    'summary': 'WhatsApp Cloud API Integration for Odoo 19 Community (Phase 1)',
    'description': """
        WhatsApp Core Community - Phase 1
        ==================================
        Enterprise-like WhatsApp integration using Meta's WhatsApp Cloud API.

        Features:
        - WhatsApp Business API configuration in Settings
        - Connection test & credential validation
        - Manual message sending (Text, Template, Media)
        - Inbound webhook receiver
        - Message logging with chatter integration
        - Partner-level WhatsApp support
        - Reusable service layer for future automations
    """,
    'author': 'Your Company',
    'category': 'Discuss',
    'depends': ['base', 'mail', 'contacts', 'crm'],

    'data': [
        # Security (must load first)
        'security/ir.model.access.csv',
        'security/whatsapp_security.xml',
        # Data
        'data/whatsapp_data.xml',
        # Views
        'views/res_config_settings_views.xml',
        'views/whatsapp_message_log_views.xml',
        'views/res_partner_views.xml',
        'views/crm_lead_views.xml',
        'views/whatsapp_menus_views.xml',
        'views/whatsapp_template_views.xml',
        # Wizard


        'wizard/whatsapp_send_wizard_views.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'whatsapp_core_community/static/src/css/whatsapp_send_wizard.css',
        ],
    },
    'installable': True,
    'application': True,
    'auto_install': False,
    'license': 'LGPL-3',
    # 'images': ['static/description/icon.png'],
}
