# users/config_check.py
"""
The settings the site needs, checked every morning by the daily check-up (users/checkup.py):
a missing setting, the debug mode left on in production, or a key a service now refuses
(revoked, expired, rotated without updating backend/.env) is reported by email the same day,
instead of a job failing quietly. Where each setting lives and how to change it: docs/CONFIG.md.

Live checks call each service the cheapest way there is (nothing paid):
  TMDB       GET /3/configuration
  Anthropic  models.retrieve (no tokens)
  email      SMTP login, no message sent
A service that can't be reached (network, outage) is not reported here: only a clear "this key
is refused" (HTTP 401 / 403, SMTP authentication error) is.
"""
import logging
import os
import smtplib
from urllib.parse import urlparse

import requests
from django.conf import settings
from users.tmdb_http import redact

log = logging.getLogger(__name__)

TMDB_URL = "https://api.themoviedb.org/3/configuration"
ANTHROPIC_PROBE_MODEL = "claude-haiku-5-5"  # the check-up's own model
TIMEOUT = 15

_RESTART = "cd /opt/taurus && docker compose up -d backend"
_ENV_FIX = "Set {name} in /opt/taurus/backend/.env (docs/CONFIG.md), then: " + _RESTART

# (name, what stops working without it). Read from the environment (backend/.env).
REQUIRED = [
    ("TMDB_API_KEY", "catalog syncs: new titles, episodes, ratings, translations"),
    ("ANTHROPIC_API_KEY", "AI tags and translations, Ask Taurus, the AI part of this email"),
    ("EMAIL_HOST_USER", "every email: password resets, new episode alerts, this check-up"),
    ("EMAIL_HOST_PASSWORD", "every email: password resets, new episode alerts, this check-up"),
    ("SITE_DOMAIN", "nginx, the heartbeat and the site's links (set in /opt/taurus/.env)"),
    ("HC_PING_SITE", "healthchecks.io: being told when the server is down"),
    ("HC_PING_CHECKUP", "healthchecks.io: being told when the check-up stops running"),
]


def _env(name):
    return (os.environ.get(name) or "").strip()


def is_production():
    """The real site (https on a public name), not a local run or the tests."""
    host = urlparse(settings.SITE_URL).hostname or ""
    return settings.SITE_URL.startswith("https://") and host not in ("", "localhost", "127.0.0.1")


def presence_problems():
    problems = []
    missing = [(n, why) for n, why in REQUIRED if not _env(n)]
    for name, why in missing:
        where = "/opt/taurus/.env" if name == "SITE_DOMAIN" else "/opt/taurus/backend/.env"
        problems.append({"kind": "config_missing", "what": f"Setting {name} is missing",
                         "detail": f"Without it: {why}.",
                         "fix": f"Set {name} in {where} (docs/CONFIG.md), then: {_RESTART}"})

    if settings.DEBUG and is_production():
        problems.append({"kind": "config_debug", "what": "Django's debug mode is on in production (DJANGO_DEBUG)",
                         "detail": "Error pages show the site's URLs, settings and code to anyone; HTTPS-only "
                                   "cookies and HSTS are off.",
                         "fix": "Set DJANGO_DEBUG=0 in /opt/taurus/backend/.env, then: " + _RESTART})

    domain = _env("SITE_DOMAIN")
    site_host = urlparse(settings.SITE_URL).hostname or ""
    if domain and is_production() and site_host not in (domain, f"www.{domain}"):
        problems.append({"kind": "config_domain", "what": f"SITE_URL ({settings.SITE_URL}) is not on SITE_DOMAIN ({domain})",
                         "detail": "Emails and search engines would link to the other name.",
                         "fix": "Remove SITE_URL from /opt/taurus/backend/.env (it then follows SITE_DOMAIN), then: "
                                + _RESTART})
    return problems


def _refused(name, service, detail):
    return {"kind": "config_refused", "what": f"{service} refuses {name}",
            "detail": detail[:300], "fix": _ENV_FIX.format(name=name) + f"   (new key: {service}'s website)"}


def check_tmdb(key):
    try:
        r = requests.get(TMDB_URL, params={"api_key": key}, timeout=TIMEOUT)
    except requests.RequestException as exc:
        log.warning("config check: TMDB unreachable: %s", redact(exc))  # the URL holds the key
        return None
    if r.status_code in (401, 403):
        return _refused("TMDB_API_KEY", "TMDB", f"HTTP {r.status_code}: {r.text}")
    return None


def check_anthropic(key):
    import anthropic

    try:
        anthropic.Anthropic(api_key=key, timeout=TIMEOUT, max_retries=1).models.retrieve(ANTHROPIC_PROBE_MODEL)
    except (anthropic.AuthenticationError, anthropic.PermissionDeniedError) as exc:
        return _refused("ANTHROPIC_API_KEY", "Anthropic", f"{type(exc).__name__}: {exc}")
    except anthropic.APIError as exc:  # connection errors, 5xx, rate limits: not the key's fault
        log.warning("config check: Anthropic check inconclusive: %s", exc)
    return None


def check_smtp():
    if "smtp" not in (settings.EMAIL_BACKEND or "").lower():
        return None
    try:
        with smtplib.SMTP(settings.EMAIL_HOST, settings.EMAIL_PORT, timeout=TIMEOUT) as smtp:
            if settings.EMAIL_USE_TLS:
                smtp.starttls()
            smtp.login(settings.EMAIL_HOST_USER, settings.EMAIL_HOST_PASSWORD)
    except smtplib.SMTPAuthenticationError as exc:
        return _refused("EMAIL_HOST_PASSWORD", f"The mail server ({settings.EMAIL_HOST})",
                        f"{exc.smtp_code} {exc.smtp_error!r}")
    except (OSError, smtplib.SMTPException) as exc:
        log.warning("config check: SMTP check inconclusive: %s", exc)
    return None


def live_problems():
    found = []
    if _env("TMDB_API_KEY"):
        found.append(check_tmdb(_env("TMDB_API_KEY")))
    if _env("ANTHROPIC_API_KEY"):
        found.append(check_anthropic(_env("ANTHROPIC_API_KEY")))
    if settings.EMAIL_HOST_USER and settings.EMAIL_HOST_PASSWORD:
        found.append(check_smtp())
    return [p for p in found if p]


def config_problems():
    """Every settings problem right now (for find_problems); live checks only on the real site."""
    problems = presence_problems()
    if is_production():
        problems += live_problems()
    return problems
