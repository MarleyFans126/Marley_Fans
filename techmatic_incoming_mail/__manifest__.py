{
    'name': 'Techmatic Incoming Mail Panel',
    'version': '19.0.1.0.0',
    'summary': 'Panel + alerts for customer email replies on CRM leads',
    'description': """
Techmatic Incoming Mail Panel
=============================
Mirrors every incoming customer email reply (threaded onto a CRM lead by the
mail gateway) into a dedicated, easy-to-scan panel, and alerts the salesperson.

- New "Incoming Mails" menu: list / kanban of replies, unread highlighted.
- Replies still appear in the lead chatter (standard Odoo) — this is an
  additional at-a-glance view.
- When a reply arrives, the lead's salesperson is notified in their inbox.
- Mark read / unread, jump straight to the lead.
""",
    'category': 'Sales/CRM',
    'author': 'Techmatic',
    'website': 'https://www.techmaticsys.com',
    'depends': ['crm', 'mail'],
    'data': [
        'security/ir.model.access.csv',
        'views/techmatic_incoming_mail_views.xml',
    ],
    'installable': True,
    'application': True,
    'auto_install': False,
    'license': 'LGPL-3',
}
