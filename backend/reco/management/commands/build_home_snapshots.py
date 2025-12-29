# reco/management/commands/build_home_snapshots.py
import time
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from users.models import Profile
from reco.models import RecoHomeSnapshot
from reco.views import build_home_payload_exact


class Command(BaseCommand):
    help = "Build and store home recommendation snapshots for profiles."

    def add_arguments(self, parser):
        parser.add_argument("--hours", type=int, default=6)
        parser.add_argument("--limit", type=int, default=5000)
        parser.add_argument("--profile-id", type=int, default=None)

        # optionnel: si tu veux limiter aux profils actifs
        parser.add_argument("--only-active-days", type=int, default=None)

    def handle(self, *args, **opts):
        hours = opts["hours"]
        limit = opts["limit"]
        profile_id = opts["profile_id"]
        only_active_days = opts["only_active_days"]

        now = timezone.now()
        expires_at = now + timedelta(hours=hours)

        qs = Profile.objects.all()

        if profile_id:
            qs = qs.filter(id=profile_id)

        if only_active_days is not None:
            cutoff = now - timedelta(days=int(only_active_days))
            qs = qs.filter(titleaction__created_at__gte=cutoff).distinct()

        profiles = list(qs.order_by("id")[:limit])
        if not profiles:
            self.stdout.write("No profiles to build.")
            return

        self.stdout.write(f"Building snapshots for {len(profiles)} profiles (hours={hours})...")

        ok = 0
        err = 0

        for p in profiles:
            t0 = time.perf_counter()
            try:
                payload = build_home_payload_exact(profile=p, user_id=p.user_id, do_logs=False)

                RecoHomeSnapshot.objects.update_or_create(
                    profile_id=p.id,
                    defaults={
                        "algo_version": "home_v1",
                        "payload": payload,
                        "expires_at": expires_at,
                        "last_error": "",
                    }
                )

                ms = (time.perf_counter() - t0) * 1000.0
                self.stdout.write(f"OK profile={p.id} rows={len(payload.get('rows', []))} ms={ms:.1f}")
                ok += 1

            except Exception as e:
                RecoHomeSnapshot.objects.update_or_create(
                    profile_id=p.id,
                    defaults={
                        "algo_version": "home_v1",
                        "payload": {},
                        "expires_at": now + timedelta(minutes=10),
                        "last_error": str(e),
                    }
                )
                self.stderr.write(f"ERR profile={p.id}: {e}")
                err += 1

        self.stdout.write(f"Done. ok={ok} err={err}")
