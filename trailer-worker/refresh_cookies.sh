#!/usr/bin/env bash
# Keeps the YouTube account's cookies alive with nobody at the keyboard: opens the Firefox
# profile of YTDLP_COOKIES_FROM_BROWSER (firefox:<dir>) on YouTube, headless, for a minute.
# YouTube's own page renews the Google session cookies; make_previews.py then reads them
# straight from the profile (yt-dlp --cookies-from-browser). Run by run.sh before every run.
# A failure never stops the run: the worker also tries without the account.
set -uo pipefail
cd "$(dirname "$0")"
[ -f .env ] && { set -a; . ./.env; set +a; }

spec=${YTDLP_COOKIES_FROM_BROWSER:-}
case "$spec" in
  firefox:/*) profile=${spec#firefox:} ;;
  *) exit 0 ;;  # no profile set up: nothing to refresh
esac
[ -d "$profile" ] || { echo "Cookie refresh: no Firefox profile at $profile"; exit 0; }

before=$(stat -c %Y "$profile/cookies.sqlite" 2>/dev/null || echo 0)
# SIGTERM after the minute: Firefox saves and quits; -k: killed if it hangs
timeout -k 20 "${COOKIE_REFRESH_SECONDS:-60}" \
  firefox --headless --no-remote --profile "$profile" "https://www.youtube.com/" > /dev/null 2>&1
# what Firefox wrote last can still sit in cookies.sqlite-wal; yt-dlp copies only cookies.sqlite
python3 -c 'import sqlite3, sys; sqlite3.connect(sys.argv[1]).execute("PRAGMA wal_checkpoint(TRUNCATE)")' \
  "$profile/cookies.sqlite" || echo "Cookie refresh: couldn't merge cookies.sqlite-wal"
after=$(stat -c %Y "$profile/cookies.sqlite" 2>/dev/null || echo 0)

if [ "$after" -gt "$before" ]; then
  echo "Cookie refresh: YouTube opened, cookies saved $(date -d "@$after" '+%F %T')"
else
  echo "Cookie refresh: the cookies did not change (still used, and the worker also tries without them)"
fi
