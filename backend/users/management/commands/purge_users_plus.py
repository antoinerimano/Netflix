import time
from django.core.management.base import BaseCommand
from django.db import transaction
from django.contrib.auth import get_user_model

from users.models import Profile, Subscription


class Command(BaseCommand):
    help = "Purge users created by seed_users_plus_bench (by email prefix), in safe chunks."

    def add_arguments(self, parser):
        parser.add_argument("--prefix", type=str, default="loadtest")
        parser.add_argument("--batch", type=int, default=25_000, help="Chunk size for deletions.")
        parser.add_argument("--db", type=str, default="default")
        parser.add_argument("--disable-fk-checks", action="store_true", help="MySQL only. Can speed deletes; use carefully.")

    def handle(self, *args, **opts):
        User = get_user_model()
        prefix = opts["prefix"].strip()
        batch = int(opts["batch"])
        db_alias = opts["db"]
        disable_fk = bool(opts["disable_fk_checks"])

        # We delete in chunks to avoid long locks / huge transactions.
        user_qs = User.objects.using(db_alias).filter(email__startswith=f"{prefix}_").order_by("email")

        total_users = user_qs.count()
        if total_users == 0:
            self.stdout.write(self.style.WARNING(f"No users found for prefix '{prefix}'. Nothing to purge."))
            return

        self.stdout.write(self.style.WARNING(
            f"Purging users with prefix '{prefix}': {total_users:,} users (batch={batch:,}, db='{db_alias}')"
        ))

        # Optional FK checks off (MySQL only). This can speed up but can be dangerous if you mix tables.
        if disable_fk:
            from django.db import connections
            conn = connections[db_alias]
            with conn.cursor() as cur:
                cur.execute("SET FOREIGN_KEY_CHECKS=0;")

        t0 = time.perf_counter()
        deleted_users = 0

        try:
            while True:
                # Pull a chunk of IDs (fast due to email index/ordering)
                ids = list(user_qs.values_list("id", flat=True)[:batch])
                if not ids:
                    break

                # Delete children first (faster + less cascade work per row)
                with transaction.atomic(using=db_alias):
                    Profile.objects.using(db_alias).filter(user_id__in=ids).delete()
                    Subscription.objects.using(db_alias).filter(user_id__in=ids).delete()
                    # Then delete users
                    n, _ = User.objects.using(db_alias).filter(id__in=ids).delete()

                deleted_users += n

                elapsed = time.perf_counter() - t0
                rate = deleted_users / elapsed if elapsed > 0 else 0
                self.stdout.write(
                    f"[OK] deleted_users={deleted_users:,}/{total_users:,} elapsed={elapsed:,.1f}s rate={rate:,.0f} users/s"
                )

        finally:
            if disable_fk:
                from django.db import connections
                conn = connections[db_alias]
                with conn.cursor() as cur:
                    cur.execute("SET FOREIGN_KEY_CHECKS=1;")

        total = time.perf_counter() - t0
        self.stdout.write(self.style.SUCCESS(
            f"Done purge. Deleted ~{deleted_users:,} users in {total:,.1f}s (~{(deleted_users/total):,.0f} users/s)"
        ))
