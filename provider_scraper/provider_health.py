#!/usr/bin/env python3
"""
provider_health.py - is an embed provider up, and does it actually serve video?

For one provider it builds test URLs for a real movie from (in order):
  1. the formats on its own docs page, filled with the probe title's ids
  2. concrete example URLs its docs give (/movie/1007757...)
  3. the embed URL template seen on a scanned site
then opens them in the browser, presses play with JS and watches the network.

States, strongest first:
  live       - a stream was requested (.m3u8 / .mpd / .mp4) or a <video> started
  up         - the embed page loads but no stream started (player may need a real click)
  no_source  - the embed page loads and says the title isn't available
  protected  - a Cloudflare / bot check answered
  down       - DNS failure, connection error, timeout or HTTP 5xx
  untested   - no domain or test URL known

Usage (standalone):  python provider_health.py [-c provider_catalog.json]
"""

import argparse, asyncio, json, re, time
from urllib.parse import urlparse

PROBE = {"tmdb": 1368337, "imdb": "tt33764258"}
STREAM = re.compile(r"\.(m3u8|mpd)(\?|$)|\.mp4(\?|$)|/(playlist|master|index)\.m3u8|/hls/|/manifest", re.I)
NO_SOURCE = re.compile(r"(not found|no sources?|unavailable|could ?n.t find|doesn.t exist|does not exist|"
                       r"no (video|stream|links?)|error 404|404 not|media not|try (another|other) server|"
                       r"coming soon|not (yet )?released)", re.I)
CHALLENGE = re.compile(r"just a moment|attention required|un instant|checking your browser|verify you are human", re.I)
NOISE = re.compile(r"doubleclick|googlesyndication|google-analytics|googletagmanager|youtube|ytimg|"
                   r"jwpcdn|jwplayer\.com/v|vast|preroll|/ads?/", re.I)

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

VIDEO_JS = r"""() => [...document.querySelectorAll('video')].some(v =>
  (v.currentSrc || v.src || '').length > 0 && (v.readyState > 0 || !v.paused))"""


def fill(fmt: str) -> str | None:
    """Docs format -> concrete movie URL for the probe title, or None (TV/anime/unfillable)."""
    u = fmt.strip().rstrip(".,;)")
    if re.search(r"/(tv|anime|series|episode)\b|season|\{s\}|\$s\b", u, re.I):
        return None
    u = re.sub(r"\{(tmdb_?id|tmdbId|tmdb|id|movie_?id)\}|\$id\b|\[(tmdb_?id|id)\]|:id\b|<(tmdb_?id|id)>",
               str(PROBE["tmdb"]), u, flags=re.I)
    u = re.sub(r"\{(imdb_?id|imdbId|imdb)\}|\{tt[^}]*\}|\[(imdb_?id)\]|<(imdb_?id)>", PROBE["imdb"], u, flags=re.I)
    if re.search(r"[{}\[\]<>$]", u) or not u.startswith("http"):
        return None
    return u


def test_urls(p: dict) -> list[str]:
    out = []
    fmts = p.get("formats") or p.get("doc_formats") or []
    placeholder = [f for f in fmts if re.search(r"\{|\$id|\[|:id\b|<", f)]
    concrete = [f for f in fmts if f not in placeholder and re.search(r"/(movie|embed|e)/", f, re.I)]
    tpl = p.get("template") or ((p.get("observed_templates") or [None])[0])
    for f in placeholder + ([tpl] if tpl else []) + concrete:
        u = fill(f) if f else None
        if u and u not in out:
            out.append(u)
    return out[:3]


async def check_url(ctx, url: str, timeout_ms: int) -> dict:
    page = await ctx.new_page()
    seen = {"stream": None}
    host = urlparse(url).hostname or ""

    def on_req(req):
        u = req.url
        if not seen["stream"] and STREAM.search(u) and not NOISE.search(u):
            seen["stream"] = urlparse(u).hostname
    page.on("request", on_req)
    out = {"test_url": url, "http": None, "latency_ms": None, "stream_host": None, "detail": ""}
    t0 = time.monotonic()
    try:
        resp = await page.goto(url, timeout=timeout_ms, wait_until="domcontentloaded")
        out["latency_ms"] = int((time.monotonic() - t0) * 1000)
        out["http"] = resp.status if resp else None
        title = (await page.title()) or ""
        if CHALLENGE.search(title):
            out.update(state="protected", detail="Cloudflare / bot check")
            return out
        if resp and resp.status >= 500:
            out.update(state="down", detail=f"HTTP {resp.status}")
            return out
        await page.wait_for_timeout(3500)
        # press play in the page and in every frame (players often sit one iframe deeper)
        for _ in range(2):
            if seen["stream"]:
                break
            for fr in page.frames:
                try:
                    await asyncio.wait_for(fr.evaluate(PLAY_JS), 3)
                except Exception:
                    pass
            await page.wait_for_timeout(4500)
        video = False
        for fr in page.frames:
            try:
                video = video or await asyncio.wait_for(fr.evaluate(VIDEO_JS), 3)
            except Exception:
                pass
        if seen["stream"] or video:
            out.update(state="live", stream_host=seen["stream"], detail="stream started" if seen["stream"] else "video playing")
            return out
        text = ""
        for fr in page.frames[:4]:
            try:
                text += " " + (await asyncio.wait_for(fr.evaluate("() => document.body ? document.body.innerText.slice(0, 3000) : ''"), 3))
            except Exception:
                pass
        if CHALLENGE.search(text):
            out.update(state="protected", detail="bot check inside player")
        elif (resp and resp.status == 404) or NO_SOURCE.search(text):
            m = NO_SOURCE.search(text)
            out.update(state="no_source", detail=(m.group(0) if m else f"HTTP {resp.status}"))
        elif resp and resp.status >= 400:
            out.update(state="down" if resp.status != 403 else "protected", detail=f"HTTP {resp.status}")
        else:
            out.update(state="up", detail="page loads, no stream seen")
        return out
    except Exception as e:
        msg = str(e).splitlines()[0] if str(e) else type(e).__name__
        kind = ("DNS: domain not found" if "ERR_NAME_NOT_RESOLVED" in msg else
                "timeout" if "Timeout" in msg else
                "certificate error" if "CERT" in msg else
                "connection refused/closed" if re.search(r"CONNECTION|ERR_EMPTY", msg) else msg[:80])
        out.update(state="down", detail=kind, latency_ms=out["latency_ms"] or int((time.monotonic() - t0) * 1000))
        return out
    finally:
        await page.close()


RANK = {"live": 5, "up": 4, "no_source": 3, "protected": 2, "down": 1, "untested": 0}


async def check_provider(ctx, p: dict, timeout_ms: int = 20000) -> dict:
    """Best result over the provider's test URLs (stops at the first 'live')."""
    urls = test_urls(p)
    if not urls:
        hosts = p.get("domains") or p.get("hosts") or []
        if not hosts:
            return {"state": "untested", "detail": "no domain known", "checked_at": time.strftime("%Y-%m-%d %H:%M:%S")}
        urls = [f"https://{hosts[0]}/"]
    best = None
    for u in urls:
        r = await check_url(ctx, u, timeout_ms)
        if best is None or RANK[r["state"]] > RANK[best["state"]]:
            best = r
        if r["state"] == "live":
            break
    if urls and urls[0].endswith("/") and len(urls) == 1 and best["state"] == "up":
        best["detail"] = "domain answers (no embed URL known to test)"
    best["checked_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
    best["tried"] = len(urls)
    return best


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("-c", "--catalog", default="provider_catalog.json")
    ap.add_argument("-n", "--concurrency", type=int, default=4)
    cfg = ap.parse_args()
    from playwright.async_api import async_playwright
    cat = json.load(open(cfg.catalog, encoding="utf-8"))
    sem = asyncio.Semaphore(cfg.concurrency)
    async with async_playwright() as pw:
        try:
            b = await pw.chromium.launch(headless=True, channel="chrome", args=["--mute-audio", "--autoplay-policy=no-user-gesture-required"])
        except Exception:
            b = await pw.chromium.launch(headless=True, args=["--mute-audio"])
        ctx = await b.new_context(ignore_https_errors=True)
        await ctx.add_init_script("window.open = () => null;")

        async def run(p):
            async with sem:
                p["health"] = await check_provider(ctx, p)
                h = p["health"]
                print(f"  {p['provider']:16s} {h['state']:10s} {str(h.get('latency_ms') or ''):>6} ms  {h.get('detail', '')}")
        await asyncio.gather(*(run(p) for p in cat["providers"]))
        await b.close()
    json.dump(cat, open(cfg.catalog, "w", encoding="utf-8"), indent=2, ensure_ascii=False)


if __name__ == "__main__":
    asyncio.run(main())
