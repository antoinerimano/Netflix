"""
The site's providers as JSON, for the provider scout on the mini PC (provider_scraper/run.sh): it
checks every one of them with its current link first, so a wrong domain or link structure is
found and fixed by the next import_providers.

    docker compose exec -T backend python manage.py export_providers > site_providers.json
"""
import json

from django.core.management.base import BaseCommand

from users.models import Provider


class Command(BaseCommand):
    help = "Print the providers (key, domain, backups, link templates, enabled) as JSON for the provider scout."

    def handle(self, *args, **opts):
        rows = [{
            "key": p.key, "domain": p.domain, "backups": p.backups(), "movie_path": p.movie_path,
            "episode_path": p.episode_path, "enabled": p.enabled, "disabled_by_scout": p.disabled_by_scout,
        } for p in Provider.objects.all()]
        self.stdout.write(json.dumps(rows, indent=1))
