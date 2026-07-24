{
    'name': 'Techmatic Incoming Mail Panel',
    'version': '19.0.2.2.0',
    'summary': 'Inbound customer email pipeline for CRM leads: match, capture, forward',
    'description': """
Techmatic Incoming Mail Panel
=============================
Handles every customer email that reaches the mail gateway, end to end.

- Matches the sender to their most recently updated OPEN lead (indexed,
  case-insensitive) so a fresh email never opens a duplicate lead. Won / Lost /
  archived leads are skipped, so a returning customer's new enquiry still
  becomes a new opportunity.
- Unknown senders get a lead created, with the email body as the description.
- The email shows in the lead chatter as a normal customer exchange, with its
  subject, HTML body and attachments intact.
- Every inbound email is mirrored into the "Incoming Mails" panel as an audit
  log: sender, subject, body, attachments, lead, salesperson, status, Message-ID.
- A copy is forwarded to the operations mailbox and to the assigned / secondary
  salesperson, with loop protection (never forwards our own, internal, bounce,
  mailer-daemon or automated mail).

Outbound automation (stage emails, templates, quotations) is untouched.
""",
    'category': 'Sales/CRM',
    'author': 'Techmatic',
    'website': 'https://www.techmaticsys.com',
    'depends': ['crm', 'mail'],
    'data': [
        'security/ir.model.access.csv',
        'data/incoming_mail_params.xml',
        'views/techmatic_incoming_mail_views.xml',
        'views/crm_lead_views.xml',
        'views/res_config_settings_views.xml',
    ],
    'installable': True,
    'application': True,
    'auto_install': False,
    'license': 'LGPL-3',
}
