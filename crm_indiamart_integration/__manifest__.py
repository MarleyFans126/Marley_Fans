{
    'name': 'IndiaMART CRM Integration',
    'version': '1.0',
    'summary': 'Integration with IndiaMART for lead generation (Data Fetching Only). Automation via Engine.',
    'description': """
         Integrates IndiaMART leads into Odoo CRM.
         Automation handled by crm_lead_automation_engine.
    """,
    'category': 'Sales/CRM',
    'author': 'Techmatic Systems',
    'website': 'https://www.techmaticsys.com',
    'depends': ['crm', 'mail', 'crm_lead_automation_engine'],
    'data': [
        'security/ir.model.access.csv',
        'data/ir_cron.xml',
        'views/indiamart_config_views.xml',
        'views/crm_lead_views.xml',
        'views/res_config_settings_views.xml',
    ],
    'installable': True,
    'application': True,
    'auto_install': False,
    'license': 'LGPL-3',
    'maintainer': 'Techmatic Odoo Team',
    'support': 'info@techmaticsys.com',
    'images': ['static/description/icon.png'],
}
