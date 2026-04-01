{
    'name': 'Marley Manufacturing BOM Kit',
    'version': '19.0.1.0.0',
    'summary': 'Kit (Phantom) BOM configuration for HVLS Fan assemblies',
    'description': 'Configures Manufacturing BOM with Kit concept. Kit auto-explodes on SO confirmation, deducting component stock without manufacturing orders.',
    'category': 'Manufacturing',
    'author': 'Marley Fans',
    'depends': [
        'mrp',
        'sale_mrp',
    ],
    'data': [
        'security/ir.model.access.csv',
        'views/mrp_bom_views.xml',
    ],
    'installable': True,
    'application': False,
    'auto_install': False,
    'license': 'LGPL-3',
}
