# Configuration: every setting, where it lives, how to change it

One page for every key, domain, address and password the site uses. **Names only, never values**:
this repository is public. Keep the values in a password manager.

The daily check-up (`users/config_check.py`) checks these every morning and emails staff when one is
missing, when a service refuses a key (TMDB, Anthropic, the mail server), or when the debug mode is
on in production. A key that stops working is reported the same day instead of a job failing quietly.

## Where the settings live

| # | Place | Machine | Holds |
|---|---|---|---|
| 1 | `/opt/taurus/.env` | server | `SITE_DOMAIN`, `MYSQL_ROOT_PASSWORD` (read by `docker-compose.yml`) |
| 2 | `/opt/taurus/backend/.env` | server | everything Django and the cron jobs use (table below) |
| 3 | `/opt/taurus/frontend/.env` | server | `REACT_APP_API_BASE` (empty: the API is on the same domain) |
| 4 | `~/Desktop/Netflix/trailer-worker/.env` | mini PC | Bunny Storage zone + key, `SERVER_SSH`, `SERVER_DIR` |
| 5 | `~/provider-scout/provider_scraper/.env` | mini PC | `SERVER_SSH`, `SERVER_DIR` |
| 6 | GitHub > Settings > Environments > `production` | GitHub | secrets `SSH_HOST`, `SSH_USER`, `SSH_PRIVATE_KEY`, `SSH_PORT`; variables `DEPLOY_ENABLED`, `DEPLOY_PATH`, `HEALTHCHECK_URL` |
| 7 | rclone remote `gdrive` (`rclone config`) | server | the Google Drive token of the nightly backups (`ops/README.md`) |
| 8 | the services' own websites | - | TMDB, Anthropic, Bunny, Gmail (app password), healthchecks.io, the domain registrar (DNS) |

The example files list every variable: `.env.example`, `backend/.env.example`, `trailer-worker/.env.example`,
`provider_scraper/.env.example`.

## `backend/.env` (server)

| Variable | What for | When it changes |
|---|---|---|
| `DJANGO_SECRET_KEY` | signs sessions and login tokens | changing it logs every user out |
| `DJANGO_DEBUG` | `0` in production | never `1` on the server: error pages would show code and settings |
| `ADMINADMIN_URL` | the Django admin path | also in `nginx/templates/default.conf.template` (`location /super-admin-.../`): change both |
| `DB_NAME`, `DB_USER`, `DB_PASSWORD`, `DB_HOST`, `DB_PORT` | MySQL | `DB_PASSWORD` = `MYSQL_ROOT_PASSWORD` in `/opt/taurus/.env` when the database was created |
| `TMDB_API_KEY` | every catalog sync | themoviedb.org > Settings > API |
| `ANTHROPIC_API_KEY` | AI tags, translations, Ask Taurus, the check-up email | console.anthropic.com > API keys |
| `EMAIL_HOST`, `EMAIL_PORT`, `EMAIL_USE_TLS`, `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD` | every email (Gmail: an app password) | myaccount.google.com > Security > App passwords |
| `DEFAULT_FROM_EMAIL`, `SUPPORT_EMAIL` | sender / reply address | optional |
| `BUNNY_CDN_BASE` | where the trailer clips are served from | Bunny > the pull zone's hostname (also in trailer-worker's `.env`) |
| `HC_PING_SITE`, `HC_PING_CHECKUP` | healthchecks.io ping URLs | healthchecks.io > the check > Ping URL |
| `DJANGO_ALLOWED_HOSTS`, `FRONTEND_URL`, `CORS_ALLOWED_ORIGINS`, `CSRF_TRUSTED_ORIGINS`, `SITE_URL` | hosts, origins, links in emails and search engines | **leave unset**: they follow `SITE_DOMAIN` |
| `AI_*`, `THROTTLE_*`, `PREMIUM_*`, `NUM_PROXIES`, `SECURE_*` | budgets, rate limits, price | tuning, defaults in `backend/streaming_backend/settings.py` |

After a change: `cd /opt/taurus && docker compose up -d backend` (a few seconds). Cron jobs read the
file at each run.

## How to...

### Replace an API key (TMDB, Anthropic, the email password)

1. Make the new key on the service's website (table above).
2. On the server: `nano /opt/taurus/backend/.env`, replace the value.
3. `cd /opt/taurus && docker compose up -d backend`.
4. Check: `docker compose exec -T backend python manage.py shell -c "from users.config_check import config_problems; print(config_problems() or 'all good')"`.
5. Revoke the old key on the website.

### Replace the Bunny Storage key (trailer clips)

On the mini PC: `nano ~/Desktop/Netflix/trailer-worker/.env` (`BUNNY_API_KEY`). The next night's run uses it.
A key Bunny refuses shows up as `error` results in `run.log`, and the check-up reports the clips as late.

### Change the domain

1. At the registrar: point the new domain (and `www.`) at the server's IP (DNS `A` records).
2. On the server, get its certificate (nginx keeps running on the old one meanwhile):
   `cd /opt/taurus && docker compose run --rm certbot certonly --webroot -w /var/www/certbot -d NEW -d www.NEW`
   (the webroot answers for any name nginx sends to it: port 80 is open for every domain).
3. `nano /opt/taurus/.env`: `SITE_DOMAIN=NEW`.
4. `cd /opt/taurus && bash scripts/deploy.sh`: rebuilds the frontend with the new links, restarts the
   backend (hosts, origins, email links) and nginx (server name, certificate path).
5. GitHub > Environments > `production` > variable `HEALTHCHECK_URL` (`https://NEW/api/health/`).
6. Optional: a redirect from the old name (an extra `server` block in the nginx template).

Everything else follows `SITE_DOMAIN`: nginx, the frontend build (`index.html`, `robots.txt`),
Django's hosts / origins / `SITE_URL` (sitemaps, canonical links, emails), `scripts/heartbeat.sh`,
the certificate check of the check-up.

### Change the server's IP (a new server)

1. GitHub > Environments > `production` > secret `SSH_HOST`.
2. Mini PC: `SERVER_SSH=root@NEW` in **both** `~/Desktop/Netflix/trailer-worker/.env` and
   `~/provider-scout/provider_scraper/.env`, then `ssh root@NEW true` once (accepts its host key).
3. DNS: the domain's `A` records.
4. A whole new server: `ops/README.md` (cron files, rclone), copy `/opt/taurus/.env`,
   `backend/.env`, `frontend/.env`, restore a backup (`ops/README.md` > Restore).

### Change the CDN (Bunny)

`BUNNY_CDN_BASE` in `backend/.env` **and** in the mini PC's `trailer-worker/.env`
(plus `BUNNY_STORAGE_ZONE` / `BUNNY_STORAGE_HOST` / `BUNNY_API_KEY` there). Existing clips keep their
old address until they are made again.

### Change the database password

Both `DB_PASSWORD` (`backend/.env`) and the MySQL user itself
(`docker compose exec db mysql -uroot -p -e "ALTER USER 'root'@'%' IDENTIFIED BY '...'"`), then
`docker compose up -d backend`. `MYSQL_ROOT_PASSWORD` in `/opt/taurus/.env` is only read when the
database is created: keep it equal, for a rebuild.

## Also worth knowing

- The mini PC reaches the server with its own SSH key (`~/.ssh/id_ed25519`, in the server's
  `authorized_keys`); the deploy uses `SSH_PRIVATE_KEY` from GitHub.
- healthchecks.io emails the address of its account; the daily check-up emails every staff user.
- The values themselves: password manager. To see what the server has without showing values:
  `grep -oE "^[A-Z_]+=" /opt/taurus/backend/.env`.
