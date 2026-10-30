#!/bin/bash
set -e

cd /opt/taurus

echo "[CRON] check_providers START $(date)"

docker compose exec -T backend \
  python manage.py check_providers

echo "[CRON] check_providers END $(date)"
