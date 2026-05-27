# -*- coding: utf-8 -*-
"""Lightweight company-website research.

Fetches the company's homepage (derived from the lead's email domain),
strips HTML to plain text, and hands the result to the LLM for
summarization. Works with any AI provider — no provider-specific web
tool required.

Security model: anything user-controlled (the lead's email_from) is
fetched, so this is a classic SSRF surface. Mitigations applied:

* Skip free/disposable providers (gmail.com, mailinator.com, …) — these
  aren't company websites and the fetch would be pointless anyway.
* Validate the domain shape with a strict regex before any network use.
* Resolve DNS up-front and refuse private / loopback / link-local /
  reserved / multicast IPs (blocks ``localhost``, ``10.x``, AWS-metadata
  ``169.254.169.254``, etc.).
* Hard timeout (8s) and response size cap (200 KB) — bounds the worst
  case if a target is slow or malicious.
* ``allow_redirects=False`` — we handle at most one redirect manually
  and revalidate the destination's IP.

This is **best-effort** — many company sites use JS-rendered pages
that won't have useful text after a plain HTTP GET. That's fine; we
report the failure as a skipped_reason rather than a hard error.
"""
import ipaddress
import logging
import re
import socket
from urllib.parse import urlparse

from .legitimacy import _FREE_PROVIDERS, _DISPOSABLE_PROVIDERS

_logger = logging.getLogger(__name__)

# Domains we never bother fetching — they're not company websites.
SKIP_DOMAINS = _FREE_PROVIDERS | _DISPOSABLE_PROVIDERS

USER_AGENT = (
    'Mozilla/5.0 (compatible; OdooAICRM/1.0; '
    '+https://www.techmaticsys.com)'
)

MAX_FETCH_BYTES = 200_000   # 200 KB cap on response body
FETCH_TIMEOUT = 8           # seconds, hard ceiling per HTTP request
MAX_REDIRECTS = 1           # follow at most one redirect (http→https,
                            # apex→www, etc.)
MAX_TEXT_FOR_LLM = 8_000    # chars handed to the model after extraction

# Domain shape: at least one dot, letters/digits/dashes, TLD ≥2 letters.
_DOMAIN_RE = re.compile(r'^[a-z0-9]([a-z0-9-]*[a-z0-9])?(\.[a-z0-9-]+)*\.[a-z]{2,}$')

# HTML cleanup — drop everything inside <script>/<style> first, THEN
# strip remaining tags. Order matters; doing it in one pass would drop
# the textual content inside e.g. <p>…</p>.
_SCRIPT_RE = re.compile(
    r'<(script|style)[^>]*>.*?</\1>', re.IGNORECASE | re.DOTALL,
)
_TAG_RE = re.compile(r'<[^>]+>')
_WS_RE = re.compile(r'\s+')


def domain_from_email(email):
    """Return the company domain to research, or None to skip."""
    if not email or '@' not in email:
        return None
    domain = email.strip().lower().rsplit('@', 1)[-1].rstrip('.')
    if domain in SKIP_DOMAINS:
        return None
    if not _DOMAIN_RE.match(domain):
        return None
    return domain


def _is_safe_ip(ip_str):
    """True only for routable, public IPv4/IPv6 addresses."""
    try:
        ip = ipaddress.ip_address(ip_str)
    except ValueError:
        return False
    return not (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_reserved
        or ip.is_multicast
        or ip.is_unspecified
    )


def _resolve_safely(host):
    """Resolve ``host`` to an IP and refuse if it's private / loopback.

    Closes the SSRF hole — without this, a crafted lead with email
    ``x@my-internal.local`` could trigger an HTTP request to Odoo's
    own VPC / metadata services.
    """
    try:
        ip = socket.gethostbyname(host)
    except socket.gaierror as e:
        raise RuntimeError('DNS resolution failed for %s: %s' % (host, e))
    if not _is_safe_ip(ip):
        raise RuntimeError(
            'Refusing to fetch %s — resolved to non-public IP %s' % (host, ip)
        )
    return ip


def _fetch_once(url):
    """Single HTTP GET with timeout + size cap. Returns (text, final_url).

    Raises on any failure. Validates the URL's host against the IP
    allowlist BEFORE making the request.
    """
    try:
        import requests
    except ImportError as e:
        raise RuntimeError(
            'The `requests` package is required for web research.'
        ) from e

    parsed = urlparse(url)
    if parsed.scheme not in ('http', 'https'):
        raise RuntimeError('Refusing non-HTTP(S) URL %s' % url)
    if not parsed.netloc:
        raise RuntimeError('URL has no host: %s' % url)
    _resolve_safely(parsed.hostname or '')

    resp = requests.get(
        url,
        headers={
            'User-Agent': USER_AGENT,
            'Accept': 'text/html,application/xhtml+xml',
            'Accept-Language': 'en-US,en;q=0.9',
        },
        timeout=FETCH_TIMEOUT,
        allow_redirects=False,   # we handle redirects ourselves
        stream=True,
    )

    # Manual redirect handling — re-validate the new host's IP.
    if 300 <= resp.status_code < 400:
        new_url = resp.headers.get('Location')
        if not new_url:
            raise RuntimeError(
                'Redirect with no Location header from %s' % url
            )
        return new_url, None  # caller decides whether to chase

    resp.raise_for_status()

    # Cap response size during streaming.
    content = b''
    for chunk in resp.iter_content(chunk_size=8192):
        if chunk:
            content += chunk
            if len(content) >= MAX_FETCH_BYTES:
                break

    encoding = resp.encoding or 'utf-8'
    text = content.decode(encoding, errors='replace')
    return resp.url, text


def fetch_homepage(domain):
    """Try https://domain/ then http://domain/. Follow ≤1 redirect.

    Returns (final_url, html_text). Raises on total failure.
    """
    last_error = None
    for scheme in ('https', 'http'):
        url = '%s://%s/' % (scheme, domain)
        try:
            redirects_left = MAX_REDIRECTS
            current = url
            while True:
                next_url, body = _fetch_once(current)
                if body is not None:
                    return current, body
                # Body is None → next_url is a redirect target.
                redirects_left -= 1
                if redirects_left < 0:
                    raise RuntimeError(
                        'Too many redirects from %s' % url
                    )
                # Resolve relative redirects against the previous URL.
                from urllib.parse import urljoin
                current = urljoin(current, next_url)
        except Exception as e:  # noqa: BLE001 — defensive at boundary
            last_error = e
            continue
    raise RuntimeError(
        'Could not fetch %s: %s' % (domain, last_error)
    )


def extract_text(html):
    """Strip HTML → cleaned text. Pure regex; no BeautifulSoup dep."""
    html = _SCRIPT_RE.sub(' ', html)
    text = _TAG_RE.sub(' ', html)
    # Decode the small set of HTML entities most company sites use.
    text = (text
            .replace('&nbsp;', ' ')
            .replace('&amp;', '&')
            .replace('&lt;', '<')
            .replace('&gt;', '>')
            .replace('&quot;', '"')
            .replace('&#39;', "'")
            )
    text = _WS_RE.sub(' ', text).strip()
    return text


def research_company(domain):
    """Top-level: fetch + extract. Returns dict the LLM can consume.

    Never raises. On failure, ``success=False`` and ``error`` is set.
    """
    try:
        url, html = fetch_homepage(domain)
    except Exception as e:  # noqa: BLE001 — boundary
        _logger.info('Web research failed for %s: %s', domain, e)
        return {
            'success': False, 'url': None, 'text': '',
            'error': str(e)[:255],
        }
    text = extract_text(html)
    return {
        'success': True,
        'url': url,
        'text': text[:MAX_TEXT_FOR_LLM],
        'error': None,
    }
