# users/signals.py
from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver
from django.utils import timezone

from users.models import Profile, Title
from reco.models import TitleAction, RecoHomeSnapshot
from reco.views import upsert_seed_snapshot


@receiver(post_save, sender=Profile)
def seed_profile_on_create(sender, instance: Profile, created, **kwargs):
    """
    IMPORTANT:
    - Crée des 'seed actions' (facultatif mais utile si ton algo se base sur actions)
    - Crée IMMÉDIATEMENT un snapshot seed (home_v1_seed) pour éviter Home vide
    """
    if not created:
        return

    lang = (getattr(instance, "language_preference", "") or "").strip().lower()

    # 1) Seed ids (lang d'abord)
    seed_ids = []
    if lang:
        seed_ids = list(
            Title.objects
            .filter(original_language=lang)
            .order_by("-popularity", "-vote_average")
            .values_list("id", flat=True)[:18]
        )

    # 2) Fallback global
    if len(seed_ids) < 18:
        extra = list(
            Title.objects
            .order_by("-popularity", "-vote_average")
            .values_list("id", flat=True)[:30]
        )
        seen = set(seed_ids)
        for tid in extra:
            if tid not in seen:
                seed_ids.append(tid)
                seen.add(tid)
            if len(seed_ids) >= 18:
                break

    # 3) Crée des actions "seed"
    now = timezone.now()
    actions = [
        TitleAction(
            profile_id=instance.id,
            title_id=int(tid),
            action="seed",
            created_at=now,
        )
        for tid in seed_ids
    ]
    if actions:
        TitleAction.objects.bulk_create(actions, ignore_conflicts=True)

    # 4) ✅ Snapshot seed immédiat (Home non-vide dès le premier load)
    #    (aucun ranker/embeddings ici, juste des rows "connues")
    upsert_seed_snapshot(instance, hours=365 * 24)  # expires loin, vu que ton cron gère refresh


@receiver(post_delete, sender=Profile)
def cleanup_profile_snapshots(sender, instance: Profile, **kwargs):
    """
    Quand on supprime un profile -> supprimer aussi les snapshots.
    """
    RecoHomeSnapshot.objects.filter(profile_id=instance.id).delete()
    TitleAction.objects.filter(profile_id=instance.id).delete()
