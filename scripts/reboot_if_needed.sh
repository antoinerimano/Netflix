#!/bin/bash
# Weekly (cron, ops/crontab: Monday 10:30 UTC, the quietest time): security updates install
# themselves (unattended-upgrades), but a new kernel / libc only applies after a reboot, and the
# server never rebooted on its own. When Ubuntu says one is needed, wait for the running cron job
# (scripts/job_locks.sh, as a deploy does), then reboot. Docker brings the containers back
# (restart: unless-stopped); a job due during the reboot runs next time.
set -uo pipefail
cd "$(dirname "$0")/.." || exit 1
if [ ! -f /var/run/reboot-required ]; then
  echo "$(date '+%F %T') no reboot needed"
  exit 0
fi
echo "$(date '+%F %T') reboot needed for: $(tr '\n' ' ' < /var/run/reboot-required.pkgs 2>/dev/null)"
# shellcheck source=job_locks.sh
. scripts/job_locks.sh
take_job_locks 3600 || { echo "a job is still running after 1 h: next week"; exit 1; }
echo "$(date '+%F %T') rebooting"
systemctl reboot  # the locks stay held until the machine goes down
