# users/management/commands/rebuild_title_indexes.py
import re
import unicodedata
from datetime import timedelta
import json
import ast


from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from users.models import (
    Title,
    TVShowExtras,
    TitleActor,
    TitleKeyword,
    TitleCompany,
    TitleCountry,
    TitleNetwork,
)

# ---------- Normalization ----------
_space_re = re.compile(r"\s+")

def norm_text(s: str) -> str:
    """Lowercase, remove accents, normalize spaces."""
    if not s:
        return ""
    s = str(s).strip().lower()
    s = unicodedata.normalize("NFKD", s)
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    s = _space_re.sub(" ", s)
    return s

def to_list(value):
    """
    Safely convert JSONField-ish value to list.
    Supports:
      - list (strings or dicts)
      - dict (wrap into list)
      - JSON string '[...]' or '{...}'
      - comma-separated string fallback
    """
    if value is None:
        return []

    if isinstance(value, list):
        return value

    if isinstance(value, dict):
        return [value]

    if isinstance(value, str):
        s = value.strip()
        if not s:
            return []
        # try JSON / python literal
        if (s.startswith("[") and s.endswith("]")) or (s.startswith("{") and s.endswith("}")):
            try:
                obj = json.loads(s)
                if isinstance(obj, list):
                    return obj
                if isinstance(obj, dict):
                    return [obj]
            except Exception:
                pass
            try:
                obj = ast.literal_eval(s)
                if isinstance(obj, list):
                    return obj
                if isinstance(obj, dict):
                    return [obj]
            except Exception:
                pass

        # fallback: comma-separated
        parts = [p.strip() for p in s.split(",")]
        return [p for p in parts if p]

    return []

def extract_company_names(value):
    """
    production_companies can be:
      - ["Columbia Pictures", ...]
      - [{"id": 5, "name": "Columbia Pictures"}, ...]
      - {"id": 5, "name": "..."} (rare)
      - JSON string version of above
    Returns list[str] of company names.
    """
    out = []
    for item in to_list(value):
        if isinstance(item, str):
            name = item.strip()
            if name:
                out.append(name)
        elif isinstance(item, dict):
            name = (item.get("name") or item.get("Name") or "").strip()
            if name:
                out.append(name)
    return out


def extract_country_codes(value):
    """
    production_countries can be:
    - ["US","CA"]
    - [{"iso_3166_1":"US","name":"United States"}, ...]
    - ["United States", ...]  (worst case)
    We prefer ISO2 codes if present; otherwise skip non-ISO2.
    """
    out = []
    if value is None:
        return out

    if isinstance(value, list):
        for item in value:
            if isinstance(item, str):
                code = item.strip().upper()
                if len(code) == 2 and code.isalpha():
                    out.append(code)
            elif isinstance(item, dict):
                code = (item.get("iso_3166_1") or item.get("code") or "").strip().upper()
                if len(code) == 2 and code.isalpha():
                    out.append(code)
    elif isinstance(value, dict):
        code = (value.get("iso_3166_1") or value.get("code") or "").strip().upper()
        if len(code) == 2 and code.isalpha():
            out.append(code)

    return out


# ---------- Command ----------
class Command(BaseCommand):
    help = "Rebuild / populate Title index tables (actors/keywords/companies/countries/networks) from JSON fields."

    def add_arguments(self, parser):
        parser.add_argument("--batch", type=int, default=2000, help="Batch size (default 2000)")
        parser.add_argument("--rebuild", action="store_true", help="Delete all index rows before rebuilding")
        parser.add_argument("--since-days", type=int, default=None, help="Only process titles updated in the last N days")
        parser.add_argument("--dry-run", action="store_true", help="Do not write to DB (print counts only)")

    def handle(self, *args, **opts):
        batch = opts["batch"]
        rebuild = opts["rebuild"]
        since_days = opts["since_days"]
        dry_run = opts["dry_run"]

        if rebuild and since_days is not None:
            self.stdout.write(self.style.WARNING("Using --rebuild with --since-days: --since-days will be ignored."))

        qs = Title.objects.all().only(
            "id",
            "type",
            "cast",
            "keywords",
            "production_companies",
            "production_countries"
        )

        if since_days is not None and not rebuild:
            cutoff = timezone.now() - timedelta(days=since_days)
            qs = qs.filter(updated_at__gte=cutoff)

        total = qs.count()
        self.stdout.write(f"[INDEX] Titles to process: {total}")

        if rebuild:
            if dry_run:
                self.stdout.write(self.style.WARNING("[DRY-RUN] Would delete all index tables."))
            else:
                self.stdout.write("[INDEX] Deleting existing index rows...")
                with transaction.atomic():
                    TitleActor.objects.all().delete()
                    TitleKeyword.objects.all().delete()
                    TitleCompany.objects.all().delete()
                    TitleCountry.objects.all().delete()
                    TitleNetwork.objects.all().delete()

        created_counts = {
            "actors": 0,
            "keywords": 0,
            "companies": 0,
            "countries": 0,
            "networks": 0,
        }

        offset = 0
        while True:
            chunk = list(qs.order_by("id")[offset : offset + batch])
            if not chunk:
                break

            title_ids = [t.id for t in chunk]

            # Preload TVShowExtras network_names for tv titles
            extras_map = {}
            tv_ids = [t.id for t in chunk if getattr(t, "type", "") == "tv"]
            if tv_ids:
                extras_map = {
                    e.title_id: e for e in TVShowExtras.objects.filter(title_id__in=tv_ids).only("title_id", "network_names")
                }

            actors_rows = []
            keyword_rows = []
            company_rows = []
            country_rows = []
            network_rows = []

            for t in chunk:
                tid = t.id

                # Actors
                for a in to_list(getattr(t, "cast", None)):
                    na = norm_text(a)
                    if na:
                        actors_rows.append(TitleActor(title_id=tid, name_norm=na))

                # Keywords
                for kw in to_list(getattr(t, "keywords", None)):
                    nkw = norm_text(kw)
                    if nkw:
                        keyword_rows.append(TitleKeyword(title_id=tid, keyword_norm=nkw))

                # Companies
                for comp_name in extract_company_names(getattr(t, "production_companies", None)):
                    nc = norm_text(comp_name)
                    if nc:
                        company_rows.append(TitleCompany(title_id=tid, company_norm=nc))

                # Countries (ISO2 only)
                for cc in extract_country_codes(getattr(t, "production_countries", None)):
                    country_rows.append(TitleCountry(title_id=tid, country_code=cc))

                # Networks from TVShowExtras
                extra = extras_map.get(tid)
                if extra:
                    for n in to_list(getattr(extra, "network_names", None)):
                        nn = norm_text(n)
                        if nn:
                            network_rows.append(TitleNetwork(title_id=tid, network_norm=nn))

            if dry_run:
                created_counts["actors"] += len(actors_rows)
                created_counts["keywords"] += len(keyword_rows)
                created_counts["companies"] += len(company_rows)
                created_counts["countries"] += len(country_rows)
                created_counts["networks"] += len(network_rows)
            else:
                with transaction.atomic():
                    TitleActor.objects.bulk_create(actors_rows, ignore_conflicts=True, batch_size=5000)
                    TitleKeyword.objects.bulk_create(keyword_rows, ignore_conflicts=True, batch_size=5000)
                    TitleCompany.objects.bulk_create(company_rows, ignore_conflicts=True, batch_size=5000)
                    TitleCountry.objects.bulk_create(country_rows, ignore_conflicts=True, batch_size=5000)
                    TitleNetwork.objects.bulk_create(network_rows, ignore_conflicts=True, batch_size=5000)

                created_counts["actors"] += len(actors_rows)
                created_counts["keywords"] += len(keyword_rows)
                created_counts["companies"] += len(company_rows)
                created_counts["countries"] += len(country_rows)
                created_counts["networks"] += len(network_rows)

            offset += batch
            self.stdout.write(
                f"[OK] processed={min(offset, total)}/{total} "
                f"actors+{len(actors_rows)} kw+{len(keyword_rows)} comp+{len(company_rows)} "
                f"cty+{len(country_rows)} net+{len(network_rows)}"
            )

        self.stdout.write(self.style.SUCCESS("[DONE] Index build finished."))
        self.stdout.write(f"Totals inserted-attempted (ignore_conflicts may skip duplicates): {created_counts}")
