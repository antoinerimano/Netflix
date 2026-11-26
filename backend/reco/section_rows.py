"""
"Popular anime" / "Popular K-dramas" home rows (ROADMAP 9.5), added live to the home page
(reco/views.py _with_live_rows) for the profiles that watch them: SECTION_ROW_MIN or more of their
recent titles (liked, played, listed) are in the section (Title.section, users/sections.py).

The row is the section's most popular titles (the same for everyone, cached), minus what the
profile already watched; the home page then takes out its dislikes and what its age limit doesn't
allow (a Kids profile gets kids anime only).
"""
from collections import Counter

from django.core.cache import cache

from users.models import Title
from users.sections import ANIME, KDRAMA, SECTIONS
from users.serializers import TitleHomeSerializer

SECTION_ROW_MIN = 2          # recent titles of the profile in the section before it gets the row
SECTION_ROW_SIZE = 30
SECTION_ROW_CANDIDATES = 60  # cached per section; the profile's watched ones come out of them
SECTION_ROWS_TTL = 1800      # 30 min
MIN_VOTES = 20               # a title nobody rated isn't "popular"
ROW_TITLES = {ANIME: "Popular anime", KDRAMA: "Popular K-dramas"}


def _section_items(section):
    ck = f"reco:section:row:v1:{section}"
    items = cache.get(ck)
    if items is None:
        titles = list(
            Title.objects.filter(section=section, vote_count__gte=MIN_VOTES)
            .order_by("-popularity", "-vote_average", "id")[:SECTION_ROW_CANDIDATES]
        )
        items = TitleHomeSerializer(titles, many=True).data
        cache.set(ck, items, SECTION_ROWS_TTL)
    return items


def profile_sections(recent_ids, min_titles=SECTION_ROW_MIN):
    """The sections the profile watches, most of its titles first (recent_ids: its recent titles)."""
    ids = list(recent_ids)[:300]
    if not ids:
        return []
    counts = Counter(
        Title.objects.filter(id__in=ids, section__in=SECTIONS).values_list("section", flat=True)
    )
    return [s for s, n in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])) if n >= min_titles]


def section_rows(recent_ids, watched_ids=()):
    """[row] for every section the profile watches: {"row_type": "anime", "title", "items"}."""
    sections = profile_sections(recent_ids)
    if not sections:
        return []
    watched = set(watched_ids)  # a queryset: read only for the profiles that get a row
    rows = []
    for section in sections:
        items = [it for it in _section_items(section) if it["id"] not in watched][:SECTION_ROW_SIZE]
        if items:
            rows.append({"row_type": section, "title": ROW_TITLES[section], "items": items})
    return rows
