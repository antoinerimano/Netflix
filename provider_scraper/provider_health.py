#!/usr/bin/env python3
"""
provider_health.py - does an embed provider play, the way tauruss plays it?

Every test reproduces the site (frontend WatchPage.jsx, titlesApi.buildProviderLinks):
  * the player is loaded in an <iframe> of a page on the site's own origin (catalog
    "site_origin", from manage.py export_providers), with the site's iframe attributes and
    referrer policy, so the player sees what it sees on tauruss
  * the link is built like the frontend builds it (domain + path, ids filled in)
  * the site's rules: an iframe page that hasn't loaded after 15 s is a failure (the site moves on
    to the next source), and the players' postMessage events the site reads (Videasy, CineSrc,
    VidCore) count as proof of playback
Run it from the mini PC: its network, not an office one that blocks some providers.

A title plays when, within ~35 s, a feature-length video (40 min+ for a movie, 10 min+ for an
episode) moves or its stream is there, or the player reports playback (postMessage). Not its TMDB
runtime: director's cuts, credits and other edits differ. A trailer, an ad or a "not available"
clip is too short; the same default video for every id shows up as 3+ titles of the very same
length.

The titles: what the viewers watch lately on the site (catalog "test_titles"), topped up with
popular ones; FILMS / EPISODES when the site gave none. A provider is "live" when it plays at least
90 % of the titles that at least one provider plays (a title nobody plays is nobody's fault):
a limited catalog shows up. Its TV link is kept on the same rule for the episodes.

Link formats tried to find the one that plays (in order): the site's current link, the formats
of its API docs, the ones seen on streaming sites, its docs' example URLs, the usual structures on
its domain, then the best one on its other KNOWN domains (backups, seen on sites, in its docs).
Domains are never guessed: vidlink.ru is not vidlink.

States, strongest first:
  live       - plays >= 90 % of the titles some provider plays
  partial    - a link format plays, but fewer titles (limited catalog, slow, some broken)
  up         - a stream starts but not the title (wrong video, never moves), or too slow for the site
  no_source  - the player says the title isn't available
  unverified - the page loads and the player asks for nothing: maybe it blocks automated browsers
               (vidfast, 111movies play for people). No verdict: the import changes nothing
  protected  - a Cloudflare / bot check answered (no verdict either)
  down       - DNS failure, connection error, timeout or HTTP 5xx
  untested   - no domain or test URL known

Usage (standalone):  python provider_health.py [-c provider_catalog.json] [-p xpass,vidlink]
"""

import argparse, asyncio, json, os, re, time
from urllib.parse import urlparse, urljoin

# When the site gave no test titles: well-known movies and an episode ("minutes": for information).
FILMS = [
    {"tmdb": 550, "imdb": "tt0137523", "name": "Fight Club", "minutes": 139},
    {"tmdb": 27205, "imdb": "tt1375666", "name": "Inception", "minutes": 148},
    {"tmdb": 238, "imdb": "tt0068646", "name": "The Godfather", "minutes": 175},
    {"tmdb": 680, "imdb": "tt0110912", "name": "Pulp Fiction", "minutes": 154},
    {"tmdb": 289, "imdb": "tt0034583", "name": "Casablanca", "minutes": 102},
]
EPISODES = [{"tmdb": 1396, "imdb": "tt0903747", "season": 1, "episode": 1, "name": "Breaking Bad 1x01", "minutes": 58}]
PROBE = {"tmdb": FILMS[0]["tmdb"], "imdb": FILMS[0]["imdb"]}  # app.py

MIN_MOVIE_S = 40 * 60   # a movie stream at least this long (not a trailer / ad / "not available" clip)
MIN_EPISODE_S = 10 * 60
MAX_MOVIE_S = 6 * 3600  # longer: not the one movie (a whole collection, a broken playlist)
MAX_EPISODE_S = 3 * 3600  # longer: not the one episode (a whole season)
SAME_VIDEO = 3          # this many titles with the very same length: one default video for every id
COVERAGE = 0.9          # share of the titles some provider plays that a provider must play
MAX_MISSES = 3          # titles missed: it can't reach COVERAGE any more, stop testing it
NO_VERDICT = ("unverified", "protected", "untested")  # a title that couldn't be judged: not a miss
MAX_NO_VERDICT = 0.3    # more of those than this share of the titles: the provider gets no verdict
SITE_LOAD_TIMEOUT = 15  # s: frontend SOURCE_LOAD_TIMEOUT_MS, the site moves on to the next source
PLAY_WINDOW = 35        # s: how long a title gets to start
# frontend WatchPage.jsx <iframe allow=...>
IFRAME_ALLOW = "autoplay; fullscreen *; picture-in-picture; encrypted-media"
REFERRER_POLICY = "strict-origin-when-cross-origin"  # nginx/security-headers.inc

STREAM = re.compile(r"\.(m3u8|mpd)(\?|$)|\.mp4(\?|$)|/(playlist|master|index)\.m3u8|/hls/|/manifest", re.I)
NO_SOURCE = re.compile(r"(not found|no sources?|unavailable|could ?n.t find|doesn.t exist|does not exist|"
                       r"no (video|stream|links?)|error 404|404 not|media not|try (another|other) server|"
                       r"coming soon|not (yet )?released)", re.I)
CHALLENGE = re.compile(r"just a moment|attention required|un instant|checking your browser|verify you are human", re.I)
NOISE = re.compile(r"doubleclick|googlesyndication|google-analytics|googletagmanager|youtube|ytimg|"
                   r"jwpcdn|jwplayer\.com/v|vast|preroll|/ads?/", re.I)
EXTINF = re.compile(r"#EXTINF:\s*([0-9.]+)")
MPD_DURATION = re.compile(r'mediaPresentationDuration="PT(?:(\d+)H)?(?:(\d+)M)?(?:([0-9.]+)S)?"')
SEGMENT = re.compile(r"\.(ts|m4s|aac|m4a|m4v|mp4|webm)(\?|$)|/seg|/frag|/chunk", re.I)

PLAY_JS = r"""() => {
  const vis = el => !!(el && (el.offsetParent || el.getClientRects().length));
  const cands = ['.jw-icon-playback', '.jw-display-icon-container', '.vjs-big-play-button',
    '.plyr__control--overlaid', 'button[aria-label*=play i]', '[class*=play-btn]', '[class*=btn-play]',
    '[class*=play-button]', '[id*=play]', '[class*=play]', 'video'];
  for (const s of cands) {
    const el = [...document.querySelectorAll(s)].find(vis);
    if (el) { try { el.click(); } catch (e) {} if (el.tagName === 'VIDEO') { try { el.muted = true; el.play(); } catch (e) {} } return s; }
  }
  return null;
}"""

# every <video> of the frame: its duration and how far it got
VIDEO_JS = r"""() => [...document.querySelectorAll('video')].map(v => {
  try { if (v.paused) { v.muted = true; v.play().catch(() => {}); } } catch (e) {}
  return {duration: isFinite(v.duration) ? v.duration : null, time: v.currentTime || 0};
})"""


def site_page(origin_url: str, embed_url: str) -> str:
    """The tauruss watch page, reduced to its player: the iframe as WatchPage.jsx renders it."""
    esc = embed_url.replace("&", "&amp;").replace('"', "&quot;")
    return f"""<!doctype html><html><head><meta charset="utf-8">
<meta name="referrer" content="{REFERRER_POLICY}"><title>tauruss</title></head>
<body style="margin:0;background:#000">
<iframe id="player" src="{esc}" title="Player" allow="{IFRAME_ALLOW}" allowfullscreen
  webkitallowfullscreen="true" mozallowfullscreen="true"
  style="width:1280px;height:720px;border:0"
  onload="window.__loadedAt = window.__loadedAt || performance.now()"></iframe>
<script>
  // the players' postMessage events, as WatchPage.jsx receives them
  window.__events = [];
  window.addEventListener("message", (e) => {{
    const f = document.getElementById("player");
    if (!f || e.source !== f.contentWindow) return;
    try {{ window.__events.push(typeof e.data === "string" ? e.data : JSON.stringify(e.data)); }} catch (x) {{}}
  }});
</script></body></html>"""


def player_event(raw: str) -> dict | None:
    """frontend playerEvents.readPlayerEvent: -> {playing, position, duration} (seconds) or None."""
    data = raw
    if isinstance(data, str):
        if data.startswith("vidcore:"):
            data = {"type": data}
        else:
            try:
                data = json.loads(data)
            except ValueError:
                return None
    if not isinstance(data, dict) or not isinstance(data.get("type"), str):
        return None

    def num(v):
        try:
            return float(v)
        except (TypeError, ValueError):
            return None
    t = data["type"]
    if t == "PLAYER_EVENT":  # Videasy
        d = data.get("data")
        if isinstance(d, str):
            try:
                d = json.loads(d)
            except ValueError:
                return None
        if not isinstance(d, dict):
            return None
        pos = num(d.get("player_progress"))
        return {"playing": d.get("player_status") == "playing" or (pos or 0) > 0,
                "position": pos, "duration": num(d.get("player_duration"))}
    if t.startswith("cinesrc:"):
        kind = t[len("cinesrc:"):]
        if kind in ("timeupdate", "seeked"):
            pos = num(data.get("currentTime"))
            return {"playing": (pos or 0) > 0, "position": pos, "duration": num(data.get("duration"))}
        return {"playing": True} if kind == "play" else None
    if t == "vidcore:play":
        return {"playing": True}
    return None


def _sub_ids(u: str) -> str | None:
    """Docs format / seen template -> '{tmdb}' '{imdb}' '{season}' '{episode}' template, or None."""
    u = u.strip().rstrip(".,;)`'\"")
    u = re.sub(r"\$\{(\w+)\}", r"{\1}", u)  # JS template literals: /movie/${tmdbId}
    u = re.sub(r"\{\{\s*(\w+)\s*\}\}", r"{\1}", u)  # {{tmdb_id}}
    u = re.sub(r"\{(tmdb_?id|tmdbId|tmdb|id|movie_?id|tv_?id|show_?id)\}|\$id\b|\[(tmdb_?id|id)\]|:id\b|<(tmdb_?id|id)>",
               "{tmdb}", u, flags=re.I)
    u = re.sub(r"\{(imdb_?id|imdbId|imdb)\}|\{tt[^}]*\}|\[(imdb_?id)\]|<(imdb_?id)>", "{imdb}", u, flags=re.I)
    u = re.sub(r"\{(season|season_?number|s|ss)\}|\$s\b", "{season}", u, flags=re.I)
    u = re.sub(r"\{(episode|episode_?number|e|ep)\}|\$e\b", "{episode}", u, flags=re.I)
    if not u.startswith("http") or not re.search(r"\{(tmdb|imdb)\}", u):
        return None
    if re.search(r"[\[\]<>$]", u) or re.search(r"[{}]", re.sub(r"\{(tmdb|imdb|season|episode)\}", "", u)):
        return None
    return u


def _concrete(u: str) -> str | None:
    """A docs example URL (/movie/786892, /e/tt1234567) -> template."""
    u = u.strip().rstrip(".,;)")
    if not u.startswith("http") or "{" in u:
        return None
    t = re.sub(r"\btt\d{7,8}\b", "{imdb}", u)
    if t == u:
        t = re.sub(r"(?<=[/=])\d{2,8}(?=[/?&#]|$)", "{tmdb}", u, count=1)
    return t if t != u else None


def is_episode(t: str) -> bool:
    return "{season}" in t and "{episode}" in t


def is_movie(t: str) -> bool:
    return not re.search(r"\{season\}|\{episode\}|/(tv|series|anime|episode)\b|season", t, re.I)


# The usual link structures, tried on the provider's domain when its documented / seen formats
# don't play (a wrong structure looks exactly like a dead provider).
COMMON_MOVIE = ["/movie/{tmdb}", "/embed/movie/{tmdb}", "/embed/movie?tmdb={tmdb}", "/e/movie/{tmdb}",
                "/embed/{tmdb}", "/movie/{imdb}", "/embed/movie/{imdb}", "/embed/movie?imdb={imdb}"]
COMMON_EPISODE = ["/tv/{tmdb}/{season}/{episode}", "/embed/tv/{tmdb}/{season}/{episode}",
                  "/embed/tv?tmdb={tmdb}&season={season}&episode={episode}", "/e/tv/{tmdb}/{season}/{episode}",
                  "/tv/{tmdb}/{season}-{episode}", "/embed/tv/{tmdb}/{season}-{episode}"]


def templates(p: dict) -> tuple[list[tuple[str, str]], list[str]]:
    """
    -> ([(movie template, source)], episode templates), best first. Sources: "current" (the site's
    link), "docs" (its API docs), "site" (seen on a streaming site), "docs example", "guess".
    """
    fmts = p.get("formats") or p.get("doc_formats") or []
    seen = [p.get("template")] + list(p.get("observed_templates") or [])
    current = p.get("site_link") or {}  # the link our site uses now: first, a working one stays
    cands = ([(_sub_ids(current["movie"]), "current")] if current.get("movie") else [])
    cands += ([(_sub_ids(f), "docs") for f in fmts] + [(_sub_ids(f), "site") for f in seen if f]
              + [(_concrete(f), "docs example") for f in fmts])
    movie, episode = [], []
    if current.get("episode") and _sub_ids(current["episode"]):
        episode.append(_sub_ids(current["episode"]))
    for t, src in cands:
        if not t:
            continue
        if is_movie(t) and t not in [m for m, _ in movie]:
            movie.append((t, src))
        elif is_episode(t) and t not in episode:
            episode.append(t)
    movie = movie[:7]
    hosts = [urlparse(t).hostname for t, _ in movie] + list(p.get("hosts") or []) + list(p.get("domains") or [])
    host = next((h for h in hosts if h), None)
    if host:
        for path in COMMON_MOVIE:
            t = f"https://{host}{path}"
            if t not in [m for m, _ in movie]:
                movie.append((t, "guess"))
        for path in COMMON_EPISODE:
            t = f"https://{host}{path}"
            if t not in episode:
                episode.append(t)
    return movie, episode[:8]


def fill(template: str, title: dict) -> str | None:
    """Like the frontend: the link, or None when the title lacks a value the link needs."""
    values = {"tmdb": title.get("tmdb"), "imdb": title.get("imdb"),
              "season": title.get("season"), "episode": title.get("episode")}
    missing = False

    def sub(m):
        nonlocal missing
        v = values.get(m.group(1))
        if v in (None, ""):
            missing = True
            return ""
        return str(v)
    url = re.sub(r"\{(tmdb|imdb|season|episode)\}", sub, template)
    return None if missing else url


def _manifest_seconds(body: str) -> float | None:
    if body.startswith("#EXTM3U"):
        if "#EXT-X-ENDLIST" not in body and "#EXTINF" in body and "#EXT-X-PLAYLIST-TYPE:VOD" not in body:
            return None  # a live / sliding playlist: not a film
        total = sum(float(x) for x in EXTINF.findall(body))
        return total or None
    m = MPD_DURATION.search(body[:5000])
    if m:
        return int(m.group(1) or 0) * 3600 + int(m.group(2) or 0) * 60 + float(m.group(3) or 0)
    return None


async def play_title(ctx, url: str, title: dict, site: str | None = None, timeout_ms: int = 25000) -> dict:
    """
    Open one embed URL the way tauruss does (in an iframe on a page of the site's origin) and
    prove the title plays. -> {state, detail, load_s, play_s, events, ...}
    """
    page = await ctx.new_page()
    seen = {"stream": None, "manifests": [], "segments": 0, "variants": [], "main_status": None}
    tasks = []

    async def read_manifest(resp):
        try:
            if resp.status >= 400:
                return
            body = (await resp.text())[:400000]
        except Exception:
            return
        if body.startswith("#EXTM3U") and "#EXT-X-STREAM-INF" in body:
            # master playlist: the player fetches a variant next; remember it in case it doesn't
            m = re.search(r"#EXT-X-STREAM-INF[^\n]*\n([^\n#]+)", body)
            if m:
                seen["variants"].append((urljoin(resp.url, m.group(1).strip()), resp.url))
            return
        secs = _manifest_seconds(body)
        if secs:
            seen["manifests"].append(secs)

    def on_resp(resp):
        u = resp.url
        if u == url and seen["main_status"] is None:
            seen["main_status"] = resp.status  # the embed page itself
        if NOISE.search(u):
            return
        ct = (resp.headers.get("content-type") or "").lower()
        if STREAM.search(u) or "mpegurl" in ct or "dash+xml" in ct:
            seen["stream"] = seen["stream"] or urlparse(u).hostname
            if not u.lower().split("?")[0].endswith(".mp4"):
                tasks.append(asyncio.ensure_future(read_manifest(resp)))
        elif SEGMENT.search(u) or ct.startswith("video/") or "mp2t" in ct:
            if resp.status < 400:
                seen["segments"] += 1
        elif resp.request.resource_type in ("xhr", "fetch") and ("text/plain" in ct or "octet-stream" in ct):
            tasks.append(asyncio.ensure_future(read_manifest(resp)))  # disguised .m3u8
    page.on("response", on_resp)

    async def videos():
        out = []
        for fr in page.frames:
            try:
                out += await asyncio.wait_for(fr.evaluate(VIDEO_JS), 3) or []
            except Exception:
                pass
        return out

    async def events():
        try:
            raws = await asyncio.wait_for(page.evaluate("window.__events || []"), 3) if site else []
        except Exception:
            raws = []
        return [e for e in (player_event(r) for r in raws) if e]

    out = {"title": title["name"], "test_url": url, "http": None, "stream_host": None, "duration_min": None,
           "load_s": None, "play_s": None, "sends_events": False}
    t0 = time.monotonic()
    try:
        if site:
            page_url = site.rstrip("/") + "/__provider_scout"
            html = site_page(page_url, url)
            await page.route(page_url, lambda r: r.fulfill(body=html, content_type="text/html; charset=utf-8",
                                                           headers={"Referrer-Policy": REFERRER_POLICY}))
            await page.goto(page_url, timeout=timeout_ms, wait_until="domcontentloaded")
        else:
            resp = await page.goto(url, timeout=timeout_ms, wait_until="domcontentloaded")
            seen["main_status"] = resp.status if resp else None
        await page.wait_for_timeout(2500)

        first_time, clicked = None, False
        while time.monotonic() - t0 < PLAY_WINDOW:
            el = time.monotonic() - t0
            if out["load_s"] is None:
                if site:
                    try:
                        v = await asyncio.wait_for(page.evaluate("window.__loadedAt || null"), 3)
                    except Exception:
                        v = None
                    if v:
                        out["load_s"] = round(v / 1000, 1)
                else:
                    out["load_s"] = round(el, 1)
            ev = await events()
            vids = [v for v in await videos() if v["duration"] and v["duration"] > 60]
            t = max((v["time"] for v in vids), default=0)
            if any(e.get("playing") for e in ev) or t > 1:
                if first_time is None:
                    first_time = t
                    out["play_s"] = round(el, 1)
                elif t > first_time + 0.5 or any((e.get("position") or 0) > 2 for e in ev):
                    break  # it moves
            else:
                # press play like a viewer: the player's own button, then a click on the player
                for fr in page.frames[1:] if site else page.frames:
                    try:
                        await asyncio.wait_for(fr.evaluate(PLAY_JS), 3)
                    except Exception:
                        pass
                if not clicked and el > 6:
                    try:
                        await asyncio.wait_for(page.mouse.click(640, 360), 5)
                    except Exception:
                        pass
                    clicked = True
            if el > 15 and not seen["stream"] and not vids and not ev:
                break  # nothing at all after 15 s
            await page.wait_for_timeout(2500)

        # a stream body that never ends must not hold the test: 10 s for the manifests to be read
        await asyncio.wait({asyncio.ensure_future(t) for t in tasks}, timeout=10) if tasks else None
        if not seen["manifests"] and seen["variants"]:  # the player never fetched the variant itself
            v_url, ref = seen["variants"][0]
            try:
                r = await ctx.request.get(v_url, headers={"Referer": ref}, timeout=10000)
                secs = _manifest_seconds((await r.text())[:400000]) if r.ok else None
                if secs:
                    seen["manifests"].append(secs)
            except Exception:
                pass

        vids = await videos()
        ev = await events()
        out["sends_events"] = bool(ev)
        out["http"] = seen["main_status"]
        out["stream_host"] = seen["stream"]
        # a real feature / episode, not its length on TMDB (director's cuts, credits, other edits
        # differ): long enough not to be a trailer, an ad or a "not available" clip
        min_s, max_s = (MIN_EPISODE_S, MAX_EPISODE_S) if title.get("season") else (MIN_MOVIE_S, MAX_MOVIE_S)
        durations = ([v["duration"] for v in vids if v["duration"]] + seen["manifests"]
                     + [e["duration"] for e in ev if e.get("duration")])
        feature = max((d for d in durations if min_s <= d <= max_s), default=None)
        too_long = max((d for d in durations if d > max_s), default=None)
        moving = (any(v["time"] > 1 for v in vids if min_s <= (v["duration"] or 0) <= max_s) or seen["segments"] >= 2
                  or any((e.get("position") or 0) > 1 for e in ev))
        reported = any(e.get("playing") for e in ev)
        shortest = max(durations, default=None)
        out["duration_s"] = round(feature or shortest) if (feature or shortest) else None
        out["duration_min"] = round(out["duration_s"] / 60) if out["duration_s"] else None
        slow = out["load_s"] is None or out["load_s"] > SITE_LOAD_TIMEOUT
        played = (feature and moving) or (reported and moving and not feature and not too_long
                                           and not (shortest and shortest < min_s))
        if played and slow and not (out["play_s"] and out["play_s"] <= SITE_LOAD_TIMEOUT):
            return {**out, "state": "up", "detail": f"plays, but the page took over {SITE_LOAD_TIMEOUT} s to load: "
                                                    f"the site moves on to the next source"}
        if played:
            return {**out, "state": "live", "detail": f"plays ({out['duration_min'] or '?'} min, "
                                                      f"page {out['load_s']} s, video {out['play_s']} s)"}
        if feature:
            # a feature-length stream is there; its start wasn't seen in the window (the mini PC
            # busy with other tests, a slow first segment): the title is available
            return {**out, "state": "live", "detail": f"a {round(feature / 60)} min stream, start not seen"}
        if too_long:
            return {**out, "state": "up", "detail": f"a {round(too_long / 3600, 1)} h video: not this one title "
                                                    f"(a whole season / collection, or a broken playlist)"}
        if shortest:
            return {**out, "state": "up", "detail": f"only a {round(shortest / 60, 1)} min video (trailer, ad or "
                                                    f"'not available' clip)"}
        if seen["stream"]:
            return {**out, "state": "up", "detail": "a stream was requested, but no video of the title's length"}
        text = ""
        for fr in page.frames[:5]:
            try:
                text += " " + (await asyncio.wait_for(fr.evaluate("() => document.body ? document.body.innerText.slice(0, 3000) : ''"), 3))
            except Exception:
                pass
        status = seen["main_status"]
        try:
            frame_titles = " ".join([await asyncio.wait_for(f.title(), 3) for f in page.frames[1:2]] if site else [])
        except Exception:
            frame_titles = ""
        if CHALLENGE.search(text) or CHALLENGE.search(frame_titles):
            return {**out, "state": "protected", "detail": "Cloudflare / bot check"}
        if status and status >= 500:
            return {**out, "state": "down", "detail": f"HTTP {status}"}
        if status == 404 or NO_SOURCE.search(text):
            m = NO_SOURCE.search(text)
            return {**out, "state": "no_source", "detail": m.group(0) if m else "HTTP 404"}
        if status and status >= 400:
            return {**out, "state": "down" if status != 403 else "protected", "detail": f"HTTP {status}"}
        if status is None and site:
            return {**out, "state": "down", "detail": "the embed page didn't answer (domain down or unreachable)"}
        # nothing at all: no stream asked for, no error shown. Some players do that for an
        # automated browser (vidfast) and play fine for people: can't tell, so no verdict
        return {**out, "state": "unverified", "detail": "page loads, the player asks for nothing (blocks automated browsers?)"}
    except Exception as e:
        msg = str(e).splitlines()[0] if str(e) else type(e).__name__
        kind = ("DNS: domain not found" if "ERR_NAME_NOT_RESOLVED" in msg else
                "timeout" if "Timeout" in msg else
                "certificate error" if "CERT" in msg else
                "connection refused/closed" if re.search(r"CONNECTION|ERR_EMPTY", msg) else msg[:80])
        return {**out, "state": "down", "detail": kind}
    finally:
        for t in tasks:
            t.cancel()
        try:
            await asyncio.wait_for(page.close(), 10)
        except Exception:
            pass


def with_host(template: str, host: str) -> str:
    u = urlparse(template)
    return template.replace(f"{u.scheme}://{u.netloc}", f"{u.scheme}://{host}", 1)


def other_domains(p: dict, movie_ts: list[str], tried: list[str]) -> list[str]:
    """
    The first movie template on the provider's other KNOWN domains: its backups on the site, the
    ones seen on streaming sites and in its docs. Never guessed ones (vidlink.ru, vidlink.site...
    are other sites, maybe clones).
    """
    if not movie_ts:
        return []
    base = movie_ts[0]
    out = []
    known = [h for h in (p.get("hosts") or []) + (p.get("domains") or []) if h]
    for h in known:
        t = with_host(base, h.lower())
        if t not in tried and t not in out:
            out.append(t)
    return out


RANK = {"live": 7, "partial": 6, "up": 5, "no_source": 4, "unverified": 3, "protected": 2, "down": 1, "untested": 0}
TRUSTED = ("current", "docs", "site", "docs example")  # formats that get a second chance


VERBOSE = False  # -v: one line per title tried, as it happens
TITLE_TIMEOUT = PLAY_WINDOW + 40  # s: a title can never hold the test longer, whatever a player does


async def bounded_play_title(ctx, url: str, title: dict, site: str | None) -> dict:
    try:
        return await asyncio.wait_for(play_title(ctx, url, title, site), TITLE_TIMEOUT)
    except asyncio.TimeoutError:
        return {"title": title["name"], "test_url": url, "state": "up",
                "detail": f"the player hung the test page for {TITLE_TIMEOUT} s"}


async def play(ctx, template: str, title: dict, site: str | None, retry: bool) -> dict:
    r = await _play(ctx, template, title, site, retry)
    if VERBOSE:
        print(f"    {urlparse(template).hostname} · {title['name'][:40]} -> {r['state']}: {r.get('detail', '')[:90]}",
              flush=True)
    return r


async def _play(ctx, template: str, title: dict, site: str | None, retry: bool) -> dict:
    """One title with one link format; a miss tried once more when retry (slow CDN, a click that didn't land)."""
    url = fill(template, title)
    if not url:
        return {"title": title["name"], "state": "untested", "detail": "the link needs an id this title lacks"}
    r = await bounded_play_title(ctx, url, title, site)
    # only a stream that didn't make it (slow CDN, a click that didn't land) gets a second try:
    # "not found", a bot check or a dead domain say the same the second time
    if retry and r["state"] == "up":
        r2 = await bounded_play_title(ctx, url, title, site)
        if RANK[r2["state"]] >= RANK[r["state"]]:
            r = r2
    return r


async def find_template(ctx, p, cands, probe_titles, site, budget: int = 12):
    """
    -> (template, source, links tried, a result: the one that played, else the most telling
    failure). The first format that plays one of probe_titles: the site's current link and the
    documented formats on two titles (a limited catalog may lack the first one), guesses and other
    domains on one. No second tries here, and at most `budget` attempts: a broken provider must not
    eat the night.
    """
    best = first = None
    tried, dead_hosts, attempts = [], set(), 0
    for t, src in cands:
        host = urlparse(t).hostname
        if host in dead_hosts:
            continue
        tried.append(t)
        for title in (probe_titles if src in ("current", "docs") else probe_titles[:1]):
            if attempts >= budget:
                return None, None, tried, (first or best)
            attempts += 1
            # the site's current link gets its second try (a slow load once must not replace a
            # link that works); the others one try
            r = await play(ctx, t, title, site, retry=src == "current")
            if r["state"] == "live":
                return t, src, tried, r
            if r["state"] == "down" and re.search(r"DNS|refused|certificate|didn't answer", r["detail"]):
                dead_hosts.add(host)
            if best is None or RANK[r["state"]] > RANK[best["state"]]:
                best = r
            if src in TRUSTED and first is None:
                first = r
            if r["state"] in ("down", "protected", "unverified"):
                break  # same answer for any title on this link
    return None, None, tried, (first or best)


async def check_provider(ctx, p: dict, titles: list | None = None, episodes: list | None = None,
                         site: str | None = None) -> dict:
    """
    Plays every test title with the link format that works. The state here counts every title;
    main() then judges against the titles some provider plays (judge()).
    """
    titles = titles or FILMS
    episodes = episodes if episodes is not None else EPISODES
    current = bool((p.get("site_link") or {}).get("movie"))
    stamp = lambda h: {**h, "current_tried": current, "site_origin": site,
                       "checked_at": time.strftime("%Y-%m-%d %H:%M:%S")}
    movie_ts, episode_ts = templates(p)
    if not movie_ts:
        return stamp({"state": "untested", "detail": "no domain or link format known"})

    template, source, tried, r = await find_template(ctx, p, movie_ts, titles[:2], site)
    if not template:
        others = other_domains(p, [t for t, _ in movie_ts], tried)
        template, source, more, r2 = await find_template(ctx, p, [(t, "other domain") for t in others], titles[:2], site,
                                                         budget=6)
        tried += more
        if template:
            r = r2
    has_docs = bool(p.get("docs_url") or any(s == "docs" for _, s in movie_ts))
    if not template:
        hint = "" if has_docs else "; no API docs found: link format unknown"
        return stamp({"state": r["state"], "test_url": r.get("test_url"), "films": [r],
                      "detail": f"{r['title']}: {r['detail']} ({len(tried)} link format(s) / domain(s) tried{hint})",
                      "verified": f"0/{len(titles)}", "docs_url": p.get("docs_url")})

    # every title with that format, until it has missed too many to reach COVERAGE
    films = []
    for t in titles:
        if sum(f["state"] not in ("live",) + NO_VERDICT for f in films) >= MAX_MISSES:
            films.append({"title": t["name"], "state": "untested", "detail": f"not tried: {MAX_MISSES} titles missed already"})
            continue
        films.append(r if t["name"] == r["title"] else await play(ctx, template, t, site, retry=True))
    same_default_video(films)
    lost = sum(f["state"] not in ("live",) + NO_VERDICT for f in films) >= MAX_MISSES
    h = {"test_url": r["test_url"], "movie_template": template, "template_source": source, "films": films,
         "docs_url": p.get("docs_url"), "sends_events": any(f.get("sends_events") for f in films)}

    # episodes: the format that plays one, then all of them (not for a provider that lost already)
    if template and episode_ts and episodes and not lost:
        ep_ts = list(dict.fromkeys([with_host(t, urlparse(template).hostname) for t in episode_ts] + episode_ts))[:8]
        et, _, _, er = await find_template(ctx, p, [(t, "current" if i == 0 else "guess") for i, t in enumerate(ep_ts)],
                                           episodes[:2], site, budget=6)
        if et:
            h["episode_link"] = et  # judge() makes it the episode_template when enough episodes play
            h["episodes"] = []
            for e in episodes:
                if sum(x["state"] != "live" for x in h["episodes"]) >= 2:
                    break  # the TV link can't make it any more
                h["episodes"].append(er if e["name"] == er["title"] else await play(ctx, et, e, site, retry=True))
            same_default_video(h["episodes"])
        else:
            h["episodes"] = [er]
        h["episode"] = er  # an episode was tried
    # standalone verdict against every title; main() judges again against what some provider plays
    return stamp(judge(h, {t["name"] for t in titles}, {e["name"] for e in episodes}))


def same_default_video(results: list) -> None:
    """
    SAME_VIDEO titles or more "playing" a video of the very same length (to the second): one default
    video for every id, not the titles. Those become misses.
    """
    by_len = {}
    for r in results:
        if r.get("state") == "live" and r.get("duration_s"):
            by_len.setdefault(r["duration_s"], []).append(r)
    for length, rs in by_len.items():
        if len({r["title"] for r in rs}) >= SAME_VIDEO:
            for r in rs:
                r.update(state="up", detail=f"the same {round(length / 60)} min video for "
                                            f"{len(rs)} different titles (a default video, not the title)")


def judge(h: dict, available: set, available_eps: set) -> dict:
    """
    State from the titles some provider plays (available): live when this one plays >= COVERAGE of
    them. Its TV link stays only on the same rule for the episodes.
    """
    films = h.get("films") or []
    if "movie_template" not in h:
        return h
    if not available:
        h.update(state="unverified", verified="0/0", detail="no provider played any test title (network?)")
        return h
    # titles this provider couldn't be judged on (its player went silent for the test browser,
    # a bot check) are left out; too many of them and there is no verdict at all
    judged = [f for f in films if f["title"] in available and f["state"] not in NO_VERDICT]
    no_verdict = [f for f in films if f["title"] in available and f["state"] in NO_VERDICT and f["state"] != "untested"]
    ok = [f for f in judged if f["state"] == "live"]
    missed = [f for f in judged if f["state"] != "live"]
    h["verified"] = f"{len(ok)}/{len(judged)}"
    if len(no_verdict) > MAX_NO_VERDICT * len(available) or not judged:
        h.update(state="unverified", detail=f"plays {len(ok)} titles, but {len(no_verdict)} couldn't be judged "
                                            f"({no_verdict[0]['detail'] if no_verdict else 'none tried'}): no verdict")
        return h
    # the misses count against every title some provider plays (untested ones included: it was
    # stopped after MAX_MISSES), the no-verdict ones don't
    base = len(available) - len(no_verdict)
    share = len(ok) / base if base else 0
    if share >= COVERAGE:
        h.update(state="live", detail=f"plays {len(ok)}/{base} titles (link from: {h.get('template_source')})"
                                      + (f"; misses {', '.join(f['title'] for f in missed)}" if missed else ""))
    else:
        h.update(state="partial", detail=f"plays {len(ok)}/{base} titles; misses "
                 + ", ".join(f"{f['title']} ({f['detail']})" for f in missed[:4]))
    eps = h.get("episodes") or []
    h.pop("episode_template", None)
    if h.get("episode_link"):
        ep_ok = [e for e in eps if e["state"] == "live" and e["title"] in available_eps]
        if available_eps and len(ep_ok) / len(available_eps) >= COVERAGE:
            h["episode_template"] = h["episode_link"]
            h["detail"] += f"; episodes {len(ep_ok)}/{len(available_eps)}"
        else:
            h["detail"] += f"; episodes {len(ep_ok)}/{len(available_eps)}: TV link left out"
    elif "episode" in h and h["state"] == "live":
        h["detail"] += f"; no episode plays ({h['episode'].get('detail', '')}): TV link left out"
    return h


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("-c", "--catalog", default="provider_catalog.json")
    ap.add_argument("-n", "--concurrency", type=int, default=4)
    ap.add_argument("-p", "--providers", default="", help="only these (comma separated); the file is not rewritten")
    ap.add_argument("--direct", action="store_true", help="open the players directly, not in the site's iframe")
    ap.add_argument("--all-available", action="store_true",
                    help="judge against every test title (with -p: the others, known to play them, aren't re-run)")
    ap.add_argument("-v", "--verbose", action="store_true", help="a line per title tried, as it happens")
    ap.add_argument("--quick", action="store_true", help="a quick look: 1 movie and 1 episode per provider (implies -v)")
    ap.add_argument("--movies", type=int, help="test only the first N movies")
    ap.add_argument("--episodes", type=int, help="test only the first N episodes")
    cfg = ap.parse_args()
    global VERBOSE
    VERBOSE = cfg.verbose or cfg.quick
    if cfg.quick:
        cfg.movies, cfg.episodes = cfg.movies or 1, cfg.episodes or 1
    from playwright.async_api import async_playwright
    cat = json.load(open(cfg.catalog, encoding="utf-8"))
    only = {x.strip() for x in cfg.providers.split(",") if x.strip()}
    todo = [p for p in cat["providers"] if (not only or p["provider"] in only)
            and not p["provider"].startswith("cdn:") and p["provider"] != "self-hosted"]
    if only:  # in the order given
        order = [x.strip() for x in cfg.providers.split(",")]
        todo.sort(key=lambda p: order.index(p["provider"]))
    tt = cat.get("test_titles") or {}
    titles, episodes = tt.get("movies") or FILMS, tt.get("episodes") or EPISODES
    if cfg.movies:
        titles = titles[:cfg.movies]
    if cfg.episodes is not None:
        episodes = episodes[:cfg.episodes]
    site = None if cfg.direct else (cat.get("site_origin") or os.environ.get("SITE_ORIGIN") or None)
    print(f"{len(titles)} movies, {len(episodes)} episodes; players in an iframe on {site or '(none: direct)'}", flush=True)

    # with a screen (run.sh: xvfb-run), a normal Chrome window: Cloudflare stops headless Chrome
    headless = not os.environ.get("DISPLAY") or os.environ.get("HEADLESS") == "1"
    print(f"Chrome {'headless' if headless else 'with a (virtual) screen'}", flush=True)
    args = ["--mute-audio", "--autoplay-policy=no-user-gesture-required"]
    sem = asyncio.Semaphore(cfg.concurrency)
    async with async_playwright() as pw:
        try:
            b = await pw.chromium.launch(headless=headless, channel="chrome", args=args)
        except Exception:
            b = await pw.chromium.launch(headless=headless, args=args)
        ctx = await b.new_context(ignore_https_errors=True, viewport={"width": 1280, "height": 720})
        await ctx.add_init_script("window.open = () => null;")  # pop-under ads

        async def run(p):
            async with sem:
                try:
                    p["health"] = await asyncio.wait_for(check_provider(ctx, p, titles, episodes, site), 1800)
                except Exception as e:
                    p["health"] = {"state": "untested", "detail": f"check failed: {type(e).__name__}"}
                h = p["health"]
                done.append(p["provider"])
                plays = sum(f.get("state") == "live" for f in h.get("films") or [])
                print(f"  [{len(done)}/{len(todo)}] {p['provider']:16s} {plays} title(s) played "
                      f"- {h.get('detail', '')[:120]}", flush=True)
        done = []
        await asyncio.gather(*(run(p) for p in todo))
        await b.close()

    # judge against the titles some provider played (a title nobody plays is nobody's fault)
    avail = {f["title"] for p in todo for f in (p["health"].get("films") or []) if f["state"] == "live"}
    avail_eps = {e["title"] for p in todo for e in (p["health"].get("episodes") or []) if e["state"] == "live"}
    if cfg.all_available:
        avail, avail_eps = {t["name"] for t in titles}, {e["name"] for e in episodes}
    print(f"titles some provider plays: {len(avail)}/{len(titles)} movies, {len(avail_eps)}/{len(episodes)} episodes",
          flush=True)
    for p in todo:
        h = judge(p["health"], avail, avail_eps)
        print(f"  {p['provider']:16s} {h['state']:10s} {h.get('verified', ''):>6}  {h.get('detail', '')}", flush=True)
    if not only:
        cat["coverage"] = {"movies": sorted(avail), "episodes": sorted(avail_eps), "required": COVERAGE}
        json.dump(cat, open(cfg.catalog, "w", encoding="utf-8"), indent=2, ensure_ascii=False)


if __name__ == "__main__":
    asyncio.run(main())
