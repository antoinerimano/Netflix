# users/maturity.py
# Age ratings: TMDB certification -> maturity level, and the per-profile title filter.
from django.db.models import Q

# Maturity levels (Title.maturity) = profile limits (Profile.age_restriction)
G, PG, PG13, R, NC17 = 0, 1, 2, 3, 4
PROFILE_LEVELS = {"G": G, "PG": PG, "PG-13": PG13, "R": R, "NC-17": NC17}
KIDS_MAX_LEVEL = PG  # a Kids profile never goes above PG, whatever its age_restriction says

# Rating -> level, per country. US first; the others fill in titles without a US rating.
RATING_LEVELS = {
    "US": {
        "G": G, "PG": PG, "PG-13": PG13, "R": R, "NC-17": NC17,
        "TV-Y": G, "TV-Y7": G, "TV-Y7-FV": G, "TV-G": G, "TV-PG": PG, "TV-14": PG13, "TV-MA": R,
    },
    "GB": {"U": G, "UC": G, "PG": PG, "12": PG13, "12A": PG13, "15": R, "18": R, "R18": NC17},
    "DE": {"0": G, "6": G, "12": PG13, "16": R, "18": R},
    "FR": {"U": G, "TP": G, "10": PG, "12": PG13, "16": R, "18": R},
}
COUNTRY_ORDER = ["US", "GB", "DE", "FR"]

# Unrated titles are only shown to restricted profiles when they are in one of these genres
FAMILY_GENRES = ("Family", "Kids")


def rating_from_tmdb(kind, full):
    """
    full: TMDB /movie/{id} (append release_dates) or /tv/{id} (append content_ratings).
    -> (certification, maturity) e.g. ("PG-13", 2), or ("", None) when unrated.
    """
    if full.get("adult"):
        return "Adult", NC17

    by_country = {}
    if kind == "movie":
        for country in (full.get("release_dates") or {}).get("results") or []:
            certs = [d.get("certification", "").strip() for d in country.get("release_dates") or []]
            by_country[country.get("iso_3166_1")] = [c for c in certs if c]
    else:
        for r in (full.get("content_ratings") or {}).get("results") or []:
            rating = (r.get("rating") or "").strip()
            by_country.setdefault(r.get("iso_3166_1"), []).append(rating)

    for country in COUNTRY_ORDER:
        levels = RATING_LEVELS[country]
        for cert in by_country.get(country) or []:
            if cert in levels:
                label = cert if country == "US" else f"{country} {cert}"
                return label, levels[cert]
    return "", None


def profile_max_level(profile):
    """Highest maturity a profile may see, or None for no limit."""
    if profile is None:
        return None
    level = PROFILE_LEVELS.get(profile.age_restriction, NC17)
    if profile.is_kids:
        level = min(level, KIDS_MAX_LEVEL)
    return None if level >= NC17 else level


def allowed_titles_q(profile, prefix=""):
    """Q() matching the titles a profile may see. prefix: e.g. "title__" when filtering another model."""
    max_level = profile_max_level(profile)
    if max_level is None:
        return Q()
    unrated_family = Q(**{f"{prefix}maturity__isnull": True}) & (
        Q(**{f"{prefix}genre__icontains": FAMILY_GENRES[0]}) | Q(**{f"{prefix}genre__icontains": FAMILY_GENRES[1]})
    )
    return Q(**{f"{prefix}maturity__lte": max_level}) | unrated_family


def request_profile(request):
    """The active profile sent by the frontend (X-Profile-Id header), if it belongs to the user."""
    from .models import Profile

    pid = request.headers.get("X-Profile-Id") or request.query_params.get("profileId")
    user = getattr(request, "user", None)
    if not pid or not str(pid).isdigit() or not (user and user.is_authenticated):
        return None
    return Profile.objects.filter(id=int(pid), user=user).first()


def rating_fields(kind, full):
    """Title fields for the sync scripts (full = TMDB details with release_dates / content_ratings)."""
    from django.utils import timezone

    certification, maturity = rating_from_tmdb(kind, full)
    return {"certification": certification, "maturity": maturity, "rating_synced_at": timezone.now()}
