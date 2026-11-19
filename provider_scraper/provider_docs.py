#!/usr/bin/env python3
"""
provider_docs.py
Builds provider_catalog.json from providers_report.json:
  * for every provider found: the sites using it, its hosts, and the embed URL
    template actually observed (the probe title's ids replaced by {tmdb_id}/{imdb_id})
  * its public site + API/docs page, with the embed formats and URL parameters
    the docs list (found by visiting the provider's homepage)

Usage:  python provider_docs.py [-r providers_report.json] [-o provider_catalog.json]
"""

import argparse, asyncio, json, re, time
from collections import defaultdict
from urllib.parse import urlparse

DOC_LINK = re.compile(r"\b(api|docs?|documentation|embed|developer|guide|usage|integration)\b", re.I)
DOC_PATH = re.compile(r"/(api|docs?|documentation|embed-?(api|docs?))(/|$|\.|#)", re.I)
FMT = re.compile(r"(https?://[^\s\"'<>]*?(tmdb|imdb|\{id\}|\$id|season|episode|/movie/|/tv/)[^\s\"'<>]*)", re.I)
PARAM = re.compile(r"\b(autoplay|autoPlay|color|theme|primaryColor|startAt|progress|sub_?url|ds_?lang|"
                   r"overlay|nextEpisode|episodeSelector|title|poster|server|lang|fallback|serverOrder)\b")
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")


def host_of(url):
    return (urlparse(url).hostname or "").lower().removeprefix("www.")


def root_host(h):
    for p in ("player.", "embed.", "play.", "api.", "web.", "www."):
        if h.startswith(p):
            return h[len(p):]
    return h


def templatize(url, probe):
    u = url.split("#")[0]
    u = u.replace(str(probe["tmdb"]), "{tmdb_id}").replace(probe["imdb"], "{imdb_id}")
    u = re.sub(r"\?.*$", lambda m: m.group(0) if "{" in m.group(0) else "", u)
    return u if "{" in u else None


def collect(report):
    probe = report.get("probe_title") or {"tmdb": 1368337, "imdb": "tt33764258"}
    cat = defaultdict(lambda: {"sites": set(), "hosts": set(), "labels": set(), "observed": set(),
                               "how": set()})
    for site, r in report["by_site"].items():
        for p in r.get("providers", []):
            if p.startswith("cdn:") or p == "self-hosted":
                continue
            cat[p]["sites"].add(site)
        for u in r.get("embed_urls", []):
            from provider_scraper import provider_from_host
            p = provider_from_host(u)
            if p in cat:
                cat[p]["hosts"].add(host_of(u))
                t = templatize(u, probe)
                if t:
                    cat[p]["observed"].add(t)
        for e in r.get("server_map", []):
            p = e["provider"]
            if p in cat:
                cat[p]["hosts"].add(e["host"])
                cat[p]["how"].add(e["how"].split(":")[0])
                if e["label"] and e["label"] != "api":
                    cat[p]["labels"].add(e["label"])
        for p in r.get("providers_text", []):
            if p in cat:
                cat[p]["how"].add("text")
    return probe, cat


async def probe_docs(ctx, host):
    out = {"site": None, "title": None, "docs_url": None, "formats": [], "params": [], "error": None}
    page = await ctx.new_page()
    try:
        tried = [f"https://{root_host(host)}/"]
        if root_host(host) != host:
            tried.append(f"https://{host}/")
        for url in tried:
            try:
                await page.goto(url, timeout=20000, wait_until="domcontentloaded")
                break
            except Exception as e:
                out["error"] = str(e).splitlines()[0][:100]
        else:
            return out
        out["error"] = None
        await page.wait_for_timeout(3500)
        out["site"], out["title"] = page.url, (await page.title())[:90]
        if re.search(r"attention required|just a moment|un instant", out["title"], re.I):
            out["error"] = "Cloudflare challenge"
            return out
        links = await page.evaluate("""() => [...document.querySelectorAll('a[href]')]
            .map(a => ({href: a.href, text: (a.innerText||'').trim().slice(0,40)}))""")
        texts = [await page.evaluate("() => document.body ? document.body.innerText : ''")]
        doc = next((l["href"] for l in links
                    if (DOC_LINK.search(l["text"]) or DOC_PATH.search(urlparse(l["href"]).path + "#" + urlparse(l["href"]).fragment))
                    and root_host(host_of(l["href"])) == root_host(host_of(page.url))), None)
        if doc:
            out["docs_url"] = doc
            if urlparse(doc).path != urlparse(page.url).path:
                await page.goto(doc, timeout=20000, wait_until="domcontentloaded")
                await page.wait_for_timeout(3000)
                texts.append(await page.evaluate("() => document.body ? document.body.innerText : ''"))
        texts.append(await page.evaluate("() => [...document.querySelectorAll('code,pre')].map(e=>e.innerText).join('\\n')"))
        fm = []
        for t in texts:
            for m in FMT.finditer(t):
                u = m.group(1).rstrip(".,);")
                if u not in fm and len(u) < 160:
                    fm.append(u)
        out["formats"] = fm[:12]
        out["params"] = sorted(set(PARAM.findall("\n".join(texts))))
    except Exception as e:
        out["error"] = f"{type(e).__name__}: {str(e).splitlines()[0][:100]}"
    finally:
        await page.close()
    return out


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("-r", "--report", default="providers_report.json")
    ap.add_argument("-o", "--out", default="provider_catalog.json")
    ap.add_argument("--no-web", action="store_true", help="skip visiting provider sites")
    cfg = ap.parse_args()

    report = json.load(open(cfg.report, encoding="utf-8"))
    probe, cat = collect(report)

    docs = {}
    if not cfg.no_web:
        from playwright.async_api import async_playwright
        hosts = {p: sorted(c["hosts"], key=len)[0] for p, c in cat.items() if c["hosts"]}
        sem = asyncio.Semaphore(6)
        async with async_playwright() as pw:
            try:
                b = await pw.chromium.launch(headless=True, channel="chrome")
            except Exception:
                b = await pw.chromium.launch(headless=True)
            ctx = await b.new_context(user_agent=UA, ignore_https_errors=True)
            await ctx.add_init_script("window.open = () => null;")

            async def run(p, h):
                async with sem:
                    try:
                        docs[p] = await asyncio.wait_for(probe_docs(ctx, h), 60)
                    except asyncio.TimeoutError:
                        docs[p] = {"error": "timeout"}
                    print(f"  {p:16s} {h:28s} docs={docs[p].get('docs_url') or '-'}  "
                          f"{len(docs[p].get('formats') or [])} formats {docs[p].get('error') or ''}")
            await asyncio.gather(*(run(p, h) for p, h in hosts.items()))
            await b.close()

    providers = []
    for p, c in cat.items():
        d = docs.get(p, {})
        providers.append({
            "provider": p, "site_count": len(c["sites"]), "sites": sorted(c["sites"]),
            "hosts": sorted(c["hosts"]), "server_labels": sorted(c["labels"])[:20],
            "detected_by": sorted(c["how"]) or ["text"],
            "observed_templates": sorted(c["observed"])[:6],
            "homepage": d.get("site"), "homepage_title": d.get("title"),
            "docs_url": d.get("docs_url"), "doc_formats": d.get("formats", []),
            "doc_params": d.get("params", []), "docs_error": d.get("error"),
        })
    providers.sort(key=lambda x: (-x["site_count"], x["provider"]))
    json.dump({"generated": time.strftime("%Y-%m-%d %H:%M:%S"), "probe_title": probe,
               "providers": providers}, open(cfg.out, "w", encoding="utf-8"), indent=2, ensure_ascii=False)
    print(f"[+] {len(providers)} providers -> {cfg.out}")


if __name__ == "__main__":
    asyncio.run(main())
