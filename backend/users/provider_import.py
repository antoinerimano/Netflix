# users/provider_import.py
# Brings provider_scraper/'s catalog (provider_catalog.json, made every night on the mini PC by
# provider_scraper/run.sh) into the Provider table, so working providers don't have to be added
# by hand:
#   * "live" = in the scout's test, which plays each provider the way tauruss does (in an iframe on
#     the site's origin, the 15 s rule, the players' postMessage events), it played >= 90 % of the
#     test titles (what the viewers watch lately) that some provider plays
#     (see provider_scraper/provider_health.py)
#   * a new provider that is live is created: enabled only when 2+ scanned sites use it (an
#     established provider), otherwise left disabled for a look in the admin
#   * a provider of the site whose own link is DEAD (domain down, or 404 on every title tried)
#     gets the link that played (old domain kept as backup); same for its TV link
#   * nothing else: the scout never turns a provider off nor touches a link that answers. Which
#     sources play best for the viewers is the site's smart playback (success rates, the source
#     that last worked) - a test in an automated browser gets that wrong too often.
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


def is_live(entry):
    """Played every test film. Catalogs from the old one-title check (no "films") don't count."""
    health = entry.get("health") or {}
    return health.get("state") == "live" and bool(health.get("films"))


def paths_for(entry, probe):
    """
    -> (domain, movie_path, episode_path) for one catalog provider: the link formats that played,
    the TV one only when an episode played too. (Old catalogs: the test URL, then the templates
    seen on sites, then its docs' formats.)
    """
    health = entry.get("health") or {}
    if health.get("films"):
        movie = to_template(health.get("movie_template") or "")
        if not movie or not _is_movie(movie[1]):
            return "", "", ""
        episode = to_template(health.get("episode_template") or "")
        same_host = bool(episode) and _bare(host_of(episode[0])) == _bare(host_of(movie[0]))
        return movie[0], movie[1], (episode[1] if same_host and _is_episode(episode[1]) else "")

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


def _path_of(domain, path):
    t = to_template(domain + path) if path else None
    return t[1] if t else path


def _apply_working_link(known, domain, movie_path, episode_path, health, lines, stats, stamp, now):
    """
    The scout found the link that plays (domain + movie_path). It replaces the provider's own link
    only when that one is dead (current_dead); same for the TV link. A link that answers is kept.
    """
    changed = False
    if health.get("current_dead") and (domain != known.domain or _path_of(domain, known.movie_path) != movie_path):
        if domain != known.domain:
            _switch_domain(known, domain, "provider scout: its link is dead, the films play on this one")
            stats["switched"] += 1
        lines.append(f"{known.key}: dead link {known.movie_path!r} -> {domain}{movie_path} (plays)")
        known.movie_path = movie_path
        stats["fixed_link"] += 1
        changed = True
    if (health.get("current_episode_dead") and episode_path
            and _path_of(known.domain, known.episode_path) != episode_path):
        lines.append(f"{known.key}: dead TV link {known.episode_path!r} -> {episode_path!r} (plays)")
        known.episode_path = episode_path
        stats["tv_fixed"] += 1
        changed = True
    if health.get("sends_events") and not known.sends_events:
        # it reported playback to the page in the scout's test: the site can tell when it plays
        known.sends_events = True
        lines.append(f"{known.key}: reports playback (postMessage): sends_events on")
        changed = True
    if changed:
        known.status, known.status_detail, known.checked_at = Provider.UP, f"fixed by provider scout {stamp}", now
    else:
        stats["known_ok"] += 1


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
             "known_ok": 0, "skipped_not_live": 0, "skipped_no_link": 0,
             "fixed_link": 0, "tv_fixed": 0}
    now = timezone.now()
    stamp = (catalog.get("generated") or now.strftime("%Y-%m-%d %H:%M"))[:16]

    with transaction.atomic():
        for entry in catalog.get("providers") or []:
            name = entry.get("provider") or ""
            if not name or name.startswith("cdn:") or name == "self-hosted":
                continue
            health = entry.get("health") or {}
            live = is_live(entry)
            domain, movie_path, episode_path = paths_for(entry, probe) if live else ("", "", "")
            known = _find_existing(entry, by_key, by_host)
            state = health.get("state", "")
            note = " ".join(x for x in (stamp, state, health.get("verified", ""),
                                        "-", health.get("detail", "")) if x)[:300]

            if known:
                if not health:
                    continue  # not checked tonight
                known.scout_check = note
                if live and domain:
                    _apply_working_link(known, domain, movie_path, episode_path, health, lines, stats, stamp, now)
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
                scout_check=note, sends_events=bool(health.get("sends_events")),
                status=Provider.UP, status_detail=f"added by provider scout {stamp}: plays every test film, "
                                                  f"used by {sites} site(s)",
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
