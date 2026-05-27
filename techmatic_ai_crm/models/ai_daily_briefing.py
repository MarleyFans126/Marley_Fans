# -*- coding: utf-8 -*-
"""AI-generated daily pipeline briefing — one per user per day.

The cron runs once a day, walks every active AI-CRM user, builds a
categorized snapshot of their pipeline (hot / closing / new / cold /
high-value), asks the LLM to write a concise actionable narrative, and
stores it as a briefing record. The briefing is also posted to the
user's chatter inbox so it shows up alongside their normal Odoo
notifications.

Salespeople can also trigger a fresh briefing on demand from the menu.
"""
import logging

from odoo import api, fields, models, _
from odoo.exceptions import AccessError, UserError

from ..services.ai_service import AIService
from ..services.exceptions import AIError

_logger = logging.getLogger(__name__)


class AiDailyBriefing(models.Model):
    _name = 'techmatic.ai.daily.briefing'
    _description = 'AI Daily Pipeline Briefing'
    _inherit = ['mail.thread']
    _order = 'briefing_date desc, id desc'
    _rec_name = 'title'

    title = fields.Char(required=True, tracking=True)
    user_id = fields.Many2one(
        'res.users', required=True, ondelete='cascade', index=True,
        default=lambda self: self.env.user,
    )
    briefing_date = fields.Date(
        required=True, default=fields.Date.context_today, index=True,
    )
    generated_at = fields.Datetime(default=fields.Datetime.now, readonly=True)
    body_html = fields.Html(readonly=True, sanitize=True)
    lead_count = fields.Integer(readonly=True)
    state = fields.Selection(
        selection=[
            ('draft', 'Draft'),
            ('generated', 'Generated'),
            ('failed', 'Failed'),
        ],
        default='draft', required=True, tracking=True,
    )
    error_message = fields.Char(readonly=True)

    _sql_constraints = [
        ('user_date_unique', 'unique(user_id, briefing_date)',
         'Only one briefing per user per day.'),
    ]

    # ------------------------------------------------------------------
    # Public actions.
    # ------------------------------------------------------------------
    def action_regenerate(self):
        """Regenerate this briefing in-place."""
        self.ensure_one()
        self._check_owner_or_admin()
        try:
            result = AIService(self.env).compose_daily_briefing(self.user_id)
        except AIError as e:
            self.write({'state': 'failed', 'error_message': str(e)[:255]})
            raise UserError(_('Briefing generation failed: %s') % e) from e
        self.write({
            'body_html': result['body_html'],
            'lead_count': result['lead_count'],
            'state': 'generated',
            'generated_at': fields.Datetime.now(),
            'error_message': False,
        })
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Briefing regenerated'),
                'message': _('%s leads covered.') % result['lead_count'],
                'type': 'success',
                'sticky': False,
            },
        }

    @api.model
    def action_generate_my_briefing(self):
        """Menu action: generate (or refresh) today's briefing for the
        current user and open it."""
        today = fields.Date.context_today(self)
        briefing = self.search([
            ('user_id', '=', self.env.uid),
            ('briefing_date', '=', today),
        ], limit=1)
        try:
            result = AIService(self.env).compose_daily_briefing(self.env.user)
        except AIError as e:
            raise UserError(_(
                'Could not generate your briefing: %s'
            ) % e) from e

        vals = {
            'user_id': self.env.uid,
            'briefing_date': today,
            'title': _('Daily Briefing — %s') % today.strftime('%b %d, %Y'),
            'body_html': result['body_html'],
            'lead_count': result['lead_count'],
            'state': 'generated',
            'generated_at': fields.Datetime.now(),
            'error_message': False,
        }
        if briefing:
            briefing.write(vals)
        else:
            briefing = self.create(vals)
        return {
            'type': 'ir.actions.act_window',
            'res_model': self._name,
            'res_id': briefing.id,
            'view_mode': 'form',
            'target': 'current',
        }

    # ------------------------------------------------------------------
    # Cron — runs daily; one briefing per active AI-CRM user.
    # ------------------------------------------------------------------
    @api.model
    def _cron_generate_daily_briefings(self):
        """Generate today's briefing for every user in the AI CRM User
        group who hasn't been briefed yet. Idempotent — safe to re-run.

        One bad user doesn't poison the batch; failures are recorded on
        the briefing row so admins can debug after the fact.
        """
        today = fields.Date.context_today(self)
        group = self.env.ref(
            'techmatic_ai_crm.group_techmatic_ai_crm_user',
            raise_if_not_found=False,
        )
        if not group:
            _logger.warning('AI CRM user group missing — cron skipped.')
            return

        # ``all_user_ids`` includes users who inherit the group via
        # ``implied_ids`` (so admins are covered too).
        users = group.all_user_ids.filtered(lambda u: u.active)

        service = AIService(self.env)
        if not service.is_enabled():
            _logger.info('AI disabled — daily briefing cron skipped.')
            return

        successes = 0
        for user in users:
            existing = self.search([
                ('user_id', '=', user.id),
                ('briefing_date', '=', today),
            ], limit=1)
            if existing and existing.state == 'generated':
                continue

            try:
                # ``AIService`` is a plain Python class, not a
                # recordset, so we can't chain ``.with_context`` on it.
                # ``compose_daily_briefing`` already searches leads as
                # ``sudo()`` filtered by ``user_id`` — that's enough to
                # produce a faithful per-user briefing.
                result = service.compose_daily_briefing(user)
            except AIError as e:
                _logger.warning(
                    'Briefing failed for user %s: %s', user.login, e,
                )
                if existing:
                    existing.write({
                        'state': 'failed',
                        'error_message': str(e)[:255],
                    })
                else:
                    self.create({
                        'user_id': user.id,
                        'briefing_date': today,
                        'title': _('Daily Briefing — %s (failed)') %
                                 today.strftime('%b %d, %Y'),
                        'state': 'failed',
                        'error_message': str(e)[:255],
                    })
                continue

            vals = {
                'body_html': result['body_html'],
                'lead_count': result['lead_count'],
                'state': 'generated',
                'generated_at': fields.Datetime.now(),
                'error_message': False,
            }
            if existing:
                existing.write(vals)
                briefing = existing
            else:
                vals.update({
                    'user_id': user.id,
                    'briefing_date': today,
                    'title': _('Daily Briefing — %s') %
                             today.strftime('%b %d, %Y'),
                })
                briefing = self.create(vals)

            # Post to the user's chatter inbox so the briefing shows up
            # alongside the usual Odoo notifications.
            briefing.message_post(
                body=result['body_html'],
                subject=briefing.title,
                partner_ids=[user.partner_id.id],
                subtype_xmlid='mail.mt_comment',
            )
            successes += 1

        _logger.info(
            'AI daily briefings: %s of %s users briefed.',
            successes, len(users),
        )

    # ------------------------------------------------------------------
    def _check_owner_or_admin(self):
        for rec in self:
            if rec.user_id.id != self.env.uid and not self.env.user.has_group(
                    'techmatic_ai_crm.group_techmatic_ai_crm_admin'):
                raise AccessError(_(
                    'You can only regenerate your own briefings.'
                ))
