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

give_results() { [ ! -f results.json ] || remote import_trailer_results - < results.json; }
end=$(( $(date +%s) + ${MAX_MINUTES:-480} * 60 ))
pause=${BLOCKED_PAUSE_MINUTES:-30}
minutes_left() { echo $(( (end - $(date +%s)) / 60 )); }

# clips made before the original audio was asked for: a few a night, redone when the video has
# AI-dubbed tracks (make_previews.py recheck_audio); nothing left to check = a few seconds
.venv/bin/python make_previews.py --recheck-audio "${RECHECK_AUDIO:-100}" --max-minutes 90
rc=$?

# the new clips until MAX_MINUTES is used up. YouTube refused (exit 75): give the site what is
# done so far, wait BLOCKED_PAUSE_MINUTES and try again, rather than losing the rest of the night
while :; do
  if [ "$rc" -eq 75 ]; then
    if [ "$(minutes_left)" -le "$pause" ]; then
      echo "YouTube refused for now: the next run carries on"; rc=0; break
    fi
    echo "YouTube refused: trying again in $pause min ($(date '+%T'))"
    give_results || echo "Couldn't give the results to the server (tried again at the end)"
    sleep $(( pause * 60 ))
  fi
  left=$(minutes_left)
  [ "$left" -le 0 ] && { rc=0; break; }
  .venv/bin/python make_previews.py jobs.json --max-minutes "$left"
  rc=$?
  [ "$rc" -ne 75 ] && break
done

give_results || rc=1
exit "$rc"
