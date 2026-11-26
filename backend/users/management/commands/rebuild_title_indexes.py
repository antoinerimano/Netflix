# users/management/commands/rebuild_title_indexes.py
"""
manage.py rebuild_title_indexes: the search / "more like this" index tables, from each title's own
fields: TitleKeyword (keywords), TitleCompany (production_companies), TitleCountry
(production_countries, as ISO codes), TitleNetwork (TVShowExtras.network_names). users/search.py
and reco/views.py read them; nothing else writes them, so a title the syncs add or clean_db
completes isn't found by keyword until this runs.

Nightly from cron (ops/crontab): the titles that have keywords / companies / networks but no index
row yet, and the titles clean_db read on TMDB in the last --since-days (their fields may have
changed). --all: every title. Each title's rows are replaced, never the whole tables.
Then Title.section (Anime / K-drama, users/sections.py) of the titles that may be in one: the syncs'
bulk writes skip Title.save(), which works it out otherwise.
(Actors are indexed by the syncs themselves: users.Actor.)
"""
import re
import unicodedata
from datetime import timedelta
import json
import ast


from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import Exists, OuterRef, Q
from django.utils import timezone

from users.countries import country_code
from users.jobs import tracked
from users.sections import SOURCE_FIELDS, section_of
from users.models import (
    Title,
    TVShowExtras,
    TitleKeyword,
    TitleCompany,
    TitleCountry,
    TitleNetwork,
)

INDEX_TABLES = (TitleKeyword, TitleCompany, TitleCountry, TitleNetwork)

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
    """production_countries -> ISO codes: TMDB's English names ("United States of America"), its
    objects, or codes (users/countries.py). Unknown names are skipped."""
    out = []
    for item in to_list(value):
        code = country_code(item)
        if code and code not in out:
            out.append(code)
    return out


# ---------- Command ----------
def titles_to_index(since_days: int):
    """Titles with keywords / companies / countries / networks but no index row for them, or read on TMDB by
    clean_db in the last since_days days."""
    def has_rows(model):
        return Exists(model.objects.filter(title_id=OuterRef("pk")))

    networks = Exists(TVShowExtras.objects.filter(title_id=OuterRef("pk")).exclude(network_names=[]))
    missing = (
        (~Q(keywords=[]) & ~has_rows(TitleKeyword))
        | (~Q(production_companies=[]) & ~has_rows(TitleCompany))
        | (~Q(production_countries=[]) & ~has_rows(TitleCountry))
        | (Q(type="tv") & networks & ~has_rows(TitleNetwork))
    )
    if since_days > 0:
        missing |= Q(tmdb_checked_at__gte=timezone.now() - timedelta(days=since_days))
    return Title.objects.filter(missing)


def index_rows(title, extra):
    rows = []
    for kw in to_list(title.keywords):
        n = norm_text(kw)[:120]
        if n:
            rows.append(TitleKeyword(title_id=title.id, keyword_norm=n))
    for name in extract_company_names(title.production_companies):
        n = norm_text(name)[:160]
        if n:
            rows.append(TitleCompany(title_id=title.id, company_norm=n))
    for code in extract_country_codes(title.production_countries):
        rows.append(TitleCountry(title_id=title.id, country_code=code))
    if extra is not None:
        for name in to_list(extra.network_names):
            n = norm_text(name)[:160]
            if n:
                rows.append(TitleNetwork(title_id=title.id, network_norm=n))
    return rows


def section_candidates():
    """Titles that are, or may be, Anime / K-drama (users/sections.py): in a section now,
    animated, or Korean / unknown-language drama shows."""
    return Title.objects.filter(
        Q(section__gt="") | Q(genre__icontains="animation")
        | (Q(type="tv") & Q(genre__icontains="drama") & Q(original_language__in=["ko", ""]))
    )


def update_sections(dry_run=False, batch=1000):
    """Title.section again for the candidates; the number of titles whose section changed."""
    changed = 0
    last = 0
    while True:
        chunk = list(section_candidates().filter(id__gt=last).order_by("id").only("id", "section", *SOURCE_FIELDS)[:batch])
        if not chunk:
            return changed
        last = chunk[-1].id
        diff = []
        for t in chunk:
            section = section_of(t)
            if section != t.section:
                t.section = section
                diff.append(t)
        changed += len(diff)
        if diff and not dry_run:
            Title.objects.bulk_update(diff, ["section"], batch_size=500)


class Command(BaseCommand):
    help = "Fill the title index tables (keywords / companies / countries / networks) for search and recommendations."

    def add_arguments(self, parser):
        parser.add_argument("--all", action="store_true", help="Every title, not only the ones missing or just read.")
        parser.add_argument("--since-days", type=int, default=2,
                            help="Also the titles clean_db read on TMDB in the last N days (0: only missing ones).")
        parser.add_argument("--batch", type=int, default=1000)
        parser.add_argument("--dry-run", action="store_true", help="Count only, no writes.")

    @tracked("rebuild_title_indexes")  # JobRun: shown on the admin dashboard
    def handle(self, *args, **opts):
        qs = Title.objects.all() if opts["all"] else titles_to_index(opts["since_days"])
        ids = list(qs.order_by("id").values_list("id", flat=True))
        self.stdout.write(f"[index] titles to index: {len(ids)}")

        written = 0
        batch = opts["batch"]
        for start in range(0, len(ids), batch):
            chunk = list(Title.objects.filter(id__in=ids[start:start + batch]).only(
                "id", "type", "keywords", "production_companies", "production_countries"))
            extras = {e.title_id: e for e in TVShowExtras.objects.filter(
                title_id__in=[t.id for t in chunk if t.type == "tv"]).only("title_id", "network_names")}
            rows = [r for t in chunk for r in index_rows(t, extras.get(t.id))]
            written += len(rows)
            if opts["dry_run"]:
                continue
            chunk_ids = [t.id for t in chunk]
            with transaction.atomic():  # replace each title's rows: a keyword TMDB dropped goes too
                for model in INDEX_TABLES:
                    model.objects.filter(title_id__in=chunk_ids).delete()
                for model in INDEX_TABLES:
                    model.objects.bulk_create([r for r in rows if type(r) is model],
                                              ignore_conflicts=True, batch_size=5000)

        self.stdout.write(f"[index] done: {len(ids)} titles, {written} index rows"
                          + (" (dry run, nothing written)" if opts["dry_run"] else ""))
        fixed = update_sections(dry_run=opts["dry_run"], batch=opts["batch"])
        self.stdout.write(f"[index] sections (anime / K-drama) changed: {fixed}")
