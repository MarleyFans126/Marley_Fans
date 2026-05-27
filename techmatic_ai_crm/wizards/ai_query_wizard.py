# -*- coding: utf-8 -*-
"""Natural-language CRM query assistant wizard.

User types a plain-English question. We:

1. Ask the LLM to emit a STRICT JSON spec (see
   :mod:`techmatic_ai_crm.services.query_translator`).
2. Validate the spec against an allow-list — operators, fields, model.
3. Execute the resulting ORM search and return the hits as a tree view.
"""
import json
import logging

from odoo import api, fields, models, _
from odoo.exceptions import UserError

from ..services.ai_service import AIService
from ..services.exceptions import AIError, AIUnsafeQueryError
from ..services import query_translator

_logger = logging.getLogger(__name__)


class AiQueryWizard(models.TransientModel):
    _name = 'techmatic.ai.query.wizard'
    _description = 'AI CRM Query Assistant'

    question = fields.Char(
        required=True,
        help='Plain English. Examples: "show leads inactive for 10 days", '
             '"high-value opportunities closing this month".',
    )
    explanation = fields.Text(readonly=True)
    spec_json = fields.Text(readonly=True, help='Validated query spec.')
    result_count = fields.Integer(readonly=True)
    state = fields.Selection(
        selection=[('draft', 'Draft'), ('done', 'Done'), ('error', 'Error')],
        default='draft',
    )
    error_message = fields.Char(readonly=True)

    def action_run(self):
        self.ensure_one()
        if not (self.question or '').strip():
            raise UserError(_('Please enter a question.'))

        service = AIService(self.env)
        try:
            raw = service.generate_response(
                query_translator.build_translator_prompt(self.question),
                system_prompt=(
                    'You translate sales questions into strict JSON query '
                    'specs. Output JSON only.'
                ),
            )
        except AIError as e:
            self.write({'state': 'error', 'error_message': str(e)})
            raise UserError(_('AI error: %s') % e) from e

        try:
            spec = query_translator.parse_spec(raw)
            validated = query_translator.validate_spec(spec)
        except AIUnsafeQueryError as e:
            self.write({'state': 'error', 'error_message': str(e)})
            raise UserError(_('Unsafe / unsupported query: %s') % e) from e

        Model = self.env[validated['model']]
        # Final defense in depth: enforce read access via the standard
        # ACL — never sudo.
        try:
            records = Model.search(
                validated['domain'],
                limit=validated['limit'],
                order=validated['order'],
            )
        except Exception as e:  # noqa: BLE001 — ORM raises many types
            self.write({'state': 'error', 'error_message': str(e)})
            raise UserError(_('Search failed: %s') % e) from e

        self.write({
            'spec_json': json.dumps(validated, indent=2, default=str),
            'result_count': len(records),
            'state': 'done',
            'explanation': _(
                'AI matched %s record(s). Domain: %s'
            ) % (len(records), validated['domain']),
        })

        action = self.env['ir.actions.act_window']._for_xml_id(
            'crm.crm_lead_all_leads',
        )
        action.update({
            'name': _('AI Query Results'),
            'domain': [('id', 'in', records.ids)],
            'context': {'create': False},
            'target': 'main',
        })
        return action
