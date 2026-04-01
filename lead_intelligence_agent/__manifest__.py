{
    'name': 'Lead Intelligence Agent',
    'version': '19.0.1.0.0',
    'summary': 'Auto-enrich, score, and prioritize CRM leads for Marley Fans',
    'description': """
        Lead Intelligence Agent — Techmatic Systems
        =============================================
        Sits on top of existing CRM setup (IndiaMart, Aajjo, WhatsApp, Email automation).
        - GST-based lead enrichment
        - Weighted lead scoring engine (0-100, grades A/B/C/D)
        - Lead priority dashboard / scoreboard
        - Enhanced duplicate detection with merge wizard
        - City tier master data for geographic scoring
    """,
    'author': 'Techmatic Systems',
    'website': 'https://www.techmatics.in',
    'category': 'Sales/CRM',
    'depends': ['crm', 'mail'],
    'data': [
        'security/ir.model.access.csv',
        'data/city_tier_data.xml',
        'data/scoring_defaults.xml',
        'views/city_tier_views.xml',
        'views/scoring_config_views.xml',
        'views/crm_lead_views.xml',
        'views/lead_dashboard_views.xml',
        'wizard/lead_merge_wizard_views.xml',
        'views/res_config_settings_views.xml',
    ],
    'installable': True,
    'application': False,
    'license': 'LGPL-3',
}
