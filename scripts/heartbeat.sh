#!/bin/bash
# Every 5 minutes (cron, ops/crontab): the site answers (nginx -> Django -> MySQL: /api/health/)
# -> healthchecks.io check HC_PING_SITE pinged. Server down, nginx / backend / database down:
# the pings stop or say "fail", and healthchecks.io emails. A deploy restarts the backend for
# a minute: the check's grace time (10 min) covers it.
cd "$(dirname "$0")/.." || exit 1
domain=$(grep -E "^SITE_DOMAIN=" .env 2>/dev/null | tail -1 | cut -d= -f2- | tr -d "\r\"' ")
# straight to this server's nginx (no DNS / hairpin through the public address)
if [ -n "$domain" ] && curl -fsS -m 15 -o /dev/null --resolve "$domain:443:127.0.0.1" "https://$domain/api/health/"; then
  scripts/hc_ping.sh HC_PING_SITE 0
else
  echo "$(date '+%F %T') /api/health/ did not answer"
  scripts/hc_ping.sh HC_PING_SITE 1
fi
