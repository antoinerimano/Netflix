#!/bin/bash
# Nightly MySQL backup (cron, see ops/crontab).
#   1. mysqldump of the app database, gzipped, into $LOCAL_DIR (newest $KEEP_LOCAL kept)
#   2. copied to Google Drive via the rclone remote in $REMOTE (files older than $KEEP_REMOTE_DAYS deleted)
# A dump is only kept and uploaded when it completed ("-- Dump completed" trailer).
#
# One-time setup of the Drive remote (needs a browser, see ops/README.md):  rclone config  -> name it "gdrive"
# Restore:  gunzip -c db-XXXX.sql.gz | docker compose exec -T -e MYSQL_PWD db mysql -h 127.0.0.1 -u"$DB_USER"   (dump includes CREATE DATABASE/USE)
set -euo pipefail

APP_DIR=/opt/taurus
LOCAL_DIR=${LOCAL_DIR:-/var/backups/taurus}
REMOTE=${REMOTE:-gdrive:taurus-backups}
KEEP_LOCAL=${KEEP_LOCAL:-3}
KEEP_REMOTE_DAYS=${KEEP_REMOTE_DAYS:-10}   # ~1.1 GB per dump: 10 days ~ 11 GB (free Google account = 15 GB)

log() { echo "[$(date -u '+%F %T')] $*"; }

cd "$APP_DIR"
envval() { grep -E "^$1=" backend/.env | tail -1 | cut -d= -f2- | tr -d '\r' | sed -e 's/^["'\'']//' -e 's/["'\'']$//'; }   # .env has CRLF endings
DB_NAME=$(envval DB_NAME)
DB_USER=$(envval DB_USER)
export MYSQL_PWD=$(envval DB_PASSWORD)   # passed by name to the container: never on a command line

umask 077
mkdir -p "$LOCAL_DIR"
OUT="$LOCAL_DIR/db-$(date -u +%Y%m%d-%H%M).sql.gz"

log "dump $DB_NAME -> $OUT"
docker compose exec -T -e MYSQL_PWD db \
  mysqldump -h 127.0.0.1 -u"$DB_USER" --single-transaction --quick --no-tablespaces \
  --set-gtid-purged=OFF --databases "$DB_NAME" 2> >(grep -v "Using a password" >&2) \
  | gzip -6 > "$OUT.part" || { log "ERROR: mysqldump failed"; rm -f "$OUT.part"; exit 1; }

if ! gzip -cd "$OUT.part" | tail -1 | grep -q -- "-- Dump completed"; then
  log "ERROR: dump incomplete, discarded"; rm -f "$OUT.part"; exit 1
fi
mv "$OUT.part" "$OUT"
log "dump ok: $(du -h "$OUT" | cut -f1)"

ls -1t "$LOCAL_DIR"/db-*.sql.gz | tail -n +$((KEEP_LOCAL + 1)) | xargs -r rm -f

if rclone listremotes | grep -qx "${REMOTE%%:*}:"; then
  rclone copy "$OUT" "$REMOTE" --retries 3
  rclone delete "$REMOTE" --min-age "${KEEP_REMOTE_DAYS}d" --include "db-*.sql.gz"
  log "uploaded to $REMOTE"
else
  log "ERROR: rclone remote '${REMOTE%%:*}' not configured, backup is LOCAL ONLY"; exit 2
fi
