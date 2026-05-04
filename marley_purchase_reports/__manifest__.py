{
    'name': 'Marley Purchase Reports',
    'version': '19.0.1.0.0',
    'summary': 'Custom Purchase Order print layout for Marley Fans (matches Quotation style)',
    'description': 'QWeb report template for Purchase Orders that mirrors the Marley Quotation '
                   'layout: red header rule, Marley logo, 3-column footer with Website/CIN/GSTIN, '
                   'light-red product table, totals, terms & delivery.',
    'category': 'Purchases',
    'author': 'Techmatic Systems',
    'website': 'https://www.techmaticsys.com',
    'depends': [
        'purchase',
        'marley_sale_reports',
    ],
    'data': [
        'report/purchase_order_report.xml',
        'report/purchase_order_template.xml',
        'report/purchase_order_document_override.xml',
        'views/purchase_order_views.xml',
    ],
    'installable': True,
    'application': False,
    'auto_install': False,
    'license': 'LGPL-3',
    'maintainer': 'Techmatic Odoo Team',
    'support': 'info@techmaticsys.com',
}
