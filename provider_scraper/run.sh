#!/usr/bin/env bash
# The nightly run on the mini PC (cron, see README.md): scan the streaming sites for the embed
# providers they use, find each one's link format, check which really play a movie, and give the
# catalog to the site (manage.py import_providers: new providers, new domains of known ones).
set -uo pipefail
cd "$(dirname "$0")"
set -a; . ./.env; set +a
: "${SERVER_SSH:?set SERVER_SSH in .env}" "${SERVER_DIR:?set SERVER_DIR in .env}"
PY=.venv/bin/python
remote() { ssh -o BatchMode=yes "$SERVER_SSH" "cd '$SERVER_DIR' && docker compose exec -T backend python manage.py $*"; }

exec 9>/tmp/provider_scout.lock
flock -n 9 || { echo "Another run is going"; exit 0; }

echo "=== $(date '+%F %T') ==="
.venv/bin/pip install -q -U -r requirements.txt   # the sites change often: keep Playwright current

# 1. which providers each site uses (about 30-60 min for the ~40 sites)
if ! $PY provider_scraper.py -c "${CONCURRENCY:-4}" -o providers_report.json.part; then
  echo "Scan failed"; rm -f providers_report.json.part; exit 1
fi
# a scan where almost every site failed (no internet, DNS...) would make every provider look gone
ok=$($PY -c "import json,sys; print(json.load(open(sys.argv[1]))['summary'].get('ok', 0))" providers_report.json.part)
if [ "${ok:-0}" -lt "${MIN_SITES_OK:-5}" ]; then
  echo "Only $ok site(s) read: not trusting this scan"; rm -f providers_report.json.part; exit 1
fi
mv providers_report.json.part providers_report.json

# a normal Chrome window on a virtual screen: Cloudflare stops headless Chrome on players that
# open fine in a real browser
on_screen() {
  if command -v xvfb-run >/dev/null; then xvfb-run -a -s "-screen 0 1366x768x24" "$@"; else "$@"; fi
}

# 2. each provider's homepage / docs -> link formats (provider_catalog.json), with every provider
#    of the site and its current link (checked every night, even if no scanned site uses it)
if ! remote export_providers > site_providers.json.part; then
  echo "Couldn't read the site's providers: checking the scanned ones only"; echo "[]" > site_providers.json.part
fi
mv site_providers.json.part site_providers.json
on_screen $PY provider_docs.py -r providers_report.json -s site_providers.json -o provider_catalog.json || exit 1
# 3. does every test film really play on it ("live"), with which link
on_screen $PY provider_health.py -c provider_catalog.json -n "${CONCURRENCY:-4}" || exit 1
$PY export_board.py >/dev/null || true   # the local board, for a look

# 4. to the site
remote import_providers - < provider_catalog.json
