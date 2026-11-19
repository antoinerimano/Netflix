# Provider Scout

Finds which embed providers streaming sites use, with each provider's domains and API docs URL.

## Run the app (live UI)

```
python app.py
```
Open http://127.0.0.1:8765, set the sites under **Scan settings**, press **Start scan**.

- **Providers: domains & API docs** — every provider as it is found: its embed domains,
  homepage, API docs URL (probed live), the embed URL seen on a site (`{tmdb_id}`) and the
  formats its docs list. Filter by name/domain/site, or by "Has docs" / "No docs".
- **Sites** — live status per site, and the domain it redirects to. Click a site for its
  server → domain map, player backends and step log.
- **Live activity** — every step of the scan as it happens.
- Exports: Providers CSV (provider, domains, homepage, docs URL, embed template),
  Catalog JSON, Report JSON.

A partial scan merges into the saved results; nothing else is lost.

## Command line

```
python provider_scraper.py                  # all sites, writes providers_report.json
python provider_scraper.py site1.com -v     # one site, step by step
python provider_docs.py                     # provider homepages + docs -> provider_catalog.json
python export_board.py                      # files for the online board
```

Needs Python 3.10+, Playwright, and Google Chrome installed (Playwright's bundled
Chromium can't play H.264, so direct HLS players never start in it).

## Every night, on the mini PC (new providers without adding them by hand)

`run.sh` scans the sites, builds the catalog, checks which providers really play a movie, then
hands `provider_catalog.json` to the site (`manage.py import_providers`, see
`backend/users/provider_import.py`):

- **new provider that plays** (`live`) -> created on the site. **Enabled** when 2+ scanned sites
  use it, otherwise **disabled**: have a look in the admin (Providers) and tick *enabled*.
  It comes after your own providers (higher priority number).
- **known provider seen playing on another domain** (same link format) -> that domain is added to
  its backup domains, and becomes its domain if the 15-min health check has it down.
- what you set in the admin (enabled, priority, paths) is never overwritten.

Same machine as `trailer-worker/` (Debian / Ubuntu):

```bash
cd ~/taurus/provider_scraper
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
sudo .venv/bin/playwright install --with-deps chrome   # real Chrome: Chromium can't play H.264
cp .env.example .env && nano .env                      # the server's SSH address (same key as trailer-worker)
chmod +x run.sh && ./run.sh                            # first run by hand: ~30-60 min
```

Try the import without changing anything first:

```bash
ssh user@your-server 'cd /opt/taurus && docker compose exec -T backend python manage.py import_providers --dry-run -' < provider_catalog.json
```

`crontab -e` (after trailer-worker's night is well under way, the scan is light):

```
30 4 * * * /home/you/taurus/provider_scraper/run.sh >> /home/you/taurus/provider_scraper/run.log 2>&1
```

The site's dashboard shows the last import ("Provider scout (mini PC)"), and the daily check-up
emails when none came for 30 hours.
