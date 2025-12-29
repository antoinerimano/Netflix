# users/signals.py
from datetime import timedelta
from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver
from django.utils import timezone

from users.models import Profile, Title
from reco.models import RecoHomeSnapshot

SEED_LIMIT = 30

def build_global_seed_payload():
    ids = list(
        Title.objects
        .order_by("-popularity", "-vote_average")
        .values_list("id", flat=True)[:SEED_LIMIT]
    )

    return {
        "mode": "seed_snapshot",
        "rows": [
            {
                "row_type": "seed_popular",
                "title": "Popular right now",
                "title_ids": ids,   # <- IMPORTANT: pas "items"
            }
        ],
    }

@receiver(post_save, sender=Profile)
def seed_profile_on_create(sender, instance: Profile, created, **kwargs):
    if not created:
        return

    payload = build_global_seed_payload()
    now = timezone.now()

    RecoHomeSnapshot.objects.update_or_create(
        profile_id=instance.id,
        algo_version="home_v1_seed",
        defaults={
            "payload": payload,
            "expires_at": now + timedelta(days=3650),
            "last_error": "",
        },
    )

@receiver(post_delete, sender=Profile)
def cleanup_profile_snapshots(sender, instance: Profile, **kwargs):
    RecoHomeSnapshot.objects.filter(profile_id=instance.id).delete()
