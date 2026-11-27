#!/usr/bin/env bash
# The nightly run (cron, see README.md): ask the site which titles need a clip, make them,
# give the results back to the site. The site's server only answers two quick commands.
set -uo pipefail
cd "$(dirname "$0")"
set -a; . ./.env; set +a
: "${SERVER_SSH:?set SERVER_SSH in .env}" "${SERVER_DIR:?set SERVER_DIR in .env}"
# (each argument quoted for the server's shell: a summary is one argument, spaces and all)
remote() { ssh -o BatchMode=yes "$SERVER_SSH" "cd '$SERVER_DIR' && docker compose exec -T backend python manage.py $(printf '%q ' "$@")"; }
# the site's dashboard: "Trailer clips (mini PC)" running, its progress every hour, then the end
# (manage.py record_job). The dashboard being unreachable never stops the run.
started=$(date '+%Y-%m-%dT%H:%M:%S')
tell_site() { remote record_job trailer_worker "$@" > /dev/null || echo "Couldn't tell the site's dashboard ($1)"; }
progress() { .venv/bin/python make_previews.py jobs.json --progress "$started" 2>/dev/null || echo "?"; }
finish() { tell_site "$@"; exit "${rc:-1}"; }

echo "=== $(date '+%F %T') ==="
tell_site --start --summary "Asking the site which titles need a clip"
.venv/bin/pip install -q -U -r requirements.txt   # YouTube changes often: old yt-dlp versions stop working
bash refresh_cookies.sh   # the account's YouTube session renewed by a headless Firefox, nobody needed

if remote export_trailer_jobs > jobs.json.part; then
  mv jobs.json.part jobs.json
else
  echo "Couldn't get the job list from the server"; rm -f jobs.json.part
  rc=1; finish --failed --summary "Couldn't get the job list from the server (see run.log)"
fi

give_results() { [ ! -f results.json ] || remote import_trailer_results - < results.json; }
end=$(( $(date +%s) + ${MAX_MINUTES:-480} * 60 ))
pause=${BLOCKED_PAUSE_MINUTES:-30}
minutes_left() { echo $(( (end - $(date +%s)) / 60 )); }

# every PROGRESS_MINUTES: the clips made so far go to the site (not only at the end, ~21 h later)
# and the dashboard gets one line of progress. results.json is always a whole file (save_results).
(
  while sleep $(( ${PROGRESS_MINUTES:-60} * 60 )); do
    give_results > /dev/null || echo "Couldn't give the results to the server (tried again later)"
    tell_site --progress --summary "$(progress)"
  done
) &
reporter=$!
trap 'kill "$reporter" 2>/dev/null' EXIT

# clips made from a YouTube search that today's rules turn down (make_previews.py search_problem):
# withdrawn, the import takes them off the site, the titles are looked for again. No network.
.venv/bin/python make_previews.py jobs.json --recheck-search | tail -n 20

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
    bash refresh_cookies.sh   # a fresh session before trying again
  fi
  left=$(minutes_left)
  [ "$left" -le 0 ] && { rc=0; break; }
  .venv/bin/python make_previews.py jobs.json --max-minutes "$left"
  rc=$?
  [ "$rc" -ne 75 ] && break
done

kill "$reporter" 2>/dev/null
give_results || { echo "Couldn't give the results to the server"; rc=1; }
if [ "$rc" -eq 0 ]; then
  finish --summary "$(progress)"
else
  finish --failed --summary "$(progress), exit $rc (see run.log)"
fi
