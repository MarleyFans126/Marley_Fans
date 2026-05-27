# -*- coding: utf-8 -*-
"""Lead legitimacy / company research.

Combines deterministic Python heuristics (disposable-email blocklist,
domain class, format checks) with an LLM judgement call. The signals
collected from Python are fed to the LLM as structured input — the
model doesn't invent facts, it only assigns weight to known signals.

Output verdicts:
    trusted    — corporate domain + complete info + specific intent
    verified   — public-domain email but otherwise legitimate-looking
    suspicious — missing critical data, generic intent, or weak signals
    spam       — disposable email, obvious template spam, or red flags

This is **not** a real-time WHOIS / domain reputation service. It's a
cheap, offline filter that catches the easy cases before the
orchestrator spends API tokens emailing low-quality leads. For
production-grade enrichment, plug in Hunter.io / Apollo / Clearbit
upstream of this — those go in :class:`AIService` as separate
providers.
"""
import re

# Common free email providers — legitimate, but worth flagging for
# B2B targeting. A gmail.com address isn't *spam*, it's just lower
# trust than a corporate domain.
_FREE_PROVIDERS = {
    'gmail.com', 'googlemail.com', 'yahoo.com', 'yahoo.co.uk',
    'yahoo.co.in', 'hotmail.com', 'hotmail.co.uk', 'outlook.com',
    'live.com', 'msn.com', 'icloud.com', 'me.com', 'mac.com',
    'aol.com', 'protonmail.com', 'proton.me', 'gmx.com', 'gmx.net',
    'mail.com', 'zoho.com', 'yandex.com', 'yandex.ru',
}

# Throwaway / disposable email services. Hard red flag — these are
# almost always used to evade tracking or send junk leads.
_DISPOSABLE_PROVIDERS = {
    'mailinator.com', 'guerrillamail.com', 'guerrillamail.net',
    '10minutemail.com', 'tempmail.com', 'temp-mail.org', 'throwaway.email',
    'trashmail.com', 'yopmail.com', 'maildrop.cc', 'getairmail.com',
    'sharklasers.com', 'dispostable.com', 'fakeinbox.com',
    'mintemail.com', 'mohmal.com', 'mytemp.email', 'mailcatch.com',
    'spambox.us', 'tempmailaddress.com', 'mailnesia.com',
    'getnada.com', 'inboxbear.com', 'tempr.email',
    # The common "examplee.com" typo of "example.com" that test data uses.
    'examplee.com', 'example.com', 'test.com', 'fake.com',
}

# Generic intent phrases — these alone don't make a lead bad, but
# when paired with other weak signals they push the verdict down.
_GENERIC_PHRASES = (
    'interested in your services', 'looking for more info',
    'please contact me', 'tell me more', 'just curious',
    'i want to know', 'lorem ipsum', 'test test', 'asdf',
)

_EMAIL_RE = re.compile(r'^[^@\s]+@[^@\s.]+(\.[^@\s.]+)+$')
_PHONE_DIGITS_RE = re.compile(r'\d')


def collect_signals(lead):
    """Run all deterministic checks. Returns a dict the LLM can read.

    No network calls, no external deps. Idempotent.
    """
    signals = {
        'red_flags': [],     # strong negatives — each pushes toward 'spam'
        'yellow_flags': [],  # weak negatives — push toward 'suspicious'
        'green_flags': [],   # positives — push toward 'verified'/'trusted'
        'email_class': None,
        'domain': None,
        'has_phone': False,
        'has_company': False,
        'has_country': False,
        'description_length': 0,
        'description_generic': False,
    }

    # ----- Email -------------------------------------------------------
    email = (lead.email_from or '').strip().lower()
    if not email:
        signals['red_flags'].append('no_email_address')
        signals['email_class'] = 'missing'
    elif not _EMAIL_RE.match(email):
        signals['red_flags'].append('malformed_email')
        signals['email_class'] = 'malformed'
    else:
        domain = email.rsplit('@', 1)[-1]
        signals['domain'] = domain
        if domain in _DISPOSABLE_PROVIDERS:
            signals['red_flags'].append('disposable_email_provider')
            signals['email_class'] = 'disposable'
        elif domain in _FREE_PROVIDERS:
            signals['yellow_flags'].append('free_email_provider')
            signals['email_class'] = 'free'
        else:
            signals['green_flags'].append('corporate_email_domain')
            signals['email_class'] = 'corporate'

    # ----- Phone -------------------------------------------------------
    # ``crm.lead`` has ``phone`` (and ``mobile`` only in some modules
    # like base_setup / contacts); use getattr so we don't crash.
    phone_text = (lead.phone or '') + (getattr(lead, 'mobile', '') or '')
    digit_count = len(_PHONE_DIGITS_RE.findall(phone_text))
    if digit_count == 0:
        signals['yellow_flags'].append('no_phone_provided')
    elif digit_count < 7:
        signals['yellow_flags'].append('phone_too_short')
    else:
        signals['has_phone'] = True
        signals['green_flags'].append('plausible_phone_number')

    # ----- Company / partner -------------------------------------------
    company = (lead.partner_name or '').strip() or (
        lead.partner_id.name if lead.partner_id else ''
    )
    if not company:
        signals['yellow_flags'].append('no_company_name')
    else:
        signals['has_company'] = True
        signals['green_flags'].append('company_name_provided')
        # Email domain matches company name → strong trust signal.
        if signals.get('domain') and signals['email_class'] == 'corporate':
            cname = re.sub(r'[^a-z0-9]', '', company.lower())
            dname = signals['domain'].split('.')[0]
            if cname and dname and (cname in dname or dname in cname):
                signals['green_flags'].append('email_domain_matches_company')

    # ----- Country -----------------------------------------------------
    if lead.country_id:
        signals['has_country'] = True
        signals['green_flags'].append('country_specified')
    else:
        signals['yellow_flags'].append('no_country')

    # ----- Description quality -----------------------------------------
    desc = (lead.description or '').strip()
    # Strip HTML if present.
    desc_plain = re.sub(r'<[^>]+>', ' ', desc)
    desc_plain = re.sub(r'\s+', ' ', desc_plain).strip()
    signals['description_length'] = len(desc_plain)
    desc_lower = desc_plain.lower()
    if len(desc_plain) < 20:
        signals['yellow_flags'].append('description_too_short')
    if any(phrase in desc_lower for phrase in _GENERIC_PHRASES):
        signals['yellow_flags'].append('generic_template_language')
        signals['description_generic'] = True
    if len(desc_plain) >= 50 and not signals['description_generic']:
        signals['green_flags'].append('specific_description')

    return signals


def heuristic_verdict(signals):
    """Initial verdict purely from the deterministic signals.

    The LLM is given this as a starting point — it can override but
    rarely should. This means we don't need the LLM at all for the
    obvious cases (disposable email = spam, full of green flags =
    trusted).

    Returns: (verdict, score 0-100, reason)
    """
    reds = len(signals['red_flags'])
    yellows = len(signals['yellow_flags'])
    greens = len(signals['green_flags'])

    # Hardest signals first.
    if 'disposable_email_provider' in signals['red_flags']:
        return ('spam', 5,
                'Disposable / throwaway email service detected.')
    if 'malformed_email' in signals['red_flags']:
        return ('spam', 10, 'Email address is malformed.')
    if 'no_email_address' in signals['red_flags']:
        return ('spam', 0, 'No email address provided.')

    # Strong trust profile.
    if greens >= 4 and yellows == 0:
        return ('trusted', 90,
                'Corporate email matches company, all key data present.')

    # Corporate email + reasonable other data.
    if signals['email_class'] == 'corporate' and yellows <= 1:
        return ('verified', 75,
                'Corporate email domain with mostly complete information.')

    # Free email but otherwise OK.
    if signals['email_class'] == 'free' and greens >= 2 and reds == 0:
        return ('verified', 60,
                'Public-domain email but with credible supporting data.')

    # Too many warnings.
    if yellows >= 4 or (yellows >= 3 and greens == 0):
        return ('suspicious', 25,
                'Multiple weak signals — incomplete or generic data.')

    if yellows >= 2:
        return ('suspicious', 40,
                'Limited information; needs salesperson eyes.')

    # Default
    return ('verified', 55, 'Standard lead with adequate information.')
