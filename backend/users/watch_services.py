"""
Streaming services a title is on, per country (ROADMAP 9.4): "On Netflix" home rows and the browse
pages' service filter. Free TMDB data ("TMDB first"): /{movie|tv}/{id}/watch/providers, which TMDB
gets from JustWatch. Only the subscription offers ("flatrate"): rent / buy aren't "on Netflix".
manage.py sync_tmdb_watch_providers stores them (TitleOnService), refreshed every 30 days.

SERVICES: our key -> the name shown (a brand, the same in every language) and the TMDB provider
ids that count as it (a service's plan with ads, its old name: HBO Max -> Max). Channels sold
through another service (Prime Video Channels) are left out: the title isn't in that subscription.
"""
import re

SERVICES = {
    "netflix": {"name": "Netflix", "tmdb_ids": (8, 1796)},               # Netflix, Netflix basic with Ads
    "prime": {"name": "Prime Video", "tmdb_ids": (9, 119, 2100)},        # Amazon Prime Video (+ with Ads)
    "disney": {"name": "Disney+", "tmdb_ids": (337,)},
    "max": {"name": "Max", "tmdb_ids": (1899, 384)},                     # Max, HBO Max
    "apple": {"name": "Apple TV+", "tmdb_ids": (350,)},
    "hulu": {"name": "Hulu", "tmdb_ids": (15,)},
    "paramount": {"name": "Paramount+", "tmdb_ids": (531, 2303, 2616)},  # + Premium, + Essential
    "peacock": {"name": "Peacock", "tmdb_ids": (386, 387)},              # Peacock, Peacock Premium
}
SERVICE_OF_TMDB_ID = {pid: key for key, s in SERVICES.items() for pid in s["tmdb_ids"]}

# the region of an app language when the visitor's browser doesn't say one ("fr" -> FR)
LANGUAGE_REGION = {
    "en": "US", "fr": "FR", "de": "DE", "es": "ES", "it": "IT", "pt": "BR", "ru": "RU", "ja": "JP",
    "zh": "TW", "ar": "SA", "ur": "PK", "hi": "IN", "bn": "IN",
}
DEFAULT_REGION = "US"
_REGION = re.compile(r"^[A-Za-z]{2}$")


def services_on(watch_providers: dict) -> set[tuple[str, str]]:
    """TMDB's watch/providers answer -> {(country, service key)} of its subscription offers."""
    out = set()
    for country, offers in ((watch_providers or {}).get("results") or {}).items():
        if not isinstance(offers, dict) or not _REGION.match(str(country)):
            continue
        for offer in offers.get("flatrate") or []:
            key = SERVICE_OF_TMDB_ID.get((offer or {}).get("provider_id"))
            if key:
                out.add((str(country).upper(), key))
    return out


def valid_region(code) -> str:
    """"fr" / "FR" -> "FR"; "" for anything that isn't a TMDB country code."""
    from users.countries import TMDB_COUNTRIES

    code = str(code or "").strip().upper()
    return code if _REGION.match(code) and code in TMDB_COUNTRIES else ""


def region_from_accept_language(header: str) -> str:
    """The first language tag with a region in an Accept-Language header: "fr-CA,fr;q=0.9" -> "CA"."""
    for part in str(header or "").split(","):
        tag = part.split(";")[0].strip().replace("_", "-")
        bits = tag.split("-")
        for bit in bits[1:]:
            region = valid_region(bit) if len(bit) == 2 else ""
            if region:
                return region
    return ""


def request_region(request, profile=None) -> str:
    """The country of the "On Netflix" rows / the service filter: the app's ?region= (the visitor's
    browser region, frontend utils/watchRegion.js), else the request's Accept-Language region, else
    the region of the profile's language, else the US."""
    region = valid_region(request.query_params.get("region")) if request is not None else ""
    if not region and request is not None:
        region = region_from_accept_language(request.META.get("HTTP_ACCEPT_LANGUAGE", ""))
    if not region and profile is not None:
        lang = str(profile.language_preference or "").replace("_", "-")
        base, _, rest = lang.partition("-")
        region = valid_region(rest) if len(rest) == 2 else ""
        region = region or LANGUAGE_REGION.get(base.lower(), "")
    return region or DEFAULT_REGION
