{
    'name': 'CRM Lead Automation Engine',
    'version': '19.0.1.5.0',
    'summary': 'Centralized automation for CRM leads (Email, WhatsApp, Stage Logic)',
    'description': """
        Handles all CRM automation independent of lead source:
        - Lead Creation: Auto-acknowledgment (Email/WhatsApp)
        - Duplicate Detection: Based on Mobile/Email
        - Stage Changes: Notifications (New -> Qualify)
        - Won/Lost Logic
    """,
    'author': 'Techmatic Systems',
    'website': 'https://www.techmaticsys.com',
    'depends': ['crm', 'mail', 'sale_management', 'base_automation'],
    'data': [
        'security/ir.model.access.csv',
        'data/business_location_data.xml',
        'data/email_templates.xml',
        'data/stage_email_automation.xml',
        'data/debug_actions.xml',
        'views/business_location_views.xml',
        'views/res_partner_views.xml',
        'views/crm_lead_views.xml',
        'views/crm_email_log_views.xml',
        'views/whatsapp_bulk_wizard_views.xml',
        'views/res_config_settings_views.xml',
    ],
    'post_init_hook': '_post_init_update_acknowledgment_template',
    'installable': True,
    'application': False,
    'license': 'LGPL-3',
    'maintainer': 'Techmatic Odoo Team',
    'support': 'info@techmaticsys.com',
}


