#!/bin/bash
set -e

cd /opt/taurus

echo "[CRON] sync_tmdb_daily_episodes START $(date)"

docker compose exec -T backend \
  python manage.py sync_tmdb_daily_episodes --pages 5 --latest-seasons 2

# titles / synopses in every app language for what the sync just added (only titles never
# translated: cheap after the first run)
docker compose exec -T backend   python manage.py sync_tmdb_translations --limit 3000

# tell profiles following a show about its new episodes (bell + email)
docker compose exec -T backend \
  python manage.py notify_new_episodes

echo "[CRON] sync_tmdb_daily_episodes END $(date)"
