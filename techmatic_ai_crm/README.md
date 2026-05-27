# Techmatic AI CRM Assistant

Production-ready Odoo 19 module that adds an AI layer to the CRM:
lead summarization, AI scoring, follow-up email drafting, activity
suggestions, and a natural-language query assistant. Supports **OpenAI**,
**Google Gemini**, and **Anthropic Claude** out of the box; designed
for clean future extension to WhatsApp, Email-Inbox, Voice, and local
LLMs (Ollama).

---

## Features

| Feature                      | Where to find it                                          |
| ---------------------------- | --------------------------------------------------------- |
| AI provider configuration    | CRM ▸ Configuration ▸ Settings ▸ **AI Assistant** block   |
| Test connection              | Same settings page, **Test Connection** button             |
| Lead AI summary              | CRM lead form header ▸ **Generate AI Summary**             |
| Lead AI scoring (Hot/Warm/Cold) | CRM lead form header ▸ **Score with AI** + nightly cron |
| Follow-up email generator    | CRM lead form header ▸ **Generate Follow-Up**              |
| Activity suggestions         | CRM lead form header ▸ **Suggest Next Actions**            |
| Floating AI chat panel       | Systray icon **AI** (top right) on every backend page      |
| NL CRM query assistant       | CRM ▸ Configuration ▸ AI Assistant ▸ **Ask AI About CRM**  |
| Prompt template editor       | CRM ▸ Configuration ▸ AI Assistant ▸ **Prompt Templates**  |

---

## Installation

1. Copy (or symlink) `techmatic_ai_crm/` into your Odoo `addons` path.
   *Tested against Odoo 19.0; depends only on `crm`, `mail`, `web`,
   `sales_team`.*

2. Install the Python dependencies. `requests` is required (OpenAI /
   Gemini providers); `anthropic` is only needed if you select the
   Claude provider:

   ```bash
   pip install requests             # required
   pip install anthropic            # only for the Claude provider
   ```

3. Restart the Odoo server with developer mode enabled and update the
   apps list:

   ```bash
   ./odoo-bin -c <conf> -u all   # or just -i techmatic_ai_crm on a fresh DB
   ```

4. As an Odoo administrator, open **Settings ▸ Users & Companies ▸ Users**
   and grant either:

   - **AI CRM: User** — sales users (chat + AI buttons on leads).
   - **AI CRM: Administrator** — can also configure API keys, models,
     and prompt templates.

5. Go to **CRM ▸ Configuration ▸ Settings** ▸ **AI Assistant** and fill
   in:

   - Provider (OpenAI / Gemini / Claude)
   - Model:
     - OpenAI: `gpt-4o-mini`, `gpt-4o`
     - Gemini: `gemini-1.5-flash`, `gemini-1.5-pro`
     - Claude: `claude-opus-4-7` (recommended), `claude-sonnet-4-6`,
       `claude-haiku-4-5`
   - API key (`sk-...` for OpenAI, `AIza...` for Gemini, `sk-ant-...`
     for Claude)
   - (optional) Temperature, max tokens, timeout, rate limit
   - (optional) Custom endpoint — e.g. an Azure OpenAI proxy or Ollama
     gateway

   Click **Test Connection** to verify.

   **Note on Claude:** the Claude provider uses the official Anthropic
   Python SDK and requires `pip install anthropic`. It supports
   prompt caching automatically (system-prompt prefix is auto-cached
   when it exceeds the provider's minimum cacheable size — ~4096 tokens
   on Opus 4.7). The `temperature` field is ignored on Opus 4.7 because
   the API removed top-level sampling params on that model.

6. Optionally enable the nightly batch scoring cron under
   **Settings ▸ Technical ▸ Scheduled Actions**:
   *AI CRM: Score Active Leads* (disabled by default).

---

## Architecture

```
techmatic_ai_crm/
├── services/                  # Pure-Python AI layer — no ORM imports here
│   ├── ai_provider.py         # Abstract base: generate_response, summarize,
│   │                          #   generate_email, score_lead
│   ├── openai_provider.py
│   ├── gemini_provider.py
│   ├── claude_provider.py     # Anthropic Claude (official SDK, auto-caching)
│   ├── ai_service.py          # Facade — reads ir.config_parameter,
│   │                          #   instantiates provider, applies rate limit,
│   │                          #   builds lead context dossiers
│   ├── prompt_sanitizer.py    # Strips injection patterns + control chars
│   ├── rate_limiter.py        # In-memory sliding window
│   ├── query_translator.py    # NL → safe ORM domain (allow-list validated)
│   └── exceptions.py
├── models/                    # ORM layer
│   ├── res_config_settings.py # Provider config + Test Connection button
│   ├── crm_lead.py            # ai_summary / ai_score / ai_priority / ai_status
│   ├── ai_chat_session.py     # Per-user assistant chat history
│   ├── ai_chat_message.py
│   └── ai_prompt_template.py  # Editable prompt library
├── wizards/
│   ├── ai_followup_wizard.py  # AI draft → user edits → log/send
│   └── ai_query_wizard.py     # NL query → validated domain → result list
├── controllers/
│   └── ai_controller.py       # JSON endpoints for the OWL panel
├── static/src/
│   ├── components/            # OWL floating assistant panel + SCSS
│   └── services/              # Front-end RPC wrapper
├── views/                     # XML inheritances + standalone views
├── security/                  # Groups, record rules, ir.model.access.csv
└── data/                      # ir.config_parameter defaults, prompts, cron
```

### Adding a new provider

1. Subclass `services.ai_provider.AIProvider` in
   `services/<name>_provider.py` and implement `_chat(messages, **kw)`.
2. Register it in `services/ai_service.py::AIService.PROVIDERS`.
3. Add the provider key to the `techmatic_ai_provider` selection in
   `models/res_config_settings.py`.

Every higher-level method (`summarize`, `generate_email`, `score_lead`,
`chat`) automatically works against the new provider with no further
changes.

### Future-ready hooks

The service layer is provider-agnostic and IO-agnostic, so adding new
channels is purely additive:

- **WhatsApp / Email inbound** — call `AIService(env).chat(...)` from a
  webhook or mail rule and pass the inbound thread as messages.
- **Voice** — same pattern; transcribe upstream, route the text through
  `AIService.generate_response`.
- **Local LLMs (Ollama)** — point the *Custom Endpoint* setting at an
  OpenAI-compatible Ollama gateway and pick an `openai` provider, **or**
  subclass `AIProvider` with the native Ollama transport.

---

## Security

- API keys are stored as `ir.config_parameter` and the settings field is
  visible **only** to members of **AI CRM: Administrator**. Sales users
  can use the assistant but never see the key.
- All inbound prompts are sanitized (control-char strip, injection
  pattern redaction, hard length cap).
- The natural-language query assistant validates every domain triple
  against an allow-list of fields and operators before hitting the ORM.
  Writes/unlinks/exec are categorically rejected.
- Per-user sliding-window rate limit (default 30 calls / minute).
- Record rules restrict each user to their own `techmatic.ai.chat.session`
  / `techmatic.ai.chat.message`; admins see everything.

---

## Sample prompts

Pre-seeded under **Prompt Templates** — admins can edit them without
touching code:

- *Summarize this lead* (`sample.summarize_lead`)
- *Generate follow-up email* (`sample.followup_email`)
- *Which opportunities have been inactive for more than 10 days?* (`sample.inactive_opportunities`)
- *Suggest the next best action and explain why* (`sample.next_action`)

These also appear as one-click chips in the floating assistant panel
when a chat session is empty.

---

## Troubleshooting

| Symptom                                         | Likely cause                                                            |
| ----------------------------------------------- | ----------------------------------------------------------------------- |
| Settings page shows no AI block                 | User not in **AI CRM: Administrator** group.                            |
| Buttons missing on lead form                    | User not in **AI CRM: User** group.                                     |
| `UserError: The 'requests' Python package…`     | `pip install requests` in the same env as the Odoo server.              |
| `UserError: The 'anthropic' Python package…`    | `pip install anthropic` in the same env (only needed for Claude).        |
| `Too many AI requests…`                         | Rate limit hit. Raise it in settings, or wait 60s.                      |
| `Unknown AI provider…`                          | Provider dropdown empty or set to a custom key without a `PROVIDERS` entry. |
| `Unsafe / unsupported query`                    | NL query assistant rejected the spec — see logs for the offending part. |

---

## License

LGPL-3 — see `__manifest__.py` for full metadata.
