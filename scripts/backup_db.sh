#!/bin/bash
# Nightly MySQL backup (cron, see ops/crontab).
#   1. mysqldump of the app database, zstd-compressed, into $LOCAL_DIR (newest $KEEP_LOCAL kept)
#      Tables in $SKIP_DATA are dumped as empty tables (structure only): they are derived data the
#      cron jobs rebuild (build_embeddings -> titlesimilar/titleembedding, cron_build_home.sh ->
#      recohomesnapshot) and are ~2/3 of the database. After a restore, run those two to refill them.
#   2. copied to Google Drive via the rclone remote in $REMOTE (newest $KEEP_REMOTE kept: the Drive is 15 GB).
#      Older ones are deleted for good, not sent to the Drive trash (the trash counts toward the 15 GB),
#      and only after the new upload is confirmed on the Drive.
# A dump is only kept and uploaded when both parts completed ("-- Dump completed" trailers).
# Each run is recorded (manage.py record_job backup_db, with its last log line): the dashboard shows
# it and the daily check-up emails when a backup failed or none ran for 30 hours.
#
# One-time setup of the Drive remote (needs a browser, see ops/README.md):  rclone config  -> name it "gdrive"
# Restore:  zstd -dc db-XXXX.sql.zst | docker compose exec -T -e MYSQL_PWD db mysql -h 127.0.0.1 -u"$DB_USER"   (dump includes CREATE DATABASE/USE)
set -euo pipefail

APP_DIR=/opt/taurus
LOCAL_DIR=${LOCAL_DIR:-/var/backups/taurus}
REMOTE=${REMOTE:-gdrive:taurus-backups}
KEEP_LOCAL=${KEEP_LOCAL:-3}
KEEP_REMOTE=${KEEP_REMOTE:-7}
SKIP_DATA=${SKIP_DATA:-"reco_titlesimilar reco_titleembedding reco_recohomesnapshot"}

STATUS="stopped before the dump"
log() { STATUS="$*"; echo "[$(date -u '+%F %T')] $*"; }

cd "$APP_DIR"
record() {  # on exit: ok or failed, with the last thing logged (never fails the backup itself)
  local rc=$? flag=""
  [ "$rc" -ne 0 ] && flag="--failed"
  docker compose exec -T backend python manage.py record_job backup_db $flag --summary "$STATUS (exit $rc)" > /dev/null 2>&1 || echo "[$(date -u '+%F %T')] couldn't record the run on the dashboard"
}
trap record EXIT
envval() { grep -E "^$1=" backend/.env | tail -1 | cut -d= -f2- | tr -d '\r' | sed -e 's/^["'\'']//' -e 's/["'\'']$//'; }   # .env has CRLF endings
DB_NAME=$(envval DB_NAME)
DB_USER=$(envval DB_USER)
export MYSQL_PWD=$(envval DB_PASSWORD)   # passed by name to the container: never on a command line

umask 077
mkdir -p "$LOCAL_DIR"
OUT="$LOCAL_DIR/db-$(date -u +%Y%m%d-%H%M).sql.zst"

IGNORE=(); for t in $SKIP_DATA; do IGNORE+=("--ignore-table=$DB_NAME.$t"); done
dump() { docker compose exec -T -e MYSQL_PWD db mysqldump -h 127.0.0.1 -u"$DB_USER" \
  --single-transaction --quick --no-tablespaces --set-gtid-purged=OFF "$@" 2> >(grep -v "Using a password" >&2); }

log "dump $DB_NAME -> $OUT (structure only: $SKIP_DATA)"
{ dump --databases "$DB_NAME" "${IGNORE[@]}" && dump --no-data "$DB_NAME" $SKIP_DATA; } \
  | zstd -q -T0 -10 > "$OUT.part" || { log "ERROR: mysqldump failed"; rm -f "$OUT.part"; exit 1; }

if [ "$(zstd -dc "$OUT.part" | grep -c -- '^-- Dump completed')" != 2 ]; then
  log "ERROR: dump incomplete, discarded"; rm -f "$OUT.part"; exit 1
fi
mv "$OUT.part" "$OUT"
log "dump ok: $(du -h "$OUT" | cut -f1)"

ls -1t "$LOCAL_DIR"/db-*.sql.* | tail -n +$((KEEP_LOCAL + 1)) | xargs -r rm -f

if rclone listremotes | grep -qx "${REMOTE%%:*}:"; then
  rclone copy "$OUT" "$REMOTE" --retries 3
  # names are db-YYYYMMDD-HHMM: sorted by name = sorted by date
  REMOTE_FILES=$(rclone lsf "$REMOTE" --files-only --include "db-*.sql.*" | sort)
  if ! grep -qx "$(basename "$OUT")" <<< "$REMOTE_FILES"; then
    log "ERROR: $(basename "$OUT") not found on $REMOTE after upload, old backups kept"; exit 1
  fi
  OLD=$(head -n -"$KEEP_REMOTE" <<< "$REMOTE_FILES")
  for f in $OLD; do rclone deletefile "$REMOTE/$f" --drive-use-trash=false; done
  log "uploaded to $REMOTE: $(du -h "$OUT" | cut -f1), $(grep -c . <<< "$OLD") old deleted, newest $KEEP_REMOTE kept"
else
  log "ERROR: rclone remote '${REMOTE%%:*}' not configured, backup is LOCAL ONLY"; exit 2
fi
