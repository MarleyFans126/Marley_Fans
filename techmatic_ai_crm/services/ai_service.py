# -*- coding: utf-8 -*-
"""Provider-agnostic AI orchestrator.

``AIService`` is the single entry point used by Odoo models / wizards /
controllers. It:

* Reads provider config from ``ir.config_parameter`` (admin-only fields).
* Instantiates the right :class:`AIProvider` subclass.
* Applies a sliding-window rate limit per user.
* Exposes the same high-level methods the providers do, plus convenience
  wrappers that pre-build prompts from records.

Add a new provider in one place::

    PROVIDERS = {
        'openai': OpenAIProvider,
        'gemini': GeminiProvider,
        'ollama': OllamaProvider,   # future
    }
"""
import logging

from odoo import _, fields

from .exceptions import AIConfigurationError, AIError
from .openai_provider import OpenAIProvider
from .gemini_provider import GeminiProvider
from .claude_provider import ClaudeProvider
from .rate_limiter import RateLimiter

_logger = logging.getLogger(__name__)


CONFIG_KEYS = {
    'provider':    'techmatic_ai_crm.provider',
    'api_key':     'techmatic_ai_crm.api_key',
    'model':       'techmatic_ai_crm.model',
    'temperature': 'techmatic_ai_crm.temperature',
    'max_tokens':  'techmatic_ai_crm.max_tokens',
    'timeout':     'techmatic_ai_crm.timeout',
    'endpoint':    'techmatic_ai_crm.endpoint',
    'rate_limit':  'techmatic_ai_crm.rate_limit',  # calls per minute / user
    'enabled':     'techmatic_ai_crm.enabled',
    # --- Auto follow-up guardrails (Flavor 3) -----------------------
    'auto_followup_enabled':       'techmatic_ai_crm.auto_followup_enabled',
    'auto_followup_max_score':     'techmatic_ai_crm.auto_followup_max_score',
    'auto_followup_inactive_days': 'techmatic_ai_crm.auto_followup_inactive_days',
    'auto_followup_per_user_cap':  'techmatic_ai_crm.auto_followup_per_user_cap',
    'auto_followup_skip_tags':     'techmatic_ai_crm.auto_followup_skip_tags',
    # --- Auto-process new leads (background AI on pipeline entry) ---
    'auto_process_enabled':        'techmatic_ai_crm.auto_process_enabled',
    'auto_process_batch_size':     'techmatic_ai_crm.auto_process_batch_size',
    # --- AI Orchestrator (initial outreach + inbound reply loop) ----
    'orchestrator_enabled':         'techmatic_ai_crm.orchestrator_enabled',
    'orchestrator_min_score':       'techmatic_ai_crm.orchestrator_min_score',
    'orchestrator_max_exchanges':   'techmatic_ai_crm.orchestrator_max_exchanges',
    'orchestrator_skip_keywords':   'techmatic_ai_crm.orchestrator_skip_keywords',
}

DEFAULTS = {
    'provider': 'openai',
    'model': 'gpt-4o-mini',
    'temperature': '0.4',
    'max_tokens': '800',
    'timeout': '30',
    'rate_limit': '30',
    'enabled': 'True',
    'auto_followup_enabled':       'False',  # OFF by default — admin opt-in
    'auto_followup_max_score':     '30',     # only cold leads
    'auto_followup_inactive_days': '7',      # don't touch recently-active leads
    'auto_followup_per_user_cap':  '5',      # max emails / user / day
    'auto_followup_skip_tags':     'vip,manual-only,do-not-contact',
    'auto_process_enabled':        'True',   # ON by default — runs automatically
    'auto_process_batch_size':     '20',
    'orchestrator_enabled':         'False',  # OFF by default — high-risk
    'orchestrator_min_score':       '50',     # only outreach to qualifying leads
    'orchestrator_max_exchanges':   '3',      # hand off after 3 round-trips
    'orchestrator_skip_keywords':   'out of office,vacation,auto-reply,auto reply,'
                                    'autoreply,do not reply,donotreply,no-reply,'
                                    'noreply,unsubscribe,bounce,mailer-daemon',
}


class AIService(object):
    """Facade. Construct with ``AIService(env)``.

    The instance is cheap; do not cache across requests — each call to
    :meth:`provider` rebuilds the underlying transport so config edits
    take effect immediately.
    """
    PROVIDERS = {
        'openai': OpenAIProvider,
        'gemini': GeminiProvider,
        'claude': ClaudeProvider,
    }

    _limiter = RateLimiter('techmatic_ai_crm', max_calls=30, window_seconds=60)

    def __init__(self, env):
        self.env = env

    # ------------------------------------------------------------------
    # Config plumbing.
    # ------------------------------------------------------------------
    def _icp(self):
        # ``sudo`` so non-admin sales users can READ provider/model — the
        # API key itself is gated by group-based access on the settings
        # form, never returned to the browser.
        return self.env['ir.config_parameter'].sudo()

    def get_config(self):
        icp = self._icp()
        cfg = {}
        for key, param in CONFIG_KEYS.items():
            cfg[key] = icp.get_param(param, DEFAULTS.get(key, ''))
        cfg['enabled'] = str(cfg.get('enabled', 'True')).lower() == 'true'
        return cfg

    def is_enabled(self):
        cfg = self.get_config()
        return bool(cfg['enabled']) and bool(cfg.get('api_key'))

    def provider(self):
        """Instantiate the configured provider. Raises if misconfigured."""
        cfg = self.get_config()
        if not cfg['enabled']:
            raise AIConfigurationError(_('AI assistant is disabled in settings.'))
        provider_key = (cfg.get('provider') or '').strip().lower()
        cls = self.PROVIDERS.get(provider_key)
        if not cls:
            raise AIConfigurationError(
                _('Unknown AI provider: %s') % provider_key
            )
        return cls(cfg)

    # ------------------------------------------------------------------
    # Rate-limit hook.
    # ------------------------------------------------------------------
    def _check_rate(self):
        cfg = self.get_config()
        try:
            max_calls = int(cfg.get('rate_limit') or 30)
        except (TypeError, ValueError):
            max_calls = 30
        # Mutate the shared limiter's cap — cheap, single int assign.
        self._limiter.max_calls = max_calls
        self._limiter.hit(self.env.uid)

    # ------------------------------------------------------------------
    # High-level helpers used across models / wizards.
    # ------------------------------------------------------------------
    def generate_response(self, user_prompt, system_prompt=None, **kw):
        self._check_rate()
        return self.provider().generate_response(user_prompt, system_prompt, **kw)

    def chat(self, messages, **kw):
        self._check_rate()
        return self.provider().chat(messages, **kw)

    def summarize_lead(self, lead):
        """Build prompt from a ``crm.lead`` record and return summary text."""
        self._check_rate()
        ctx = self._build_lead_context(lead)
        return self.provider().summarize(ctx)

    def score_lead(self, lead):
        """Return ``{'score', 'priority', 'status', 'reason'}`` for a lead."""
        self._check_rate()
        ctx = self._build_lead_context(lead, include_history=True)
        return self.provider().score_lead(ctx)

    def compose_daily_briefing(self, user):
        """Generate a daily pipeline briefing for ``user``.

        The pipeline is categorized **in Python** (hot / closing / new /
        cold / high-value) before the LLM ever sees it. That keeps the
        prompt small, deterministic, and free of LLM-side categorization
        errors — the model only does narrative writing, not classification.

        :returns: ``{'body_html': str, 'lead_count': int}``
        """
        from datetime import timedelta

        self._check_rate()

        Lead = self.env['crm.lead'].sudo()
        today = fields.Date.context_today(Lead)

        # User's open opportunities. Caps at 200 to keep prompt size
        # bounded — a salesperson with more than 200 active leads is a
        # different problem.
        leads = Lead.search([
            ('user_id', '=', user.id),
            ('active', '=', True),
            ('probability', '<', 100),
            ('probability', '>', 0),
        ], limit=200)

        if not leads:
            return {
                'body_html': '<p>%s</p>' % _(
                    'No active opportunities in your pipeline today. '
                    'Time to prospect.'
                ),
                'lead_count': 0,
            }

        # ---- Categorize ----------------------------------------------
        # ``recordset.filtered`` returns disjoint slices we can each
        # truncate to keep the prompt focused. Same lead can legitimately
        # appear in multiple categories (e.g. "hot" + "top value") — we
        # let the LLM dedupe in the narrative.
        hot = leads.filtered(
            lambda lead_: lead_.ai_status == 'Hot' or lead_.probability >= 80
        )[:5]
        closing = leads.filtered(
            lambda lead_: 60 <= lead_.probability < 80
        )[:5]
        # ``date_last_stage_update`` is bumped on stage changes; using
        # it as a freshness proxy avoids depending on mail.message scans.
        cold = leads.filtered(
            lambda lead_: lead_.date_last_stage_update and
            (today - lead_.date_last_stage_update.date()).days >= 10
        )[:8]
        new_leads = leads.filtered(
            lambda lead_: lead_.create_date and
            (today - lead_.create_date.date()).days <= 1
        )[:8]
        high_value = leads.sorted(key='expected_revenue', reverse=True)[:5]

        # ---- Build LLM context ---------------------------------------
        sections = []
        for label, recordset in [
            ('🔥 Hot / High-Probability', hot),
            ('🎯 Closing Soon', closing),
            ('🆕 New (last 24h)', new_leads),
            ('❄️ Cold (10+ days no stage change)', cold),
            ('💰 Top Value', high_value),
        ]:
            if not recordset:
                continue
            lines = []
            for lead_ in recordset:
                lines.append(
                    '- "%s" | Stage: %s | Probability: %s%% | '
                    'Revenue: %s | AI: %s | Last stage update: %s' % (
                        (lead_.name or '-').replace('"', "'")[:80],
                        lead_.stage_id.display_name or '-',
                        int(lead_.probability or 0),
                        int(lead_.expected_revenue or 0),
                        lead_.ai_status or 'N/A',
                        lead_.date_last_stage_update and
                        lead_.date_last_stage_update.strftime('%Y-%m-%d')
                        or 'N/A',
                    )
                )
            sections.append('## %s\n%s' % (label, '\n'.join(lines)))

        if not sections:
            return {
                'body_html': '<p>%s</p>' % _(
                    'You have %s open leads today, but none stood out '
                    'in any focus category. Consider reviewing them.'
                ) % len(leads),
                'lead_count': len(leads),
            }

        context_text = '\n\n'.join(sections)

        sys_p = (
            'You are a CRM briefing assistant. Write a concise, '
            'actionable morning briefing for the salesperson. Output '
            'plain HTML using only these tags: <h3>, <p>, <ul>, <li>, '
            '<b>, <em>, <br>. No <html>, <body>, or <style>. Group leads '
            'by recommended action — start with whichever group needs '
            'the most urgent attention. Reference each lead by name and '
            'end its bullet with one concrete next action (e.g. "Call '
            'today", "Send pricing", "Try a different angle"). Keep the '
            'whole briefing under 350 words. Use 🔥 ❄️ 🆕 ⚠️ 💰 sparingly. '
            'Open with one short sentence framing the day.'
        )
        user_p = (
            'Salesperson: %s\n'
            'Today: %s\n'
            'Total open opportunities: %s\n\n'
            'Categorized snapshot:\n\n%s\n\n'
            'Write the briefing now.'
        ) % (user.name, today.isoformat(), len(leads), context_text)

        body_html = self.provider().generate_response(
            user_p, system_prompt=sys_p, max_tokens=900,
        )
        return {
            'body_html': body_html or '<p>(briefing was empty)</p>',
            'lead_count': len(leads),
        }

    def research_company_from_web(self, lead):
        """Fetch the lead's company website + AI-summarize what they do.

        Returns dict::

            {
                'status':  'completed' | 'skipped' | 'failed',
                'url':     <final URL fetched, or None>,
                'summary': <LLM brief, or empty>,
                'reason':  <why we skipped / what failed>,
            }

        Skip conditions (no API tokens spent):
          * Email is from a free or disposable provider.
          * Email domain is malformed.
        Failure conditions (tokens NOT spent — fetch failed before LLM):
          * Network error / timeout / non-2xx response.
          * Site resolves to a private/loopback IP (SSRF guard).
          * Site returned no extractable text content.

        Completed flow: fetch homepage → strip HTML → LLM produces a
        3-5 sentence brief grounded ONLY in the fetched text.
        """
        from . import web_research

        domain = web_research.domain_from_email(lead.email_from)
        if not domain:
            return {
                'status': 'skipped',
                'url': None, 'summary': '',
                'reason': 'Free/disposable/invalid email domain — '
                          'no company website to research.',
            }

        research = web_research.research_company(domain)
        if not research['success']:
            return {
                'status': 'failed',
                'url': None, 'summary': '',
                'reason': research['error'] or 'Unknown fetch error',
            }

        text = (research['text'] or '').strip()
        if len(text) < 50:
            return {
                'status': 'failed',
                'url': research['url'], 'summary': '',
                'reason': 'Site returned no usable text (likely JS-rendered).',
            }

        # Hand the cleaned text to the model and ask for a short brief
        # grounded ONLY in that text. The system prompt is deliberately
        # strict — no invented facts, no general-knowledge embellishment.
        self._check_rate()
        sys_p = (
            'You write a short company brief for a sales rep from a '
            'snippet of the company\'s public website. Use ONLY what '
            'appears in the supplied text. Do NOT add facts from your '
            'training data even if you "know" the company. If the text '
            'is too sparse to cover one of the points below, skip that '
            'point — do not guess.\n\n'
            'Cover, in flowing prose (3-5 sentences total, no bullets):\n'
            '  1. What the company sells or does (industry / product).\n'
            '  2. Size or scale signals visible in the text (employees, '
            '     offices, customer logos, founding year, etc.).\n'
            '  3. Geographic presence if mentioned.\n'
            '  4. Anything notable for the sales conversation.'
        )
        user_p = (
            'Source URL: %s\n'
            'Domain: %s\n\n'
            'Website content (cleaned to plain text):\n%s\n\n'
            'Write the company brief now.'
        ) % (research['url'], domain, text)
        summary = self.provider().generate_response(
            user_p, system_prompt=sys_p, max_tokens=500,
        )
        return {
            'status': 'completed',
            'url': research['url'],
            'summary': (summary or '').strip(),
            'reason': None,
        }

    def research_lead_legitimacy(self, lead):
        """Decide how trustworthy this lead is before we spend tokens
        emailing them.

        Combines deterministic signals (disposable email blocklist,
        domain class, completeness checks) with an LLM judgement
        layered on top. The LLM never invents facts — it only weights
        the signals we've already collected from the lead.

        :returns: dict with keys::

            verdict        # 'trusted' | 'verified' | 'suspicious' | 'spam'
            score          # int 0-100 (higher = more legitimate)
            notes          # short narrative explaining the verdict
            signals        # the raw signal dict (red/yellow/green flags)
            llm_used       # True if we called the model, False on shortcut

        For obvious cases (disposable email, malformed) we shortcut the
        LLM call entirely — saves tokens and avoids the round-trip.
        """
        import json as _json
        from . import legitimacy

        signals = legitimacy.collect_signals(lead)
        verdict, score, reason = legitimacy.heuristic_verdict(signals)

        # Shortcut: if the heuristic verdict is 'spam' (disposable /
        # malformed), no LLM call needed — these are deterministic.
        if verdict == 'spam':
            return {
                'verdict': verdict,
                'score': score,
                'notes': reason,
                'signals': signals,
                'llm_used': False,
            }

        # For everything else, let the LLM weigh in. It can adjust the
        # score or even override the verdict if it spots something the
        # heuristics missed (e.g. a real-looking domain like
        # "acmecorp.example" that's obviously fake).
        self._check_rate()
        sys_p = (
            'You are a CRM lead-quality auditor. Review the signals '
            'below and decide how legitimate this lead is. Output '
            'STRICT JSON only, no markdown:\n'
            '{\n'
            '  "verdict": "trusted"|"verified"|"suspicious"|"spam",\n'
            '  "score": <int 0-100>,\n'
            '  "notes": "<one short sentence justifying the verdict>"\n'
            '}\n\n'
            'Rules:\n'
            '- Only assign "trusted" if the signals show a corporate '
            '  domain matching a real-sounding company AND complete '
            '  contact info AND specific, non-generic intent.\n'
            '- Assign "suspicious" if multiple key fields are missing '
            '  or the description reads like a template.\n'
            '- Assign "spam" if you detect template language, disposable '
            '  email patterns, or obviously fake data the heuristics '
            '  may have missed (e.g. "Acme Test Test" as company name).\n'
            '- Be calibrated, not paranoid: a gmail.com address is NOT '
            '  spam on its own — many freelancers and small businesses '
            '  use them legitimately.'
        )
        # Pass the raw lead fields plus the precomputed signals.
        user_p = (
            'Lead fields:\n'
            '  Name: %s\n'
            '  Email: %s\n'
            '  Phone: %s\n'
            '  Company: %s\n'
            '  Country: %s\n'
            '  Description: %s\n\n'
            'Heuristic pre-check:\n'
            '  Initial verdict: %s (score %s)\n'
            '  Email class: %s\n'
            '  Red flags: %s\n'
            '  Yellow flags: %s\n'
            '  Green flags: %s\n\n'
            'Issue your final verdict now.'
        ) % (
            lead.name or '-',
            lead.email_from or '-',
            (lead.phone or '') + (getattr(lead, 'mobile', '')
                                  and (' / ' + getattr(lead, 'mobile', ''))
                                  or ''),
            lead.partner_name or (lead.partner_id.name if lead.partner_id else '-'),
            lead.country_id.name or '-',
            (lead.description or '-')[:600],
            verdict, score, signals.get('email_class'),
            signals.get('red_flags'),
            signals.get('yellow_flags'),
            signals.get('green_flags'),
        )

        raw = self.provider().generate_response(
            user_p, system_prompt=sys_p, max_tokens=300,
        )
        parsed = self.provider()._parse_json_blob(raw, default=None)
        if isinstance(parsed, dict):
            llm_verdict = (parsed.get('verdict') or '').lower()
            if llm_verdict in ('trusted', 'verified', 'suspicious', 'spam'):
                verdict = llm_verdict
            try:
                score = max(0, min(100, int(parsed.get('score') or score)))
            except (TypeError, ValueError):
                pass
            notes = (parsed.get('notes') or reason)[:255]
        else:
            notes = reason

        return {
            'verdict': verdict,
            'score': score,
            'notes': notes,
            'signals': signals,
            'llm_used': True,
        }

    def generate_initial_outreach(self, lead):
        """Draft the first outreach email after a lead has been scored.

        This is **gated by score** at the orchestrator level — the
        prompt assumes the lead is already qualified, so the model's
        only job is to write a short, warm opener.

        :returns: dict ``{'body_html', 'subject', 'should_send', 'reason'}``.

        Like :meth:`generate_inbound_reply`, the model is allowed to
        decline (``should_send=False``) — for example if the lead
        context is too thin to write a credible message.
        """
        self._check_rate()
        ctx = self._build_lead_context(lead, include_history=True)
        sys_p = (
            'You are an automated AI sales assistant writing the FIRST '
            'outreach email to a newly-qualified lead. Decide whether '
            'this lead has enough usable context to send a credible, '
            'non-generic opener. Output STRICT JSON, no markdown:\n'
            '{\n'
            '  "should_send": true|false,\n'
            '  "subject":     "<short subject, under 60 chars>",\n'
            '  "body_html":   "<email body as HTML, only <p>, <br>>",\n'
            '  "reason":      "<one short sentence>"\n'
            '}\n\n'
            'should_send=false if any of these apply:\n'
            '- The lead description is missing or empty.\n'
            '- You can\'t name a specific reason to reach out beyond '
            '  "we saw your interest" filler.\n'
            '- The lead\'s context suggests this is a returning customer '
            '  who already has a salesperson — let the human handle it.\n\n'
            'When should_send=true: write 3-5 sentences. Open with a '
            'specific reference to the lead\'s stated interest or need. '
            'Ask exactly ONE concrete question to invite a reply. Sign '
            'off as the salesperson by NAME. No promises, no pricing, '
            'no commitments.'
        )
        user_p = (
            'Lead context (use these facts only):\n%s\n\n'
            'Write the initial outreach now.'
        ) % ctx
        raw = self.provider().generate_response(
            user_p, system_prompt=sys_p, max_tokens=600,
        )
        parsed = self.provider()._parse_json_blob(raw, default=None)
        if not isinstance(parsed, dict):
            return {
                'should_send': False, 'subject': '', 'body_html': '',
                'reason': 'AI returned non-JSON output; safer to skip.',
            }
        return {
            'should_send': bool(parsed.get('should_send')),
            'subject': (str(parsed.get('subject') or '').strip())[:120],
            'body_html': str(parsed.get('body_html') or '').strip(),
            'reason': str(parsed.get('reason') or '')[:200],
        }

    def generate_inbound_reply(self, lead, incoming_message):
        """Draft an automated reply to a customer's inbound email.

        :param lead: ``crm.lead`` record.
        :param incoming_message: ``mail.message`` record — the customer's
            email that triggered this reply.
        :returns: dict ``{'body_html', 'should_send', 'reason'}``.

        The model returns STRICT JSON. If ``should_send`` is False the
        cron logs an "AI deferred — needs human" audit row and posts an
        internal note on the lead's chatter instead of sending anything.
        That keeps the door open for low-confidence cases without
        forcing a bad reply on the customer.
        """
        import json as _json
        self._check_rate()
        from .prompt_sanitizer import sanitize

        lead_ctx = self._build_lead_context(lead, include_history=True)
        customer_body = sanitize(
            incoming_message.body or '',
            max_chars=4000,
            raise_on_block=False,  # never crash on injection in customer email
        )
        # Strip HTML to plain text crudely — the LLM reads plain text
        # better and html2text would be another dep.
        import re
        customer_text = re.sub(r'<[^>]+>', ' ', customer_body)
        customer_text = re.sub(r'\s+', ' ', customer_text).strip()

        sys_p = (
            'You are an automated CRM assistant replying to an incoming '
            'customer email on behalf of the salesperson. Your job is to '
            'decide whether THIS specific email is safe and appropriate '
            'to answer automatically. You MUST reply in STRICT JSON, no '
            'commentary, no markdown:\n'
            '{\n'
            '  "should_send": true|false,\n'
            '  "body_html": "<email body as HTML; use only <p>, <br>>",\n'
            '  "reason": "<one short sentence explaining your decision>"\n'
            '}\n\n'
            'Rules — set should_send=false (and explain) if ANY of these '
            'apply:\n'
            '- The customer is angry, escalating, or threatening churn.\n'
            '- The customer asks about pricing, contracts, legal terms, '
            '  or any commitment.\n'
            '- The customer asks a factual question you can\'t answer '
            '  from the lead context.\n'
            '- The customer is requesting human contact specifically.\n'
            '- You are not at least 90%% confident the reply is correct '
            '  and helpful.\n'
            'When should_send=true, write a short, polite acknowledgement '
            '(2-4 sentences) that buys the salesperson time to follow '
            'up personally, NEVER promises specifics, and signs off as '
            'the salesperson by NAME (no "Dear customer"). Keep body_html '
            'minimal — paragraphs only, no inline styles, no scripts.'
        )
        user_p = (
            'Lead context:\n%s\n\n'
            '=== INCOMING CUSTOMER EMAIL ===\n%s\n=== END ===\n\n'
            'Decide and reply now.'
        ) % (lead_ctx, customer_text)

        raw = self.provider().generate_response(
            user_p, system_prompt=sys_p, max_tokens=600,
        )
        parsed = self.provider()._parse_json_blob(raw, default=None)
        if not isinstance(parsed, dict):
            return {
                'should_send': False,
                'body_html': '',
                'reason': 'AI returned non-JSON output; safer to skip.',
            }
        return {
            'should_send': bool(parsed.get('should_send')),
            'body_html': str(parsed.get('body_html') or '').strip(),
            'reason': str(parsed.get('reason') or '')[:200],
        }

    def generate_followup_email(self, lead, instructions=None):
        self._check_rate()
        ctx = self._build_lead_context(lead, include_history=True)
        if instructions:
            ctx = 'Additional instructions: %s\n\n%s' % (instructions, ctx)
        return self.provider().generate_email(ctx)

    def suggest_activities(self, lead):
        """Return a short list (1-4) of recommended next activities."""
        import json as _json
        self._check_rate()
        ctx = self._build_lead_context(lead)
        sys_p = (
            'Suggest 1-4 concrete next CRM actions for this lead. '
            'Reply as a JSON array of objects: '
            '[{"action": "<call|email|demo|quote|followup>", '
            '"summary": "<one line>", "due_in_days": <int>}]. '
            'No prose, no markdown — JSON only.'
        )
        raw = self.provider().generate_response(ctx, system_prompt=sys_p) or ''
        # Strip optional ``` fences then locate the JSON array.
        text = raw.strip()
        if text.startswith('```'):
            text = text.split('\n', 1)[-1]
            if text.endswith('```'):
                text = text[:-3]
        start, end = text.find('['), text.rfind(']')
        if start == -1 or end == -1 or end < start:
            _logger.warning('suggest_activities: no JSON array in: %r', raw[:200])
            return []
        try:
            data = _json.loads(text[start:end + 1])
        except ValueError as e:
            _logger.warning('suggest_activities parse failed: %s', e)
            return []
        return data if isinstance(data, list) else []

    def test_connection(self):
        """Cheap round-trip used by the settings ``Test Connection`` button."""
        self._check_rate()
        try:
            text = self.provider().generate_response(
                'Reply with the single word: OK',
                system_prompt='Reply with only "OK".',
            )
            ok = 'ok' in (text or '').lower()
            return {'success': ok, 'message': text or 'No response.'}
        except AIError as e:
            return {'success': False, 'message': str(e)}

    # ------------------------------------------------------------------
    # Prompt context builders. Keep these read-only — never mutate the
    # ORM here.
    # ------------------------------------------------------------------
    def _build_lead_context(self, lead, include_history=False):
        """Compact text dossier for a lead, safe to embed in a prompt."""
        from .prompt_sanitizer import sanitize  # local to avoid cycles

        bits = [
            'Lead: %s' % (lead.name or '-'),
            'Stage: %s' % (lead.stage_id.display_name or '-'),
            'Type: %s' % (lead.type or '-'),
            'Probability: %s%%' % (lead.probability or 0),
            'Expected Revenue: %s' % (lead.expected_revenue or 0),
            'Partner: %s' % (lead.partner_id.display_name or '-'),
            'Email: %s' % (lead.email_from or '-'),
            'Phone: %s' % (lead.phone or '-'),
            'Country: %s' % (lead.country_id.name or '-'),
            'Salesperson: %s' % (lead.user_id.name or '-'),
            'Team: %s' % (lead.team_id.name or '-'),
            'Tags: %s' % (', '.join(lead.tag_ids.mapped('name')) or '-'),
            'Source: %s' % (lead.source_id.name or '-'),
            'Description: %s' % (lead.description or '-'),
        ]
        if include_history:
            messages = lead.message_ids.sorted('date')[:10]
            if messages:
                hist = []
                for msg in messages:
                    body = sanitize(msg.body or '', max_chars=400)
                    if body:
                        hist.append('- [%s] %s: %s' % (
                            msg.date and msg.date.strftime('%Y-%m-%d') or '',
                            msg.author_id.name or 'system',
                            body,
                        ))
                if hist:
                    bits.append('Recent Messages:\n' + '\n'.join(hist))

            activities = lead.activity_ids[:10]
            if activities:
                act = ['- %s due %s (assigned %s)' % (
                    a.activity_type_id.name or '-',
                    a.date_deadline or '-',
                    a.user_id.name or '-',
                ) for a in activities]
                bits.append('Open Activities:\n' + '\n'.join(act))

        return sanitize('\n'.join(bits))
