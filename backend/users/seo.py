# users/seo.py
"""
What search engines and link previews see: the app's page shell with real tags, real status
codes, and the sitemaps.

The app renders in the browser, so every URL used to get the same index.html: one title, one
description, one preview image, and status 200 even for pages that don't exist. nginx now sends
every app URL that isn't a file (see nginx/default.conf, "@spa") here, and this module answers
with the frontend's index.html, rewritten for that page:

  /movies/<id>, /tv/<id>   the title's name (in the page's language), synopsis, poster, canonical
                           URL, hreflang links to every language, JSON-LD Movie / TVSeries;
                           404 when the title doesn't exist
  /actor/<tmdb id>         the actor's name and photo, JSON-LD Person; 404 when unknown
  other app routes         the shell as is (status 200)
  anything else            the shell with status 404 + noindex (the app shows "Page not found")

Everyone gets the same HTML (no crawler sniffing). The language of a page is ?lng=<code> (the
same parameter the app reads), English without it; hreflang links point at each ?lng= variant.

index.html comes from the frontend container (FRONTEND_INDEX_URL) with a conditional GET on every
request, so a deploy is picked up at once: a cached shell would point at JS bundles that no
longer exist. FRONTEND_INDEX_FILE (a path) is used instead when set (local runs / tests).

Sitemaps (/sitemap.xml + its parts) are built from the database and cached for a few hours, so
they no longer need a script run by hand.
"""
import html
import json
import logging
import re
import threading
from pathlib import Path

import requests
from django.conf import settings
from django.core.cache import cache
from django.http import HttpResponse, HttpResponseNotFound
from django.utils import translation
from django.utils.translation import gettext as _

from .i18n import APP_LANGUAGES, DEFAULT_LANGUAGE, RTL_LANGUAGES, to_app_language, to_django_language
from .models import Actor, Title, TitleTranslation

log = logging.getLogger(__name__)

SITE_NAME = "Tauruss"
DESCRIPTION_LENGTH = 160
# pages per sitemap file: each page is listed once per language (13 <url>s), each with links to
# all its languages, so a file holds 13,000 URLs and weighs ~20 MB (the limits: 50,000 / 50 MB)
SITEMAP_PAGES_PER_FILE = 1_000
SITEMAP_CACHE_SECONDS = 6 * 3600

# og:locale per app language
OG_LOCALES = {"en": "en_US", "fr": "fr_FR", "es": "es_ES", "de": "de_DE", "it": "it_IT", "ja": "ja_JP",
              "zh": "zh_CN", "hi": "hi_IN", "pt": "pt_BR", "ru": "ru_RU", "bn": "bn_BD", "ar": "ar_AR", "ur": "ur_PK"}
# hreflang per app language (BCP 47)
HREFLANGS = {"zh": "zh-Hans", "pt": "pt-BR"}

# Routes of the app (frontend/src/App.js) that aren't title / actor pages. Keep in sync.
APP_ROUTES = [re.compile(p) for p in (
    r"^/$",
    r"^/(profiles|search|movies|tv|list|register|login|create-profile|choose-subscription)/?$",
    r"^/(taste|import|calendar|history|stats|pick)/?$",
    r"^/(collection|lists)/[^/]+/?$",
    r"^/account/[^/]+/?$",
    r"^/watch/[^/]+/?$",
    r"^/reset-password/[^/]+/[^/]+/?$",
    r"^/confirm-email-change(/[^/]+/[^/]+)?/?$",
    r"^/admin(/.*)?$",
)]

# Tags of the shell that each page replaces (index.html keeps them for the home page)
_REPLACED_TAGS = re.compile(
    r"""\s*(<title>.*?</title>"""
    r"""|<meta\s+name="(description|robots|googlebot|twitter:[\w:]+)"[^>]*>"""
    r"""|<meta\s+property="og:[\w:]+"[^>]*>"""
    r"""|<link\s+rel="(canonical|alternate)"[^>]*>)""",
    re.S | re.I,
)


# ---------------------------------------------------------------- index.html from the frontend

class _Shell:
    """The frontend's index.html, revalidated on every use (ETag / Last-Modified)."""

    def __init__(self):
        self._lock = threading.Lock()
        self._html = None
        self._validators = {}

    def get(self):
        path = getattr(settings, "FRONTEND_INDEX_FILE", "")
        if path:
            return Path(path).read_text(encoding="utf-8")
        url = settings.FRONTEND_INDEX_URL
        with self._lock:
            headers = {}
            if self._html is not None:
                if self._validators.get("etag"):
                    headers["If-None-Match"] = self._validators["etag"]
                if self._validators.get("last-modified"):
                    headers["If-Modified-Since"] = self._validators["last-modified"]
            try:
                res = requests.get(url, headers=headers, timeout=3)
                if res.status_code == 304 and self._html is not None:
                    return self._html
                res.raise_for_status()
                res.encoding = "utf-8"
                self._html = res.text
                self._validators = {k: res.headers.get(k) for k in ("etag", "last-modified")}
            except requests.RequestException:
                if self._html is None:
                    raise
                log.warning("seo: %s unreachable, using the last index.html", url)
            return self._html


shell = _Shell()


# ---------------------------------------------------------------- helpers

def _site():
    return settings.SITE_URL.rstrip("/")


def _lang(request):
    return to_app_language(request.GET.get("lng"), DEFAULT_LANGUAGE)


def _page_url(path, lang):
    return f"{_site()}{path}" + ("" if lang == DEFAULT_LANGUAGE else f"?lng={lang}")


def _clip(text, length=DESCRIPTION_LENGTH):
    text = " ".join((text or "").split())
    if len(text) <= length:
        return text
    cut = text[: length - 1].rsplit(" ", 1)[0].rstrip(",;:.-–")
    return cut + "…"


def _esc(value):
    return html.escape(str(value), quote=True)


def _json_ld(data):
    # "</" can't appear inside the <script>
    return json.dumps(data, ensure_ascii=False).replace("</", "<\\/")


def _head(*, title, description, path, lang, image=None, og_type="website", noindex=False, json_ld=None):
    """The tags that replace the shell's ones, before </head>."""
    url = _page_url(path, lang)
    tags = [f"<title>{_esc(title)}</title>",
            f'<meta name="description" content="{_esc(description)}" />']
    if noindex:
        tags.append('<meta name="robots" content="noindex" />')
    else:
        tags.append('<meta name="robots" content="index, follow, max-image-preview:large" />')
        tags.append(f'<link rel="canonical" href="{_esc(url)}" />')
        for code in APP_LANGUAGES:
            tags.append(f'<link rel="alternate" hreflang="{HREFLANGS.get(code, code)}" href="{_esc(_page_url(path, code))}" />')
        tags.append(f'<link rel="alternate" hreflang="x-default" href="{_esc(_page_url(path, DEFAULT_LANGUAGE))}" />')
    tags += [
        f'<meta property="og:type" content="{og_type}" />',
        f'<meta property="og:site_name" content="{SITE_NAME}" />',
        f'<meta property="og:title" content="{_esc(title)}" />',
        f'<meta property="og:description" content="{_esc(description)}" />',
        f'<meta property="og:url" content="{_esc(url)}" />',
        f'<meta property="og:locale" content="{OG_LOCALES.get(lang, "en_US")}" />',
        f'<meta name="twitter:card" content="{"summary_large_image" if image else "summary"}" />',
        f'<meta name="twitter:title" content="{_esc(title)}" />',
        f'<meta name="twitter:description" content="{_esc(description)}" />',
    ]
    if image:
        tags += [f'<meta property="og:image" content="{_esc(image)}" />',
                 f'<meta name="twitter:image" content="{_esc(image)}" />']
    if json_ld:
        tags.append(f'<script type="application/ld+json">{_json_ld(json_ld)}</script>')
    return "\n  ".join(tags)


def render_shell(head, lang, status=200):
    page = _REPLACED_TAGS.sub("", shell.get())
    page = page.replace("</head>", f"  {head}\n</head>", 1)
    # right-to-left languages are mirrored from the first paint, before the app loads
    direction = "rtl" if lang in RTL_LANGUAGES else "ltr"
    page = re.sub(r'<html lang="[^"]*"(\s+dir="[^"]*")?', f'<html lang="{HREFLANGS.get(lang, lang)}" dir="{direction}"', page, count=1)
    res = HttpResponse(page, status=status, content_type="text/html; charset=utf-8")
    res["Cache-Control"] = "no-cache"  # the shell names the current JS bundles
    return res


def _image(url):
    if not url:
        return None
    return url if url.startswith("http") else f"https://image.tmdb.org/t/p/w780{url}"


# ---------------------------------------------------------------- pages

def _title_page(request, title_id):
    lang = _lang(request)
    t = Title.objects.filter(pk=title_id).first()
    if t is None:
        return _not_found(request)

    name, overview = t.title, t.description
    if lang != DEFAULT_LANGUAGE:
        tr = TitleTranslation.objects.filter(title=t, language=lang).first()
        if tr:
            name, overview = tr.name or name, tr.overview or overview

    # canonical path follows the title's type (a show opened as /movies/<id> points at /tv/<id>)
    path = f"/{'tv' if t.type == 'tv' else 'movies'}/{t.pk}"
    year = t.release_year or (t.first_air_date[:4] if t.first_air_date else "")
    title = f"{name} ({year}) | {SITE_NAME}" if year else f"{name} | {SITE_NAME}"
    with translation.override(to_django_language(lang)):
        description = _clip(overview) or _("Watch %(name)s on Tauruss.") % {"name": name}
    image = _image(t.landscape_image) or _image(t.poster)

    ld = {
        "@context": "https://schema.org",
        "@type": "TVSeries" if t.type == "tv" else "Movie",
        "name": name,
        "url": _page_url(path, lang),
        "inLanguage": HREFLANGS.get(lang, lang),
    }
    if overview:
        ld["description"] = _clip(overview, 500)
    if t.poster:
        ld["image"] = _image(t.poster)
    if t.release_date or t.first_air_date:
        ld["startDate" if t.type == "tv" else "datePublished"] = t.first_air_date or t.release_date
    if t.genre:
        ld["genre"] = [g.strip() for g in t.genre.split(",") if g.strip()]
    if t.director:
        ld["director"] = {"@type": "Person", "name": t.director}
    if t.vote_average and t.vote_count:
        ld["aggregateRating"] = {"@type": "AggregateRating", "ratingValue": round(t.vote_average, 1),
                                 "bestRating": 10, "ratingCount": t.vote_count}

    head = _head(title=title, description=description, path=path, lang=lang, image=image,
                 og_type="video.tv_show" if t.type == "tv" else "video.movie", json_ld=ld)
    return render_shell(head, lang)


def movie_page(request, title_id):
    return _title_page(request, title_id)


def tv_page(request, title_id):
    return _title_page(request, title_id)


def actor_page(request, tmdb_id):
    lang = _lang(request)
    actor = (Actor.objects.filter(tmdb_id=tmdb_id).exclude(name="")
             .order_by("-profile_path").values("name", "profile_path").first())
    if actor is None:
        return _not_found(request)
    path = f"/actor/{tmdb_id}"
    with translation.override(to_django_language(lang)):
        description = _("Movies and TV shows with %(name)s.") % {"name": actor["name"]}
    image = _image(actor["profile_path"])
    ld = {"@context": "https://schema.org", "@type": "Person", "name": actor["name"], "url": _page_url(path, lang)}
    if image:
        ld["image"] = image
    head = _head(title=f"{actor['name']} | {SITE_NAME}", description=description, path=path, lang=lang,
                 image=image, og_type="profile", json_ld=ld)
    return render_shell(head, lang)


def list_page(request, share_id):
    """A shared list (/l/<share_id>): its name, what's in it, the first poster. Private or
    unknown: a real 404 (nobody can guess what a private list holds)."""
    from reco.models import UserList, UserListItem

    lst = UserList.objects.filter(share_id=share_id, is_public=True).select_related("profile").first()
    if lst is None:
        return _not_found(request)
    lang = _lang(request)
    path = f"/l/{share_id}"
    titles = list(
        UserListItem.objects.filter(user_list=lst).order_by("added_at", "id")
        .values_list("title__title", "title__poster")[:50]
    )
    names = [t for t, _p in titles]
    description = lst.description or ", ".join(names[:6])
    image = _image(next((p for _t, p in titles if p), None))
    ld = {
        "@context": "https://schema.org", "@type": "ItemList", "name": lst.name, "url": _page_url(path, lang),
        "numberOfItems": len(titles),
        "itemListElement": [{"@type": "ListItem", "position": i + 1, "name": n} for i, n in enumerate(names)],
    }
    head = _head(title=f"{lst.name} | {SITE_NAME}", description=_clip(f"{lst.profile.name}: {description}"),
                 path=path, lang=lang, image=image, json_ld=ld)
    return render_shell(head, lang)


def _not_found(request):
    lang = _lang(request)
    with translation.override(to_django_language(lang)):
        title = _("Page not found")
    head = _head(title=f"{title} | {SITE_NAME}", description=title, path=request.path, lang=lang, noindex=True)
    return render_shell(head, lang, status=404)


def app_page(request, path=""):
    """Any other URL nginx couldn't find as a file: an app route (200) or not (404)."""
    if any(r.match(request.path) for r in APP_ROUTES):
        res = HttpResponse(shell.get(), content_type="text/html; charset=utf-8")
        res["Cache-Control"] = "no-cache"
        return res
    return _not_found(request)


# ---------------------------------------------------------------- sitemaps

def _sitemap_sections():
    """{"movies": [ids], "tv": [ids], "actors": [tmdb ids]}: cached, the queries are heavy."""
    data = cache.get("seo:sitemap")
    if data is None:
        data = {
            "movies": list(Title.objects.filter(type="movie").order_by("id").values_list("id", flat=True)),
            "tv": list(Title.objects.filter(type="tv").order_by("id").values_list("id", flat=True)),
            "actors": list(Actor.objects.filter(tmdb_id__isnull=False).values_list("tmdb_id", flat=True)
                           .distinct().order_by("tmdb_id")),
        }
        cache.set("seo:sitemap", data, SITEMAP_CACHE_SECONDS)
    return data


SITEMAP_PATHS = {"movies": "/movies/{}", "tv": "/tv/{}", "actors": "/actor/{}"}
STATIC_PAGES = ("/", "/movies", "/tv")


def _xml(body):
    res = HttpResponse('<?xml version="1.0" encoding="UTF-8"?>\n' + body, content_type="application/xml; charset=utf-8")
    res["Cache-Control"] = "public, max-age=3600"
    return res


def sitemap_index(request):
    site = _site()
    files = ["sitemap-static.xml"]
    for section, ids in _sitemap_sections().items():
        pages = max(1, -(-len(ids) // SITEMAP_PAGES_PER_FILE)) if ids else 0
        files += [f"sitemap-{section}-{n}.xml" for n in range(1, pages + 1)]
    items = "".join(f"<sitemap><loc>{site}/{f}</loc></sitemap>" for f in files)
    return _xml(f'<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{items}</sitemapindex>')


def _urlset(paths):
    """Every page in every language (?lng=), each listing all its languages: how Google finds
    and pairs the translated pages (the same links as in each page's <head>)."""
    items = []
    for path in paths:
        urls = {code: _esc(_page_url(path, code)) for code in APP_LANGUAGES}
        links = "".join(f'<xhtml:link rel="alternate" hreflang="{HREFLANGS.get(code, code)}" href="{url}"/>'
                        for code, url in urls.items())
        links += f'<xhtml:link rel="alternate" hreflang="x-default" href="{urls[DEFAULT_LANGUAGE]}"/>'
        items += [f"<url><loc>{url}</loc>{links}</url>" for url in urls.values()]
    return _xml('<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9" xmlns:xhtml="http://www.w3.org/1999/xhtml">'
                + "".join(items) + "</urlset>")


def sitemap_static(request):
    return _urlset(STATIC_PAGES)


def sitemap_section(request, section, page):
    if section not in SITEMAP_PATHS:
        return HttpResponseNotFound()
    ids = _sitemap_sections()[section]
    chunk = ids[(page - 1) * SITEMAP_PAGES_PER_FILE: page * SITEMAP_PAGES_PER_FILE]
    if page < 1 or not chunk:
        return HttpResponseNotFound()
    return _urlset(SITEMAP_PATHS[section].format(i) for i in chunk)
