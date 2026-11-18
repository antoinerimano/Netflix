#!/bin/bash

LOG="/var/log/weekly-cleanup.log"
echo "========================================" >> $LOG
echo "  Weekly cleanup - $(date)" >> $LOG
echo "========================================" >> $LOG

echo "[1/4] Cleaning Docker..." >> $LOG
docker system prune -a -f >> $LOG 2>&1
docker builder prune -a -f >> $LOG 2>&1

echo "[2/4] Trimming journal logs..." >> $LOG
journalctl --vacuum-size=200M >> $LOG 2>&1

echo "[3/4] Truncating app logs..." >> $LOG
> /var/log/taurus_reco.log
> /var/log/clean_db_weekly.log
> /var/log/taurus_clean_db.log
> /var/log/build_embeddings_weekly.log
echo "App logs truncated." >> $LOG

echo "[4/4] Disk usage after cleanup:" >> $LOG
df -h / >> $LOG

echo "Done." >> $LOG

# recorded for the dashboard / daily check-up (late when this stops running)
cd /opt/taurus && docker compose exec -T backend python manage.py record_job weekly_cleanup --summary "$(df -h / | tail -1 | awk '{print $4 " free (" $5 " used)"}')" >> $LOG 2>&1
