# users/management/commands/check_providers.py
from django.core.management.base import BaseCommand

from users.models import Provider
from users.providers import check_providers


class Command(BaseCommand):
    help = (
        "Health-check streaming providers: mark them up/down, follow redirects to a new domain "
        "and fall back to backup domains (when auto_switch is on). Run it from cron every ~15 min."
    )

    def add_arguments(self, parser):
        parser.add_argument("keys", nargs="*", help="Provider keys to check (default: all enabled).")

    def handle(self, *args, **opts):
        qs = Provider.objects.filter(enabled=True)
        if opts["keys"]:
            qs = Provider.objects.filter(key__in=opts["keys"])
        for line in check_providers(qs):
            self.stdout.write(line)
