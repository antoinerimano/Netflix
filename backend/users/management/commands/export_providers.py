"""
What the provider scout on the mini PC (provider_scraper/run.sh) needs to test providers the way
tauruss plays them:

    docker compose exec -T backend python manage.py export_providers > site_providers.json

  site_origin  the site's address: each player is tested in an iframe on a page of that origin
  providers    every provider with its current link (tested first, so a wrong domain or link
               structure is found and fixed by the next import_providers)
  test_titles  what the viewers watch lately (movies, episodes, with their runtime), topped up
               with popular titles: a provider with a limited catalog shows up; "anime": anime
               episodes (ROADMAP 9.5), One Piece 1x01 and a late season of the most popular
               anime shows (TMDB numbers its long shows by season: a player that counts
               episodes from 1 to 1100 plays the wrong one), -> Provider.scout_anime
  reports      "Playback problem?" reports not re-checked yet (ROADMAP 9.8, reco/problems.py): the
               scout checks those sources first and plays the reported titles on them; its answer
               comes back with import_providers (health "reports"). The reported sources are
               also first in "providers".
"""
import json

from django.conf import settings
from django.core.management.base import BaseCommand

from users.models import Episode, Provider, Title

MOVIES = 11
EPISODES = 4
# always in the test: old classics (a provider with only recent titles shows up), TMDB runtimes
LEGACY_MOVIES = [
    {"tmdb": 238, "imdb": "tt0068646", "name": "The Godfather", "minutes": 175},
    {"tmdb": 680, "imdb": "tt0110912", "name": "Pulp Fiction", "minutes": 154},
    {"tmdb": 289, "imdb": "tt0034583", "name": "Casablanca", "minutes": 102},
]
LEGACY_EPISODES = [
    {"tmdb": 1668, "imdb": "tt0108778", "season": 1, "episode": 1, "name": "Friends 1x01", "minutes": 22},
]
ANIME = 4
LEGACY_ANIME = [
    {"tmdb": 37854, "imdb": "tt0388629", "season": 1, "episode": 1, "name": "One Piece 1x01", "minutes": 24},
]


def _recent_watch():
    try:
        from reco.models import WatchProgress
    except ImportError:  # the reco app is optional
        return []
    return WatchProgress.objects.select_related("title").order_by("-updated_at")


def test_titles(movies=MOVIES, episodes=EPISODES):
    """
    -> {"movies": [{tmdb, imdb, name, minutes}], "episodes": [{tmdb, imdb, season, episode, name, minutes}]}:
    the classics, then what the viewers opened lately, then popular titles.
    """
    picked_movies, picked_eps = list(LEGACY_MOVIES), list(LEGACY_EPISODES)
    seen = {("movie", m["tmdb"]) for m in LEGACY_MOVIES} | {("tv", e["tmdb"]) for e in LEGACY_EPISODES}

    def add_movie(t):
        key = ("movie", t.tmdb_id)
        if len(picked_movies) < movies and key not in seen and t.tmdb_id and (t.runtime_minutes or 0) >= 60:
            seen.add(key)
            picked_movies.append({"tmdb": t.tmdb_id, "imdb": t.imdb_code or "", "name": t.title[:60],
                                  "minutes": t.runtime_minutes})

    def add_episode(t, season, number):
        key = ("tv", t.tmdb_id)
        if len(picked_eps) >= episodes or key in seen or not t.tmdb_id or not season or not number:
            return
        runtime = (Episode.objects.filter(season__tv=t, season__season_number=season, episode_number=number)
                   .values_list("runtime", flat=True).first())
        if runtime and runtime >= 15:
            seen.add(key)
            picked_eps.append({"tmdb": t.tmdb_id, "imdb": t.imdb_code or "", "season": season, "episode": number,
                               "name": f"{t.title[:50]} {season}x{number:02d}", "minutes": runtime})

    # what the viewers opened lately
    for w in _recent_watch()[:300]:
        if w.title.type == Title.MOVIE:
            add_movie(w.title)
        else:
            add_episode(w.title, w.season_number, w.episode_number)
        if len(picked_movies) >= movies and len(picked_eps) >= episodes:
            break
    # topped up with popular ones, out for a year at least (every provider should have them)
    for t in (Title.objects.filter(type=Title.MOVIE, tmdb_id__isnull=False, runtime_minutes__gte=60,
                                   release_year__lte=_last_year()).order_by("-popularity")[:200]):
        add_movie(t)
        if len(picked_movies) >= movies:
            break
    for t in Title.objects.filter(type=Title.TV, tmdb_id__isnull=False).order_by("-popularity")[:100]:
        add_episode(t, 1, 1)
        if len(picked_eps) >= episodes:
            break
    return {"movies": picked_movies, "episodes": picked_eps, "anime": anime_episodes()}


def anime_episodes(count=ANIME):
    """
    -> [{tmdb, imdb, season, episode, name, minutes}]: One Piece 1x01, then the most popular anime
    shows of the catalog (Title.section, users/sections.py), each at E1 of its last aired season
    (a late season: what a player with its own episode numbering gets wrong).
    """
    from django.utils import timezone

    picked = list(LEGACY_ANIME)
    seen = {e["tmdb"] for e in picked}
    today = timezone.now().date()
    shows = Title.objects.filter(type=Title.TV, section="anime", tmdb_id__isnull=False).order_by("-popularity")[:40]
    for t in shows:
        if len(picked) >= count:
            break
        if t.tmdb_id in seen:
            continue
        aired = sorted(Episode.objects.filter(season__tv=t, season__season_number__gte=1, episode_number=1,
                                              air_date__lte=today)
                       .values_list("season__season_number", "runtime"))
        if not aired:
            continue
        season, runtime = aired[-1]
        seen.add(t.tmdb_id)
        picked.append({"tmdb": t.tmdb_id, "imdb": t.imdb_code or "", "season": season, "episode": 1,
                       "name": f"{t.title[:50]} {season}x01", "minutes": runtime or 24})
    return picked


def _last_year():
    from django.utils import timezone
    return timezone.now().year - 1


class Command(BaseCommand):
    help = "Print the site's origin, providers and test titles as JSON for the provider scout."

    def handle(self, *args, **opts):
        reports = _reports()
        reported = {r["provider"] for r in reports}
        providers = [{
            "key": p.key, "domain": p.domain, "backups": p.backups(), "movie_path": p.movie_path,
            "episode_path": p.episode_path, "enabled": p.enabled,
            "sends_events": p.sends_events,
        } for p in Provider.objects.all()]
        providers.sort(key=lambda p: p["key"] not in reported)  # stable: the reported ones first
        self.stdout.write(json.dumps({"site_origin": settings.SITE_URL, "providers": providers,
                                      "test_titles": test_titles(), "reports": reports}, indent=1))


def _reports():
    try:
        from reco.problems import open_reports
    except ImportError:  # the reco app is optional
        return []
    return open_reports()
