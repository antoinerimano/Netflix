import time
import re
from django.core.management.base import BaseCommand
from django.db import transaction
from users.models import Title, Actor


def norm(s: str) -> str:
    return " ".join((s or "").strip().lower().split())


_AS_SPLIT_RE = re.compile(r"\s+as\s+", re.IGNORECASE)
_TRAILING_PARENS_RE = re.compile(r"\(([^)]+)\)\s*$")


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


class Command(BaseCommand):
    help = "Populate Actor table from Title.cast JSONField (top N, dedupe per title, progress logs)."

    def add_arguments(self, parser):
        parser.add_argument("--top", type=int, default=8, help="Max actors per title from Title.cast")
        parser.add_argument("--limit", type=int, default=0, help="Max titles to process (0 = all)")
        parser.add_argument("--log-every", type=int, default=500, help="Log every N titles processed")
        parser.add_argument("--dry-run", action="store_true", help="Don't write, only log counts")

    @transaction.atomic
    def handle(self, *args, **opts):
        top = int(opts["top"])
        limit = int(opts["limit"])
        log_every = int(opts["log_every"])
        dry = bool(opts["dry_run"])

        qs = Title.objects.all().only("id", "cast").order_by("id")
        total_titles = qs.count() if limit <= 0 else min(qs.count(), limit)
        if limit > 0:
            qs = qs[:limit]

        self.stdout.write(self.style.MIGRATE_HEADING(
            f"populate_actors: titles={total_titles} top={top} dry_run={dry}"
        ))

        t0 = time.time()
        created = 0
        skipped_existing = 0
        skipped_empty = 0
        skipped_bad_cast = 0

        processed = 0

        for title in qs:
            processed += 1

            cast = title.cast or []
            if not isinstance(cast, list):
                skipped_bad_cast += 1
                continue

            cast = cast[:top] if top > 0 else cast

            seen = set()  # dedupe within this title

            for item in cast:
                if isinstance(item, str):
                    name = item.strip()
                    character = ""
                    tmdb_id = None
                    profile_path = None
                elif isinstance(item, dict):
                    name = (item.get("name") or item.get("original_name") or "").strip()
                    character = (item.get("character") or "").strip()
                    tmdb_id = item.get("id") or item.get("tmdb_id")
                    profile_path = item.get("profile_path")
                else:
                    continue

                if not name:
                    skipped_empty += 1
                    continue

                name, character = split_name_character(name, character)
                if not name:
                    skipped_empty += 1
                    continue

                name_norm = norm(name)
                if not name_norm or name_norm in seen:
                    continue
                seen.add(name_norm)

                exists = Actor.objects.filter(title_id=title.id, name_norm=name_norm).exists()
                if exists:
                    skipped_existing += 1
                    continue

                if not dry:
                    Actor.objects.create(
                        title_id=title.id,
                        name=name,
                        name_norm=name_norm,
                        character=character,
                        tmdb_id=tmdb_id,
                        profile_path=profile_path,
                    )
                created += 1

            if processed % log_every == 0 or processed == total_titles:
                elapsed = time.time() - t0
                rate = processed / elapsed if elapsed > 0 else 0
                remaining = total_titles - processed
                eta = (remaining / rate) if rate > 0 else 0

                self.stdout.write(
                    f"[{processed}/{total_titles}] "
                    f"created={created} skipped_existing={skipped_existing} "
                    f"bad_cast={skipped_bad_cast} empty={skipped_empty} "
                    f"rate={rate:.1f} titles/s ETA={eta/60:.1f}m"
                )

        elapsed = time.time() - t0
        self.stdout.write(self.style.SUCCESS(
            f"DONE populate_actors: titles={processed} created={created} "
            f"skipped_existing={skipped_existing} bad_cast={skipped_bad_cast} empty={skipped_empty} "
            f"elapsed={elapsed:.1f}s"
        ))
