"""
Bring the provider scout's catalog (provider_scraper/provider_catalog.json, made every night on
the mini PC by provider_scraper/run.sh) into the Provider table:

    docker compose exec -T backend python manage.py import_providers - < provider_catalog.json

Every provider's link (domain + structure) becomes the one that played every test film (several
well-known movies); providers that don't play them all are turned off, back on when they do. New
providers that play them all are added (enabled when 2+ scanned sites use them, otherwise disabled
for a look in the admin). See users/provider_import.py.
Running it again with the same file changes nothing.
"""
import json
import sys

from django.core.management.base import BaseCommand, CommandError

from users.jobs import tracked
from users.provider_import import MIN_SITES_TO_ENABLE, import_catalog


class Command(BaseCommand):
    help = "Import provider_scraper/'s provider_catalog.json (or - for stdin) into the providers."

    def add_arguments(self, parser):
        parser.add_argument("file", help="provider_catalog.json, or - to read it from stdin")
        parser.add_argument("--dry-run", action="store_true", help="Show what would change, change nothing.")
        parser.add_argument("--min-sites", type=int, default=MIN_SITES_TO_ENABLE,
                            help=f"Sites a new provider must be used by to be enabled (default {MIN_SITES_TO_ENABLE}).")

    # JobRun: the dashboard / check-up see when the mini PC last brought a catalog back
    @tracked("import_providers")
    def handle(self, *args, **opts):
        try:
            raw = sys.stdin.read() if opts["file"] == "-" else open(opts["file"], encoding="utf-8").read()
            catalog = json.loads(raw)
        except (OSError, ValueError) as e:
            raise CommandError(f"Can't read the catalog: {e}")
        if not isinstance(catalog, dict) or not isinstance(catalog.get("providers"), list):
            raise CommandError('Not a provider_catalog.json (no "providers" list).')

        lines, stats = import_catalog(catalog, dry_run=opts["dry_run"], min_sites=opts["min_sites"])
        for line in lines:
            self.stdout.write(line)
        self.stdout.write(
            ("[dry run] " if opts["dry_run"] else "")
            + f"catalog {catalog.get('generated', '?')}: {stats['created']} new "
              f"({stats['created_enabled']} enabled), {stats['new_backup']} new backup domain(s), "
              f"{stats['known_ok']} known and playing as they are, {stats['switched']} moved to another domain, "
              f"{stats['fixed_link']} movie link(s) and {stats['tv_fixed']} TV link(s) fixed, "
              f"{stats['disabled']} turned off, {stats['reenabled']} back on, {stats['unchecked']} couldn't be checked, "
              f"{stats['skipped_not_live']} new not playing, {stats['skipped_no_link']} without a link"
        )
