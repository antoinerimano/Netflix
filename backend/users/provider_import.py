# users/provider_import.py
# Brings provider_scraper/'s catalog (provider_catalog.json, made every night on the mini PC by
# provider_scraper/run.sh) into the Provider table, so working providers don't have to be added
# by hand:
#   * "live" = played EVERY test film (several well-known movies, each stream as long as the film
#     and moving, see provider_scraper/provider_health.py), with the provider's current link
#     tried first, then its docs' formats, the usual structures and its other domains
#   * every provider (the scout checks all the site's providers, export_providers): live with
#     another domain / link structure -> that one becomes its link (old domain kept as backup);
#     its TV link becomes the one an episode played with, or is removed when none did
#   * a provider that doesn't play every test film is turned off (disabled_by_scout), back on the
#     night they all play again. "Couldn't check" (a Cloudflare page in the scout's browser)
#     changes nothing.
#   * a new provider that is live is created: enabled only when 2+ scanned sites use it (an
#     established provider), otherwise left disabled for a look in the admin
# Priority and providers turned off by hand (not by the scout) are left as they are.
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


NOT_PLAYING = {"partial", "up", "no_source", "down"}  # checked, and a film didn't play
UNKNOWN = {"protected", "unverified", "untested"}  # couldn't be checked (bot check, player silent for robots): no change


def is_checked(entry):
    """
    Checked with the film test, the site's current link included: a night the scout couldn't read
    the site's providers, only its own formats were tried, and those failing says nothing.
    """
    health = entry.get("health") or {}
    return health.get("current_tried") is True and (bool(health.get("films")) or health.get("state") == "down")


def _path_of(domain, path):
    t = to_template(domain + path) if path else None
    return t[1] if t else path


def _apply_working_link(known, domain, movie_path, episode_path, health, lines, stats, stamp, now):
    """
    Every test film played with domain + movie_path: make it the provider's link when its own is
    another domain or structure (its current link is tried first, so a different one means it
    didn't play). The TV link: the one an episode played with, removed when none did.
    """
    changed = False
    if domain != known.domain:
        _switch_domain(known, domain, "provider scout: the films play on this domain")
        stats["switched"] += 1
        lines.append(f"{known.key}: domain -> {domain} (films play there)")
        changed = True
    # same structure once both drop their placeholder-less parameters (autoplay...): keep the admin's
    if _path_of(domain, known.movie_path) != movie_path:
        lines.append(f"{known.key}: movie link {known.movie_path!r} -> {movie_path!r} (the one that plays)")
        known.movie_path = movie_path
        stats["fixed_link"] += 1
        changed = True
    if "episode" in health:  # an episode was tried
        if episode_path and _path_of(domain, known.episode_path) != episode_path:
            lines.append(f"{known.key}: TV link {known.episode_path!r} -> {episode_path!r} (the one that plays)")
            known.episode_path = episode_path
            stats["tv_fixed"] += 1
            changed = True
        elif not episode_path and known.episode_path:
            lines.append(f"{known.key}: TV link {known.episode_path!r} removed: no episode plays "
                         f"({(health.get('episode') or {}).get('detail', '')})")
            known.episode_path = ""
            stats["tv_fixed"] += 1
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
             "disabled": 0, "reenabled": 0, "unchecked": 0, "fixed_link": 0, "tv_fixed": 0}
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
                    if known.disabled_by_scout:
                        known.enabled, known.disabled_by_scout = True, False
                        stats["reenabled"] += 1
                        lines.append(f"{known.key}: back ON, plays every test film again")
                elif state in NOT_PLAYING and not is_checked(entry) and known.enabled:
                    lines.append(f"{known.key}: its current link wasn't checked tonight, left as is")
                elif state in NOT_PLAYING and known.enabled:
                    known.enabled, known.disabled_by_scout = False, True
                    stats["disabled"] += 1
                    lines.append(f"{known.key}: OFF, doesn't play every test film - {health.get('detail', '')}")
                elif state in UNKNOWN and known.enabled:
                    # a bot check in a headless browser is not "doesn't play": changes nothing
                    stats["unchecked"] += 1
                    lines.append(f"{known.key}: couldn't be checked ({health.get('detail', state)}), left as is")
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
                scout_check=note,
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
