import math
import pickle
from datetime import datetime, timedelta
from collections import Counter

import time
import logging
import numpy as np

from django.db.models import Count
from django.utils import timezone
from django.shortcuts import get_object_or_404
from django.core.cache import cache
from django.core.exceptions import FieldError

from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated

from users.models import (
    Title, Profile, TVShowExtras,
    Actor, TitleKeyword, TitleCompany, TitleCountry, TitleNetwork
)
from users.serializers import TitleHomeSerializer

from .models import (
    RecoHomeSnapshot, TitleEmbedding, TitleSimilar,
    TitleImpression, TitleAction,
    EditorialCollection, RecoModelArtifact
)
from .serializers import ImpressionInSerializer, ActionInSerializer


logger = logging.getLogger(__name__)

RANKER_CACHE_TTL = 600  # 10 min

MODEL_NAME = "all-MiniLM-L6-v2"
CANDS_PER_SOURCE = 900

# Cache TTLs
HOME_CACHE_TTL = 300          # payload final par profil (5 min)
GLOBAL_CANDS_TTL = 900        # candidats globaux (15 min)
TREND_IDS_TTL = 120           # trending ids (2 min)

# --- NEW: heavy global candidates TTL (cuts 20s+ plan_rows on cache miss)
HEAVY_CANDS_TTL = 6 * 3600    # 6h

# --- NEW: time budget for plan_rows (hard cap)
PLAN_ROWS_BUDGET_MS = 2500
MAX_PLANNED_ROWS = 14

# --- NEW: per-title serializer cache
TITLE_HOME_CACHE_VERSION = "v1"
TITLE_HOME_CACHE_TTL = 24 * 3600
TITLE_HOME_CACHE_PREFIX = f"reco:titlehome:{TITLE_HOME_CACHE_VERSION}:"

GENRE_ROWS_MAX = 2          # <= allège: 1 ou 2
GENRE_CANDS_LIMIT = 250     # <= allège: 200-300 (au lieu de 700)
GENRE_TOP_TTL = 30 * 60     # 30 min cache des top genres par profil
GENRE_IDS_TTL = 6 * 3600    # 6h cache ids par genre (comme heavy)

IMPRESSION_EXCLUDE_DAYS = 7
IMPRESSION_EXCLUDE_LIMIT = 4000


RANK_FIELDS = [
    "id", "type", "release_date", "first_air_date",
    "vote_average", "vote_count", "popularity", "original_language",
]

DISPLAY_ONLY_FIELDS = [
    "id", "type",
    "title",
    "landscape_image",
    "release_year",
    "rating",
    "description",
    "trailer_clip_url",
]


def _ms(dt_seconds):
    return dt_seconds * 1000.0


def _log_step(tag, t0, level="info", **kv):
    t1 = time.perf_counter()
    dt = t1 - t0
    extra = " ".join(f"{k}={v}" for k, v in kv.items()) if kv else ""
    msg = f"[reco-home] {tag} took={_ms(dt):.1f}ms"
    if extra:
        msg += " " + extra
    getattr(logger, level, logger.info)(msg)
    return t1


# ============================================================
# BASIC HELPERS
# ============================================================

def _primary_genre(genre_csv):
    return (genre_csv or "").split(",")[0].strip().lower()


def _parse_date(s):
    if not s:
        return None
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except Exception:
        return None


def _freshness_days(title):
    d = _parse_date(getattr(title, "release_date", "")) or _parse_date(getattr(title, "first_air_date", ""))
    if not d:
        return 9999
    return (timezone.now().date() - d).days


def _norm(s):
    return str(s or "").strip().lower()


# ============================================================
# INDEX FIELD INTROSPECTION (defensive)
# ============================================================

def _model_field(model_cls, candidates):
    try:
        fields = {f.name for f in model_cls._meta.get_fields()}
    except Exception:
        fields = set()
    for name in candidates:
        if name in fields:
            return name
    return None


def _values_for_seed_titles(model_cls, seed_title_ids, field_candidates, limit=2000):
    field = _model_field(model_cls, field_candidates)
    if not field or not seed_title_ids:
        return []
    return list(
        model_cls.objects
        .filter(title_id__in=list(seed_title_ids))  # FK column exists as title_id
        .values_list(field, flat=True)
        .exclude(**{f"{field}__isnull": True})
        .exclude(**{field: ""})[:limit]
    )


def _ids_from_index(model_cls, field_candidates, value, limit=CANDS_PER_SOURCE):
    field = _model_field(model_cls, field_candidates)
    if not field:
        return []
    v = _norm(value)
    if not v:
        return []
    try:
        return list(
            model_cls.objects
            .filter(**{field: v})
            .values_list("title_id", flat=True)
            .distinct()[:limit]
        )
    except (FieldError, Exception):
        return []


def _ids_from_table(qs, limit=CANDS_PER_SOURCE):
    return list(qs.values_list("title_id", flat=True).distinct()[:limit])


# ============================================================
# RANKER / EMBEDDINGS
# ============================================================

def _get_latest_ranker(name="lgbm_ranker_v1"):
    ck = f"reco:ranker:{name}"
    cached = cache.get(ck)
    if cached:
        return cached  # (model, schema)

    art = (
        RecoModelArtifact.objects
        .filter(name=name)
        .order_by("-trained_at")
        .only("model_blob", "feature_schema")
        .first()
    )
    if not art:
        cache.set(ck, (None, None), RANKER_CACHE_TTL)
        return None, None

    try:
        model = pickle.loads(art.model_blob)
    except Exception:
        cache.set(ck, (None, None), RANKER_CACHE_TTL)
        return None, None

    schema = art.feature_schema or {}
    cache.set(ck, (model, schema), RANKER_CACHE_TTL)
    return model, schema


def _cosine(a, b):
    if a is None or b is None:
        return 0.0
    na, nb = np.linalg.norm(a), np.linalg.norm(b)
    if na == 0 or nb == 0:
        return 0.0
    return float(np.dot(a, b) / (na * nb))


def _build_profile_vector(profile_id, limit=80):
    ids = list(
        TitleAction.objects
        .filter(profile_id=profile_id)
        .order_by("-created_at")
        .values_list("title_id", flat=True)[:limit]
    )
    if not ids:
        return None

    embs = (
        TitleEmbedding.objects
        .filter(title_id__in=ids, model_name=MODEL_NAME)
        .values_list("title_id", "dim", "vector_blob")
    )
    by_id = {}
    for tid, dim, blob in embs:
        if blob:
            by_id[tid] = np.frombuffer(blob, dtype=np.float32, count=int(dim) if dim else -1)

    vecs = [by_id.get(tid) for tid in ids if by_id.get(tid) is not None]
    if not vecs:
        return None
    return np.mean(np.stack(vecs).astype(np.float32, copy=False), axis=0)


def _bulk_fill_embeddings(emb_cache: dict, title_ids: list[int], model_name=MODEL_NAME):
    if not title_ids:
        return

    rows = (
        TitleEmbedding.objects
        .filter(model_name=model_name, title_id__in=title_ids)
        .values_list("title_id", "dim", "vector_blob")
    )

    for tid, dim, blob in rows:
        if blob:
            emb_cache[tid] = np.frombuffer(blob, dtype=np.float32, count=int(dim) if dim else -1)
        else:
            emb_cache[tid] = None


# ============================================================
# GLOBAL CANDIDATES CACHING
# ============================================================

def _cached_ids(key, builder_fn, ttl=GLOBAL_CANDS_TTL):
    ck = f"reco:global:{key}"
    ids = cache.get(ck)
    if ids:
        return ids
    ids = list(builder_fn())
    cache.set(ck, ids, ttl)
    return ids


def _cached_trending_ids(hours=72):
    ck = f"reco:trend:{hours}h"
    ids = cache.get(ck)
    if ids:
        return ids
    since = timezone.now() - timedelta(hours=hours)
    ids = list(
        TitleAction.objects
        .filter(action="outbound", created_at__gte=since)
        .values("title_id")
        .annotate(c=Count("id"))
        .order_by("-c")
        .values_list("title_id", flat=True)[:1200]
    )
    cache.set(ck, ids, TREND_IDS_TTL)
    return ids


# ============================================================
# SERIALIZER CACHE (per title)
# ============================================================

def _title_cache_key(tid: int) -> str:
    return f"{TITLE_HOME_CACHE_PREFIX}{int(tid)}"


# ============================================================
# RANK + PICK
# ============================================================

def _rank_and_pick_ids(profile, prof_vec, rank_model, row_type, cand_ids, k,
                      exclude_ids, emb_cache, title_by_id, logger=None):
    if not cand_ids:
        return [], set()

    _t0 = time.perf_counter()

    uniq_ids = []
    seen_local = set()
    for tid in cand_ids:
        if tid in exclude_ids or tid in seen_local:
            continue
        if tid not in title_by_id:
            continue
        seen_local.add(tid)
        uniq_ids.append(tid)

    if len(uniq_ids) < 4:
        return [], set()

    _t1 = time.perf_counter()
    _bulk_fill_embeddings(emb_cache, uniq_ids)
    _t2 = time.perf_counter()

    lang = getattr(profile, "language_preference", "") or ""
    row_hash = float(hash(row_type) % 997)

    X = []
    for pos, tid in enumerate(uniq_ids):
        t = title_by_id[tid]

        vec = emb_cache.get(tid)
        cosine = _cosine(prof_vec, vec) if prof_vec is not None else 0.0
        pop = float(getattr(t, "popularity", 0.0) or 0.0)
        va = float(getattr(t, "vote_average", 0.0) or 0.0)
        vc = float(getattr(t, "vote_count", 0.0) or 0.0)
        log_vc = math.log1p(vc)
        fresh = _freshness_days(t)
        lang_match = 1.0 if (lang and getattr(t, "original_language", "") == lang) else 0.0
        is_movie = 1.0 if str(getattr(t, "type", "")).lower() == "movie" else 0.0
        is_tv = 1.0 if str(getattr(t, "type", "")).lower() == "tv" else 0.0

        X.append([cosine, pop, va, log_vc, float(fresh), lang_match, is_movie, is_tv, float(pos), row_hash])

    _t3 = time.perf_counter()

    scores = None
    if rank_model is not None:
        try:
            scores = rank_model.predict(np.array(X, dtype=np.float32))
        except Exception:
            scores = None

    _t4 = time.perf_counter()

    if scores is None:
        scores = []
        for feat in X:
            cosine, pop, va, log_vc, fresh, lang_match, is_movie, is_tv, pos, rh = feat
            s = (0.55 * cosine) + (0.25 * (va / 10.0)) + (0.20 * (pop / 100.0))
            s += 0.05 * lang_match
            s -= 0.00002 * fresh
            scores.append(s)

    ranked = sorted(zip(uniq_ids, scores), key=lambda x: x[1], reverse=True)
    picked_ids = [tid for tid, _ in ranked[:k]]
    picked_set = set(picked_ids)

    _t5 = time.perf_counter()
    if logger:
        logger.info(
            f"[reco-home] rank_row row_type={row_type} cand={len(cand_ids)} uniq={len(uniq_ids)} "
            f"emb_fill={_ms(_t2-_t1):.1f}ms feat={_ms(_t3-_t2):.1f}ms score={_ms(_t4-_t3):.1f}ms "
            f"sort_pick={_ms(_t5-_t4):.1f}ms total={_ms(_t5-_t0):.1f}ms picked={len(picked_ids)}"
        )

    return picked_ids, picked_set


# views.py

def build_home_payload_exact(profile, user_id=None, do_logs=True):
    """
    EXACT copy of RecoHomeView.get() compute path, but:
    - no request/Response
    - returns payload {"rows": rows}
    - user_id is optional for logs
    """
    start_t = time.perf_counter()
    t0 = start_t

    if do_logs:
        logger.info(f"[reco-home] start profile_id={profile.id} user_id={user_id}")

    rank_model, _schema = _get_latest_ranker()
    t0 = _log_step("load_ranker", t0) if do_logs else t0

    prof_vec = _build_profile_vector(profile.id)
    t0 = _log_step("build_profile_vector", t0, has_vec=bool(prof_vec is not None)) if do_logs else t0

    # 1) recent actions
    recent_action_ids = list(
        TitleAction.objects
        .filter(profile_id=profile.id)
        .order_by("-created_at")
        .values_list("title_id", flat=True)[:200]
    )
    recent_action_ids = [tid for tid in recent_action_ids if tid]
    t0 = _log_step("recent_actions", t0, n=len(recent_action_ids)) if do_logs else t0

    # 2) seen ids (actions + impressions recentes)
    seen_ids = set(
        TitleAction.objects
        .filter(profile_id=profile.id)
        .values_list("title_id", flat=True)[:4000]
    )
    action_seen_count = len(seen_ids)
    imp_since = timezone.now() - timedelta(days=IMPRESSION_EXCLUDE_DAYS)
    impression_ids = list(
        TitleImpression.objects
        .filter(profile_id=profile.id, created_at__gte=imp_since)
        .order_by("-created_at")
        .values_list("title_id", flat=True)[:IMPRESSION_EXCLUDE_LIMIT]
    )
    seen_ids.update([tid for tid in impression_ids if tid])
    t0 = _log_step(
        "seen_ids",
        t0,
        actions=action_seen_count,
        impressions=len(impression_ids),
        total=len(seen_ids),
    ) if do_logs else t0

    rows = []
    exclude = set(seen_ids)

    planned_rows = []  # (row_type, title, cand_ids, k)

    _tplan = time.perf_counter()

    def _plan_mark(name, **kv):
        nonlocal _tplan
        if do_logs:
            _tplan = _log_step(f"plan_rows:{name}", _tplan, **kv)

    # ---- cold start (identique)
    if not recent_action_ids:
        popular_ids = _cached_ids(
            "popular",
            lambda: Title.objects.order_by("-popularity", "-vote_average").values_list("id", flat=True)[:1200]
        )
        planned_rows.append(("popular", "Popular right now", list(popular_ids), 30))

        top_ids = _cached_ids(
            "top_rated",
            lambda: Title.objects.order_by("-vote_average", "-vote_count").values_list("id", flat=True)[:1200]
        )
        planned_rows.append(("top_rated", "Top rated", list(top_ids), 30))

        new_movies_ids = _cached_ids(
            "new_movies",
            lambda: (
                Title.objects.filter(type="movie")
                .exclude(release_date="")
                .order_by("-release_date")
                .values_list("id", flat=True)[:1200]
            )
        )
        planned_rows.append(("new_movies", "New movies", list(new_movies_ids), 30))

        tv_hits_ids = _cached_ids(
            "tv_hits",
            lambda: (
                Title.objects.filter(type="tv")
                .order_by("-popularity", "-vote_average")
                .values_list("id", flat=True)[:1200]
            )
        )
        planned_rows.append(("tv_hits", "TV hits", list(tv_hits_ids), 30))

        lang = getattr(profile, "language_preference", "") or ""
        if lang:
            in_lang_ids = _cached_ids(
                f"in_lang:{lang}",
                lambda: (
                    Title.objects.filter(original_language=lang)
                    .order_by("-popularity", "-vote_average")
                    .values_list("id", flat=True)[:1200]
                )
            )
            planned_rows.append(("in_lang", f"In {lang.upper()}", list(in_lang_ids), 30))

    _plan_mark("cold_start", planned=len(planned_rows))

    # ---- normal reco (identique)
    if recent_action_ids:
        seed_ids = recent_action_ids[:6]
        sim_ids = list(
            TitleSimilar.objects
            .filter(title_id__in=seed_ids, model_name=MODEL_NAME)
            .order_by("-score")
            .values_list("similar_id", flat=True)[:800]
        )
        planned_rows.append(("for_you", "For you", sim_ids, 30))
        _plan_mark("for_you_similars", seeds=len(seed_ids), sim=len(sim_ids), planned=len(planned_rows))

        seed2 = []
        seen_seed = set()
        for tid in recent_action_ids:
            if tid in seen_seed:
                continue
            seen_seed.add(tid)
            seed2.append(tid)
            if len(seed2) >= 2:
                break

        seed_title_map = {}
        if seed2:
            for t in Title.objects.filter(id__in=seed2).only("id", "title", "original_title"):
                seed_title_map[t.id] = (t.title or t.original_title or "this")

        for tid in seed2:
            seed_title = seed_title_map.get(tid, "this")
            sim_ids = list(
                TitleSimilar.objects
                .filter(title_id=tid, model_name=MODEL_NAME)
                .order_by("-score")
                .values_list("similar_id", flat=True)[:700]
            )
            planned_rows.append((f"because:{tid}", f"Because you watched {seed_title}", sim_ids, 30))

        _plan_mark("because_rows", n_seeds=len(seed2), planned=len(planned_rows))

        recent_titles_for_features = list(
            Title.objects.filter(id__in=recent_action_ids[:80]).only("id", "genre")
        )
        genres = Counter()
        for t in recent_titles_for_features:
            g = _primary_genre(getattr(t, "genre", "") or "")
            if g:
                genres[g] += 1

        genre_field = _model_field(Title, ["primary_genre_norm"])
        for g, _ in genres.most_common(2):
            ids = _cached_ids(
                f"genre:{g}",
                lambda gg=g: (
                    Title.objects.filter(**({genre_field: gg} if genre_field else {"genre__icontains": gg}))
                    .order_by("-popularity", "-vote_average")
                    .values_list("id", flat=True)[:1200]
                )
            )
            planned_rows.append((f"genre:{g}", f"More {g.title()}", list(ids), 30))

        _plan_mark("genres", top=len(genres), planned=len(planned_rows))

        seed_title_ids = recent_action_ids[:80]

        comp_vals = _values_for_seed_titles(
            TitleCompany, seed_title_ids,
            ["company_norm", "name_norm", "company", "name"],
            limit=4000,
        )
        if comp_vals:
            comp, _ = Counter(comp_vals).most_common(1)[0]
            comp_ids = _ids_from_index(TitleCompany, ["company_norm", "name_norm", "company", "name"], comp)
            planned_rows.append((f"studio:{comp}", f"From {str(comp).title()}", comp_ids, 30))

        net_vals = _values_for_seed_titles(
            TitleNetwork, seed_title_ids,
            ["network_norm", "name_norm", "network", "name"],
            limit=4000,
        )
        if net_vals:
            net, _ = Counter(net_vals).most_common(1)[0]
            net_ids = _ids_from_index(TitleNetwork, ["network_norm", "name_norm", "network", "name"], net)
            planned_rows.append((f"network:{net}", f"On {str(net).title()}", net_ids, 30))

        country_vals = _values_for_seed_titles(
            TitleCountry, seed_title_ids,
            ["country_norm", "name_norm", "country", "name"],
            limit=4000,
        )
        if country_vals:
            ctry, _ = Counter(country_vals).most_common(1)[0]
            ctry_ids = _ids_from_index(TitleCountry, ["country_norm", "name_norm", "country", "name"], ctry)
            planned_rows.append((f"country:{ctry}", f"Made in {str(ctry).upper()}", ctry_ids, 30))

        _plan_mark("studio_network_country", planned=len(planned_rows))

        recent_titles_for_features = list(
            Title.objects.filter(id__in=recent_action_ids[:120]).only("id", "cast", "keywords")
        )

        actors = Counter()
        for t in recent_titles_for_features:
            for name in (t.cast or [])[:5]:
                actors[str(name).lower()] += 1
        for actor, _ in actors.most_common(2):
            ids = _ids_from_table(Actor.objects.filter(name_norm=actor))
            planned_rows.append((f"actor:{actor}", f"Starring {actor.title()}", ids, 30))

        keywords = Counter()
        for t in recent_titles_for_features:
            for k in (t.keywords or [])[:5]:
                keywords[str(k).lower()] += 1
        for kw, _ in keywords.most_common(2):
            ids = _ids_from_table(TitleKeyword.objects.filter(keyword_norm=kw))
            planned_rows.append((f"kw:{kw}", f"Based on “{kw}”", ids, 30))

        _plan_mark("actors_keywords", planned=len(planned_rows), actors=len(actors), keywords=len(keywords))

    hidden_ids = _cached_ids(
        "hidden_gems",
        lambda: (
            Title.objects
            .filter(vote_average__gte=7.2, vote_count__gte=250)
            .order_by("popularity", "-vote_average")
            .values_list("id", flat=True)[:1400]
        )
    )
    planned_rows.append(("hidden_gems", "Hidden gems", list(hidden_ids), 30))
    _plan_mark("hidden_gems", n=len(hidden_ids), planned=len(planned_rows))

    fresh_movies_ids = _cached_ids(
        "fresh_movies",
        lambda: (
            Title.objects
            .filter(type="movie", release_date__isnull=False)
            .exclude(release_date="")
            .order_by("-release_date")
            .values_list("id", flat=True)[:900]
        )
    )
    fresh_tv_ids = _cached_ids(
        "fresh_tv",
        lambda: (
            Title.objects
            .filter(type="tv", first_air_date__isnull=False)
            .exclude(first_air_date="")
            .order_by("-first_air_date")
            .values_list("id", flat=True)[:900]
        )
    )
    planned_rows.append(("fresh_for_you", "New for you", list(fresh_movies_ids) + list(fresh_tv_ids), 30))
    _plan_mark("fresh_for_you", n=len(fresh_movies_ids) + len(fresh_tv_ids), planned=len(planned_rows))

    trend_ids = _cached_trending_ids(hours=72)
    lang = getattr(profile, "language_preference", "") or ""
    if lang:
        lang_trend_ids = list(
            Title.objects.filter(id__in=list(trend_ids), original_language=lang)
            .order_by("-popularity", "-vote_average")
            .values_list("id", flat=True)[:1200]
        )
        planned_rows.append(("lang_trending", f"Trending in {lang.upper()}", lang_trend_ids, 30))
        _plan_mark("lang_trending", n=len(lang_trend_ids), planned=len(planned_rows))

    planned_rows.append(("trending", "Trending", list(trend_ids), 30))
    _plan_mark("trending", n=len(trend_ids), planned=len(planned_rows))

    t0 = _log_step("plan_rows", t0, planned=len(planned_rows)) if do_logs else t0

    # collect candidates (identique)
    all_cand_ids = []
    for _, __, ids, ___ in planned_rows:
        if ids:
            all_cand_ids.extend(ids)

    all_cand_ids = list(dict.fromkeys(all_cand_ids))
    t0 = _log_step("collect_candidates", t0, unique=len(all_cand_ids)) if do_logs else t0

    title_by_id = {}
    if all_cand_ids:
        qs = Title.objects.filter(id__in=all_cand_ids).only(*RANK_FIELDS)
        title_by_id = {t.id: t for t in qs}
    t0 = _log_step("fetch_titles", t0, fetched=len(title_by_id)) if do_logs else t0

    rows_plan = []
    picked_total = []
    emb_cache = {}

    for row_type, row_title, cand_ids, k in planned_rows:
        _row_t0 = time.perf_counter()

        picked_ids_list, picked_set = _rank_and_pick_ids(
            profile=profile,
            prof_vec=prof_vec,
            rank_model=rank_model,
            row_type=row_type,
            cand_ids=cand_ids,
            k=k,
            exclude_ids=exclude,
            emb_cache=emb_cache,
            title_by_id=title_by_id,
            logger=logger if do_logs else None,
        )

        if do_logs:
            _row_dt = time.perf_counter() - _row_t0
            logger.info(
                f"[reco-home] build_row row_type={row_type} cand={len(cand_ids) if cand_ids else 0} "
                f"picked={len(picked_set)} took={_ms(_row_dt):.1f}ms"
            )

        if picked_ids_list:
            rows_plan.append((row_type, row_title, picked_ids_list))
            picked_total.extend(picked_ids_list)
            exclude |= picked_set

    picked_total = list(dict.fromkeys(picked_total))
    display_by_id = {}
    if picked_total:
        dqs = Title.objects.filter(id__in=picked_total).only(*DISPLAY_ONLY_FIELDS)
        display_by_id = {t.id: t for t in dqs}

    rows = []
    for row_type, row_title, ids in rows_plan:
        objs = [display_by_id[i] for i in ids if i in display_by_id]
        rows.append({
            "row_type": row_type,
            "title": row_title,
            "items": TitleHomeSerializer(objs, many=True).data,
        })

    payload = {"rows": rows}
    t0 = _log_step("finalize_payload", t0, rows=len(rows)) if do_logs else t0

    if do_logs:
        logger.info(f"[reco-home] done profile_id={profile.id} total_ms={_ms(time.perf_counter() - start_t):.1f} rows={len(rows)}")

    return payload



def build_seed_home_payload(profile):
    rows_plan = []

    # 1) Popular
    popular_ids = _cached_ids(
        "popular_seed",
        lambda: Title.objects.order_by("-popularity", "-vote_average")
            .values_list("id", flat=True)[:1200]
    )
    rows_plan.append(("popular", "Popular right now", list(popular_ids)[:30]))

    # 2) Top rated
    top_ids = _cached_ids(
        "top_seed",
        lambda: Title.objects.order_by("-vote_average", "-vote_count")
            .values_list("id", flat=True)[:1200]
    )
    rows_plan.append(("top_rated", "Top rated", list(top_ids)[:30]))

    # 3) Trending
    trend_ids = list(_cached_trending_ids(hours=72))[:1200]
    rows_plan.append(("trending", "Trending", trend_ids[:30]))

    # 4) Language row (si dispo)
    lang = getattr(profile, "language_preference", "") or ""
    if lang:
        in_lang_ids = _cached_ids(
            f"in_lang_seed:{lang}",
            lambda: Title.objects.filter(original_language=lang)
                .order_by("-popularity", "-vote_average")
                .values_list("id", flat=True)[:1200]
        )
        rows_plan.insert(1, ("in_lang", f"In {lang.upper()}", list(in_lang_ids)[:30]))

    # Fetch display fields en 1 query
    picked = []
    for _, __, ids in rows_plan:
        picked.extend(ids)
    picked = list(dict.fromkeys(picked))

    display_by_id = {}
    if picked:
        qs = Title.objects.filter(id__in=picked).only(*DISPLAY_ONLY_FIELDS)
        display_by_id = {t.id: t for t in qs}

    rows = []
    for row_type, title, ids in rows_plan:
        objs = [display_by_id[i] for i in ids if i in display_by_id]
        rows.append({
            "row_type": row_type,
            "title": title,
            "items": TitleHomeSerializer(objs, many=True).data,
        })

    return {"rows": rows}

def upsert_seed_snapshot(profile, hours=6):
    payload = build_seed_home_payload(profile)
    now = timezone.now()
    RecoHomeSnapshot.objects.update_or_create(
        profile_id=profile.id,
        defaults={
            "algo_version": "home_v1_seed",
            "payload": payload,
            "expires_at": now + timedelta(hours=hours),
            "last_error": "",
        }
    )
    return payload


# ============================================================
# RECO: HOME
# ============================================================

# dans reco/views.py (RecoHomeView.get)
class RecoHomeView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        profile_id = request.query_params.get("profileId")
        profile = get_object_or_404(Profile, id=profile_id, user=request.user)

        # 1) Snapshot principal (cron)
        snap = (
            RecoHomeSnapshot.objects
            .filter(profile_id=profile.id, algo_version="home_v1")
            .only("payload", "built_at", "expires_at")
            .order_by("-built_at")
            .first()
        )
        if snap and snap.payload and snap.payload.get("rows") is not None:
            payload = snap.payload
            payload.setdefault("mode", "snapshot")
            return Response(payload)

        # 2) Snapshot seed (créé au moment de la création du profile)
        seed = (
            RecoHomeSnapshot.objects
            .filter(profile_id=profile.id, algo_version="home_v1_seed")
            .only("payload", "built_at")
            .order_by("-built_at")
            .first()
        )
        if seed and seed.payload and seed.payload.get("rows") is not None:
            payload = seed.payload
            payload.setdefault("mode", "seed_snapshot")
            return Response(payload)

        # 3) ultime fallback (ne devrait plus arriver)
        return Response({"mode": "no_snapshot_yet", "rows": []})


# ============================================================
# EVENTS
# ============================================================

class LogImpressionView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = ImpressionInSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        items = serializer.validated_data["items"]

        to_create = [
            TitleImpression(
                profile_id=item["profile_id"],
                title_id=item["title_id"],
                session_id=item["session_id"],
                row_type=item.get("row_type", ""),
                position=item.get("position", 0),
                device=item.get("device", ""),
                country=item.get("country", ""),
            )
            for item in items
        ]
        TitleImpression.objects.bulk_create(to_create, ignore_conflicts=True)
        return Response({"ok": True, "count": len(to_create)})


class LogActionView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = ActionInSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        data = serializer.validated_data
        TitleAction.objects.create(
            profile_id=data["profile_id"],
            title_id=data["title_id"],
            action=data["action"],
            session_id=data["session_id"],
            provider=data.get("provider", ""),
        )
        return Response({"ok": True})
