# Server ops

What lives on the server outside the app code, so the server can be rebuilt.

| File | Installed at | Install |
|---|---|---|
| `crontab` | root's crontab | `crontab ops/crontab` |
| `weekly-cleanup.sh` | `/usr/local/bin/weekly-cleanup.sh` | `install -m 755 ops/weekly-cleanup.sh /usr/local/bin/` |

`crontab` is a copy: after `crontab -e` on the server, refresh it with `crontab -l > ops/crontab`.

Not in git (keep them in a password manager): `.env`, `backend/.env`, `frontend/.env`.

## Database backups

`scripts/backup_db.sh` runs nightly at 01:30 UTC (log: `/var/log/taurus_backup.log`):
zstd-compressed `mysqldump` into `/var/backups/taurus` (newest 3 kept), copied to Google Drive
folder `taurus-backups` through the rclone remote `gdrive` (10 days kept, ~210 MB each: ~2 GB of Drive).
`reco_titlesimilar`, `reco_titleembedding` and `reco_recohomesnapshot` are saved as empty tables:
they are derived data (~2/3 of the database) the cron jobs rebuild.
MySQL binary logs are off (`--skip-log-bin`), so these dumps are the only restore points.

### One-time Google Drive setup (needs a browser)

On the server: `rclone config` → `n` (new remote) → name `gdrive` → storage `drive` →
client id/secret: blank → scope `3` (drive.file: rclone only sees files it created) →
root folder / service account: blank → advanced config `n` →
"Use web browser to automatically authenticate?" `n`.
It prints a `rclone authorize "drive" "..."` command: run that on a computer that has a
browser and rclone installed, log in to Google, and paste the token it prints back into
the server prompt. Shared drive `n`, then `y` to keep it.
Check: `rclone lsd gdrive:` and `./scripts/backup_db.sh`.

### Restore

```bash
rclone copy gdrive:taurus-backups/db-YYYYMMDD-HHMM.sql.zst .   # or take one from /var/backups/taurus
export MYSQL_PWD='<DB_PASSWORD from backend/.env>'
zstd -dc db-YYYYMMDD-HHMM.sql.zst | docker compose exec -T -e MYSQL_PWD db mysql -h 127.0.0.1 -uroot
# refill the derived tables (home snapshots ~20 min); recommendations are degraded until then
docker compose exec -T backend python manage.py build_embeddings --type all --topk 80 --model-name all-MiniLM-L6-v2
./scripts/cron_build_home.sh
```

The dump contains `CREATE DATABASE` / `USE user_data_db` and drops and recreates each table.
