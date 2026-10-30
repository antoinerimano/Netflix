#!/bin/bash
set -e

cd /opt/taurus

echo "[CRON] sync_tmdb_daily_episodes START $(date)"

docker compose exec -T backend \
  python manage.py sync_tmdb_daily_episodes --pages 5 --latest-seasons 2

echo "[CRON] sync_tmdb_daily_episodes END $(date)"
