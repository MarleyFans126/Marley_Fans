{
    'name': 'Marley Account Customization',
    'version': '19.0.1.0.0',
    'summary': 'Cash receipt entry, outstanding management, and proforma invoice linking',
    'description': 'Adds Cash Receipt menu, customer outstanding views, and proforma invoice linking for Marley Fans.',
    'category': 'Accounting',
    'author': 'Techmatic Systems',
    'website': 'https://www.techmaticsys.com',
    'depends': [
        'account',
    ],
    'data': [
        'security/ir.model.access.csv',
        'views/account_payment_views.xml',
        'views/account_move_views.xml',
    ],
    'installable': True,
    'application': False,
    'auto_install': False,
    'license': 'LGPL-3',
    'maintainer': 'Techmatic Odoo Team',
    'support': 'info@techmaticsys.com',
}
