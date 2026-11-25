"""
"Top 10" and "On Netflix / Prime Video..." home rows (ROADMAP 9.4), added live to every home page
(reco/views.py _with_live_rows), like "New episodes": the same for everyone, cached a few minutes.

Top 10: TMDB's trending charts (users TitleChartEntry, manage.py sync_tmdb_charts), mixed with
our own plays once there are enough of them: movies played today, shows this week, counted in
people (a binge = 1). Below OWN_PLAYS_MIN people the chart is TMDB's alone; above, each title's
score is OWN_WEIGHT of its share of our plays + the rest from its TMDB position, so a title our
viewers love climbs, and one only we watch can come in. The rows send up to TOP10_CANDIDATES
titles: the profile's age limit / dislikes take some out, the app shows the first 10, numbered.

On <service>: popular titles in a service's subscription in the visitor's country
(TitleOnService, users/watch_services.py), for the services with enough titles there; the ones
the profile watched most first, then the biggest catalogs.
"""
from collections import Counter
from datetime import timedelta

from django.core.cache import cache
from django.db.models import Count
from django.utils import timezone

from users.models import Title, TitleChartEntry, TitleOnService
from users.serializers import TitleHomeSerializer
from users.watch_services import SERVICES

from .models import TitleAction

TOP10_TTL = 600                 # 10 min
TOP10_CANDIDATES = 20
OWN_PLAYS_MIN = 30              # plays (people x title) in the window before ours count
OWN_WEIGHT = 0.5
WINDOWS = {TitleChartEntry.MOVIE_DAY: timedelta(days=1), TitleChartEntry.TV_WEEK: timedelta(days=7)}
ROW_TYPES = {TitleChartEntry.MOVIE_DAY: "top10_movies", TitleChartEntry.TV_WEEK: "top10_tv"}
ROW_TITLES = {TitleChartEntry.MOVIE_DAY: "Top 10 movies today", TitleChartEntry.TV_WEEK: "Top 10 shows this week"}

SERVICE_ROWS_TTL = 1800         # 30 min
SERVICE_ROW_SIZE = 30
SERVICE_ROW_MIN = 10            # fewer titles on a service in this country: no row for it
SERVICE_ROWS_MAX = 3


def blend(chart_ids, plays, min_people=OWN_PLAYS_MIN, own_weight=OWN_WEIGHT, size=TOP10_CANDIDATES):
    """
    chart_ids: title ids in TMDB's order; plays: {title id: people who played it}.
    Returns the ids, best first. TMDB's order alone until min_people people played something.
    """
    if sum(plays.values()) < min_people or not plays:
        return list(chart_ids)[:size]
    n = max(len(chart_ids), 1)
    top = max(plays.values())
    score = Counter()
    for i, tid in enumerate(chart_ids):
        score[tid] += (1 - own_weight) * (1 - i / n)
    for tid, count in plays.items():
        score[tid] += own_weight * count / top
    # ties: TMDB's order, then the most played
    order = {tid: i for i, tid in enumerate(chart_ids)}
    return sorted(score, key=lambda tid: (-score[tid], order.get(tid, n), -plays.get(tid, 0)))[:size]


def _own_plays(kind, since):
    return dict(
        TitleAction.objects
        .filter(action="outbound", created_at__gte=since, title__type=kind)
        .values("title_id")
        .annotate(c=Count("profile", distinct=True))
        .order_by("-c")
        .values_list("title_id", "c")[:200]
    )


def top10_rows():
    """[top 10 movies row, top 10 shows row], without the empty ones."""
    rows = cache.get("reco:top10:v1")
    if rows is not None:
        return rows
    rows = []
    now = timezone.now()
    for chart, kind in ((TitleChartEntry.MOVIE_DAY, "movie"), (TitleChartEntry.TV_WEEK, "tv")):
        chart_ids = list(TitleChartEntry.objects.filter(chart=chart).order_by("position").values_list("title_id", flat=True))
        ids = blend(chart_ids, _own_plays(kind, now - WINDOWS[chart]))
        by_id = {t.id: t for t in Title.objects.filter(id__in=ids, type=kind)}
        titles = [by_id[i] for i in ids if i in by_id]
        if titles:
            rows.append({
                "row_type": ROW_TYPES[chart],
                "title": ROW_TITLES[chart],
                "items": TitleHomeSerializer(titles, many=True).data,
            })
    cache.set("reco:top10:v1", rows, TOP10_TTL)
    return rows


def _services_in(region):
    """{service: titles on it in region}, only the services with enough of them."""
    ck = f"reco:services:count:{region}"
    counts = cache.get(ck)
    if counts is None:
        counts = dict(
            TitleOnService.objects.filter(country=region)
            .values("service").annotate(n=Count("id")).values_list("service", "n")
        )
        cache.set(ck, counts, SERVICE_ROWS_TTL)
    return {s: n for s, n in counts.items() if s in SERVICES and n >= SERVICE_ROW_MIN}


def service_row(region, service):
    ck = f"reco:services:row:{region}:{service}"
    row = cache.get(ck)
    if row is not None:
        return row
    titles = list(
        Title.objects.filter(services_rel__country=region, services_rel__service=service)
        .order_by("-popularity", "-vote_average", "id")[:SERVICE_ROW_SIZE]
    )
    name = SERVICES[service]["name"]
    row = {
        "row_type": f"service:{service}",
        "title": f"On {name}",
        "items": TitleHomeSerializer(titles, many=True).data,
    }
    cache.set(ck, row, SERVICE_ROWS_TTL)
    return row


def service_rows(region, watched_ids=(), limit=SERVICE_ROWS_MAX):
    """The "On <service>" rows for this country: the services the profile's titles are on most
    first (watched_ids: its recent titles), then the biggest catalogs."""
    counts = _services_in(region)
    if not counts:
        return []
    mine = Counter()
    if watched_ids:
        mine.update(
            TitleOnService.objects.filter(country=region, title_id__in=list(watched_ids)[:300], service__in=list(counts))
            .values_list("service", flat=True)
        )
    order = sorted(counts, key=lambda s: (-mine[s], -counts[s], s))[:limit]
    return [row for row in (service_row(region, s) for s in order) if row["items"]]
