# Server ops

What lives on the server outside the app code, so the server can be rebuilt.

| File | Installed at | Install |
|---|---|---|
| `crontab` | root's crontab | `crontab ops/crontab` |
| `weekly-cleanup.sh` | `/usr/local/bin/weekly-cleanup.sh` | `install -m 755 ops/weekly-cleanup.sh /usr/local/bin/` |
| `logrotate-taurus` | `/etc/logrotate.d/taurus` | `install -m 644 ops/logrotate-taurus /etc/logrotate.d/taurus` |

Each deploy (`scripts/deploy.sh`) installs these three when they changed (the old crontab is kept in
`/var/backups/crontab.before-*`). So edit them **here**, never with `crontab -e` on the server: the
next deploy would put `ops/crontab` back.

## Running without anyone

- **healthchecks.io** emails when the server is down. Two checks:
  - `HC_PING_SITE`: every 5 min, `scripts/heartbeat.sh` asks this server's nginx for `/api/health/`
    (Django + MySQL) and pings it, or pings `/fail`. Period 5 min, grace 10 min (a deploy restarts the
    backend for a minute).
  - `HC_PING_CHECKUP`: the 07:00 daily check-up pings it when it ran. Period 1 day, grace 2 h.
  The ping URLs go in `backend/.env` (`HC_PING_SITE=https://hc-ping.com/...`), not in git: the
  repository is public. Without them `scripts/hc_ping.sh` does nothing.
- **Reboots**: security updates install themselves (unattended-upgrades); when one needs a reboot,
  `scripts/reboot_if_needed.sh` (Monday 10:30 UTC) waits for the running cron job like a deploy does
  (`scripts/job_locks.sh`), then reboots. Docker restarts the containers (`restart: unless-stopped`).
  Log: `/var/log/taurus_reboot.log`.

Not in git (keep them in a password manager): `.env`, `backend/.env`, `frontend/.env`.

## Watched jobs

Every job in the dashboard's `JOBS` (`backend/users/dashboard.py`) records its runs (`JobRun`): the
dashboard shows them and the daily check-up emails staff when one failed or is late. Django commands
use `@tracked`; the shell scripts here call `manage.py record_job <name>` when they end
(`backup_db.sh`: ok or failed, `weekly-cleanup.sh`); the mini PC's trailer clips are seen when it
imports them (`import_trailer_results`). The check-up also warns when the HTTPS certificate has
less than 14 days left (certbot renews at 30).

The dashboard's jobs card groups them (Catalog, Recommendations & home pages, AI, Health & safety)
with their schedule and what they do (`JOB_INFO`, next to `JOBS`); a new job needs a line in both.
Its "Catalog freshness" card shows what they keep up to date, in % of the titles.

Fresh titles, every night: `sync_tmdb_new_releases` (00:30) adds the movies just out (TMDB's trending,
in theatres, new on streaming; the weekly sync only takes 500+ votes), then the jobs that complete a
new title: age rating, translations, related titles, `rebuild_title_indexes` (07:15: keyword / studio /
network search) and `build_embeddings --missing` (08:00: "more like this"; the full build stays on Sundays).

`scripts/test_backup_restore.sh` (Wednesdays 02:15) loads the newest dump into a throwaway MySQL
container and checks the main tables came back (log: `/var/log/taurus_restore_test.log`).

`clean_db` runs every night for at most 150 minutes, on the titles not read on TMDB for 30 days
(`Title.tmdb_checked_at`): a run cut off by a deploy carries on the next night.

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
