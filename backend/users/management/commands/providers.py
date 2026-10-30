# users/management/commands/providers.py
import json
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from users.models import Provider

# Config only: health-check fields (status, checked_at, ...) are per-server.
FIELDS = ["key", "label", "domain", "backup_domains", "movie_path", "episode_path",
          "enabled", "priority", "auto_switch"]
DEFAULT_FILE = Path(settings.BASE_DIR) / "providers.json"


class Command(BaseCommand):
    help = (
        "Copy the stream provider setup between servers through a JSON file (tracked in git).\n"
        "  export: write the providers of this DB to the file\n"
        "  import: make this DB match the file (matched by key; providers not in the file are deleted)"
    )

    def add_arguments(self, parser):
        parser.add_argument("action", choices=["export", "import"])
        parser.add_argument("--file", default=str(DEFAULT_FILE), help=f"Default: {DEFAULT_FILE}")
        parser.add_argument("--dry-run", action="store_true", help="import: show what would change, write nothing.")

    def handle(self, *args, **opts):
        path = Path(opts["file"])
        if opts["action"] == "export":
            rows = list(Provider.objects.order_by("priority", "key").values(*FIELDS))
            path.write_text(json.dumps(rows, indent=2) + "\n", encoding="utf-8")
            self.stdout.write(f"Exported {len(rows)} providers to {path}")
            return

        if not path.exists():
            raise CommandError(f"{path} not found (run 'providers export' where the setup is right).")
        rows = json.loads(path.read_text(encoding="utf-8"))
        keys = [r["key"] for r in rows]
        if len(keys) != len(set(keys)):
            raise CommandError("Duplicate keys in the file.")

        with transaction.atomic():
            for row in rows:
                values = {f: row[f] for f in FIELDS if f in row and f != "key"}
                current = Provider.objects.filter(key=row["key"]).first()
                if current is None:
                    self.stdout.write(f"+ add    {row['key']}: {values.get('domain')}")
                else:
                    diff = {f: v for f, v in values.items() if getattr(current, f) != v}
                    if not diff:
                        continue
                    self.stdout.write(f"~ update {row['key']}: " + ", ".join(f"{f}={v!r}" for f, v in diff.items()))
                if not opts["dry_run"]:
                    Provider.objects.update_or_create(key=row["key"], defaults=values)

            for p in Provider.objects.exclude(key__in=keys):
                self.stdout.write(f"- delete {p.key}: {p.domain}")
                if not opts["dry_run"]:
                    p.delete()

        self.stdout.write("Dry run, nothing written." if opts["dry_run"] else "Providers imported.")
