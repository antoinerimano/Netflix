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

`run.sh` scans the sites, builds the catalog, checks which providers really play movies, then
hands `provider_catalog.json` to the site (`manage.py import_providers`, see
`backend/users/provider_import.py`).

**Tested the way tauruss plays them** (`provider_health.py`): each player is loaded in an
iframe of a page on the site's own origin (`site_origin` from `export_providers`), with the
site's iframe attributes and referrer policy, the link built like the frontend builds it, and the
frontend's rules: a page not loaded after 15 s is a failure (the site moves on to the next source),
and the players' postMessage events the site reads (Videasy, CineSrc, VidCore) count as proof.
Run it from the mini PC's network: an office network blocks some providers.

**The test titles are what the viewers watch** (`export_providers`: the latest movies and episodes
opened on the site, plus classics: The Godfather, Pulp Fiction, Casablanca, Friends 1x01, topped
up with popular ones). A title plays when a feature-length video (40 min+ for a movie, 10 min+ for
an episode: not a trailer, an ad or a "not available" clip) moves, or the player reports it. Not
compared with the TMDB runtime: director's cuts, credits and other edits differ. One default video
for every id shows up as 3+ titles of the very same length. **`live` = plays at least 90 % of
the titles that some provider plays** (a title nobody plays is nobody's fault): a limited catalog
shows up as `partial`. Same rule for the episodes, or the TV link is left out.

**Every provider of the site is checked every night** (`manage.py export_providers`), not only
the ones a scanned site uses, **its current link first**. A wrong link is not a dead provider, so
before saying "doesn't play" the check tries, in order: the current link, the link formats of
the provider's **API docs** (`provider_docs.py` follows every docs link of its homepage, else
tries /docs, /api, /documentation..., and reads full URLs, `${tmdbId}` and "/movie/{id}" written
apart from the base URL), the links seen on streaming sites, its docs' example URLs, the usual
structures (/movie/{id}, /embed/movie/{id}, ?tmdb=...), then its other KNOWN domains (backups,
seen on streaming sites, in its docs). Domains are never guessed: vidlink.ru is not vidlink. The catalog says which one played
(`template_source`).

Chrome runs as a normal window on a virtual screen (`xvfb-run`, needs the `xvfb` package):
headless Chrome gets Cloudflare pages on players that open fine in a real browser (vidfast).
Check a few providers by hand: `xvfb-run -a python provider_health.py -p xpass,vidlink`
(doesn't rewrite the catalog).

Then on the site (`import_providers`):
- **new provider that plays** -> created. **Enabled** when 2+ scanned sites use it, otherwise
  **disabled**: have a look in the admin (Providers) and tick *enabled*. It comes after the
  others (higher priority number).
- **a provider whose own link is dead** (domain down, or 404 on every title tried) and another
  link plays -> that one becomes its link (the old domain stays as a backup). Same for its TV link.
- **reports its playback to the page** (postMessage) -> *sends events* on, so the site can tell
  when it plays and offer the next source when it stays silent.
- **nothing else**: the scout never turns a provider off, nor touches a link that answers (slow,
  a bot check, a missing title...). Which sources play best for the viewers is the site's smart
  playback (success rates, the source that last worked for a title). The admin shows the scout's
  last check under *Provider scout*.

Same machine as `trailer-worker/` (Debian / Ubuntu):

```bash
cd ~/taurus/provider_scraper
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
sudo .venv/bin/playwright install --with-deps chrome   # real Chrome: Chromium can't play H.264
sudo apt install -y xvfb                                # a virtual screen: Chrome as a normal window
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
