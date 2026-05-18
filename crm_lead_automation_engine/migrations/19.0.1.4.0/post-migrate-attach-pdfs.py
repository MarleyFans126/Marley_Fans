"""Migration 19.0.1.4.0 — attach brochure & client-list PDFs to
'New stage mail' template.

The post_init_hook fires only on fresh install, so existing
installations never got the attachments linked. This migration
runs once on upgrade and idempotently links the two PDFs to the
'New stage mail' template (id varies per DB — looked up by XML ID).
"""

import base64
import logging
import os

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    from odoo import api, SUPERUSER_ID

    env = api.Environment(cr, SUPERUSER_ID, {})

    template = env.ref(
        'crm_lead_automation_engine.email_template_new_stage',
        raise_if_not_found=False,
    )
    if not template:
        _logger.warning(
            "[MIGRATE 1.4.0] 'New stage mail' template missing, skipping PDF attach."
        )
        return

    # Resolve the static/attachments folder relative to this migration file:
    # .../crm_lead_automation_engine/migrations/19.0.1.4.0/<this file>
    module_path = os.path.dirname(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    )
    attachments_dir = os.path.join(module_path, 'static', 'attachments')

    pdf_files = [
        ('Latest Brochure - 2026.pdf', 'Latest_Brochure_2026.pdf'),
        ('Marley Client List.pdf', 'Marley_Client_List.pdf'),
    ]

    attachment_ids = []
    for display_name, filename in pdf_files:
        filepath = os.path.join(attachments_dir, filename)
        if not os.path.isfile(filepath):
            _logger.warning("[MIGRATE 1.4.0] PDF missing: %s", filepath)
            continue

        existing = env['ir.attachment'].search([
            ('name', '=', display_name),
            ('res_model', '=', 'mail.template'),
            ('res_id', '=', template.id),
        ], limit=1)

        with open(filepath, 'rb') as f:
            b64_data = base64.b64encode(f.read())

        if existing:
            existing.write({'datas': b64_data})
            attachment_ids.append(existing.id)
            _logger.info(
                "[MIGRATE 1.4.0] Refreshed attachment %s on template %d.",
                display_name, template.id,
            )
        else:
            att = env['ir.attachment'].create({
                'name': display_name,
                'type': 'binary',
                'datas': b64_data,
                'res_model': 'mail.template',
                'res_id': template.id,
                'mimetype': 'application/pdf',
            })
            attachment_ids.append(att.id)
            _logger.info(
                "[MIGRATE 1.4.0] Created attachment %s (id %d) on template %d.",
                display_name, att.id, template.id,
            )

    if attachment_ids:
        template.write({'attachment_ids': [(6, 0, attachment_ids)]})
        _logger.info(
            "[MIGRATE 1.4.0] Linked %d PDF(s) to template '%s' (id %d).",
            len(attachment_ids), template.name, template.id,
        )
