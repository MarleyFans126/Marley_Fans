{
    'name': 'CRM AAJJO Integration',
    'version': '19.0.1.1.0',
    'summary': 'Integrate AAJJO API leads (Data Fetching Only). Automation handled by crm_lead_automation_engine.',
    'description': """
        Integrates AAJJO leads into CRM.
        Dependencies: crm_lead_automation_engine handles automation/duplicates.
    """,
    'author': 'Your Company',
    'website': 'https://www.yourcompany.com',
    'category': 'Sales/CRM',
    'depends': ['base', 'crm', 'sale_management', 'project', 'crm_lead_automation_engine'],
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
    'installable': True,
    'application': True,
    'auto_install': False,
    'license': 'LGPL-3',
    'images': ['static/description/icon.png'],
}
