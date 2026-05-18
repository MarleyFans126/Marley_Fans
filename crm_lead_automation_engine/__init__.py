from . import models

import base64
import logging
import os

_logger = logging.getLogger(__name__)


def _post_init_update_acknowledgment_template(env):
    """Post-init hook: cleanup stale views and attach PDFs to New stage template."""
    env['crm.lead'].init()
    _attach_pdfs_to_new_template(env)


def _attach_pdfs_to_new_template(env):
    """Attach brochure and client-list PDFs to the 'New stage mail' template only.

    Per product decision: brochure + client list go out only with the first
    (New stage) introduction email — later stage emails (Qualify, Proposition,
    Won) do not include these PDFs.
    """
    template = env.ref(
        'crm_lead_automation_engine.email_template_new_stage',
        raise_if_not_found=False,
    )
    if not template:
        _logger.warning("[INIT] New stage mail template not found, skipping PDF attach.")
        return

    module_path = os.path.dirname(os.path.abspath(__file__))
    attachments_dir = os.path.join(module_path, 'static', 'attachments')

    pdf_files = [
        ('Latest Brochure - 2026.pdf', 'Latest_Brochure_2026.pdf'),
        ('Marley Client List.pdf', 'Marley_Client_List.pdf'),
    ]

    attachment_ids = []
    for display_name, filename in pdf_files:
        filepath = os.path.join(attachments_dir, filename)
        if not os.path.isfile(filepath):
            _logger.warning("[INIT] PDF not found: %s", filepath)
            continue

        # Check if attachment already exists for this template
        existing = env['ir.attachment'].search([
            ('name', '=', display_name),
            ('res_model', '=', 'mail.template'),
            ('res_id', '=', template.id),
        ], limit=1)

        if existing:
            # Update with latest file content
            with open(filepath, 'rb') as f:
                existing.write({'datas': base64.b64encode(f.read())})
            attachment_ids.append(existing.id)
            _logger.info("[INIT] Updated existing attachment: %s", display_name)
        else:
            with open(filepath, 'rb') as f:
                att = env['ir.attachment'].create({
                    'name': display_name,
                    'type': 'binary',
                    'datas': base64.b64encode(f.read()),
                    'res_model': 'mail.template',
                    'res_id': template.id,
                    'mimetype': 'application/pdf',
                })
            attachment_ids.append(att.id)
            _logger.info("[INIT] Created attachment: %s (ID %d)", display_name, att.id)

    if attachment_ids:
        # Set attachments on template (replace to avoid stale duplicates)
        template.write({'attachment_ids': [(6, 0, attachment_ids)]})
        _logger.info(
            "[INIT] Linked %d PDF attachment(s) to 'New stage mail' template.",
            len(attachment_ids),
        )
