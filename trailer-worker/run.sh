#!/usr/bin/env bash
# The nightly run (cron, see README.md): ask the site which titles need a clip, make them,
# give the results back to the site. The site's server only answers two quick commands.
set -uo pipefail
cd "$(dirname "$0")"
set -a; . ./.env; set +a
: "${SERVER_SSH:?set SERVER_SSH in .env}" "${SERVER_DIR:?set SERVER_DIR in .env}"
remote() { ssh -o BatchMode=yes "$SERVER_SSH" "cd '$SERVER_DIR' && docker compose exec -T backend python manage.py $*"; }

echo "=== $(date '+%F %T') ==="
.venv/bin/pip install -q -U -r requirements.txt   # YouTube changes often: old yt-dlp versions stop working

if remote export_trailer_jobs > jobs.json.part; then
  mv jobs.json.part jobs.json
else
  echo "Couldn't get the job list from the server"; rm -f jobs.json.part; exit 1
fi

.venv/bin/python make_previews.py jobs.json --max-minutes "${MAX_MINUTES:-480}"
rc=$?
[ "$rc" -eq 75 ] && echo "YouTube refused for now: the next run carries on" && rc=0

if [ -f results.json ]; then
  remote import_trailer_results - < results.json || rc=1
fi
exit "$rc"
