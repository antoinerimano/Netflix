#!/usr/bin/env python3
"""
app.py - local web UI for provider_scraper, with live progress.

    python app.py            -> open http://127.0.0.1:8765

Runs the scraper in a background thread and streams every event to the page
(Server-Sent Events): site started, each step, each provider/server found,
each provider's homepage + API docs URL as soon as it is probed, site done.
Only the standard library and Playwright are needed.
"""

import asyncio, csv, io, json, os, queue, re, sys, threading, time, traceback
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse

import provider_scraper as ps
import provider_docs as pd
import provider_health as ph

HOST, PORT = "127.0.0.1", int(os.environ.get("PORT", "8765"))
HERE = os.path.dirname(os.path.abspath(__file__))
REPORT = os.path.join(HERE, "providers_report.json")
CATALOG = os.path.join(HERE, "provider_catalog.json")
UI = os.path.join(HERE, "ui.html")

lock = threading.RLock()
clients: list[queue.Queue] = []
STATE = {"running": False, "job": "", "started": None, "finished": None, "total": 0, "done": 0,
         "sites": {}, "providers": {}, "log": [], "source": "empty"}
RUN = {"loop": None, "task": None, "thread": None}
ALL_RESULTS: dict = {}   # site -> raw scraper result; saved scans + this session's, merged


# ---------------------------------------------------------------------------
# state + broadcast
# ---------------------------------------------------------------------------

def domain(u: str) -> str:
    return ps.host_of(u if "://" in u else "https://" + u)


def new_site(site: str) -> dict:
    return {"site": site, "domain": domain(site), "final_domain": "", "status": "queued",
            "providers": [], "servers": [], "title_url": "", "reason": "", "seconds": None,
            "stream_cdn": [], "backends": [], "log": []}


def new_provider(name: str) -> dict:
    return {"provider": name, "domains": [], "sites": [], "homepage": "", "docs_url": "",
            "docs_state": "pending", "formats": [], "params": [], "template": "", "title": "",
            "health": {}, "history": []}


def push(kind: str, data: dict):
    """Send one event to every open page."""
    msg = json.dumps({"type": kind, **data}, ensure_ascii=False, default=list)
    with lock:
        for q in list(clients):
            try:
                q.put_nowait(msg)
            except queue.Full:
                pass


def add_log(site: str, msg: str):
    line = {"t": time.strftime("%H:%M:%S"), "site": site, "msg": msg[:240]}
    with lock:
        STATE["log"].append(line)
        del STATE["log"][:-400]
        s = STATE["sites"].get(site)
        if s is not None:
            s["log"].append(line)
            del s["log"][:-60]
    push("log", line)


def touch_provider(name: str, host: str = "", site: str = "", url: str = "") -> tuple[dict, bool]:
    with lock:
        p = STATE["providers"].get(name)
        created = p is None
        if created:
            p = STATE["providers"][name] = new_provider(name)
        if host and host not in p["domains"]:
            p["domains"].append(host)
        if site and site not in p["sites"]:
            p["sites"].append(site)
        if url and not p["template"]:
            t = pd.templatize(url, ps.PROBE)
            if t:
                p["template"] = t
    push("provider", p)
    return p, created


def load_previous():
    """Show the last saved scan until a new one runs."""
    try:
        rep = json.load(open(REPORT, encoding="utf-8"))
    except Exception:
        return
    cat = {}
    try:
        cat = {c["provider"]: c for c in json.load(open(CATALOG, encoding="utf-8"))["providers"]}
    except Exception:
        pass
    with lock:
        ALL_RESULTS.update(rep.get("by_site", {}))
        for site, r in rep.get("by_site", {}).items():
            s = new_site(site)
            s.update(status=r["status"], final_domain=domain(r["final_url"]) if r.get("final_url") else "",
                     providers=r.get("providers", []), servers=r.get("server_map", []),
                     title_url=r.get("title_url") or "", seconds=r.get("seconds"),
                     reason=r.get("blocked") or r.get("error") or "",
                     stream_cdn=r.get("stream_hosts", []), backends=r.get("backends", []))
            STATE["sites"][site] = s
            for u in r.get("embed_urls", []):
                p = ps.provider_from_host(u)
                if p:
                    touch_provider(p, ps.host_of(u), site, u)
            for e in r.get("server_map", []):
                touch_provider(e["provider"], e["host"], site)
            for p in r.get("providers_text", []):
                touch_provider(p, "", site)
        for name, p in STATE["providers"].items():
            c = cat.get(name)
            if c:
                p.update(homepage=c.get("homepage") or "", docs_url=clean_docs(c.get("docs_url")),
                         formats=c.get("doc_formats", []), params=c.get("doc_params", []),
                         title=c.get("homepage_title") or "",
                         health=c.get("health") or {}, history=c.get("history") or [])
                p["docs_state"] = c.get("docs_state") or docs_state(p, c.get("docs_error"))
                if p["docs_state"] == "pending" or redirects_away(p):
                    p["docs_state"] = docs_state(p, c.get("docs_error"))
            elif not p["domains"]:
                p["docs_state"] = "name only"
        STATE["total"] = STATE["done"] = len(STATE["sites"])
        STATE["finished"] = rep.get("generated")
        STATE["source"] = "previous scan"


def clean_docs(u):
    return u if u and not re.search(r"(#|#top)$|/tv/|/movie/|session-handoff|/episode/", u) else ""


def redirects_away(p) -> bool:
    """Homepage now lives on an unrelated domain (dropped / sold / parked):
    vidsrcme.ru -> a tarot blog. Same name on another TLD (atlantic.st -> .bz) is fine."""
    names = {ps.bare_host("https://" + d) for d in p["domains"]}
    return bool(p["homepage"] and names and ps.bare_host(p["homepage"]) not in names)


def docs_state(p, err):
    if redirects_away(p):
        p["docs_url"] = ""
        return "redirects away"
    if p["docs_url"]:
        return "docs found"
    if err and "cloudflare" in err.lower():
        return "cloudflare"
    if err:
        return "site down"
    return "no docs page" if p["homepage"] else "pending"


def set_health(name: str, h: dict):
    with lock:
        p = STATE["providers"][name]
        p["health"] = h
        p["history"].append({"t": h.get("checked_at"), "state": h.get("state"), "ms": h.get("latency_ms")})
        del p["history"][:-30]
    push("provider", p)
    add_log("", f"health: {name} -> {h.get('state')} {h.get('latency_ms') or ''}ms {h.get('detail', '')}")


async def health_of(ctx, name: str):
    with lock:
        p = json.loads(json.dumps(STATE["providers"][name]))
    try:
        h = await asyncio.wait_for(ph.check_provider(ctx, p), 900)
    except Exception as e:
        h = {"state": "down", "detail": f"check failed: {type(e).__name__}",
             "checked_at": time.strftime("%Y-%m-%d %H:%M:%S")}
    set_health(name, h)


def save_catalog():
    with lock:
        rows = [{"provider": p["provider"], "site_count": len(p["sites"]), "sites": sorted(p["sites"]),
                 "hosts": p["domains"], "observed_templates": [p["template"]] if p["template"] else [],
                 "homepage": p["homepage"], "homepage_title": p["title"], "docs_url": p["docs_url"],
                 "doc_formats": p["formats"], "doc_params": p["params"],
                 "docs_state": "" if p["docs_state"] == "pending" else p["docs_state"],
                 "health": p["health"], "history": p["history"][-30:]}
                for p in STATE["providers"].values()]
    rows.sort(key=lambda x: (-x["site_count"], x["provider"]))
    json.dump({"generated": time.strftime("%Y-%m-%d %H:%M:%S"), "probe_title": ps.PROBE,
               "providers": rows}, open(CATALOG, "w", encoding="utf-8"), indent=2, ensure_ascii=False)


# ---------------------------------------------------------------------------
# the scan (runs in its own thread + event loop)
# ---------------------------------------------------------------------------

async def scan(sites: list[str], concurrency: int, probe_docs: bool, reprobe: bool, health: bool = True):
    from playwright.async_api import async_playwright
    cfg = ps.default_config(concurrency=concurrency)
    docs_q: asyncio.Queue = asyncio.Queue()
    queued_docs: set = set()
    results: dict = {}

    def want_docs(name, host):
        with lock:
            p = STATE["providers"].get(name)
            fresh = p and (reprobe or p["docs_state"] in ("pending",))
        if host and name not in queued_docs and ((probe_docs and fresh) or health):
            queued_docs.add(name)
            docs_q.put_nowait((name, host, bool(probe_docs and fresh)))

    def hook(kind, data):
        site = data.get("site", "")
        if kind == "log":
            add_log(site, data["msg"])
        elif kind == "site_start":
            with lock:
                STATE["sites"][site]["status"] = "running"
            push("site", STATE["sites"][site])
        elif kind == "embed":
            _, created = touch_provider(data["provider"], data["host"], site, data["url"])
            add_log(site, f"embed {data['provider']} ({data['host']})")
            want_docs(data["provider"], data["host"])
        elif kind == "server":
            add_log(site, f"server {data['label'][:30]!r} -> {data['host']}")
            with lock:
                s = STATE["sites"][site]
                s["servers"].append(data)
            push("site", s)

    ps.EVENT_HOOK = hook

    async with async_playwright() as pw:
        browser = await ps.launch_browser(pw, cfg)
        docs_ctx = await browser.new_context(user_agent=pd.UA, ignore_https_errors=True)
        await docs_ctx.add_init_script("window.open = () => null;")

        async def docs_worker():
            while True:
                name, host, do_docs = await docs_q.get()
                try:
                    if do_docs:
                        add_log("", f"docs: probing {name} ({host})")
                        try:
                            d = await asyncio.wait_for(pd.probe_docs(docs_ctx, host), 60)
                        except Exception as e:
                            d = {"error": f"{type(e).__name__}"}
                        with lock:
                            p = STATE["providers"][name]
                            p.update(homepage=d.get("site") or "", title=d.get("title") or "",
                                     docs_url=clean_docs(d.get("docs_url")), formats=d.get("formats") or [],
                                     params=d.get("params") or [])
                            p["docs_state"] = docs_state(p, d.get("error"))
                        push("provider", p)
                        add_log("", f"docs: {name} -> {p['docs_url'] or p['docs_state']}")
                    if health:
                        await health_of(docs_ctx, name)
                finally:
                    docs_q.task_done()

        workers = [asyncio.create_task(docs_worker()) for _ in range(3)]
        sem = asyncio.Semaphore(max(1, concurrency))

        async def run(site):
            async with sem:
                t0 = time.monotonic()
                try:
                    r = await asyncio.wait_for(ps.process_site(browser, site, cfg), cfg.site_timeout)
                except asyncio.TimeoutError:
                    r = ps.empty_result(site)
                    r.update(status="timeout", error=f"gave up after {cfg.site_timeout}s",
                             seconds=round(time.monotonic() - t0, 1))
            results[site] = r
            with lock:
                s = STATE["sites"][site]
                s.update(status=r["status"], providers=r["providers"], title_url=r.get("title_url") or "",
                         final_domain=domain(r["final_url"]) if r.get("final_url") else "",
                         reason=r.get("blocked") or r.get("error") or "", seconds=r["seconds"],
                         servers=r.get("server_map", []), stream_cdn=r.get("stream_hosts", []),
                         backends=r.get("backends", []))
                STATE["done"] += 1
            for p in r.get("providers_text", []):
                touch_provider(p, "", site)
            for p in r["providers"]:
                with lock:
                    if p in STATE["providers"] and site not in STATE["providers"][p]["sites"]:
                        STATE["providers"][p]["sites"].append(site)
                        push("provider", STATE["providers"][p])
            push("site", s)
            push("progress", {"done": STATE["done"], "total": STATE["total"]})
            add_log(site, f"done: {ps.describe(r)}")
            with lock:
                ALL_RESULTS[site] = r
                merged = list(ALL_RESULTS.values())
            ps.write_report(REPORT, merged)

        try:
            await asyncio.gather(*(run(s) for s in sites))
            if probe_docs or health:
                await asyncio.wait_for(docs_q.join(), 900)
        finally:
            for w in workers:
                w.cancel()
            await browser.close()
            ps.EVENT_HOOK = None


def start_scan(sites, concurrency, probe_docs, reprobe, health=True):
    with lock:
        if STATE["running"]:
            return False
        STATE.update(running=True, job="scan", started=time.strftime("%Y-%m-%d %H:%M:%S"), finished=None,
                     total=len(sites), done=0, source="live scan")
        for s in sites:
            old = STATE["sites"].get(s)
            STATE["sites"][s] = new_site(s)
        for p in STATE["providers"].values():   # site lists are rebuilt by this scan
            p["sites"] = [x for x in p["sites"] if x not in sites]
    push("reset", snapshot())

    def target():
        loop = asyncio.new_event_loop()
        RUN["loop"] = loop
        task = loop.create_task(scan(sites, concurrency, probe_docs, reprobe, health))
        RUN["task"] = task
        try:
            loop.run_until_complete(task)
            add_log("", "scan finished")
        except asyncio.CancelledError:
            add_log("", "scan stopped")
        except Exception as e:
            add_log("", f"scan crashed: {type(e).__name__}: {e}")
            traceback.print_exc()
        finally:
            with lock:
                for s in STATE["sites"].values():
                    if s["status"] in ("queued", "running"):
                        s["status"] = "stopped"
                STATE.update(running=False, job="", finished=time.strftime("%Y-%m-%d %H:%M:%S"))
            save_catalog()
            push("reset", snapshot())
            loop.close()

    RUN["thread"] = threading.Thread(target=target, daemon=True)
    RUN["thread"].start()
    return True


def start_health(names: list[str] | None):
    """Re-check providers (all with a known domain when names is empty)."""
    with lock:
        if STATE["running"]:
            return 0
        names = [n for n in (names or STATE["providers"]) if n in STATE["providers"]
                 and (STATE["providers"][n]["domains"] or STATE["providers"][n]["formats"])]
        STATE.update(running=True, job="health", total=len(names), done=0)
    push("reset", snapshot())

    async def job():
        from playwright.async_api import async_playwright
        cfg = ps.default_config()
        async with async_playwright() as pw:
            browser = await ps.launch_browser(pw, cfg)
            ctx = await browser.new_context(user_agent=pd.UA, ignore_https_errors=True)
            await ctx.add_init_script("window.open = () => null;")
            sem = asyncio.Semaphore(5)

            async def one(n):
                async with sem:
                    await health_of(ctx, n)
                with lock:
                    STATE["done"] += 1
                push("progress", {"done": STATE["done"], "total": STATE["total"]})
            try:
                await asyncio.gather(*(one(n) for n in names))
            finally:
                await browser.close()

    def target():
        loop = asyncio.new_event_loop()
        RUN["loop"] = loop
        RUN["task"] = loop.create_task(job())
        try:
            loop.run_until_complete(RUN["task"])
            add_log("", f"health check finished ({len(names)} providers)")
        except asyncio.CancelledError:
            add_log("", "health check stopped")
        except Exception as e:
            add_log("", f"health check crashed: {type(e).__name__}: {e}")
        finally:
            with lock:
                STATE.update(running=False, job="", finished=time.strftime("%Y-%m-%d %H:%M:%S"),
                             total=len(STATE["sites"]), done=len(STATE["sites"]))
            save_catalog()
            push("reset", snapshot())
            loop.close()

    RUN["thread"] = threading.Thread(target=target, daemon=True)
    RUN["thread"].start()
    return len(names)


def stop_scan():
    loop, task = RUN["loop"], RUN["task"]
    if loop and task and not task.done():
        loop.call_soon_threadsafe(task.cancel)
        return True
    return False


def snapshot() -> dict:
    with lock:
        return json.loads(json.dumps({k: STATE[k] for k in
                                      ("running", "job", "started", "finished", "total", "done", "source")} |
                                     {"sites": list(STATE["sites"].values()),
                                      "providers": list(STATE["providers"].values()),
                                      "log": STATE["log"][-150:], "default_sites": ps.SITES},
                                     default=list))


def providers_csv() -> str:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["provider", "health", "latency_ms", "checked_at", "test_url", "domains", "homepage",
                "docs_url", "docs_state", "embed_template", "documented_formats", "sites"])
    with lock:
        for p in sorted(STATE["providers"].values(), key=lambda p: (-len(p["sites"]), p["provider"])):
            h = p.get("health") or {}
            w.writerow([p["provider"], h.get("state", "untested"), h.get("latency_ms") or "", h.get("checked_at") or "",
                        h.get("test_url") or "", " ".join(p["domains"]), p["homepage"], p["docs_url"],
                        p["docs_state"], p["template"], " | ".join(p["formats"][:6]), " ".join(p["sites"])])
    return buf.getvalue()


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------

class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def send(self, code, body, ctype="application/json", extra=None):
        data = body.encode("utf-8") if isinstance(body, str) else body
        self.send_response(code)
        self.send_header("Content-Type", ctype + "; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        path = urlparse(self.path).path
        if path in ("/", "/index.html"):
            return self.send(200, open(UI, encoding="utf-8").read(), "text/html")
        if path == "/api/state":
            return self.send(200, json.dumps(snapshot(), ensure_ascii=False))
        if path == "/api/events":
            return self.events()
        if path == "/api/export/providers.csv":
            return self.send(200, providers_csv(), "text/csv",
                             {"Content-Disposition": 'attachment; filename="providers.csv"'})
        if path == "/api/export/report.json" and os.path.exists(REPORT):
            return self.send(200, open(REPORT, encoding="utf-8").read(), "application/json",
                             {"Content-Disposition": 'attachment; filename="providers_report.json"'})
        if path == "/api/export/catalog.json":
            save_catalog()
            return self.send(200, open(CATALOG, encoding="utf-8").read(), "application/json",
                             {"Content-Disposition": 'attachment; filename="provider_catalog.json"'})
        self.send(404, '{"error":"not found"}')

    def do_POST(self):
        path = urlparse(self.path).path
        n = int(self.headers.get("Content-Length") or 0)
        try:
            body = json.loads(self.rfile.read(n) or b"{}")
        except Exception:
            body = {}
        if path == "/api/run":
            sites = [s.strip().removeprefix("https://").removeprefix("http://").strip("/")
                     for s in body.get("sites") or ps.SITES]
            sites = list(dict.fromkeys(s for s in sites if s and not s.startswith("#")))
            ok = start_scan(sites, int(body.get("concurrency") or 4), bool(body.get("docs", True)),
                            bool(body.get("reprobe", False)), bool(body.get("health", True)))
            return self.send(200 if ok else 409, json.dumps({"started": ok, "sites": len(sites)}))
        if path == "/api/health":
            n = start_health(body.get("providers") or None)
            return self.send(200 if n else 409, json.dumps({"checking": n}))
        if path == "/api/stop":
            return self.send(200, json.dumps({"stopping": stop_scan()}))
        self.send(404, '{"error":"not found"}')

    def events(self):
        q: queue.Queue = queue.Queue(maxsize=5000)
        with lock:
            clients.append(q)
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "keep-alive")
        self.end_headers()
        try:
            self.wfile.write(b"retry: 2000\n\n")
            self.wfile.flush()
            while True:
                try:
                    msg = q.get(timeout=15)
                    self.wfile.write(f"data: {msg}\n\n".encode("utf-8"))
                except queue.Empty:
                    self.wfile.write(b": ping\n\n")
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass
        finally:
            with lock:
                if q in clients:
                    clients.remove(q)


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    load_previous()
    # Windows lets two servers share a port when reuse is on: refuse instead,
    # so a stale copy can't keep answering with old code.
    ThreadingHTTPServer.allow_reuse_address = False
    try:
        srv = ThreadingHTTPServer((HOST, PORT), Handler)
    except OSError:
        print(f"[!] Port {PORT} is already in use - is Provider Scout already running? "
              f"Close it, or start with PORT=8766 python app.py")
        return
    srv.daemon_threads = True
    print(f"Provider Scout running at http://{HOST}:{PORT}  (Ctrl+C to quit)")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        stop_scan()
        print("\nbye")


if __name__ == "__main__":
    main()
