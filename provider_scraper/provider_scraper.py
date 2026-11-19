#!/usr/bin/env python3
"""
provider_scraper.py
For each site: find a title page -> open its player -> list the embed providers it uses.

How each site is read (patterns learned by opening every site in a browser):
  * Title page: a per-site URL template with a known TMDB id (most of these sites
    route /movie/{tmdb} or /watch/movie/{tmdb}), else the homepage's dominant
    title-link pattern, else generic TMDB templates. Splash pages ("View Full
    Site") are followed to the real homepage.
  * Server list: three layers, most reliable first
      1. cycle  - open the server menu, click every server, record which iframe
                  host it loads ("Hyena" -> airflix1.com). Labels are often
                  codenames, so the host is the truth.
      2. attrs  - embed URLs sitting in attributes (data-link, data-url, onclick
                  variables...): hydrahd, onionplay, doraby.
      3. text   - known provider names in the page text (last resort).
  * Network: every sub-frame document is an embed; .m3u8/.mpd requests reveal the
    CDN of direct (iframe-less) players. A stream proxied through the site itself
    is reported as "self-hosted".
  * Clicks are dispatched with JS on the element (not the mouse), and window.open
    is disabled: real clicks on these sites land on invisible ad overlays.

Usage:
  python provider_scraper.py                      # all SITES
  python provider_scraper.py doraby.com nepu.io   # only these
  python provider_scraper.py -f sites.txt -c 6 --headful -o report.json -v
"""

import argparse, asyncio, contextvars, json, re, sys, time
from urllib.parse import urlparse, urljoin
from collections import defaultdict, Counter
from playwright.async_api import async_playwright

SITES = [
    "soap2night.cc","ramoflix.net","doraby.com","wmovies.nl","hydrahd.gd",
    "goojara.to","7movies.ac","aether.ist","movy.sx","flixer.su",
    "moviebite.org","primeshows.org","67movies.st","shuttletv.su",
    "popcornmovies.ac","rivestream.app","stellar.rip","onionplay.ae",
    "lookmovie2.to","pressplayz.top","nepu.io","fmoviess.org",
    "soap2dayhd.net","azmovies.to","mapple.fun","streamex.hn",
    "opstream.fun","latestmovies.net","officialmoviebox.com","hdtoday24.at",
    "cinebytv.com","ridomovie.to","123moviesfree.net","willowmovies.com",
    "vidplay.top","cinemaos.live","yesmovies.ag","anixtv.us.cc",
    "primewire.mov","moviepire.ru","flicker-mini.pages.dev","m4uhd.page",
]

# A recent, widely available movie used to build title URLs.
PROBE = {"tmdb": 1368337, "imdb": "tt33764258", "slug": "the-odyssey", "name": "odyssey"}

# Per-site title URL templates, learned by browsing each site.
# {tmdb} {imdb} {slug} are filled from PROBE. Several = tried in order.
SITE_HINTS = {
    "cinebytv.com":  ["/watch/movie/{tmdb}"],
    "7movies.ac":    ["/movie/{tmdb}/watch"],
    "67movies.st":   ["/watch/movie/{tmdb}"],
    "stellar.rip":   ["/en/watch/movie/{tmdb}", "/en/movie/{tmdb}"],
    "streamex.hn":   ["/watch/movie/{tmdb}"],
    "movy.sx":       ["/movie/{tmdb}"],
    "moviebite.org": ["/watch/movie/{tmdb}/{slug}"],
    "aether.ist":    ["/media/tmdb-movie-{tmdb}-{slug}"],
    "latestmovies.net": ["/movie/{tmdb}"],
    "willowmovies.com": ["/stream/movie/{tmdb}"],
    "flixer.su":     ["/watch/movie/{tmdb}"],
}

# Tried when nothing else gives a working title page.
GENERIC_TEMPLATES = [
    "/watch/movie/{tmdb}", "/movie/{tmdb}/watch", "/movie/{tmdb}",
    "/en/watch/movie/{tmdb}", "/watch/{tmdb}", "/stream/movie/{tmdb}",
]

USER_AGENT = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")

# Known embed providers, as sites write them in server lists or hostnames.
# key = name in the report, value = regexes matched on the lowercased text.
PROVIDERS = {
    "111movies":    [r"111\s*movies"],
    "vidsrc":       [r"vid\s*src"],
    "vidlink":      [r"vid\s*link"],
    "vidfast":      [r"vid\s*fast"],
    "videasy":      [r"vid\s*easy"],
    "vidking":      [r"vid\s*king"],
    "vidzee":       [r"vid\s*zee"],
    "vidjoy":       [r"vid\s*joy"],
    "vidora":       [r"vidora"],
    "vidbinge":     [r"vid\s*binge"],
    "vidcore":      [r"vid\s*core"],
    "vidrift":      [r"vid\s*rift"],
    "vidqueen":     [r"vid\s*queen"],
    "vidup":        [r"vid\s*up"],
    "vidbolt":      [r"vid\s*bolt"],
    "vidify":       [r"vidify"],
    "vidly":        [r"vidly"],
    "vidy":         [r"vidy"],
    "vixsrc":       [r"vix\s*src"],
    "primesrc":     [r"prime\s*src"],
    "cinesrc":      [r"cine\s*src"],
    "cinezo":       [r"cinezo"],
    "1src":         [r"1src"],
    "xpass":        [r"xpass"],
    "airflix":      [r"airflix\d*"],
    "embedmaster":  [r"embed\s*master"],
    "embedsu":      [r"embed\s*\.?\s*su"],
    "2embed":       [r"2\s*embed"],
    "autoembed":    [r"auto\s*embed"],
    "multiembed":   [r"multi\s*embed", r"super\s*embed"],
    "smashystream": [r"smashy\s*stream", r"smashy"],
    "moviesapi":    [r"movies\s*api"],
    "vidapi":       [r"vaplayer", r"vid\s*api"],
    "nontongo":     [r"nontongo"],
    "rivestream":   [r"rive\s*stream"],
    "frembed":      [r"frembed"],
    "upcloud":      [r"up\s*cloud"],
    "megacloud":    [r"mega\s*cloud"],
    "vidcloud":     [r"vid\s*cloud"],
    "rabbitstream": [r"rabbit\s*stream"],
    "filemoon":     [r"file\s*moon"],
    "filelions":    [r"file\s*lions"],
    "streamwish":   [r"stream\s*wish"],
    "streamtape":   [r"stream\s*tape"],
    "doodstream":   [r"dood\s*stream", r"dood"],
    "mixdrop":      [r"mix\s*drop"],
    "vidhide":      [r"vid\s*hide"],
    "vidplay":      [r"vid\s*play"],
    "mycloud":      [r"my\s*cloud"],
    "upstream":     [r"upstream"],
    "wootly":       [r"wootly"],
    "voe":          [r"voe"],
}
# Whole-word match, so "voe" doesn't hit "voyage" and "dood" doesn't hit "moodstreams".
_PROVIDER_RE = [
    (name, re.compile(r"(?<![a-z0-9])(?:" + "|".join(pats) + r")(?![a-z0-9])"))
    for name, pats in PROVIDERS.items()
]

# Hosts that are never video providers: ads, analytics, captchas, social, trailers.
NOISE_HOSTS = re.compile(
    r"(doubleclick|googlesyndication|googletagmanager|google-analytics|googleapis|"
    r"gstatic|google\.|recaptcha|hcaptcha|cloudflare|facebook|twitter|x\.com|disqus|"
    r"(^|\.)youtube\.com|youtube-nocookie|youtu\.be|ytimg|vimeo|histats|yandex|adsterra|popads|propeller|onclick|adcash|"
    r"exoclick|juicyads|hilltop|a-ads|clarity\.ms|hotjar|sentry|intercom|crisp\.chat|"
    r"tawk\.to|lijit|sharethis|adtrafficquality|fundingchoices|dtscout|uidsync|"
    r"rapidadexchange|adexchangerapid|installstational|opera\.com|proadblocker|"
    r"secutorlunts|seembey|riggaluntruth|excuditcycle|raccoonunbutteredbagel|elodescrakesunglow|"
    r"ukankingwithea|luugy|adsco\.re|rtmark|s1q2105|mxzhxco8dft|janitorprecisiontrio|onmarshtompor|"
    r"azafrancestrumprows|hassletorbited|apexpe|^analytics\.|"
    r"media-imdb|imdb-video|wecollege|trustpilot|cookiebot|consentcdn|"
    r"themoviedb|tmdb\.org|theintrodb|ipify|firebase|opensubtitles|subdl|subscene|wyzie|^undefined$|about:blank)", re.I)

# Resources we never need: speeds up loads a lot on these heavy, ad-filled sites.
BLOCKED_RESOURCES = {"image", "media", "font"}

# Links to these are files, not title pages (fmoviess / 123moviesfree link a PDF).
FILE_EXT = re.compile(r"\.(pdf|zip|rar|7z|apk|exe|dmg|msi|jpg|jpeg|png|gif|webp|mp4|mkv|txt|xml)$", re.I)

STREAM_URL = re.compile(r"\.(m3u8|mpd)(\?|$)|/(playlist|master)\.m3u8", re.I)

# A frame stuck in an ad script can make evaluate() hang forever.
FRAME_EVAL_TIMEOUT = 5

# Runs in every frame before any page script: no popups / popunders.
INIT_JS = "window.open = () => null;"

VERBOSE = False

# Live events for a UI (app.py): set EVENT_HOOK to fn(kind, data). Every log line,
# provider and server found is sent with the site it belongs to.
EVENT_HOOK = None
CURRENT_SITE: contextvars.ContextVar = contextvars.ContextVar("site", default="")


def emit(kind: str, **data):
    if EVENT_HOOK:
        try:
            data.setdefault("site", CURRENT_SITE.get())
            EVENT_HOOK(kind, data)
        except Exception:
            pass


def log(msg: str):
    if VERBOSE:
        print(f"      . {msg}", flush=True)
    emit("log", msg=msg)


def providers_in_text(text: str) -> list[str]:
    """Known provider names found in the text, in order of first appearance."""
    t = text.lower()
    hits = []
    for name, rx in _PROVIDER_RE:
        m = rx.search(t)
        if m:
            hits.append((m.start(), name))
    return [name for _, name in sorted(hits)]


def norm(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", name.lower())


def host_of(url: str) -> str:
    try:
        return (urlparse(url).hostname or "").lower().removeprefix("www.")
    except Exception:
        return ""


def bare_host(url: str) -> str:
    """https://embed.vidrift.net/... -> vidrift"""
    parts = host_of(url).split(".")
    return parts[-2] if len(parts) >= 2 else parts[0]


def same_site(a: str, b: str) -> bool:
    """example.com vs watch.example.com -> True; also same registrable name
    (flixer.su -> flixer.gd, moviepire.ru -> moviepire.co: mirror domains)."""
    ha, hb = host_of(a), host_of(b)
    if not ha or not hb:
        return False
    return ha == hb or ha.endswith("." + hb) or hb.endswith("." + ha) or bare_host(a) == bare_host(b)


def provider_from_host(url: str) -> str | None:
    """Embed URL -> provider name. Known host -> PROVIDERS key, else the bare host."""
    host = host_of(url)
    if not host or NOISE_HOSTS.search(host):
        return None
    known = providers_in_text(host)
    return known[0] if known else bare_host(url)


# ---------------------------------------------------------------------------
# In-page scripts
# ---------------------------------------------------------------------------

# Visible and hidden text (closed dropdowns count), without script/style code.
PAGE_TEXT_JS = r"""() => {
  const parts = [];
  if (document.body) {
    const skip = new Set(['SCRIPT', 'STYLE', 'NOSCRIPT', 'TEMPLATE']);
    const w = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT, {
      acceptNode: n => skip.has(n.parentNode && n.parentNode.nodeName)
        ? NodeFilter.FILTER_REJECT : NodeFilter.FILTER_ACCEPT });
    while (w.nextNode()) {
      const s = w.currentNode.nodeValue.trim();
      if (s) parts.push(s);
    }
  }
  document.querySelectorAll('[title],[aria-label],[data-name],[data-server],[data-provider],option')
    .forEach(el => ['title','aria-label','data-name','data-server','data-provider','label']
      .forEach(a => { const v = el.getAttribute(a); if (v) parts.push(v); }));
  return parts.join('\n');
}"""

# Every element attribute holding an embed URL, with the element's label.
#   hydrahd:   <div class="iframe-server-button" data-link="https://vixsrc.to/...">Hydra2</div>
#   onionplay: <button data-url="https://vidlink.pro/...">VidLink</button>
#   doraby:    <li class="server" onclick="loadServer(superembed)"><span>Vidcore</span>
#              where `superembed` is a page variable holding the URL.
ATTR_EMBEDS_JS = r"""() => {
  const out = [];
  const label = el => (el.firstChild && el.firstChild.nodeType === 3 && el.firstChild.textContent.trim())
                      || (el.innerText || el.textContent || '').trim().replace(/\s+/g, ' ');
  const resolve = v => {
    const m = v.match(/(?:https?:)?\/\/[^'"\s)<>]+/);
    if (m) return m[0].startsWith('//') ? 'https:' + m[0] : m[0];
    // onclick="loadServer(varName)" -> value of the page variable
    const a = v.match(/\(\s*([A-Za-z_$][\w$]*)\s*[,)]/);
    if (a) { try { const x = (0, eval)(a[1]);
                   if (typeof x === 'string' && /^https?:\/\//.test(x)) return x; } catch (e) {} }
    return '';
  };
  for (const el of document.querySelectorAll('body *')) {
    if (/^(SCRIPT|STYLE|LINK|META|IMG|SOURCE|VIDEO|IFRAME|A)$/.test(el.tagName)) continue;
    for (const at of el.attributes) {
      if (!/^(data-|onclick$|value$)/.test(at.name)) continue;
      const url = resolve(at.value);
      if (url) out.push({label: label(el).slice(0, 40), url, attr: at.name});
    }
  }
  return out;
}"""

# Open the server menus, click every server, record what each one loads.
# Runs in the page with JS clicks only (no mouse -> no ad overlays).
SERVER_CYCLE_JS = r"""async ({budgetMs, waitMs, maxItems}) => {
  const t0 = Date.now();
  const sleep = ms => new Promise(r => setTimeout(r, ms));
  const vis = el => !!(el && (el.offsetParent || el.getClientRects().length));
  const txt = el => ((el.innerText || el.textContent || '').trim()
                     || el.getAttribute('aria-label') || '').replace(/\s+/g, ' ').trim();
  const CLICK = 'button,li,[role=option],[role=menuitem],[role=menuitemradio],[role=radio],' +
                '[role=tab],a,[onclick],[data-server],[data-link],[data-url],[data-embed],[data-nume]';
  const SERVERISH = /server|source|embed|provider|mirror|player[-_]?opt|host|stream-?list/i;
  const OPENER = /^(servers?( & mode| and quality| list)?|list servers?|sources?|change server|select server|choose server|embed lists?|mirrors?)$/i;
  const NOT_SERVER = /^(\d{3,4}p\b.*|4k|uhd|quality.*|speed|subtitles?|captions?|settings|full ?screen|pause|play( now)?|watch( now)?|mute|unmute|volume|back|go back|return to site|related|share|download|trailer|add to.*|favorite.*|report.*|close|hide|next.*|prev.*|episodes?|seasons?|light.*|cinema mode|auto ?(play|next)|comments?|login|sign ?in|home|movies|tv( shows)?|search|\d+)$/i;
  const frames = () => [...document.querySelectorAll('iframe')]
      .map(f => f.src || f.getAttribute('data-src') || '').filter(s => /^https?:/.test(s));
  const leaf = el => ![...el.querySelectorAll(CLICK)].some(c => c !== el && vis(c) && txt(c));
  const navigates = el => {
    const a = el.closest('a[href]'); if (!a) return false;
    const h = a.getAttribute('href') || '';
    if (h === '' || h.startsWith('#') || h.startsWith('javascript')) return false;
    try { const u = new URL(a.href); return u.pathname !== location.pathname || u.host !== location.host; }
    catch (e) { return true; }
  };
  const serverish = el => { for (let e = el, i = 0; e && i < 5; e = e.parentElement, i++)
      if (SERVERISH.test((e.className || '').toString() + ' ' + (e.id || ''))) return true;
    return false; };
  // Hidden server buttons count too (soap2dayhd: <button id="srv-1" class="server"> hidden
  // until the player opens) - a JS click works on them anyway.
  const items = () => [...document.querySelectorAll(CLICK)].filter(el => {
      const t = txt(el);
      return (vis(el) || serverish(el)) && t && t.length >= 2 && t.length <= 32 && !NOT_SERVER.test(t)
             && leaf(el) && !navigates(el);
  });
  const openers = () => [...document.querySelectorAll('button,summary,[role=button],[aria-haspopup]')]
      .filter(el => vis(el) && (OPENER.test(txt(el)) || OPENER.test(el.getAttribute('aria-label') || '')));
  // Menus found by behaviour (cinebytv: <button>Main<svg/></button> -> 17 servers)
  let probed = [];
  const openAll = async () => {
    document.querySelectorAll('details').forEach(d => d.open = true);
    const ops = [...openers(), ...probed.filter(o => o.isConnected && vis(o))];
    for (const o of ops) { if (o.tagName !== 'SUMMARY' && o.getAttribute('aria-expanded') !== 'true') { o.click(); await sleep(500); } }
  };

  // Candidates: server-ish items already on the page + items a menu reveals.
  const before = new Set(items());
  await openAll(); await sleep(600);
  let revealed = items().filter(el => !before.has(el));
  if (revealed.length < 2) {
    // try short-text buttons with an icon (dropdown chevrons) as openers
    const tries = [...document.querySelectorAll('button,[role=button],[aria-haspopup]')]
      .filter(b => vis(b) && b.querySelector('svg,i,img') && txt(b).length >= 2 && txt(b).length <= 40
                   && !NOT_SERVER.test(txt(b)) && !navigates(b)).slice(0, 6);
    for (const b of tries) {
      const pre = new Set(items());
      b.click(); await sleep(700);
      const fresh = items().filter(el => !pre.has(el));
      if (fresh.length >= 3) { probed.push(b); revealed = fresh; break; }
      if (b.isConnected && vis(b)) { b.click(); await sleep(300); }   // close it again
    }
  }
  const cands = [];
  const seen = new Set();
  for (const el of [...revealed, ...items().filter(serverish)]) {
    const k = txt(el); if (seen.has(k)) continue; seen.add(k); cands.push(k);
  }

  // Mode groups (7movies: <details>Direct|Embed</details><details>servers</details>):
  // iterate the small first group, re-reading servers in each mode.
  const groups = [...document.querySelectorAll('details')]
      .map(d => [...d.querySelectorAll('button,li,[role=option]')].map(txt).filter(Boolean));
  const modes = groups.length >= 2 && groups[0].length <= 4 ? groups[0] : [null];

  const find = k => items().find(el => txt(el) === k);
  const results = [];
  for (const mode of modes) {
    let list = cands;
    if (mode) {
      await openAll(); const m = find(mode); if (m) { m.click(); await sleep(waitMs); }
      await openAll();   // server list differs per mode: re-read it now
      const cur = [...document.querySelectorAll('details')]
          .map(d => [...d.querySelectorAll('button,li,[role=option]')].map(txt).filter(Boolean));
      list = [...new Set([...cur.slice(1).flat(), ...cands])].filter(k => !groups[0].includes(k));
    }
    list = list.filter(k => !OPENER.test(k));
    for (const k of list.slice(0, maxItems)) {
      if (Date.now() - t0 > budgetMs) return {results, cands, truncated: true};
      let el = find(k);
      if (!el) { await openAll(); el = find(k); }
      if (!el) continue;
      try { el.click(); } catch (e) { continue; }
      await sleep(waitMs);
      results.push({mode, label: k, frames: frames()});
    }
  }
  return {results, cands, truncated: false};
}"""

# Things that lead from a title page to its player (JS-clicked, first match wins).
PLAY_JS = r"""() => {
  const vis = el => !!(el && (el.offsetParent || el.getClientRects().length));
  const txt = el => ((el.innerText || '').trim() || el.getAttribute('aria-label') || '').replace(/\s+/g, ' ');
  // hydrahd/vidplay: <span class="ajaxlink_mov0"><a><div class="vidzp">  (loads servers by AJAX)
  const sels = ['[class*=ajaxlink] a', '[class*=ajaxlink]', 'button.play', '.play-button',
                '.jw-icon-playback', '.vjs-big-play-button', '.plyr__control--overlaid'];
  // class WORD "play" (not "display"), e.g. btn-play, play_btn, play-icon
  const playClass = el => /(^|[\s_-])play([\s_-]|$)|play-?(btn|button|icon)|btn-?play/i
      .test((el.className || '').toString() + ' ' + (el.id || ''));
  const byText = [...document.querySelectorAll('a,button,[role=button]')]
      .find(el => vis(el) && /^(play( now)?|watch( now| online| free)?|stream now)!?$/i.test(txt(el)));
  const el = byText || sels.map(s => [...document.querySelectorAll(s)].find(vis)).find(Boolean)
      || [...document.querySelectorAll('a,button,div,span,i')].find(el => vis(el) && playClass(el)
             && !(el.closest('a[href]') && /\/(genre|category|tag|country|year)/.test(el.closest('a[href]').href)));
  if (!el) return null;
  const desc = el.tagName + ':' + txt(el).slice(0, 20);
  el.click();
  return desc;
}"""

# Splash pages: "View Full Site", "Go to homepage"...
SPLASH_JS = r"""() => {
  const a = [...document.querySelectorAll('a[href]')].find(a =>
      /full site|go to (home|site)|enter( site)?|continue to|watch now|homepage|^\s*home\s*$/i.test(a.innerText || '')
      || /\/home(\.html)?\/?$/.test(a.pathname));
  return a ? a.href : null;
}"""

LINKS_JS = r"""() => [...document.querySelectorAll('a[href]')].map(e => ({
  href: e.href, text: (e.textContent || '').trim().replace(/\s+/g, ' ').slice(0, 80),
  img: !!e.querySelector('img, picture, [style*=background]')}))
  .filter(x => x.href.startsWith('http'))"""


# ---------------------------------------------------------------------------
# Browser helpers
# ---------------------------------------------------------------------------

async def eval_all_frames(page, js: str) -> list:
    """Run `js` in the page and every frame; frames that refuse are skipped."""
    out = []
    for frame in page.frames:
        try:
            out.append(await asyncio.wait_for(frame.evaluate(js), FRAME_EVAL_TIMEOUT))
        except Exception:
            continue
    return out


async def blocked_reason(page) -> str | None:
    """Something answered instead of the site (network filter, bot challenge, dead host)."""
    try:
        title = (await page.title()).lower()
        body = (await page.inner_text("body", timeout=3000))[:2000].lower()
    except Exception:
        return None
    url = page.url.lower()
    if "web filter violation" in title or "fortiguard" in body or "access blocked" in body:
        return "blocked by network web filter"
    if ("just a moment" in title or "attention required" in title or "un instant" in title
            or "checking your browser" in body or "verify you are human" in body
            or "/verify" in url):
        return "bot challenge (Cloudflare or similar)"
    if "suspendedpage" in url or "account suspended" in body:
        return "hosting account suspended"
    if "domain" in title and ("for sale" in body or "parked" in body):
        return "parked / for-sale domain"
    return None


async def goto(page, url: str, cfg, retries: int = 1, settle: int | None = None):
    """page.goto with a retry on timeouts / transient network errors."""
    last = None
    for attempt in range(retries + 1):
        try:
            resp = await page.goto(url, timeout=cfg.timeout, wait_until="domcontentloaded")
            await page.wait_for_timeout(cfg.settle if settle is None else settle)
            return resp
        except Exception as e:
            if "Download is starting" in str(e):
                raise
            last = e
            if attempt < retries:
                await page.wait_for_timeout(1500)
    raise last


async def same_site_links(page, base: str, min_links: int = 10, wait_ms: int = 6000) -> list[dict]:
    """Links on the page, waiting a bit for JS-rendered catalogs (stellar.rip)."""
    deadline = time.monotonic() + wait_ms / 1000
    while True:
        try:
            links = [l for l in await page.evaluate(LINKS_JS) if same_site(l["href"], base)]
        except Exception:
            links = []
        if len(links) >= min_links or time.monotonic() > deadline:
            return links
        await page.wait_for_timeout(1000)


def path_shape(path: str) -> str:
    """/movie/12345-the-beast -> /movie/{id}"""
    out = []
    for s in [s for s in path.split("/") if s]:
        if re.fullmatch(r"\d+", s) or re.match(r"\d+[-_]", s) or re.search(r"[-_]\d{3,}$", s):
            out.append("{id}")
        elif "-" in s and len(s) > 10:
            out.append("{slug}")
        elif len(s) >= 5 and re.fullmatch(r"[A-Za-z0-9]+", s) and re.search(r"\d", s) and re.search(r"[A-Za-z]", s):
            out.append("{code}")
        else:
            out.append(s)
    return "/" + "/".join(out)


JUNK_SEGMENTS = {
    "genre", "genres", "category", "categories", "page", "login", "register", "signup",
    "search", "dmca", "contact", "about", "privacy", "terms", "home", "tag", "tags",
    "year", "country", "faq", "request", "trending", "popular", "filter", "browse",
    "az-list", "a-z", "discord", "telegram", "app", "donate", "person", "people", "actor",
    "actors", "cast", "studio", "network", "collection", "section", "discover", "explore",
    "settings", "watchlist", "your-lists", "list", "lists", "my-list", "news", "schedule",
    "download", "download-app", "ranking", "ranking-list", "advertise", "cookies", "sitemap",
    "newweb", "upcoming", "games", "sport", "sports", "live", "livetv"}


def is_junk_path(path: str) -> bool:
    segs = [x for x in path.lower().split("/") if x]
    return any(x in JUNK_SEGMENTS or re.match(r"(genre|country|tag|year|release|top)-", x)
               for x in segs)


JUNK_PATH = ("/genre", "/category", "/page/", "/login", "/register", "/signup",
             "/search", "/dmca", "/contact", "/about", "/privacy", "/terms", "/home",
             "/tag/", "/year/", "/country/", "/faq", "/request", "/top-", "/trending",
             "/popular", "/filter", "/browse", "/az-list", "/a-z", "/discord",
             "/telegram", "/app", "/donate", "/person/", "/actor", "/cast/", "/studio/",
             "/network/", "/collection/", "/section/", "/discover", "/explore",
             "/settings", "/watchlist", "/your-lists", "/list", "/news", "/schedule",
             "/download", "/ranking", "/advertise", "/cookies", "/sitemap")


# One-segment catalog/listing pages: /movies, /series/, /release-year-2026, /movies-rd1
LISTING = re.compile(r"^/(movies?|series|shows?|tv(-shows?|-series)?|films?|anime|new[\w-]*|latest[\w-]*|"
                     r"top[\w-]*|release[\w-]*|year[\w-]*|[\w]+-rd\d+|rd\d+|yes)(\.html)?/?$", re.I)


def rank_title_links(links: list[dict], limit: int = 3) -> list[str]:
    """Most plausible movie/show detail links. A site's catalog is the link
    pattern repeated most often (/movie/{id} x124), so that counts a lot."""
    year = re.compile(r"\(?(?:19|20)\d{2}\)?")
    kw = re.compile(r"/(movies?|watch|film|tv|show|series|title|play|v|detail|media|stream)(/|-|$)", re.I)
    shapes = Counter(path_shape(urlparse(l["href"]).path) for l in links)
    scored = {}
    for i, l in enumerate(links):
        h = l["href"].split("#")[0]
        path = urlparse(h).path
        lp = path.lower()
        if (lp.strip("/") in ("", "en", "home") or FILE_EXT.search(lp) or LISTING.match(lp)
                or is_junk_path(lp)):
            continue
        shape = path_shape(path)
        score = 2 if kw.search(lp) else 0
        if "{" in shape and shapes[shape] >= 6:   # the repeated catalog pattern
            score += 3
        if re.search(r"/\d{2,}|\d{4,}", path):     # numeric id
            score += 1
        if l["img"]:                                # poster
            score += 2
        if year.search(l["text"]):                  # "The Beast (2026)"
            score += 1
        if score < 2:
            continue
        prev = scored.get(h)
        if not prev or score > prev[0]:
            scored[h] = (score, prev[1] if prev else i)
    ranked = sorted(scored.items(), key=lambda kv: (-kv[1][0], kv[1][1]))
    return [h for h, _ in ranked[:limit]]


def fill(template: str) -> str:
    return template.format(**PROBE)


# ---------------------------------------------------------------------------
# Collecting
# ---------------------------------------------------------------------------

class Collector:
    """Findings for one title page across clicks, frames and network."""

    def __init__(self, site_url: str):
        self.site_url = site_url
        self.embeds: dict[str, str] = {}      # provider -> first embed URL seen
        self.server_map: list[dict] = []      # {label, mode, provider, host, how}
        self.stream_hosts: list[str] = []     # CDN hosts of .m3u8/.mpd
        self.from_text: list[str] = []
        self.self_hosted = False
        self.api_hosts: Counter = Counter()   # third-party xhr/fetch hosts (player backends)
        self.api_hits: list[dict] = []        # provider URLs found inside JSON responses
        # network callbacks run outside the site's context: remember it here
        self.site = CURRENT_SITE.get()

    def add_embed(self, url: str) -> str | None:
        if not url.startswith("http") or same_site(url, self.site_url):
            return None
        p = provider_from_host(url)
        if p and p not in self.embeds:
            self.embeds[p] = url
            emit("embed", provider=p, host=host_of(url), url=url[:300], site=self.site)
        return p

    def add_server(self, label: str, url: str, how: str, mode=None):
        p = self.add_embed(url)
        if not p:
            return
        entry = {"label": label, "mode": mode, "provider": p, "host": host_of(url), "how": how}
        if not any(e["label"] == label and e["provider"] == p for e in self.server_map):
            self.server_map.append(entry)
            emit("server", **entry, site=self.site)

    def on_request(self, req, main_frame):
        try:
            url = req.url
            if req.resource_type in ("xhr", "fetch") and not same_site(url, self.site_url):
                h = host_of(url)
                if h and not NOISE_HOSTS.search(h):
                    self.api_hosts[h] += 1
            if req.resource_type == "document" and req.frame != main_frame:
                self.add_embed(url)
            elif STREAM_URL.search(url):
                if same_site(url, self.site_url):
                    self.self_hosted = True
                else:
                    h = host_of(url)
                    if h and h not in self.stream_hosts and not NOISE_HOSTS.search(h):
                        self.stream_hosts.append(h)
        except Exception:
            pass

    async def on_response(self, resp):
        """Direct players fetch a JSON list of sources first: read it.
        Provider URLs inside become servers; .m3u8 URLs reveal the CDN."""
        try:
            req = resp.request
            if req.resource_type not in ("xhr", "fetch"):
                return
            ctype = (resp.headers.get("content-type") or "").lower()
            if "json" not in ctype and "text/plain" not in ctype:
                return
            body = await resp.text()
            if len(body) > 400_000:
                return
            for u in set(re.findall(r"https?:\\?/\\?/[^\s\"'<>\\]+", body)):
                u = u.replace("\\/", "/")
                if STREAM_URL.search(u):
                    h = host_of(u)
                    if same_site(u, self.site_url):
                        self.self_hosted = True
                    elif h and h not in self.stream_hosts and not NOISE_HOSTS.search(h):
                        self.stream_hosts.append(h)
                elif providers_in_text(host_of(u)) and not same_site(u, self.site_url):
                    self.add_server("api", u, how=f"api:{host_of(req.url)}")
                    if len(self.api_hits) < 30:
                        self.api_hits.append({"api": host_of(req.url), "url": u[:150]})
        except Exception:
            pass

    async def snapshot(self, page):
        """Frames + attribute embeds + page text, in every frame."""
        for frame in page.frames:
            if frame != page.main_frame:
                self.add_embed(frame.url)
        for chunk in await eval_all_frames(page, ATTR_EMBEDS_JS):
            for it in chunk:
                self.add_server(it["label"], it["url"], how=f"attr:{it['attr']}")
        text = "\n".join(await eval_all_frames(page, PAGE_TEXT_JS))
        for p in providers_in_text(text):
            if p not in self.from_text:
                self.from_text.append(p)

    async def cycle_servers(self, page, cfg):
        """Click every server in the main frame, map label -> loaded host."""
        try:
            res = await asyncio.wait_for(
                page.evaluate(SERVER_CYCLE_JS, {"budgetMs": cfg.cycle_budget * 1000,
                                                "waitMs": cfg.server_wait,
                                                "maxItems": cfg.max_servers}),
                cfg.cycle_budget + 15)
        except Exception as e:
            log(f"cycle failed: {type(e).__name__}: {str(e).splitlines()[0][:150] if str(e) else ''}")
            return
        log(f"cycle: {len(res['cands'])} candidates, {len(res['results'])} clicked"
            + (" (budget hit)" if res["truncated"] else ""))
        prev: set = set()
        for r in res["results"]:
            frames = [f for f in r["frames"] if not same_site(f, self.site_url)]
            # the frame that appeared/changed with this click is the server's
            new = [f for f in frames if f not in prev] or frames[:1]
            for f in new[:1]:
                self.add_server(r["label"], f, how="cycle", mode=r["mode"])
            prev = set(frames)

    def confirmed(self) -> list[str]:
        """Embeds that are a known provider or that a server entry points to."""
        tied = {e["provider"] for e in self.server_map}
        return [p for p in self.embeds if p in tied or p in PROVIDERS]

    def other_embeds(self) -> list[str]:
        ok = set(self.confirmed())
        return [host_of(u) for p, u in self.embeds.items() if p not in ok]

    def providers(self) -> list[str]:
        out = self.confirmed()
        for p in self.from_text:
            if p not in out:
                out.append(p)
        if self.self_hosted and not out:
            out.append("self-hosted")
        return out

    def has_player(self) -> bool:
        return bool(self.embeds or self.stream_hosts or self.self_hosted)

    def backends(self) -> list[str]:
        """Player API hosts of a direct (iframe-less) player."""
        return [h for h, _ in self.api_hosts.most_common(8)]


async def scan_title(context, title_url: str, cfg) -> tuple[Collector, bool]:
    """Open a title page, reach the player, collect providers.
    Returns (collector, page_ok) - page_ok False when the URL didn't lead to the title."""
    page = await context.new_page()
    col = Collector(title_url)
    page.on("request", lambda req: col.on_request(req, page.main_frame))
    page.on("response", lambda resp: asyncio.ensure_future(col.on_response(resp)))
    ok = True
    try:
        log(f"open {title_url}")
        resp = await goto(page, title_url, cfg)
        if resp is not None and resp.status in (404, 410):
            log(f"HTTP {resp.status}")
            return col, False
        if not same_site(page.url, title_url):
            log(f"redirected away to {host_of(page.url)}")
            return col, False
        await col.snapshot(page)

        # Reach the player: JS-click play/watch (2 tries: the 1st is often an ad trap)
        for _ in range(2):
            if col.has_player():
                break
            try:
                clicked = await asyncio.wait_for(page.evaluate(PLAY_JS), FRAME_EVAL_TIMEOUT)
            except Exception:
                clicked = None
            if not clicked:
                break
            log(f"play: {clicked}")
            await page.wait_for_timeout(cfg.click_wait)
            if not same_site(page.url, title_url):
                await goto(page, title_url, cfg, retries=0)
            await col.snapshot(page)

        await col.cycle_servers(page, cfg)
        await col.snapshot(page)
        log(f"providers: {col.providers()}")
    except Exception as e:
        msg = str(e).splitlines()[0][:80] if str(e) else ""
        print(f"      [!] {title_url} -> {type(e).__name__}: {msg}")
        ok = "Download is starting" not in str(e)
    finally:
        await page.close()
    return col, ok


async def title_candidates(page, site_url: str, cfg) -> list[tuple[str, str]]:
    """[(url, how)] in the order to try them."""
    out: list[tuple[str, str]] = []
    root = f"{urlparse(page.url).scheme}://{urlparse(page.url).netloc}"
    for t in SITE_HINTS.get(host_of(site_url), []):
        out.append((root + fill(t), "hint"))

    links = await same_site_links(page, page.url)
    if len(links) < 15 or not rank_title_links(links, 1):  # splash / landing page
        try:
            splash = await page.evaluate(SPLASH_JS)
        except Exception:
            splash = None
        if splash and same_site(splash, page.url) and splash.rstrip("/") != page.url.rstrip("/"):
            log(f"splash page -> {splash}")
            try:
                await goto(page, splash, cfg, retries=0)
                links = await same_site_links(page, page.url)
            except Exception:
                pass
    for u in rank_title_links(links, cfg.titles):
        out.append((u, "homepage"))
    for t in GENERIC_TEMPLATES:
        out.append((root + fill(t), "template"))

    log("candidates: " + ", ".join(f"{how}:{urlparse(u).path[:40]}" for u, how in out[:6]))
    seen, uniq = set(), []
    for u, how in out:
        if u not in seen:
            seen.add(u)
            uniq.append((u, how))
    return uniq


async def process_site(browser, site: str, cfg) -> dict:
    CURRENT_SITE.set(site)
    emit("site_start")
    base = site if site.startswith("http") else f"https://{site}"
    info = empty_result(site)
    t0 = time.monotonic()

    context = await browser.new_context(
        viewport={"width": 1280, "height": 800}, user_agent=USER_AGENT,
        locale="en-US", ignore_https_errors=True, accept_downloads=False)
    context.set_default_timeout(cfg.timeout)
    await context.add_init_script(INIT_JS)

    # Ad popups that still get through: close any page that has an opener.
    async def close_popup(p):
        try:
            if await p.opener():
                await p.close()
        except Exception:
            pass
    context.on("page", lambda p: asyncio.ensure_future(close_popup(p)))

    # Network guard:
    #  * ad scripts redirect the whole tab (7movies -> opera.com): once the site is
    #    loaded, top-level navigations to another domain are aborted;
    #  * images/media/fonts are dropped (unless --load-images).
    site_urls = [base]
    async def guard(route):
        req = route.request
        try:
            try:
                top_nav = req.is_navigation_request() and req.frame.parent_frame is None
            except Exception:
                top_nav = False
            if (top_nav
                    and not any(same_site(req.url, u) for u in site_urls)):
                log(f"blocked redirect to {host_of(req.url)}")
                # 204 = "no content": the browser stays on the current page
                # (abort() would swap in an error page and kill the player)
                return await route.fulfill(status=204, body="")
            if not cfg.load_images and req.resource_type in BLOCKED_RESOURCES:
                return await route.abort()
            await route.continue_()
        except Exception:
            try:
                await route.continue_()
            except Exception:
                pass
    await context.route("**/*", guard)

    try:
        page = await context.new_page()
        try:
            await goto(page, base, cfg, retries=cfg.retries)
            info["final_url"] = page.url
            site_urls.append(page.url)          # arms the redirect guard
            info["blocked"] = await blocked_reason(page)
            if info["blocked"]:
                info["status"] = "blocked"
                return info
            cands = await title_candidates(page, base, cfg)
        finally:
            await page.close()

        for title_url, how in cands[:cfg.max_tries]:
            info["tried_titles"].append(title_url)
            col, ok = await scan_title(context, title_url, cfg)
            direct = not col.providers() and bool(col.stream_hosts or col.self_hosted)
            if col.providers() or direct:
                info.update(
                    status="ok", title_url=title_url, title_found_by=how,
                    providers=col.providers(),
                    providers_embed=col.confirmed(),
                    other_embeds=col.other_embeds(),
                    providers_text=[p for p in col.from_text if p not in col.embeds],
                    server_map=col.server_map,
                    embed_urls=[col.embeds[p] for p in col.confirmed()],
                    stream_hosts=col.stream_hosts,
                    self_hosted=col.self_hosted,
                    backends=col.backends(),
                    api_hits=col.api_hits,
                )
                if direct:
                    # iframe-less player: name it by its CDN / backend
                    info["status"] = "direct"
                    info["providers"] = (["self-hosted"] if col.self_hosted else []) + \
                        [f"cdn:{bare_host('https://' + h)}" for h in col.stream_hosts[:3]]
                break
            if not info["backends"] and col.backends():
                info["backends"] = col.backends()
        if info["status"] not in ("ok", "direct"):
            info["status"] = "no_providers" if info["tried_titles"] else "no_title_link"
    except Exception as e:
        info["error"] = f"{type(e).__name__}: {str(e).splitlines()[0][:120] if str(e) else ''}"
    finally:
        info["seconds"] = round(time.monotonic() - t0, 1)
        await context.close()
    return info


def empty_result(site: str) -> dict:
    return {"site": site, "status": "failed", "final_url": None, "blocked": None,
            "error": None, "title_url": None, "title_found_by": None, "tried_titles": [],
            "providers": [], "providers_embed": [], "providers_text": [], "other_embeds": [],
            "server_map": [], "embed_urls": [], "stream_hosts": [], "self_hosted": False,
            "backends": [], "api_hits": [],
            "seconds": None}


# ---------------------------------------------------------------------------
# Report / CLI
# ---------------------------------------------------------------------------

def describe(r: dict) -> str:
    s = r["status"]
    if s == "ok":
        return f"providers ({r['title_found_by']}): " + ", ".join(r["providers"])
    if s == "blocked":
        return r["blocked"]
    if s == "direct":
        return "direct player: " + ", ".join(r["providers"]) + (
            f" (backend: {', '.join(r['backends'][:3])})" if r["backends"] else "")
    if s == "no_providers":
        return f"no provider found ({len(r['tried_titles'])} title pages tried)"
    if s == "no_title_link":
        return "homepage OK, no title page found"
    if s == "timeout":
        return r["error"]
    return f"homepage failed ({r['error'] or 'dead / unreachable'})"


def write_report(path: str, results: list[dict]):
    by_provider = defaultdict(set)
    for r in results:
        for p in r["providers"]:
            by_provider[p].add(r["site"])
    status = Counter(r["status"] for r in results)
    report = {
        "generated": time.strftime("%Y-%m-%d %H:%M:%S"),
        "probe_title": PROBE,
        "summary": dict(status),
        "providers_unique": sorted(by_provider),
        "by_provider": {k: sorted(v) for k, v in
                        sorted(by_provider.items(), key=lambda kv: (-len(kv[1]), kv[0]))},
        "by_site": {r["site"]: r for r in results},
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)
    return by_provider


async def launch_browser(pw, cfg):
    """Real Chrome when installed: Playwright's bundled Chromium has no H.264,
    so hls.js players (movy, moviebite...) never request their stream."""
    launch = dict(headless=not cfg.headful,
                  args=["--disable-blink-features=AutomationControlled", "--mute-audio",
                        "--autoplay-policy=no-user-gesture-required"])
    try:
        return (await pw.chromium.launch(channel=cfg.browser, **launch) if cfg.browser
                else await pw.chromium.launch(**launch))
    except Exception as e:
        print(f"[!] {cfg.browser} not available ({type(e).__name__}), using bundled Chromium")
        return await pw.chromium.launch(**launch)


def default_config(**over):
    """The CLI defaults as a config object, for use from other code (app.py)."""
    cfg = parse_args([])
    for k, v in over.items():
        setattr(cfg, k, v)
    return cfg


def parse_args(argv=None):
    ap = argparse.ArgumentParser(description="Find which embed providers streaming sites use.")
    ap.add_argument("sites", nargs="*", help="sites to scan (default: built-in list)")
    ap.add_argument("-f", "--file", help="text file with one site per line")
    ap.add_argument("-c", "--concurrency", type=int, default=4, help="sites in parallel (default 4)")
    ap.add_argument("-o", "--out", default="providers_report.json")
    ap.add_argument("--headful", action="store_true", help="show the browser")
    ap.add_argument("--browser", default="chrome",
                    help="Chrome channel: chrome (default), msedge, or '' for bundled Chromium")
    ap.add_argument("--timeout", type=int, default=25_000, help="navigation timeout, ms")
    ap.add_argument("--settle", type=int, default=6_000, help="wait after each load, ms")
    ap.add_argument("--click-wait", type=int, default=5_000, help="wait after clicking play, ms")
    ap.add_argument("--server-wait", type=int, default=2_500, help="wait after each server click, ms")
    ap.add_argument("--max-servers", type=int, default=25, help="servers to click per mode")
    ap.add_argument("--cycle-budget", type=int, default=75, help="seconds for server cycling")
    ap.add_argument("--titles", type=int, default=3, help="homepage title links to consider")
    ap.add_argument("--max-tries", type=int, default=5, help="title pages to try per site")
    ap.add_argument("--retries", type=int, default=1, help="homepage load retries")
    ap.add_argument("--site-timeout", type=int, default=300, help="hard limit per site, s")
    ap.add_argument("--load-images", action="store_true",
                    help="don't block images/media/fonts (slower, sometimes needed)")
    ap.add_argument("-v", "--verbose", action="store_true", help="log each step")
    cfg = ap.parse_args(argv)

    sites = list(cfg.sites)
    if cfg.file:
        with open(cfg.file, encoding="utf-8") as f:
            sites += [l.strip() for l in f if l.strip() and not l.lstrip().startswith("#")]
    cfg.sites = list(dict.fromkeys(sites or SITES))
    return cfg


async def main():
    global VERBOSE
    cfg = parse_args()
    VERBOSE = cfg.verbose
    sites = cfg.sites
    results: dict[str, dict] = {}
    sem = asyncio.Semaphore(max(1, cfg.concurrency))
    lock = asyncio.Lock()
    done = 0

    async with async_playwright() as pw:
        browser = await launch_browser(pw, cfg)

        async def run(site):
            nonlocal done
            async with sem:
                t0 = time.monotonic()
                try:
                    r = await asyncio.wait_for(process_site(browser, site, cfg), cfg.site_timeout)
                except asyncio.TimeoutError:
                    r = empty_result(site)
                    r.update(status="timeout", error=f"gave up after {cfg.site_timeout}s",
                             seconds=round(time.monotonic() - t0, 1))
            async with lock:
                done += 1
                results[site] = r
                print(f"[{done}/{len(sites)}] {site:24s} {r['seconds']:>5}s  {describe(r)}", flush=True)
                for s in r["server_map"]:
                    mode = f"[{s['mode']}] " if s["mode"] else ""
                    print(f"       {mode}{s['label'][:22]:22s} -> {s['host']}")
                if r["stream_hosts"]:
                    print(f"       stream CDN: {', '.join(r['stream_hosts'])}")
                write_report(cfg.out, [results[s] for s in sites if s in results])

        await asyncio.gather(*(run(s) for s in sites))
        await browser.close()

    ordered = [results[s] for s in sites]
    by_provider = write_report(cfg.out, ordered)

    print("\n===== RESULTS =====")
    for r in ordered:
        provs = ", ".join(r["providers"]) or "-"
        print(f"  {r['site']:24s} {r['status']:13s} {provs}")

    print("\n===== PROVIDERS =====")
    for p, ss in sorted(by_provider.items(), key=lambda x: (-len(x[1]), x[0])):
        print(f"  {p:16s} {len(ss):>2}  {', '.join(sorted(ss))}")

    print(f"\n[+] Saved {cfg.out}")


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n[!] Interrupted - partial results are in the report file")
