# Sourced by scripts/deploy.sh and scripts/reboot_if_needed.sh: every cron job's lock (the
# /tmp/*.lock files ops/crontab runs them with `flock -n`), and a function that takes them all.
# Holding them: no job is running, and one that is due skips this time (it runs next time).
# Restarting the backend or the server kills any job running inside it (the weekly clean_db was cut
# off at 61,200 / 106,102 by a deploy on 2026-11-15): take these first.
LOCKS=(
  /tmp/clean_db_weekly.lock /tmp/sync_tmdb_weekly.lock /tmp/taurus_heavy.lock
  /tmp/taurus_tags.lock /tmp/taurus_related.lock /tmp/taurus_checkup.lock
  /tmp/taurus_episodes.lock /tmp/taurus_home.lock /tmp/taurus_backup.lock /tmp/taurus_translate.lock
  /tmp/taurus_ratings.lock /tmp/taurus_new_releases.lock /tmp/taurus_index.lock /tmp/taurus_restore_test.lock
  /tmp/taurus_charts.lock /tmp/taurus_watch_providers.lock
)

# take_job_locks SECONDS: wait (up to SECONDS in all) for the running jobs to finish, then hold
# every lock until the calling script ends. Returns 1, naming the job, if one is still busy.
take_job_locks() {
  local deadline=$(( $(date +%s) + $1 )) lock fd left
  for lock in "${LOCKS[@]}"; do
    exec {fd}>>"$lock"  # kept open (and locked) until the calling script ends
    left=$(( deadline - $(date +%s) ))
    (( left < 1 )) && left=1
    if ! flock -n "$fd"; then
      echo "Waiting for the job holding $lock to finish (up to ${left}s)..."
      if ! flock -w "$left" "$fd"; then
        echo "::error::A job still holds $lock: nothing restarted. Try again once it is done."
        return 1
      fi
    fi
  done
  echo "Every job lock taken: no job is running, none will start until this script ends."
}
