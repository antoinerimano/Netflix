#!/usr/bin/env python3
"""
export_board.py
Turns providers_report.json + provider_catalog.json into the three files the
provider board reads:  board/sites.json, board/providers.json, board/links.json
Each is {rows, meta} so the board can show how the numbers were made.
"""
import json, os, re

REPORT, CATALOG, OUT = "providers_report.json", "provider_catalog.json", "board"


def main():
    rep = json.load(open(REPORT, encoding="utf-8"))
    cat = {p["provider"]: p for p in json.load(open(CATALOG, encoding="utf-8"))["providers"]} \
        if os.path.exists(CATALOG) else {}
    os.makedirs(OUT, exist_ok=True)
    meta = [{"label": "Scan", "value": rep.get("generated", "")},
            {"label": "Probe title", "value": f"TMDB {rep['probe_title']['tmdb']} / {rep['probe_title']['imdb']}"},
            {"label": "Made by", "value": "provider_scraper.py, then export_board.py"}]

    sites, links = [], []
    for s, r in rep["by_site"].items():
        provs = [p for p in r["providers"]]
        reason = r.get("blocked") or r.get("error") or ""
        sites.append({
            "site": s,
            "status": r["status"],
            "provider_count": len([p for p in provs if not p.startswith("cdn:") and p != "self-hosted"]),
            "providers": ", ".join(provs),
            "found_title_by": r.get("title_found_by") or "",
            "title_url": r.get("title_url") or "",
            "servers_mapped": len(r.get("server_map", [])),
            "stream_cdn": ", ".join(r.get("stream_hosts", [])[:3]),
            "backends": ", ".join(r.get("backends", [])[:3]),
            "reason": reason[:120],
            "seconds": r.get("seconds"),
        })
        how = {}
        for e in r.get("server_map", []):
            how.setdefault(e["provider"], e["how"].split(":")[0])
        for p in provs:
            if p.startswith("cdn:") or p == "self-hosted":
                continue
            h = how.get(p) or ("iframe" if p in r.get("providers_embed", []) else "text")
            labels = sorted({e["label"] for e in r.get("server_map", []) if e["provider"] == p and e["label"] != "api"})
            links.append({"site": s, "provider": p, "detected_by": h, "server_labels": ", ".join(labels)[:120]})

    providers = []
    counts = {}
    for l in links:
        counts.setdefault(l["provider"], set()).add(l["site"])
    def real_docs(u):
        # links that matched the "docs" heuristic but are not docs pages
        return bool(u) and not re.search(r"(#|#top)$|/tv/|/movie/|session-handoff|/episode/", u)

    for p, ss in counts.items():
        c = dict(cat.get(p, {}))
        if not real_docs(c.get("docs_url")):
            c["docs_url"] = None
        docs_state = ("docs found" if c.get("docs_url") else
                      "cloudflare" if (c.get("docs_error") or "").lower().startswith("cloudflare") else
                      "site down" if c.get("docs_error") else
                      "no docs page" if c.get("homepage") else "not checked")
        providers.append({
            "provider": p, "site_count": len(ss), "sites": ", ".join(sorted(ss)),
            "hosts": ", ".join(c.get("hosts", [])[:4]),
            "server_labels": ", ".join(c.get("server_labels", [])[:10]),
            "observed_template": (c.get("observed_templates") or [""])[0],
            "doc_formats": "\n".join(c.get("doc_formats", [])[:6]),
            "doc_params": ", ".join(c.get("doc_params", [])),
            "docs_url": c.get("docs_url") or "",
            "homepage": c.get("homepage") or "",
            "docs_state": docs_state,
        })
    providers.sort(key=lambda x: (-x["site_count"], x["provider"]))
    sites.sort(key=lambda x: (-x["provider_count"], x["site"]))

    for name, rows in (("sites", sites), ("providers", providers), ("links", links)):
        json.dump({"rows": rows, "meta": meta}, open(f"{OUT}/{name}.json", "w", encoding="utf-8"),
                  ensure_ascii=False, indent=1)
        print(f"  {OUT}/{name}.json  {len(rows)} rows")


if __name__ == "__main__":
    main()
