#!/bin/bash
set -e

cd /opt/taurus

echo "[CRON] build_home_snapshots START $(date)"

docker compose exec -T backend \
  python manage.py build_home_snapshots

echo "[CRON] build_home_snapshots END $(date)"
