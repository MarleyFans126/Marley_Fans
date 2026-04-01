{
    'name': 'Custom Installation Report',
    'version': '19.0.1.0.0',
    'category': 'Sales',
    'summary': 'Installation Order Report with Product Box Details & Site Specifications',
    'description': """
        Custom Installation Report module that generates
        installation order documents including:
        - Sales Representative & Scheduled Date
        - Company Details with GSTIN
        - Site Contact Person & Number
        - Product Model / Box & Quantity / Weight / Terms
        - Box Dimensions, Qty, Weight per unit
        - Site Specifications (rod length, field height, electrical wire, etc.)
        - Footer with company contact info
    """,
    'author': 'Custom',
    'depends': ['sale', 'sale_management'],
    'data': [
        'views/sale_order_views.xml',
        'reports/report_action.xml',
        'reports/report_installation.xml',
    ],
    'installable': True,
    'application': False,
    'license': 'LGPL-3',
}
