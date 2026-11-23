#!/usr/bin/env python3
"""
provider_health.py - does an embed provider really play well-known movies?

A provider counts as working ("live") only when EVERY film of FILMS plays on it:
  * the player loads a stream (HLS / DASH manifest or an mp4), and
  * that stream lasts as long as the film (TMDB runtime, a few minutes either way): a trailer,
    an ad, a "not available" clip or the same default movie for every id don't, and
  * the video really moves (currentTime advances) or its segments download.
A provider playing 4 films out of 5 is not live: on the site, a source that doesn't play a
famous film is worse than no source.

Link formats tried (in order), each as a template with the film's ids:
  1. the formats on its own docs page
  2. the embed URL template seen on a scanned site
  3. concrete example URLs its docs give (/movie/1007757 -> /movie/{tmdb})
The first format that plays the first film is used for the others. A TV format, when known, is
checked on EPISODE too: a provider whose episodes don't play is imported without its TV link.

States, strongest first:
  live       - every film played (see above)
  partial    - some films played, not all (not imported)
  up         - the embed page loads, a stream starts but not the film (wrong video, never moves)
  unverified - the page loads and the player asks for nothing: maybe it blocks automated browsers
               (vidfast plays for people, not here). No verdict: the import changes nothing
  no_source  - the embed page loads and says the title isn't available
  protected  - a Cloudflare / bot check answered
  down       - DNS failure, connection error, timeout or HTTP 5xx
  untested   - no domain or test URL known

Usage (standalone):  python provider_health.py [-c provider_catalog.json] [-p xpass,vidlink]
"""

import argparse, asyncio, json, os, re, time
from urllib.parse import urlparse, urljoin

# Well-known movies, with their TMDB runtime in minutes. Distinct enough runtimes that a provider
# serving one default movie for every id fails.
FILMS = [
    {"tmdb": 550, "imdb": "tt0137523", "name": "Fight Club", "minutes": 139},
    {"tmdb": 27205, "imdb": "tt1375666", "name": "Inception", "minutes": 148},
    {"tmdb": 157336, "imdb": "tt0816692", "name": "Interstellar", "minutes": 169},
    {"tmdb": 155, "imdb": "tt0468569", "name": "The Dark Knight", "minutes": 152},
    {"tmdb": 693134, "imdb": "tt15239678", "name": "Dune: Part Two", "minutes": 167},
]
EPISODE = {"tmdb": 1396, "imdb": "tt0903747", "season": 1, "episode": 1, "name": "Breaking Bad 1x01", "minutes": 58}
# kept for the old single-title callers (app.py)
PROBE = {"tmdb": FILMS[0]["tmdb"], "imdb": FILMS[0]["imdb"]}

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
  const c = document.elementFromPoint(innerWidth / 2, innerHeight / 2);
  if (c) { c.click(); return 'center'; }
  return null;
}"""

# every <video> of the frame: its duration and how far it got
VIDEO_JS = r"""() => [...document.querySelectorAll('video')].map(v => {
  try { if (v.paused) { v.muted = true; v.play().catch(() => {}); } } catch (e) {}
  return {src: (v.currentSrc || v.src || '').slice(0, 200), duration: isFinite(v.duration) ? v.duration : null,
          time: v.currentTime || 0, ready: v.readyState};
})"""


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
    -> ([(movie template, source)], episode templates), best first. Sources: "docs" (its API docs),
    "site" (seen on a streaming site), "docs example" (a concrete URL in its docs), "guess" (a usual
    structure on its domain).
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


def fill(template: str, title: dict) -> str:
    return (template.replace("{tmdb}", str(title["tmdb"])).replace("{imdb}", str(title["imdb"]))
            .replace("{season}", str(title.get("season", ""))).replace("{episode}", str(title.get("episode", ""))))


def runtime_ok(seconds: float | None, minutes: int) -> bool:
    """A stream of the film: within max(5 min, 6 %) of its runtime."""
    if not seconds:
        return False
    return abs(seconds / 60 - minutes) <= max(5, minutes * 0.06)


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


async def play_title(ctx, url: str, title: dict, timeout_ms: int = 25000) -> dict:
    """Open one embed URL and prove the title plays. -> {state, detail, duration_min, ...}"""
    page = await ctx.new_page()
    seen = {"stream": None, "manifests": [], "segments": 0, "variants": []}
    host = urlparse(url).hostname or ""
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

    out = {"title": title["name"], "test_url": url, "http": None, "stream_host": None, "duration_min": None}
    t0 = time.monotonic()
    try:
        resp = await page.goto(url, timeout=timeout_ms, wait_until="domcontentloaded")
        out["latency_ms"] = int((time.monotonic() - t0) * 1000)
        out["http"] = resp.status if resp else None
        if CHALLENGE.search((await page.title()) or ""):
            return {**out, "state": "protected", "detail": "Cloudflare / bot check"}
        if resp and resp.status >= 500:
            return {**out, "state": "down", "detail": f"HTTP {resp.status}"}
        await page.wait_for_timeout(3500)
        # press play in the page and in every frame (players often sit one iframe deeper), and
        # wait for the stream to start and move
        first_time = None
        for i in range(5):
            if not seen["manifests"] and not any(v["time"] > 0 for v in await videos()):
                for fr in page.frames:
                    try:
                        await asyncio.wait_for(fr.evaluate(PLAY_JS), 3)
                    except Exception:
                        pass
            await page.wait_for_timeout(3500)
            vids = [v for v in await videos() if v["duration"] and v["duration"] > 60]
            t = max((v["time"] for v in vids), default=0)
            if first_time is None and t > 0:
                first_time = t
            elif first_time is not None and t > first_time + 0.5:
                break  # it moves
            if i >= 2 and not seen["stream"] and not vids:
                break  # nothing after three tries
        await asyncio.gather(*tasks, return_exceptions=True)
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
        durations = [v["duration"] for v in vids if v["duration"]] + seen["manifests"]
        match = next((d for d in durations if runtime_ok(d, title["minutes"])), None)
        moving = any(v["time"] > 1 for v in vids) or seen["segments"] >= 2
        out["stream_host"] = seen["stream"]
        longest = max(durations, default=None)
        out["duration_min"] = round((match or longest) / 60) if (match or longest) else None
        if match and moving:
            return {**out, "state": "live", "detail": f"plays ({round(match / 60)} min)"}
        if match:
            return {**out, "state": "up", "detail": f"stream of the right length ({round(match / 60)} min) but it never moved"}
        if longest:
            return {**out, "state": "up", "detail": f"wrong video: {round(longest / 60)} min, the film is {title['minutes']}"}
        if seen["stream"]:
            return {**out, "state": "up", "detail": "a stream was requested, but no film-length video"}
        text = ""
        for fr in page.frames[:4]:
            try:
                text += " " + (await asyncio.wait_for(fr.evaluate("() => document.body ? document.body.innerText.slice(0, 3000) : ''"), 3))
            except Exception:
                pass
        if CHALLENGE.search(text):
            return {**out, "state": "protected", "detail": "bot check inside player"}
        if (resp and resp.status == 404) or NO_SOURCE.search(text):
            m = NO_SOURCE.search(text)
            return {**out, "state": "no_source", "detail": m.group(0) if m else f"HTTP {resp.status}"}
        if resp and resp.status >= 400:
            return {**out, "state": "down" if resp.status != 403 else "protected", "detail": f"HTTP {resp.status}"}
        # nothing at all: no stream asked for, no error shown. Some players do that for an
        # automated browser (vidfast) and play fine for people: can't tell, so no verdict
        return {**out, "state": "unverified", "detail": "page loads, the player asks for nothing (blocks automated browsers?)"}
    except Exception as e:
        msg = str(e).splitlines()[0] if str(e) else type(e).__name__
        kind = ("DNS: domain not found" if "ERR_NAME_NOT_RESOLVED" in msg else
                "timeout" if "Timeout" in msg else
                "certificate error" if "CERT" in msg else
                "connection refused/closed" if re.search(r"CONNECTION|ERR_EMPTY", msg) else msg[:80])
        return {**out, "state": "down", "detail": kind, "latency_ms": int((time.monotonic() - t0) * 1000)}
    finally:
        for t in tasks:
            t.cancel()
        await page.close()


GUESS_TLDS = ["net", "top", "to", "pro", "cc", "xyz", "su", "ru", "me", "org", "io", "site", "online",
              "st", "vc", "ws", "live", "click", "store", "lol", "cx", "sx", "is", "co", "tv"]


def with_host(template: str, host: str) -> str:
    u = urlparse(template)
    return template.replace(f"{u.scheme}://{u.netloc}", f"{u.scheme}://{host}", 1)


async def _resolves(host: str) -> bool:
    try:
        await asyncio.wait_for(asyncio.get_running_loop().getaddrinfo(host, 443), 5)
        return True
    except Exception:
        return False


async def other_domains(p: dict, movie_ts: list[str], tried: list[str], max_guesses: int = 6) -> list[str]:
    """
    The first movie template on the provider's other domains: the ones seen on sites / in its
    docs first, then its name on other extensions that exist (vidlink.pro -> vidlink.net ...).
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
    # guesses: same sub-domain + name, other extension; only the ones that resolve
    host = urlparse(base).hostname or ""
    parts = host.split(".")
    if len(parts) >= 2:
        sub, name = parts[:-2], parts[-2]
        guesses = []
        for tld in GUESS_TLDS:
            for pre in ([".".join(sub)] if sub else []) + [""]:
                h = ".".join(x for x in (pre, name, tld) if x)
                if h != host and h not in guesses:
                    guesses.append(h)
        ok = await asyncio.gather(*(_resolves(h) for h in guesses))
        found = 0
        for h, alive in zip(guesses, ok):
            t = with_host(base, h)
            if alive and t not in tried and t not in out and found < max_guesses:
                out.append(t)
                found += 1
    return out


RANK = {"live": 7, "partial": 6, "up": 5, "no_source": 4, "unverified": 3, "protected": 2, "down": 1, "untested": 0}


async def play_with_retry(ctx, template: str, title: dict) -> dict:
    """A miss is tried once more (slow CDN, a click that didn't land)."""
    r = await play_title(ctx, fill(template, title), title)
    if r["state"] != "live" and r["state"] not in ("down", "protected", "unverified"):
        r2 = await play_title(ctx, fill(template, title), title)
        if RANK[r2["state"]] >= RANK[r["state"]]:
            r = r2
    return r


async def check_provider(ctx, p: dict, timeout_ms: int = 25000) -> dict:
    """Live only when every film of FILMS plays with one link format."""
    # the site's current link was among the ones tried: only then may the import turn it off
    current = bool((p.get("site_link") or {}).get("movie"))
    stamp = lambda h: {**h, "current_tried": current, "checked_at": time.strftime("%Y-%m-%d %H:%M:%S")}
    movie_ts, episode_ts = templates(p)
    if not movie_ts:
        hosts = p.get("domains") or p.get("hosts") or []
        if not hosts:
            return stamp({"state": "untested", "detail": "no domain known"})
        r = await play_title(ctx, f"https://{hosts[0]}/", FILMS[0], timeout_ms)
        state = "up" if r["state"] in ("live", "up", "no_source") else r["state"]
        return stamp({"state": state, "detail": "domain answers, but no movie link format known" if state == "up" else r["detail"],
                      "latency_ms": r.get("latency_ms"), "test_url": r["test_url"]})

    # the link format that plays the first film, in order: its API docs' formats, the ones seen on
    # streaming sites, its docs' example URLs, the usual structures on its domain, then the best
    # format on its other known domains and on its name with other extensions (.net / .top ...)
    best, first, template, source = None, None, None, None
    tried, dead_hosts = [], set()

    async def attempt(t, src):
        nonlocal best, first, template, source
        host = urlparse(t).hostname
        if host in dead_hosts:
            return False
        tried.append(t)
        # documented / seen formats get a second chance; guesses and other domains one try
        r = await (play_with_retry(ctx, t, FILMS[0]) if src in ("current", "docs", "site", "docs example")
                   else play_title(ctx, fill(t, FILMS[0]), FILMS[0], timeout_ms))
        if r["state"] == "down" and re.search(r"DNS|refused|certificate", r["detail"]):
            dead_hosts.add(host)
        if best is None or RANK[r["state"]] > RANK[best["state"]]:
            best = r
        if src in ("current", "docs", "site", "docs example") and first is None:
            first = r
        if r["state"] == "live":
            template, source = t, src
            return True
        return False

    for t, src in movie_ts:
        if await attempt(t, src):
            break
    if not template:
        base = [t for t, _ in movie_ts]
        for t in await other_domains(p, base, tried):
            if await attempt(t, "other domain"):
                break
    has_docs = bool(p.get("docs_url") or any(s == "docs" for _, s in movie_ts))
    if template:
        episode_ts = [with_host(t, urlparse(template).hostname) for t in episode_ts] + episode_ts
        episode_ts = list(dict.fromkeys(episode_ts))[:8]
    else:
        # report what its own link (docs / site) gave, not a guessed domain's "not found"
        best = first or best
        hint = "" if has_docs else "; no API docs found: link format unknown"
        return stamp({**{k: best.get(k) for k in ("state", "detail", "test_url", "latency_ms", "stream_host")},
                      "detail": f"{FILMS[0]['name']}: {best['detail']} ({len(tried)} link format(s) / domain(s) tried{hint})",
                      "films": [best], "verified": f"0/{len(FILMS)}", "tried": len(tried), "docs_url": p.get("docs_url")})

    # ... must play every other film too
    films = [best]
    for f in FILMS[1:]:
        films.append(await play_with_retry(ctx, template, f))
    ok = [r for r in films if r["state"] == "live"]
    failed = [r for r in films if r["state"] != "live"]
    h = {"test_url": best["test_url"], "latency_ms": best.get("latency_ms"), "stream_host": best.get("stream_host"),
         "films": films, "verified": f"{len(ok)}/{len(FILMS)}", "movie_template": template,
         "template_source": source, "docs_url": p.get("docs_url")}
    if failed:
        h.update(state="partial", detail="does not play " + ", ".join(f"{r['title']} ({r['detail']})" for r in failed))
        return stamp(h)
    h.update(state="live", detail=f"plays all {len(FILMS)} test films (link from: {source})")

    # TV: kept only when an episode plays too
    for i, t in enumerate(episode_ts):
        # the current / documented ones get a second chance, the usual structures one try
        r = await (play_with_retry(ctx, t, EPISODE) if i < 2 else play_title(ctx, fill(t, EPISODE), EPISODE, timeout_ms))
        h["episode"] = r
        if r["state"] == "live":
            h["episode_template"] = t
            break
    if episode_ts and not h.get("episode_template"):
        h["detail"] += f"; episodes don't play ({h['episode']['detail']}): TV link left out"
    return stamp(h)


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("-c", "--catalog", default="provider_catalog.json")
    ap.add_argument("-n", "--concurrency", type=int, default=4)
    ap.add_argument("-p", "--providers", default="", help="only these (comma separated); the file is not rewritten")
    cfg = ap.parse_args()
    from playwright.async_api import async_playwright
    cat = json.load(open(cfg.catalog, encoding="utf-8"))
    only = {x.strip() for x in cfg.providers.split(",") if x.strip()}
    todo = [p for p in cat["providers"] if not only or p["provider"] in only]
    sem = asyncio.Semaphore(cfg.concurrency)
    # with a screen (run.sh: xvfb-run), a normal Chrome window: Cloudflare stops headless Chrome
    # on players that open fine in a real browser (vidfast...)
    headless = not os.environ.get("DISPLAY") or os.environ.get("HEADLESS") == "1"
    print(f"Chrome {'headless' if headless else 'with a (virtual) screen'}", flush=True)
    args = ["--mute-audio", "--autoplay-policy=no-user-gesture-required", "--disable-blink-features=AutomationControlled"]
    async with async_playwright() as pw:
        try:
            b = await pw.chromium.launch(headless=headless, channel="chrome", args=args)
        except Exception:
            b = await pw.chromium.launch(headless=headless, args=args)
        ctx = await b.new_context(ignore_https_errors=True)
        await ctx.add_init_script("window.open = () => null;")

        async def run(p):
            async with sem:
                p["health"] = await check_provider(ctx, p)
                h = p["health"]
                print(f"  {p['provider']:16s} {h['state']:10s} {h.get('verified', ''):>4}  {h.get('detail', '')}", flush=True)
        await asyncio.gather(*(run(p) for p in todo))
        await b.close()
    if not only:
        cat["test_films"] = FILMS
        json.dump(cat, open(cfg.catalog, "w", encoding="utf-8"), indent=2, ensure_ascii=False)


if __name__ == "__main__":
    asyncio.run(main())
