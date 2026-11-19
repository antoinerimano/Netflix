# users/provider_import.py
# Brings provider_scraper/'s catalog (provider_catalog.json, made every night on the mini PC by
# provider_scraper/run.sh) into the Provider table, so working providers don't have to be added
# by hand:
#   * a known provider found playing on another domain, with the same link format: that domain
#     becomes a backup, and the main domain if the health check has it down (auto_switch on)
#   * a new provider seen playing a movie ("live": a stream started in the browser) is created;
#     enabled only when 2+ scanned sites use it (an established provider), otherwise left
#     disabled for a look in the admin
# Existing rows keep their enabled / priority / paths: what was set in the admin wins.
import re
from urllib.parse import urlsplit

from django.db import transaction
from django.utils import timezone
from django.utils.text import slugify

from .models import Provider
from .providers import PLACEHOLDER_RE, PLACEHOLDERS, _switch_domain, normalize_domain

MIN_SITES_TO_ENABLE = 2
NEW_PRIORITY_STEP = 10

# how the scraper / provider docs write the ids -> our placeholders
_TMDB = re.compile(r"\{(tmdb_?id|tmdbid|tmdb|id|movie_?id|tv_?id)\}|\$id\b|:id\b|\[(tmdb_?id|id)\]|<(tmdb_?id|id)>", re.I)
_IMDB = re.compile(r"\{(imdb_?id|imdbid|imdb)\}|\[imdb_?id\]|<imdb_?id>", re.I)
_SEASON = re.compile(r"\{(season|season_?number|s|ss)\}", re.I)
_EPISODE = re.compile(r"\{(episode|episode_?number|e|ep)\}", re.I)


def host_of(url):
    return (urlsplit(url).hostname or "").lower()


def _bare(host):
    return host.removeprefix("www.")


def to_template(url, probe=None):
    """
    'https://vidfast.vc/movie/{id}?autoPlay=true' -> ('https://vidfast.vc', '/movie/{tmdb_id}').
    With probe ({"tmdb": .., "imdb": ..}), the probe title's ids in a concrete URL become
    placeholders too. Query parameters without a placeholder are dropped (autoplay, colors...).
    None when it has no id placeholder or an unknown one.
    """
    if not url or not url.startswith("http"):
        return None
    u = url.split("#")[0].strip().rstrip(".,;)")
    u = _TMDB.sub("{tmdb_id}", u)
    u = _IMDB.sub("{imdb_id}", u)
    u = _SEASON.sub("{season}", u)
    u = _EPISODE.sub("{episode}", u)
    if probe:
        if probe.get("imdb"):
            u = u.replace(str(probe["imdb"]), "{imdb_id}")
        if probe.get("tmdb"):
            u = re.sub(rf"(?<![0-9]){probe['tmdb']}(?![0-9])", "{tmdb_id}", u)
    parts = urlsplit(u)
    domain = normalize_domain(f"{parts.scheme}://{parts.netloc}") if parts.netloc else None
    if not domain:
        return None
    query = "&".join(kv for kv in parts.query.split("&") if "{" in kv)
    path = (parts.path or "/") + (f"?{query}" if query else "")
    names = set(PLACEHOLDER_RE.findall(path))
    if not names & {"tmdb_id", "imdb_id"} or names - PLACEHOLDERS or re.search(r"[{}]", PLACEHOLDER_RE.sub("", path)):
        return None
    return domain, path


def _is_episode(path):
    return "{season}" in path and "{episode}" in path


def _is_movie(path):
    return not re.search(r"\{season\}|\{episode\}|/(tv|series|anime|episode)\b", path, re.I)


def paths_for(entry, probe):
    """
    -> (domain, movie_path, episode_path) for one catalog provider, from what played (the health
    check's test URL) first, then the templates seen on sites, then its docs' formats.
    """
    health = entry.get("health") or {}
    candidates = []
    if health.get("state") == "live" and health.get("test_url"):
        candidates.append(health["test_url"])
    candidates += entry.get("observed_templates") or []
    candidates += entry.get("doc_formats") or entry.get("formats") or []

    domain = movie_path = episode_path = ""
    for c in candidates:
        t = to_template(c, probe)
        if not t:
            continue
        d, path = t
        if not movie_path and _is_movie(path):
            domain, movie_path = d, path
        elif not episode_path and _is_episode(path) and (not domain or _bare(host_of(d)) == _bare(host_of(domain))):
            episode_path = path
    return domain, movie_path, episode_path


def _find_existing(entry, by_key, by_host):
    p = by_key.get(slugify(entry["provider"])[:40])
    if p:
        return p
    for h in entry.get("hosts") or []:
        p = by_host.get(_bare(h.lower()))
        if p:
            return p
    return None


def import_catalog(catalog, dry_run=False, min_sites=MIN_SITES_TO_ENABLE):
    """Apply a provider_catalog.json (dict). Returns (lines, stats)."""
    probe = catalog.get("probe_title") or {}
    existing = list(Provider.objects.all())
    by_key = {p.key: p for p in existing}
    by_host = {}
    for p in existing:
        for d in [p.domain] + p.backups():
            by_host.setdefault(_bare(host_of(d)), p)
    next_priority = max([p.priority for p in existing] or [0]) + NEW_PRIORITY_STEP

    lines = []
    stats = {"created": 0, "created_enabled": 0, "new_backup": 0, "switched": 0,
             "known_ok": 0, "skipped_not_live": 0, "skipped_no_link": 0}
    now = timezone.now()
    stamp = (catalog.get("generated") or now.strftime("%Y-%m-%d %H:%M"))[:16]

    with transaction.atomic():
        for entry in catalog.get("providers") or []:
            name = entry.get("provider") or ""
            if not name or name.startswith("cdn:") or name == "self-hosted":
                continue
            health = entry.get("health") or {}
            live = health.get("state") == "live"
            domain, movie_path, episode_path = paths_for(entry, probe) if live else ("", "", "")
            known = _find_existing(entry, by_key, by_host)

            if known:
                if not live or not domain:
                    continue  # nothing proven: the 15-min check_providers keeps watching it
                # same format once both drop their placeholder-less query parameters (autoplay...)
                known_t = to_template(known.domain + known.movie_path) if known.movie_path else None
                same_link = bool(known_t) and known_t[1] == movie_path
                if domain == known.domain:
                    stats["known_ok"] += 1
                    continue
                if not same_link:
                    lines.append(f"{known.key}: plays on {domain}{movie_path}, another link format "
                                 f"than {known.movie_path!r}: left as is, have a look")
                    continue
                if domain not in known.backups():
                    known.backup_domains = "\n".join([domain] + known.backups())
                    stats["new_backup"] += 1
                    lines.append(f"{known.key}: new working domain {domain} added as backup")
                if known.status == Provider.DOWN and known.auto_switch:
                    _switch_domain(known, domain, "provider scout: down here, playing there")
                    known.status, known.status_detail = Provider.UP, f"live in provider scout {stamp}"
                    known.checked_at = now
                    stats["switched"] += 1
                    lines.append(f"{known.key}: was down, switched to {domain}")
                if not dry_run:
                    known.save()
                continue

            if not live:
                stats["skipped_not_live"] += 1
                continue
            if not domain or not movie_path:
                stats["skipped_no_link"] += 1
                lines.append(f"{name}: plays, but no movie link template could be made: skipped")
                continue

            key = slugify(name)[:40]
            sites = int(entry.get("site_count") or len(entry.get("sites") or []))
            enabled = sites >= min_sites
            p = Provider(
                key=key, label=name[:1].upper() + name[1:], domain=domain,
                movie_path=movie_path, episode_path=episode_path,
                enabled=enabled, priority=min(next_priority, 32767), auto_switch=True,
                status=Provider.UP, status_detail=f"added by provider scout {stamp}: live, used by {sites} site(s)",
                checked_at=now,
            )
            next_priority += NEW_PRIORITY_STEP
            if not dry_run:
                p.save()
            by_key[key] = p
            by_host[_bare(host_of(domain))] = p
            stats["created"] += 1
            stats["created_enabled"] += enabled
            lines.append(f"{key}: NEW, {'enabled' if enabled else 'disabled (1 site: check it in the admin)'} - "
                         f"{domain}{movie_path}" + (f" | {episode_path}" if episode_path else " | no TV link"))

        if dry_run:
            transaction.set_rollback(True)
    return lines, stats
