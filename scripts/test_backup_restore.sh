#!/bin/bash
# Weekly backup restore test (cron, see ops/crontab): proves the newest nightly dump really restores.
#   1. starts a throwaway MySQL container (same image as the app's, nothing shared with it),
#   2. loads the newest /var/backups/taurus/db-*.sql.zst into it,
#   3. checks the main tables came back with about as many rows as the live database
#      (at least MIN_PCT %: the live one has grown since the dump),
#   4. removes the container and its data.
# Each run is recorded (manage.py record_job backup_restore_test): the dashboard shows it and the
# daily check-up emails when it failed or none ran for 8 days.
set -euo pipefail

APP_DIR=/opt/taurus
LOCAL_DIR=${LOCAL_DIR:-/var/backups/taurus}
MIN_PCT=${MIN_PCT:-95}
TABLES=${TABLES:-"users_title users_episode users_user users_profile reco_titleaction"}
NAME=taurus-restore-test

STATUS="stopped before the restore"
log() { STATUS="$*"; echo "[$(date -u '+%F %T')] $*"; }

cd "$APP_DIR"
finish() {  # on exit: remove the container, record ok or failed (never fails on its own)
  local rc=$? flag=""
  docker rm -f -v "$NAME" > /dev/null 2>&1 || true
  [ "$rc" -ne 0 ] && flag="--failed"
  docker compose exec -T backend python manage.py record_job backup_restore_test $flag --summary "$STATUS" > /dev/null 2>&1 \
    || echo "[$(date -u '+%F %T')] couldn't record the run on the dashboard"
}
trap finish EXIT
envval() { grep -E "^$1=" backend/.env | tail -1 | cut -d= -f2- | tr -d '\r' | sed -e 's/^["'\'']//' -e 's/["'\'']$//'; }
DB_NAME=$(envval DB_NAME)
DB_USER=$(envval DB_USER)
export MYSQL_PWD=$(envval DB_PASSWORD)

DUMP=$(ls -1t "$LOCAL_DIR"/db-*.sql.zst 2>/dev/null | head -1 || true)
[ -n "$DUMP" ] || { log "ERROR: no dump in $LOCAL_DIR"; exit 1; }
AGE_H=$(( ( $(date +%s) - $(stat -c %Y "$DUMP") ) / 3600 ))
[ "$AGE_H" -le 48 ] || { log "ERROR: newest dump $(basename "$DUMP") is ${AGE_H} h old"; exit 1; }

# a random root password that only lives in this container, passed by name (never on a command line)
export RESTORE_PWD=$(head -c 24 /dev/urandom | base64 | tr -dc 'A-Za-z0-9')
docker rm -f -v "$NAME" > /dev/null 2>&1 || true
log "starting $NAME for $(basename "$DUMP")"
docker run -d --name "$NAME" --memory 2g -e MYSQL_ROOT_PASSWORD="$RESTORE_PWD" mysql:8.0 \
  --skip-log-bin --innodb-buffer-pool-size=512M > /dev/null
in_test() { docker exec -i -e MYSQL_PWD="$RESTORE_PWD" "$NAME" mysql -uroot -N "$@"; }
for _ in $(seq 1 90); do
  in_test -e "SELECT 1" > /dev/null 2>&1 && break
  sleep 2
done
in_test -e "SELECT 1" > /dev/null || { log "ERROR: test MySQL didn't start"; exit 1; }

started=$(date +%s)
log "restoring $(basename "$DUMP")"
zstd -dc "$DUMP" | in_test || { log "ERROR: restore of $(basename "$DUMP") failed"; exit 1; }
minutes=$(( ( $(date +%s) - started + 59 ) / 60 ))

report=""
for t in $TABLES; do
  restored=$(in_test -e "SELECT COUNT(*) FROM \`$DB_NAME\`.\`$t\`")
  live=$(docker compose exec -T -e MYSQL_PWD db mysql -h 127.0.0.1 -u"$DB_USER" -N -e "SELECT COUNT(*) FROM \`$DB_NAME\`.\`$t\`" 2>/dev/null)
  [[ "$live" =~ ^[0-9]+$ ]] || { log "ERROR: couldn't count $t in the live database"; exit 1; }
  report="$report $t=$restored/$live"
  if [ "$live" -gt 0 ] && [ $(( restored * 100 )) -lt $(( live * MIN_PCT )) ]; then
    log "ERROR: $(basename "$DUMP"): $t has $restored rows restored, $live live (under $MIN_PCT %):$report"; exit 1
  fi
done
log "$(basename "$DUMP") restores in ${minutes} min, rows restored/live:$report"
