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
> /var/log/build_embeddings_weekly.log
echo "App logs truncated." >> $LOG

echo "[4/4] Disk usage after cleanup:" >> $LOG
df -h / >> $LOG

echo "Done." >> $LOG
