import time
import uuid
import random
import string
from statistics import mean

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone
from django.contrib.auth import get_user_model

from users.models import Profile, Subscription


def rand_str(n=8):
    return "".join(random.choices(string.ascii_lowercase + string.digits, k=n))


def percentile(sorted_list, pct):
    if not sorted_list:
        return 0.0
    k = (len(sorted_list) - 1) * (pct / 100.0)
    f = int(k)
    c = min(f + 1, len(sorted_list) - 1)
    if f == c:
        return float(sorted_list[f])
    return float(sorted_list[f] * (c - k) + sorted_list[c] * (k - f))


class Command(BaseCommand):
    help = "Seed N users + 1 profile + 1 subscription each, then run a mini benchmark."

    def add_arguments(self, parser):
        parser.add_argument("--count", type=int, default=1_000_000)
        parser.add_argument("--batch", type=int, default=10_000)
        parser.add_argument("--prefix", type=str, default="loadtest")
        parser.add_argument("--password", type=str, default="Test1234!")
        parser.add_argument("--bench-iters", type=int, default=2000)
        parser.add_argument("--bench-sample", type=int, default=50_000, help="Max users to sample from (speeds up sampling).")
        parser.add_argument("--seed-only", action="store_true")
        parser.add_argument("--bench-only", action="store_true")
        parser.add_argument("--db", type=str, default="default")

    def handle(self, *args, **opts):
        User = get_user_model()
        db_alias = opts["db"]

        count = int(opts["count"])
        batch_size = int(opts["batch"])
        prefix = opts["prefix"].strip()
        password = opts["password"]
        bench_iters = int(opts["bench_iters"])
        bench_sample = int(opts["bench_sample"])
        seed_only = bool(opts["seed_only"])
        bench_only = bool(opts["bench_only"])

        if seed_only and bench_only:
            raise SystemExit("Use only one of --seed-only or --bench-only")

        # Pre-hash password once (avoid set_password 1M times)
        tmp = User(email="tmp@example.com", name="tmp")
        tmp.set_password(password)
        password_hash = tmp.password

        if not bench_only:
            self._seed(User, password_hash, count, batch_size, prefix, db_alias)

        if not seed_only:
            self._bench(User, prefix, bench_iters, bench_sample, db_alias)

    def _seed(self, User, password_hash, count, batch_size, prefix, db_alias):
        self.stdout.write(self.style.WARNING(
            f"Seeding {count:,} users + 1 profile + 1 subscription each "
            f"(batch={batch_size:,}, prefix='{prefix}', db='{db_alias}')"
        ))

        t0 = time.perf_counter()
        created = 0
        now = timezone.now()

        # simple distributions
        langs = ["en", "fr", "es"]
        ages = ["G", "PG", "13+", "16+", "18+"]

        while created < count:
            remaining = count - created
            n = min(batch_size, remaining)
            start_idx = created + 1

            users = []
            profiles = []
            subs = []

            for i in range(start_idx, start_idx + n):
                # IMPORTANT: explicit UUID so we can reference user_id without DB roundtrips
                uid = uuid.uuid4()
                suffix = rand_str(8)
                email = f"{prefix}_{i:012d}_{suffix}@example.com"

                u = User(
                    id=uid,
                    email=email,
                    name=f"{prefix} user {i}",
                    is_active=True,
                    is_staff=False,
                )
                u.password = password_hash
                users.append(u)

                profiles.append(Profile(
                    user_id=uid,
                    name=f"Profile {i}",
                    age_restriction=random.choice(ages),
                    avatar_url=None,
                    language_preference=random.choice(langs),
                ))

                plan_type = "Premium" if (i % 2 == 0) else "Basic"
                renewal = (now + timezone.timedelta(days=30)) if plan_type == "Premium" else None

                subs.append(Subscription(
                    user_id=uid,
                    plan_id=plan_type,          # ton modèle a plan_id + plan_type :contentReference[oaicite:1]{index=1}
                    plan_type=plan_type,
                    renewal_date=renewal,
                    status="Active",
                    is_trial=False,
                ))

            with transaction.atomic(using=db_alias):
                User.objects.using(db_alias).bulk_create(users, batch_size=n)
                Profile.objects.using(db_alias).bulk_create(profiles, batch_size=n)
                Subscription.objects.using(db_alias).bulk_create(subs, batch_size=n)

            created += n
            elapsed = time.perf_counter() - t0
            rate = created / elapsed if elapsed > 0 else 0

            self.stdout.write(
                f"[OK] created={created:,}/{count:,} elapsed={elapsed:,.1f}s rate={rate:,.0f} users/s"
            )

        total = time.perf_counter() - t0
        self.stdout.write(self.style.SUCCESS(
            f"Done seeding. {created:,} users (+profiles+subs) in {total:,.1f}s "
            f"(~{(created/total):,.0f} users/s)"
        ))

    def _bench(self, User, prefix, bench_iters, bench_sample, db_alias):
        self.stdout.write(self.style.WARNING(
            f"Benchmarking with prefix='{prefix}', iters={bench_iters:,}, sample_max={bench_sample:,} (db='{db_alias}')"
        ))

        # To avoid loading 1M ids in memory, we sample from a limited slice.
        # We pick random users by email prefix ordering.
        # (Works because email is unique and indexed)
        qs = User.objects.using(db_alias).filter(email__startswith=f"{prefix}_").order_by("email").values_list("id", "email")

        total = qs.count()
        if total == 0:
            self.stdout.write(self.style.ERROR("No users found for that prefix. Seed first or change --prefix."))
            return

        sample_n = min(total, bench_sample)
        # Get first sample_n rows (fast with index on email)
        sample_rows = list(qs[:sample_n])
        # Pre-sample ids/emails for benchmark loops
        picks = [random.choice(sample_rows) for _ in range(bench_iters)]

        timings_user_get = []
        timings_profiles = []
        timings_sub = []
        timings_prefetch = []

        # 1) user by email
        for uid, email in picks:
            t = time.perf_counter()
            _ = User.objects.using(db_alias).only("id", "email", "name").get(email=email)
            timings_user_get.append((time.perf_counter() - t) * 1000.0)

        # 2) profiles for user (typical “choose profile”)
        for uid, email in picks:
            t = time.perf_counter()
            _ = list(Profile.objects.using(db_alias)
                     .filter(user_id=uid)
                     .only("id", "name", "age_restriction", "language_preference")
                     .order_by("id")[:4])
            timings_profiles.append((time.perf_counter() - t) * 1000.0)

        # 3) subscription for user (typical “account status”)
        for uid, email in picks:
            t = time.perf_counter()
            _ = (Subscription.objects.using(db_alias)
                 .filter(user_id=uid)
                 .only("id", "plan_type", "status", "renewal_date")
                 .order_by("-start_date")  # start_date auto_now_add :contentReference[oaicite:2]{index=2}
                 .first())
            timings_sub.append((time.perf_counter() - t) * 1000.0)

        # 4) prefetch profiles+subs (pattern “load user account page in one go”)
        # NOTE: reverse relations depend on related_name; by default it's profile_set/subscription_set.
        for uid, email in picks:
            t = time.perf_counter()
            u = (User.objects.using(db_alias)
                 .filter(id=uid)
                 .prefetch_related("profile_set", "subscription_set")
                 .only("id", "email")
                 .first())
            # touch them so prefetch actually runs
            if u:
                _ = len(list(u.profile_set.all()))
                _ = len(list(u.subscription_set.all()))
            timings_prefetch.append((time.perf_counter() - t) * 1000.0)

        def report(name, arr):
            arr_sorted = sorted(arr)
            return {
                "name": name,
                "avg_ms": mean(arr_sorted),
                "p50_ms": percentile(arr_sorted, 50),
                "p95_ms": percentile(arr_sorted, 95),
                "max_ms": arr_sorted[-1] if arr_sorted else 0.0,
            }

        r1 = report("User by email (get)", timings_user_get)
        r2 = report("Profiles by user (list)", timings_profiles)
        r3 = report("Subscription by user (first)", timings_sub)
        r4 = report("User + prefetch (profiles+subs)", timings_prefetch)

        self.stdout.write("\n=== BENCH REPORT (ms) ===")
        for r in (r1, r2, r3, r4):
            self.stdout.write(
                f"- {r['name']}: avg={r['avg_ms']:.3f} | p50={r['p50_ms']:.3f} | p95={r['p95_ms']:.3f} | max={r['max_ms']:.3f}"
            )

        # Quick “QPS-ish”: based on total time for the arrays
        total_ops = 4 * bench_iters
        total_ms = sum(timings_user_get) + sum(timings_profiles) + sum(timings_sub) + sum(timings_prefetch)
        total_s = total_ms / 1000.0
        qps = (total_ops / total_s) if total_s > 0 else 0.0
        self.stdout.write(self.style.SUCCESS(
            f"\nApprox throughput: {qps:,.0f} ops/sec (over {total_ops:,} ORM ops)"
        ))
        self.stdout.write(self.style.WARNING(
            "Tip: if p95 is bad, add composite indexes: Profile(user_id), Subscription(user_id, status/start_date)."
        ))
