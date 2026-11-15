# reco/ai_report.py
"""
"Does the AI help?" (roadmap 8.7): compares what people do with suggestions, group against group.
No AI call, read from what the app records:
  shown   TitleImpression, row_type "<surface>:<group>" (the app logs each suggestion it shows)
  clicked TitleAction "click" from that surface, same profile + title, within 24 h of being shown
  played  WatchEvent (the player opened) for that profile + title within 48 h of being shown

Comparisons:
  pick_moods       "What to watch?": moods from the AI tags vs genres alone (A/B test,
                   reco/experiments.py; shown as "pick:ai" / "pick:control")
  more_like_this   "More like this": TMDB's recommendations vs the embeddings' neighbours
                   (shown as "more_like_this:tmdb" / "more_like_this:embeddings", on the same pages)
A verdict only once each group has MIN_SHOWN suggestions shown and MIN_EVENTS clicks / plays in
all, and a two-proportion z-test says the gap is unlikely to be chance (p < 0.05).
Shown on the admin dashboard and by manage.py ai_report.
"""
import math
from datetime import timedelta

from django.utils import timezone

MIN_SHOWN = 100
MIN_EVENTS = 10
CLICK_WINDOW = timedelta(hours=24)
PLAY_WINDOW = timedelta(hours=48)

COMPARISONS = [
    # (key, label, surface for clicks, [(group, label)], metric that decides)
    ("pick_moods", '"What to watch?" moods', "pick", [("ai", "AI tags"), ("control", "Genres only")], "played"),
    ("more_like_this", '"More like this"', "more_like_this",
     [("tmdb", "TMDB recommendations"), ("embeddings", "Embeddings")], "clicked"),
]


def p_value(s1, n1, s2, n2):
    """Two-sided p-value of a two-proportion z-test (1.0 when it can't be computed)."""
    if not n1 or not n2:
        return 1.0
    pooled = (s1 + s2) / (n1 + n2)
    se = math.sqrt(pooled * (1 - pooled) * (1 / n1 + 1 / n2))
    if se == 0:
        return 1.0
    z = abs(s1 / n1 - s2 / n2) / se
    return math.erfc(z / math.sqrt(2))


def _group_stats(row_type, click_surface, since, now):
    """{"shown", "clicked", "played"} for one group."""
    from .models import TitleAction, TitleImpression, WatchEvent

    first_seen = {}  # (profile, title) -> first time shown in the period
    for pid, tid, at in (
        TitleImpression.objects.filter(row_type=row_type, created_at__gte=since, created_at__lt=now)
        .order_by("created_at").values_list("profile_id", "title_id", "created_at")
    ):
        first_seen.setdefault((pid, tid), at)
    if not first_seen:
        return {"shown": 0, "clicked": 0, "played": 0}
    profiles = {pid for pid, _ in first_seen}
    titles = {tid for _, tid in first_seen}

    clicks, plays = {}, {}
    for pid, tid, at in TitleAction.objects.filter(
        action="click", provider__endswith=f"surface:{click_surface}", profile_id__in=profiles,
        title_id__in=titles, created_at__gte=since,
    ).values_list("profile_id", "title_id", "created_at"):
        clicks.setdefault((pid, tid), []).append(at)
    for pid, tid, at in WatchEvent.objects.filter(
        profile_id__in=profiles, title_id__in=titles, watched_at__gte=since,
    ).values_list("profile_id", "title_id", "watched_at"):
        plays.setdefault((pid, tid), []).append(at)

    def within(times, start, window):
        return any(start <= t <= start + window for t in times or ())

    clicked = sum(within(clicks.get(k), at, CLICK_WINDOW) for k, at in first_seen.items())
    played = sum(within(plays.get(k), at, PLAY_WINDOW) for k, at in first_seen.items())
    return {"shown": len(first_seen), "clicked": clicked, "played": played}


def verdict(groups, metric):
    """A sentence on the two groups for one metric ("played" / "clicked")."""
    (a_label, a), (b_label, b) = groups
    if min(a["shown"], b["shown"]) < MIN_SHOWN or a[metric] + b[metric] < MIN_EVENTS:
        return "Not enough data yet", None
    p = p_value(a[metric], a["shown"], b[metric], b["shown"])
    ra, rb = a[metric] / a["shown"], b[metric] / b["shown"]
    if p >= 0.05:
        return f"No clear difference yet ({ra:.1%} vs {rb:.1%})", p
    better, worse = (a_label, b_label) if ra > rb else (b_label, a_label)
    return f"{better} does better than {worse} ({max(ra, rb):.1%} vs {min(ra, rb):.1%} {metric})", p


def report(days=28, now=None):
    """[{key, label, metric, groups: [{group, label, shown, clicked, played, click_rate, play_rate}],
    verdict, p}] for the last `days` days."""
    now = now or timezone.now()
    since = now - timedelta(days=days)
    out = []
    for key, label, surface, groups, metric in COMPARISONS:
        rows, pairs = [], []
        for group, group_label in groups:
            stats = _group_stats(f"{surface}:{group}", surface, since, now)
            shown = stats["shown"]
            rows.append({
                "group": group, "label": group_label, **stats,
                "click_rate": stats["clicked"] / shown if shown else None,
                "play_rate": stats["played"] / shown if shown else None,
            })
            pairs.append((group_label, stats))
        text, p = verdict(pairs, metric)
        out.append({"key": key, "label": label, "metric": metric, "groups": rows, "verdict": text, "p": p})
    return out
