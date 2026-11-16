#!/bin/bash
# Deploy on the server (run by .github/workflows/ci-cd.yml after `git merge --ff-only origin/main`,
# from /opt/taurus): rebuild + restart the backend / frontend containers, then migrate.
#
# Restarting the backend kills any job running inside it (the weekly clean_db was cut off at
# 61,200 / 106,102 by a deploy on 2026-11-15). So the deploy first takes every cron job's lock
# (the same /tmp/*.lock files ops/crontab runs them with `flock -n`):
#   - a job running now: the deploy waits for it to finish (up to WAIT_SECONDS in all);
#   - a job due during the deploy: it finds its lock taken and skips this time (runs next time);
#   - still busy after WAIT_SECONDS: the deploy stops without restarting anything, says which job,
#     and can be run again from GitHub (Actions > the run > "Re-run failed jobs").
#   --locks-only   take the locks, say so, release them, restart nothing (a check)
set -euo pipefail

WAIT_SECONDS="${WAIT_SECONDS:-1200}"
LOCKS=(
  /tmp/clean_db_weekly.lock /tmp/sync_tmdb_weekly.lock /tmp/taurus_heavy.lock
  /tmp/taurus_tags.lock /tmp/taurus_related.lock /tmp/taurus_checkup.lock
  /tmp/taurus_episodes.lock /tmp/taurus_home.lock /tmp/taurus_backup.lock /tmp/taurus_recaps.lock
)

deadline=$(( $(date +%s) + WAIT_SECONDS ))
for lock in "${LOCKS[@]}"; do
  exec {fd}>>"$lock"  # kept open (and locked) until this script ends
  left=$(( deadline - $(date +%s) ))
  (( left < 1 )) && left=1
  if ! flock -n "$fd"; then
    echo "Waiting for the job holding $lock to finish (up to ${left}s)..."
    if ! flock -w "$left" "$fd"; then
      echo "::error::A job still holds $lock: nothing restarted. Run the deploy again once it is done."
      exit 1
    fi
  fi
done
echo "Every job lock taken: no job is running, none will start until the deploy ends."

if [[ "${1:-}" == "--locks-only" ]]; then
  echo "--locks-only: nothing restarted."
  exit 0
fi

docker compose up -d --build backend frontend
docker compose exec -T backend python manage.py migrate --noinput
docker image prune -f
