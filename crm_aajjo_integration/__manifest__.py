{
    'name': 'CRM AAJJO Integration',
    'version': '19.0.1.1.0',
    'summary': 'Integrate AAJJO API leads (Data Fetching Only). Automation handled by crm_lead_automation_engine.',
    'description': """
        Integrates AAJJO leads into CRM.
        Dependencies: crm_lead_automation_engine handles automation/duplicates.
    """,
    'author': 'Techmatic Systems',
    'website': 'https://www.techmaticsys.com',
    'category': 'Sales/CRM',
    'depends': ['base', 'crm', 'sale_management', 'crm_lead_automation_engine'],
    'data': [
        'security/ir.model.access.csv',
        'data/ir_cron.xml',
        'views/res_config_settings_views.xml',
        'views/crm_lead_views.xml',
        'views/crm_lead_lost_views.xml',
        'views/res_partner_views.xml',
        'views/aajjo_api_log_views.xml',
        # 'data/mail_templates.xml', # Moved to automation engine
    ],
    'post_init_hook': '_reactivate_aajjo_settings_view',
    'installable': True,
    'application': True,
    'auto_install': False,
    'license': 'LGPL-3',
    'maintainer': 'Techmatic Odoo Team',
    'support': 'info@techmaticsys.com',
    'images': ['static/description/icon.png'],
}
