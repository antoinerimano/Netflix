#!/bin/bash
# Deploy on the server (run by .github/workflows/ci-cd.yml after `git merge --ff-only origin/main`,
# from /opt/taurus): rebuild + restart the backend / frontend containers, then migrate.
#
# Restarting the backend kills any job running inside it (the weekly clean_db was cut off at
# 61,200 / 106,102 by a deploy on 2026-11-15). So the deploy first takes every cron job's lock
# (scripts/job_locks.sh: the same /tmp/*.lock files ops/crontab runs them with `flock -n`):
#   - a job running now: the deploy waits for it to finish (up to WAIT_SECONDS in all);
#   - a job due during the deploy: it finds its lock taken and skips this time (runs next time);
#   - still busy after WAIT_SECONDS: the deploy stops without restarting anything, says which job,
#     and can be run again from GitHub (Actions > the run > "Re-run failed jobs").
#   --locks-only   take the locks, say so, release them, restart nothing (a check)
#
# Then it installs the server's cron files from ops/ (root's crontab, weekly-cleanup.sh, the logrotate
# config) when they changed: a job a PR adds runs without anyone touching the server. Edit them in
# ops/, never with `crontab -e` on the server (the next deploy puts ops/crontab back).
set -euo pipefail

WAIT_SECONDS="${WAIT_SECONDS:-1200}"

# the site's domain (docs/CONFIG.md): docker compose refuses to run without it
if ! grep -qE "^SITE_DOMAIN=.+" .env 2>/dev/null; then
  echo "::error::SITE_DOMAIN is not set in $(pwd)/.env (see .env.example): nothing restarted."
  exit 1
fi
# shellcheck source=job_locks.sh
. "$(dirname "$0")/job_locks.sh"
take_job_locks "$WAIT_SECONDS" || exit 1

if [[ "${1:-}" == "--locks-only" ]]; then
  echo "--locks-only: nothing restarted."
  exit 0
fi

docker compose up -d --build backend frontend
docker compose exec -T backend python manage.py migrate --noinput

# nginx renders its config from nginx/templates (SITE_DOMAIN filled in) only when it starts: when the
# template, the headers, the domain or nginx's compose settings changed, check the new config in a
# throwaway container first (a bad one fails the deploy, the running nginx keeps the old one), then
# restart it (a second without answering).
nginx_sig=$( { cat nginx/templates/* nginx/security-headers.inc; grep -E "^SITE_DOMAIN=" .env; docker compose config nginx; } | sha256sum | cut -d" " -f1)
if [[ "$(cat /var/lib/taurus/nginx.sig 2>/dev/null)" != "$nginx_sig" ]]; then
  docker compose run --rm --no-deps -T nginx nginx -t
  docker compose up -d --force-recreate --no-deps nginx
  mkdir -p /var/lib/taurus && echo "$nginx_sig" > /var/lib/taurus/nginx.sig
  echo "::notice::nginx restarted with its new config"
fi
docker image prune -f

install_ops_file() {  # $1: the file in ops/, $2: where it goes ("crontab": root's crontab)
  local installed
  if [[ "$2" == crontab ]]; then installed=$(crontab -l 2>/dev/null || true); else installed=$(cat "$2" 2>/dev/null || true); fi
  [[ "$installed" == "$(cat "$1")" ]] && return 0
  if [[ "$2" == crontab ]]; then
    crontab -l > "/var/backups/crontab.before-$(date +%Y%m%d-%H%M)" 2>/dev/null || true
    crontab "$1"  # checks the syntax first: a bad file changes nothing and fails the deploy
  else
    install -m "$3" "$1" "$2"
  fi
  echo "::notice::installed $1 as $2"
}
install_ops_file ops/crontab crontab
install_ops_file ops/weekly-cleanup.sh /usr/local/bin/weekly-cleanup.sh 755
install_ops_file ops/logrotate-taurus /etc/logrotate.d/taurus 644
