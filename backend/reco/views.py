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
    TitleEmbedding, TitleSimilar,
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


def _serialize_titles_cached(objs):
    if not objs:
        return []

    ids = [int(o.id) for o in objs]
    key_by_id = {tid: _title_cache_key(tid) for tid in ids}

    cached_map = cache.get_many([key_by_id[tid] for tid in ids]) or {}
    out = []
    missing = []
    missing_keys = []

    for o in objs:
        ck = key_by_id[int(o.id)]
        hit = cached_map.get(ck)
        if hit is not None:
            out.append(hit)
        else:
            out.append(None)
            missing.append(o)
            missing_keys.append(ck)

    if missing:
        serialized = TitleHomeSerializer(missing, many=True).data
        to_set = {}
        j = 0
        for i in range(len(out)):
            if out[i] is None:
                item = serialized[j]
                out[i] = item
                to_set[missing_keys[j]] = item
                j += 1
        if to_set:
            cache.set_many(to_set, timeout=TITLE_HOME_CACHE_TTL)

    return out


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


# ============================================================
# RECO: HOME
# ============================================================

class RecoHomeView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        profile_id = request.query_params.get("profileId")
        profile = get_object_or_404(Profile, id=profile_id, user=request.user)

        start_t = time.perf_counter()
        t0 = start_t
        logger.info(f"[reco-home] start profile_id={profile.id} user_id={request.user.id}")

        cache_key = f"reco:home:p{profile.id}"
        cached = cache.get(cache_key)
        if cached:
            logger.info(f"[reco-home] cache_hit profile_id={profile.id} rows={len(cached.get('rows', []))}")
            return Response(cached)

        rank_model, _schema = _get_latest_ranker()
        t0 = _log_step("load_ranker", t0)

        prof_vec = _build_profile_vector(profile.id)
        t0 = _log_step("build_profile_vector", t0, has_vec=bool(prof_vec is not None))

        recent_action_ids = list(
            TitleAction.objects
            .filter(profile_id=profile.id)
            .order_by("-created_at")
            .values_list("title_id", flat=True)[:200]
        )
        recent_action_ids = [tid for tid in recent_action_ids if tid]
        t0 = _log_step("recent_actions", t0, n=len(recent_action_ids))

        seen_ids = set(
            TitleAction.objects
            .filter(profile_id=profile.id)
            .values_list("title_id", flat=True)[:4000]
        )
        t0 = _log_step("seen_ids", t0, n=len(seen_ids))
        exclude = set(seen_ids)

        planned_rows = []  # (row_type, title, cand_ids, k)

        _tplan = time.perf_counter()
        deadline = _tplan + (PLAN_ROWS_BUDGET_MS / 1000.0)

        def _plan_mark(name, **kv):
            nonlocal _tplan
            _tplan = _log_step(f"plan_rows:{name}", _tplan, **kv)

        def _can_continue():
            return (time.perf_counter() < deadline) and (len(planned_rows) < MAX_PLANNED_ROWS)

        # ---- cold start
        if not recent_action_ids and _can_continue():
            popular_ids = _cached_ids(
                "popular",
                lambda: Title.objects.order_by("-popularity", "-vote_average").values_list("id", flat=True)[:900],
                ttl=HEAVY_CANDS_TTL,
            )
            planned_rows.append(("popular", "Popular right now", list(popular_ids), 30))

            top_ids = _cached_ids(
                "top_rated",
                lambda: Title.objects.order_by("-vote_average", "-vote_count").values_list("id", flat=True)[:900],
                ttl=HEAVY_CANDS_TTL,
            )
            planned_rows.append(("top_rated", "Top rated", list(top_ids), 30))

            new_movies_ids = _cached_ids(
                "new_movies",
                lambda: (
                    Title.objects.filter(type="movie")
                    .exclude(release_date="")
                    .order_by("-release_date")
                    .values_list("id", flat=True)[:900]
                ),
                ttl=HEAVY_CANDS_TTL,
            )
            planned_rows.append(("new_movies", "New movies", list(new_movies_ids), 30))

            tv_hits_ids = _cached_ids(
                "tv_hits",
                lambda: (
                    Title.objects.filter(type="tv")
                    .order_by("-popularity", "-vote_average")
                    .values_list("id", flat=True)[:900]
                ),
                ttl=HEAVY_CANDS_TTL,
            )
            planned_rows.append(("tv_hits", "TV hits", list(tv_hits_ids), 30))

            lang = getattr(profile, "language_preference", "") or ""
            if lang and _can_continue():
                in_lang_ids = _cached_ids(
                    f"in_lang:{lang}",
                    lambda: (
                        Title.objects.filter(original_language=lang)
                        .order_by("-popularity", "-vote_average")
                        .values_list("id", flat=True)[:900]
                    ),
                    ttl=HEAVY_CANDS_TTL,
                )
                planned_rows.append(("in_lang", f"In {lang.upper()}", list(in_lang_ids), 30))

        _plan_mark("cold_start", planned=len(planned_rows))

        # ---- normal reco
        if recent_action_ids and _can_continue():
            seed_ids = recent_action_ids[:6]
            sim_ids = list(
                TitleSimilar.objects
                .filter(title_id__in=seed_ids, model_name=MODEL_NAME)
                .order_by("-score")
                .values_list("similar_id", flat=True)[:800]
            )
            planned_rows.append(("for_you", "For you", sim_ids, 30))
            _plan_mark("for_you_similars", seeds=len(seed_ids), sim=len(sim_ids), planned=len(planned_rows))

        if recent_action_ids and _can_continue():
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

               # ====================================================
        # GENRES (ALLÉGÉ + CACHÉ)
        # Objectif:
        # - Ne jamais refaire des grosses requêtes genres à chaque request
        # - Limiter à 1-2 rows genres
        # - Limiter cand_ids (250 au lieu de 700)
        # ====================================================
        if recent_action_ids and _can_continue():
            # 1) Cache des "top genres" par profil (très rapide)
            top_genres_ck = f"reco:home:top_genres:p{profile.id}"
            top_genres = cache.get(top_genres_ck)

            if not top_genres:
                # Ne charge que le minimum
                recent_titles = list(
                    Title.objects
                    .filter(id__in=recent_action_ids[:80])
                    .only("id", "primary_genre_norm", "genre")
                )
                genres = Counter()
                for t in recent_titles:
                    g = (getattr(t, "primary_genre_norm", "") or "").strip().lower()
                    if not g:
                        g = _primary_genre(getattr(t, "genre", "") or "")
                    if g:
                        genres[g] += 1

                # garde seulement 1-2 genres max
                top_genres = [g for g, _ in genres.most_common(GENRE_ROWS_MAX)]
                cache.set(top_genres_ck, top_genres, GENRE_TOP_TTL)

            # 2) Pour chaque genre, cache la liste d'IDs (évite DB lente)
            for g in (top_genres or [])[:GENRE_ROWS_MAX]:
                if not _can_continue():
                    break

                # IMPORTANT: si tu as d'autres dimensions (lang/pays), ajoute-les au cache key
                genre_ids_ck = f"reco:home:genre_ids:{g}"
                ids = cache.get(genre_ids_ck)

                if not ids:
                    # Query simple, index-friendly (primary_genre_norm)
                    ids = list(
                        Title.objects
                        .filter(primary_genre_norm=g)
                        .order_by("-popularity", "-vote_average")
                        .values_list("id", flat=True)[:GENRE_CANDS_LIMIT]
                    )
                    cache.set(genre_ids_ck, ids, GENRE_IDS_TTL)

                planned_rows.append((f"genre:{g}", f"More {g.title()}", list(ids), 30))

            _plan_mark("genres", top=len(top_genres or []), planned=len(planned_rows))

        # STUDIO / NETWORK / COUNTRY via mapping tables
        if recent_action_ids and _can_continue():
            seed_title_ids = recent_action_ids[:80]

            comp_vals = _values_for_seed_titles(TitleCompany, seed_title_ids, ["company_norm"], limit=4000)
            if comp_vals and _can_continue():
                comp, _ = Counter(comp_vals).most_common(1)[0]
                comp_ids = _ids_from_index(TitleCompany, ["company_norm"], comp, limit=600)
                planned_rows.append((f"studio:{comp}", f"From {str(comp).title()}", comp_ids, 30))

            net_vals = _values_for_seed_titles(TitleNetwork, seed_title_ids, ["network_norm"], limit=4000)
            if net_vals and _can_continue():
                net, _ = Counter(net_vals).most_common(1)[0]
                net_ids = _ids_from_index(TitleNetwork, ["network_norm"], net, limit=600)
                planned_rows.append((f"network:{net}", f"On {str(net).title()}", net_ids, 30))

            # IMPORTANT: TitleCountry uses country_code in your models.py
            ctry_vals = _values_for_seed_titles(TitleCountry, seed_title_ids, ["country_code"], limit=4000)
            if ctry_vals and _can_continue():
                ctry, _ = Counter(ctry_vals).most_common(1)[0]
                ctry_ids = _ids_from_index(TitleCountry, ["country_code"], ctry, limit=600)
                planned_rows.append((f"country:{ctry}", f"Made in {str(ctry).upper()}", ctry_ids, 30))

            _plan_mark("studio_network_country", planned=len(planned_rows))

        # ACTORS / KEYWORDS
        if recent_action_ids and _can_continue():
            recent_titles = list(Title.objects.filter(id__in=recent_action_ids[:120]).only("id", "cast", "keywords"))

            actors = Counter()
            for t in recent_titles:
                for name in (t.cast or [])[:5]:
                    actors[str(name).lower()] += 1
            for actor, _ in actors.most_common(2):
                ids = _ids_from_table(Actor.objects.filter(name_norm=actor), limit=600)
                planned_rows.append((f"actor:{actor}", f"Starring {actor.title()}", ids, 30))

            keywords = Counter()
            for t in recent_titles:
                for k in (t.keywords or [])[:5]:
                    keywords[str(k).lower()] += 1
            for kw, _ in keywords.most_common(2):
                ids = _ids_from_table(TitleKeyword.objects.filter(keyword_norm=kw), limit=600)
                planned_rows.append((f"kw:{kw}", f"Based on “{kw}”", ids, 30))

            _plan_mark("actors_keywords", planned=len(planned_rows), actors=len(actors), keywords=len(keywords))

        # HIDDEN GEMS (very heavy when cache miss) -> budget guarded + long TTL
        if _can_continue():
            hidden_ids = _cached_ids(
                "hidden_gems",
                lambda: (
                    Title.objects
                    .filter(vote_average__gte=7.2, vote_count__gte=250)
                    .order_by("popularity", "-vote_average")
                    .values_list("id", flat=True)[:600]
                ),
                ttl=HEAVY_CANDS_TTL,
            )
            planned_rows.append(("hidden_gems", "Hidden gems", list(hidden_ids), 30))
            _plan_mark("hidden_gems", n=len(hidden_ids), planned=len(planned_rows))

        # FRESH FOR YOU (heavy) -> budget guarded + long TTL
        if _can_continue():
            fresh_movies_ids = _cached_ids(
                "fresh_movies",
                lambda: (
                    Title.objects
                    .filter(type="movie")
                    .exclude(release_date="")
                    .order_by("-release_date")
                    .values_list("id", flat=True)[:450]
                ),
                ttl=HEAVY_CANDS_TTL,
            )
            fresh_tv_ids = _cached_ids(
                "fresh_tv",
                lambda: (
                    Title.objects
                    .filter(type="tv")
                    .exclude(first_air_date="")
                    .order_by("-first_air_date")
                    .values_list("id", flat=True)[:450]
                ),
                ttl=HEAVY_CANDS_TTL,
            )
            planned_rows.append(("fresh_for_you", "New for you", list(fresh_movies_ids) + list(fresh_tv_ids), 30))
            _plan_mark("fresh_for_you", n=len(fresh_movies_ids) + len(fresh_tv_ids), planned=len(planned_rows))

        # TRENDING
        trend_ids = _cached_trending_ids(hours=72)
        lang = getattr(profile, "language_preference", "") or ""
        if lang and _can_continue():
            lang_trend_ids = list(
                Title.objects.filter(id__in=list(trend_ids), original_language=lang)
                .order_by("-popularity", "-vote_average")
                .values_list("id", flat=True)[:700]
            )
            planned_rows.append(("lang_trending", f"Trending in {lang.upper()}", lang_trend_ids, 30))
            _plan_mark("lang_trending", n=len(lang_trend_ids), planned=len(planned_rows))

        planned_rows.append(("trending", "Trending", list(trend_ids), 30))
        _plan_mark("trending", n=len(trend_ids), planned=len(planned_rows))

        t0 = _log_step("plan_rows", t0, planned=len(planned_rows))

        # ====================================================
        # Fetch titles for ranking (light fields)
        # ====================================================
        all_cand_ids = []
        for _, __, ids, ___ in planned_rows:
            if ids:
                all_cand_ids.extend(ids)
        all_cand_ids = list(dict.fromkeys(all_cand_ids))
        t0 = _log_step("collect_candidates", t0, unique=len(all_cand_ids))

        title_by_id = {}
        if all_cand_ids:
            qs = Title.objects.filter(id__in=all_cand_ids).only(*RANK_FIELDS)
            title_by_id = {t.id: t for t in qs}
        t0 = _log_step("fetch_titles", t0, fetched=len(title_by_id))

        # ====================================================
        # Rank rows
        # ====================================================
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
                logger=logger,
            )

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
                "items": _serialize_titles_cached(objs),  # NEW: cached serializer
            })

        # payload stats
        try:
            import json
            total_items = sum(len(r.get("items", [])) for r in rows)
            empty_rows = sum(1 for r in rows if not r.get("items"))
            max_items = max((len(r.get("items", [])) for r in rows), default=0)
            approx_bytes = len(json.dumps({"rows": rows}))
            logger.info(
                "[reco-home] payload_stats rows=%s total_items=%s empty_rows=%s max_items=%s approx_bytes=%s",
                len(rows), total_items, empty_rows, max_items, approx_bytes
            )
        except Exception as e:
            logger.info("[reco-home] payload_stats_error %s", e)

        payload = {"rows": rows}
        t0 = _log_step("finalize_payload", t0, rows=len(rows))
        cache.set(cache_key, payload, HOME_CACHE_TTL)

        logger.info(f"[reco-home] done profile_id={profile.id} total_ms={_ms(time.perf_counter() - start_t):.1f} rows={len(rows)}")
        return Response(payload)


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
