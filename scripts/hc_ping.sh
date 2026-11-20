#!/bin/bash
# hc_ping.sh NAME [EXIT_CODE]: tell healthchecks.io a check is alive (EXIT_CODE 0 or none) or
# failed (anything else). NAME is a variable in backend/.env holding the check's ping URL
# (HC_PING_SITE, HC_PING_CHECKUP): kept out of git, the repository is public. No URL: does
# nothing. healthchecks.io emails when a check stops pinging, so a dead server is noticed even
# though the daily check-up (which runs on it) can't send anything.
cd "$(dirname "$0")/.." || exit 0
url=$(grep -E "^$1=" backend/.env 2>/dev/null | tail -1 | cut -d= -f2- | tr -d '\r' | sed -e 's/^["'\'']//' -e 's/["'\'']$//')
[ -n "$url" ] || exit 0
[ "${2:-0}" = 0 ] || url="$url/fail"
curl -fsS -m 10 --retry 3 -o /dev/null "$url" || echo "healthchecks.io ping failed ($1)"
exit 0
