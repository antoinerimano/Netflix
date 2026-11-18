#!/bin/bash
# Weekly server cleanup (cron, Sunday 03:00 UTC: ops/crontab). Installed at /usr/local/bin/weekly-cleanup.sh.

LOG="/var/log/weekly-cleanup.log"
echo "========================================" >> $LOG
echo "  Weekly cleanup - $(date)" >> $LOG
echo "========================================" >> $LOG

echo "[1/3] Cleaning Docker..." >> $LOG
docker system prune -a -f >> $LOG 2>&1
docker builder prune -a -f >> $LOG 2>&1

echo "[2/3] Trimming journal logs..." >> $LOG
journalctl --vacuum-size=200M >> $LOG 2>&1

# app logs: not emptied here, /etc/logrotate.d/taurus (ops/logrotate-taurus) keeps 4 weeks of them

echo "[3/3] Disk usage after cleanup:" >> $LOG
df -h / >> $LOG

echo "Done." >> $LOG

# recorded for the dashboard / daily check-up (late when this stops running)
cd /opt/taurus && docker compose exec -T backend python manage.py record_job weekly_cleanup --summary "$(df -h / | tail -1 | awk '{print $4 " free (" $5 " used)"}')" >> $LOG 2>&1
