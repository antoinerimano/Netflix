#!/usr/bin/env bash
set -euo pipefail

cd /opt/taurus
/usr/bin/docker compose run --rm backend python /app/add_trailer_to_cdn.py >> /opt/taurus/logs/add_trailer_to_cdn.log 2>&1
