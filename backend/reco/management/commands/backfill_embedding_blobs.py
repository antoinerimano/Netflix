from django.core.management.base import BaseCommand
from django.db import transaction
from reco.models import TitleEmbedding  # adapte si ton app s'appelle autrement

import numpy as np

BATCH = 500

class Command(BaseCommand):
    help = "Convert TitleEmbedding.vector (JSON) to vector_blob (float32 bytes)"

    def add_arguments(self, parser):
        parser.add_argument("--batch", type=int, default=BATCH)
        parser.add_argument("--limit", type=int, default=0)  # 0 = no limit
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **opts):
        batch = opts["batch"]
        limit = opts["limit"]
        dry = opts["dry_run"]

        qs = TitleEmbedding.objects.filter(vector_blob__isnull=True).only("id", "dim", "vector")
        total = qs.count() if limit == 0 else min(limit, qs.count())
        self.stdout.write(self.style.WARNING(f"[backfill] to_convert={total} batch={batch} dry={dry}"))

        done = 0
        while True:
            chunk = list(qs[:batch])
            if not chunk:
                break

            updates = []
            for te in chunk:
                vec = te.vector or []
                if not vec:
                    # rien à convertir
                    te.vector_blob = b""
                    te.dim = 0
                else:
                    arr = np.asarray(vec, dtype=np.float32)
                    te.vector_blob = arr.tobytes()
                    te.dim = int(arr.shape[0])
                updates.append(te)

            if not dry:
                with transaction.atomic():
                    TitleEmbedding.objects.bulk_update(updates, ["vector_blob", "dim"])
            done += len(updates)

            self.stdout.write(f"[backfill] done={done}/{total}")
            if limit and done >= limit:
                break

        self.stdout.write(self.style.SUCCESS("[backfill] finished"))
