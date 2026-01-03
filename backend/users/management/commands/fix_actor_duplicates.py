import re
import time
import unicodedata
from dataclasses import dataclass

from django.core.management.base import BaseCommand
from django.db import transaction, IntegrityError

from users.models import Title, Actor


def norm(s: str) -> str:
    return " ".join((s or "").strip().lower().split())


_AS_SPLIT_RE = re.compile(r"\s+as\s+", re.IGNORECASE)
_TRAILING_PARENS_RE = re.compile(r"\(([^)]+)\)\s*$")


def fold_key(s: str) -> str:
    raw = unicodedata.normalize("NFKD", s or "")
    no_marks = "".join(ch for ch in raw if not unicodedata.combining(ch))
    lowered = no_marks.lower()
    lowered = re.sub(r"[^a-z0-9]+", " ", lowered)
    return " ".join(lowered.split())


def split_name_character(name: str, character: str):
    n = (name or "").strip()
    c = (character or "").strip()
    if n and not c:
        m = _TRAILING_PARENS_RE.search(n)
        if m:
            cand = m.group(1).strip()
            base = n[:m.start()].strip()
            if base and cand:
                return base, cand
        parts = _AS_SPLIT_RE.split(n)
        if len(parts) >= 2:
            base = " ".join(parts[:-1]).strip()
            cand = parts[-1].strip()
            if base and cand:
                return base, cand
    return n, c


@dataclass
class ActorItem:
    actor: Actor
    parsed_name: str
    parsed_character: str
    base_norm: str
    canonical_norm: str


def pick_keep(items):
    def score(it: ActorItem):
        a = it.actor
        return (
            1 if a.tmdb_id else 0,
            1 if a.profile_path else 0,
            1 if (a.character or it.parsed_character) else 0,
            1 if a.name == it.parsed_name else 0,
            -a.id,
        )
    return max(items, key=score)


class Command(BaseCommand):
    help = "Normalize Actor names (strip character in name) and merge duplicates per title."

    def add_arguments(self, parser):
        parser.add_argument("--limit", type=int, default=0, help="Max titles to process (0 = all)")
        parser.add_argument("--log-every", type=int, default=500, help="Log every N titles processed")
        parser.add_argument("--dry-run", action="store_true", help="Don't write, only log counts")

    @transaction.atomic
    def handle(self, *args, **opts):
        limit = int(opts["limit"])
        log_every = int(opts["log_every"])
        dry = bool(opts["dry_run"])

        qs = Title.objects.all().only("id").order_by("id")
        total_titles = qs.count() if limit <= 0 else min(qs.count(), limit)
        if limit > 0:
            qs = qs[:limit]

        self.stdout.write(self.style.MIGRATE_HEADING(
            f"fix_actor_duplicates: titles={total_titles} dry_run={dry}"
        ))

        t0 = time.time()
        processed = 0
        groups_merged = 0
        actors_deleted = 0
        actors_updated = 0

        for title in qs:
            processed += 1
            actors = list(Actor.objects.filter(title_id=title.id).order_by("id"))
            if not actors:
                continue

            groups = {}
            for a in actors:
                parsed_name, parsed_character = split_name_character(a.name, a.character)
                base_norm = norm(parsed_name)
                if not base_norm:
                    continue
                canonical_norm = fold_key(parsed_name)
                key = fold_key(a.name_norm or parsed_name)
                if not key:
                    continue
                groups.setdefault(key, []).append(
                    ActorItem(
                        actor=a,
                        parsed_name=parsed_name,
                        parsed_character=parsed_character,
                        base_norm=base_norm,
                        canonical_norm=canonical_norm,
                    )
                )

            for _, items in groups.items():
                if not items:
                    continue
                # Expand with any exact name_norm conflicts for this normalized key.
                target_norm = items[0].canonical_norm or items[0].base_norm
                if target_norm:
                    conflicts = (
                        Actor.objects
                        .filter(title_id=title.id, name_norm=target_norm)
                        .exclude(id__in=[it.actor.id for it in items])
                    )
                    for a in conflicts:
                        parsed_name, parsed_character = split_name_character(a.name, a.character)
                        items.append(
                            ActorItem(
                                actor=a,
                                parsed_name=parsed_name,
                                parsed_character=parsed_character,
                                base_norm=norm(parsed_name),
                                canonical_norm=fold_key(parsed_name),
                            )
                        )

                keep = pick_keep(items)
                changed = False

                # Merge data into keep, delete the rest.
                for it in items:
                    a = it.actor
                    if a.id == keep.actor.id:
                        continue

                    if not keep.actor.tmdb_id and a.tmdb_id:
                        keep.actor.tmdb_id = a.tmdb_id
                        changed = True
                    if not keep.actor.profile_path and a.profile_path:
                        keep.actor.profile_path = a.profile_path
                        changed = True
                    if not keep.actor.character and it.parsed_character:
                        keep.actor.character = it.parsed_character
                        changed = True

                    if not dry:
                        a.delete()
                    actors_deleted += 1

                # Normalize keep name + name_norm + character
                if keep.actor.name != keep.parsed_name and keep.parsed_name:
                    keep.actor.name = keep.parsed_name
                    changed = True
                target_norm = keep.canonical_norm or base_norm
                if keep.actor.name_norm != target_norm:
                    keep.actor.name_norm = target_norm
                    changed = True
                if not keep.actor.character and keep.parsed_character:
                    keep.actor.character = keep.parsed_character
                    changed = True

                if changed:
                    if not dry:
                        try:
                            keep.actor.save()
                        except IntegrityError:
                            conflict = (
                                Actor.objects
                                .filter(title_id=title.id, name_norm=target_norm)
                                .exclude(id=keep.actor.id)
                                .order_by("id")
                                .first()
                            )
                            if not conflict:
                                raise
                            # Merge keep into conflict, then drop keep to satisfy unique constraint.
                            conflict_changed = False
                            if not conflict.tmdb_id and keep.actor.tmdb_id:
                                conflict.tmdb_id = keep.actor.tmdb_id
                                conflict_changed = True
                            if not conflict.profile_path and keep.actor.profile_path:
                                conflict.profile_path = keep.actor.profile_path
                                conflict_changed = True
                            if not conflict.character and keep.parsed_character:
                                conflict.character = keep.parsed_character
                                conflict_changed = True
                            if keep.parsed_name and conflict.name != keep.parsed_name:
                                conflict.name = keep.parsed_name
                                conflict_changed = True
                            if conflict.name_norm != target_norm:
                                conflict.name_norm = target_norm
                                conflict_changed = True
                            if conflict_changed:
                                conflict.save()
                            keep.actor.delete()
                            actors_deleted += 1
                    actors_updated += 1

                if len(items) > 1:
                    groups_merged += 1

            if processed % log_every == 0 or processed == total_titles:
                elapsed = time.time() - t0
                rate = processed / elapsed if elapsed > 0 else 0
                remaining = total_titles - processed
                eta = (remaining / rate) if rate > 0 else 0
                self.stdout.write(
                    f"[{processed}/{total_titles}] merged_groups={groups_merged} "
                    f"deleted={actors_deleted} updated={actors_updated} "
                    f"rate={rate:.1f} titles/s ETA={eta/60:.1f}m"
                )

        elapsed = time.time() - t0
        self.stdout.write(self.style.SUCCESS(
            f"DONE fix_actor_duplicates: titles={processed} merged_groups={groups_merged} "
            f"deleted={actors_deleted} updated={actors_updated} elapsed={elapsed:.1f}s"
        ))
