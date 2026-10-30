# users/providers.py
# Stream links = Provider.domain + path template. Plus the health check that keeps
# domains working: detects dead domains, follows moves (redirects) and falls back
# to backup domains.
import logging
import re
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlsplit

import requests
from django.utils import timezone

from .models import Provider

logger = logging.getLogger(__name__)

PLACEHOLDER_RE = re.compile(r"\{(\w+)\}")
PLACEHOLDERS = {"tmdb_id", "imdb_id", "season", "episode"}
ORIGIN_RE = re.compile(r"^https?://[A-Za-z0-9.-]+(:\d+)?$")

# Known-good titles to probe providers with (Fight Club, Breaking Bad S1E1).
PROBE_MOVIE = {"tmdb_id": 550, "imdb_id": "tt0137523"}
PROBE_EPISODE = {"tmdb_id": 1396, "imdb_id": "tt0903747", "season": 1, "episode": 1}

PROBE_TIMEOUT = 10
PROBE_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/130.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
}


def normalize_domain(value):
    """'vidfast.pro' / 'https://vidfast.pro/' -> 'https://vidfast.pro' (None if invalid)."""
    value = (value or "").strip().rstrip("/")
    if value and "://" not in value:
        value = "https://" + value
    return value if ORIGIN_RE.match(value) else None


def origin_of(url):
    parts = urlsplit(url)
    return f"{parts.scheme}://{parts.netloc}"


def build_url(domain, path, **values):
    """Fill a path template; '' if it needs a value we don't have (e.g. no imdb_id)."""
    if not path:
        return ""
    missing = [name for name in PLACEHOLDER_RE.findall(path) if values.get(name) in (None, "")]
    if missing:
        return ""
    return domain + PLACEHOLDER_RE.sub(lambda m: str(values[m.group(1)]), path)


# ------------------------------------------------------------------
# Health check
# ------------------------------------------------------------------

def _probe(url):
    """
    -> (alive, final_url, detail). A domain is "alive" if its server answers at all
    (even 403/404: the site exists, it just dislikes bots or this exact path).
    Dead = DNS failure, refused/reset connection, TLS error, timeout, or a 5xx that
    isn't a Cloudflare bot challenge (503). Cloudflare 52x = the site behind it is down.
    """
    try:
        r = requests.get(url, headers=PROBE_HEADERS, timeout=PROBE_TIMEOUT, allow_redirects=True, stream=True)
        r.close()
    except requests.RequestException as exc:
        return False, "", f"{type(exc).__name__}: {str(exc)[:200]}"

    cloudflare_challenge = r.status_code == 503 and "cloudflare" in r.headers.get("Server", "").lower()
    alive = r.status_code < 500 or cloudflare_challenge
    return alive, r.url, f"HTTP {r.status_code}"


def _probe_target(provider):
    if provider.movie_path:
        return provider.movie_path, PROBE_MOVIE
    return provider.episode_path, PROBE_EPISODE


def _switch_domain(provider, new_domain, reason):
    old = provider.domain
    backups = [d for d in provider.backups() if d != new_domain]
    if old not in backups:
        backups.append(old)  # keep the old one as a fallback in case it comes back
    provider.domain = new_domain
    provider.backup_domains = "\n".join(backups)
    provider.domain_changed_at = timezone.now()
    provider.suggested_domain = ""
    logger.warning("provider %s: domain %s -> %s (%s)", provider.key, old, new_domain, reason)


def check_provider(provider, save=True):
    """Probe one provider, update its status (and domain when auto_switch). Returns a summary line."""
    path, values = _probe_target(provider)
    if not path:
        provider.status, provider.status_detail = Provider.UNKNOWN, "no path template to probe"
    else:
        url = build_url(provider.domain, path, **values)
        alive, final_url, detail = _probe(url)
        moved_to = ""
        if alive and final_url:
            final_origin = origin_of(final_url)
            # redirected to another domain but same page -> the provider moved
            if final_origin != provider.domain and urlsplit(final_url).path == urlsplit(url).path:
                moved_to = final_origin

        if moved_to:
            if provider.auto_switch:
                _switch_domain(provider, moved_to, f"redirect, {detail}")
                detail = f"moved, now on {moved_to} ({detail})"
            else:
                provider.suggested_domain = moved_to
                detail = f"redirects to {moved_to} ({detail})"
        elif not alive:
            for backup in provider.backups():
                b_alive, b_final, b_detail = _probe(build_url(backup, path, **values))
                if b_alive:
                    if provider.auto_switch:
                        _switch_domain(provider, backup, f"main down: {detail}")
                        detail = f"main down ({detail}), switched to {backup} ({b_detail})"
                        alive = True
                    else:
                        provider.suggested_domain = backup
                        detail = f"{detail}; backup {backup} works"
                    break

        provider.status = Provider.UP if alive else Provider.DOWN
        provider.status_detail = detail[:300]

    provider.checked_at = timezone.now()
    if save:
        provider.save()
    return f"{provider.key}: {provider.status} - {provider.status_detail}"


def check_providers(queryset=None):
    providers = list(queryset if queryset is not None else Provider.objects.filter(enabled=True))
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda p: check_provider(p, save=False), providers))
    for p in providers:  # save from the main thread (DB connections are per thread)
        p.save()
    return results
