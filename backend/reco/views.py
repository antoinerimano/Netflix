import math
import pickle
from datetime import datetime, timedelta
from collections import Counter

import time
import logging
import numpy as np

from django.db.models import Count, Q
from django.utils import timezone
from django.shortcuts import get_object_or_404
from django.core.cache import cache
from django.core.exceptions import FieldError

from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated

from users.i18n import current_language, to_app_language
from users.localize import title_names
from users.models import (
    Title, Profile, TVShowExtras, Episode, Provider,
    Actor, TitleKeyword, TitleCompany, TitleCountry, TitleNetwork
)
from users.serializers import TitleHomeSerializer
from users.maturity import allowed_titles_q, profile_max_level

from .models import (
    RecoHomeSnapshot, TitleEmbedding, TitleSimilar,
    TitleImpression, TitleAction,
    EditorialCollection, RecoModelArtifact, WatchProgress, MyListItem, TitleRating, PlaybackOutcome,
    ShowFollow, Notification,
)
from .taste import has_taste_signal
from .history import WATCH_SIGNALS, record_watch
from .serializers import ImpressionInSerializer, ActionInSerializer, WatchProgressInSerializer


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
CLICK_EXCLUDE_DAYS = 14  # opened but not played: can come back after this

# "Top rated" needs enough votes, otherwise it fills with 10/10 titles rated by 5 people
TOP_RATED_MIN_VOTES = 1000

# actions that say "I like this", with weights (keep in sync with train_ranker._profile_vec).
# outbound = pressed Play here, watched = seen elsewhere (imported history), click = opened the detail page.
PROFILE_ACTION_WEIGHTS = {"outbound": 4.0, "watched": 3.0, "add_to_list": 3.0, "like": 2.0, "click": 1.0}

# Dislike: titles most similar to a disliked one are pushed down by this much in every row
DISLIKE_NEIGHBORS = 30
DISLIKE_PENALTY = 0.25


def _interest_actions(profile_id):
    """Positive actions of a profile. Removing from My List is logged as add_to_list
    with provider "remove|...", so it must not count as interest. Likes come from
    TitleRating (current thumb), not from the action log: an undone like must not count."""
    return (
        TitleAction.objects
        .filter(profile_id=profile_id, action__in=[a for a in PROFILE_ACTION_WEIGHTS if a != "like"])
        .exclude(action="add_to_list", provider__startswith="remove")
    )


def _interest_events(profile_id, limit):
    """[(title_id, kind)] newest first: positive actions + current likes, minus disliked titles."""
    ratings = list(
        TitleRating.objects.filter(profile_id=profile_id)
        .order_by("-updated_at")
        .values_list("title_id", "value", "updated_at")[:limit]
    )
    disliked = {tid for tid, value, _ in ratings if value == TitleRating.DISLIKE}
    events = [(when, tid, "like") for tid, value, when in ratings if value == TitleRating.LIKE]
    events += [
        (when, tid, action)
        for tid, action, when in _interest_actions(profile_id)
        .order_by("-created_at")
        .values_list("title_id", "action", "created_at")[:limit]
        if tid not in disliked
    ]
    events.sort(key=lambda e: e[0], reverse=True)
    return [(tid, kind) for _, tid, kind in events[:limit]]


def _rejected_ids(profile_id):
    """Titles the profile said no to: current dislikes + "not interested" (permanent)."""
    disliked = TitleRating.objects.filter(profile_id=profile_id, value=TitleRating.DISLIKE).values_list("title_id", flat=True)
    not_interested = TitleAction.objects.filter(profile_id=profile_id, action="not_interested").values_list("title_id", flat=True)
    return set(disliked) | set(not_interested)


def _disliked_neighbors(profile_id, per_title=DISLIKE_NEIGHBORS):
    """Titles most similar to the ones the profile disliked: pushed down in every row."""
    disliked = list(
        TitleRating.objects.filter(profile_id=profile_id, value=TitleRating.DISLIKE).values_list("title_id", flat=True)[:50]
    )
    if not disliked:
        return set()
    neighbors = set()
    for tid in disliked:
        neighbors.update(
            TitleSimilar.objects.filter(title_id=tid, model_name=MODEL_NAME)
            .order_by("-score").values_list("similar_id", flat=True)[:per_title]
        )
    return neighbors

# "New episodes" row: global (same for everyone), added to every home payload at request time
NEW_EPISODES_TTL = 600       # 10 min
NEW_EPISODES_DAYS = 10
NEW_EPISODES_SIZE = 30

# "Continue watching" row: live per profile, first row of the home page
CONTINUE_WATCHING_DAYS = 60
CONTINUE_WATCHING_SIZE = 20
WATCH_FINISHED_RATIO = 0.92  # past this share of the duration, a movie / episode counts as watched
IMPRESSION_EXCLUDE_LIMIT = 4000


RANK_FIELDS = [
    "id", "type", "release_date", "first_air_date",
    "vote_average", "vote_count", "popularity", "original_language",
]

DISPLAY_ONLY_FIELDS = [
    "id", "type",
    "title",
    "landscape_image",
    "poster",
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
    # memoized on the object for the day: title objects are shared across profiles (_rank_titles)
    today = timezone.now().date()
    cached = getattr(title, "_freshness", None)
    if cached and cached[0] == today:
        return cached[1]
    d = _parse_date(getattr(title, "release_date", "")) or _parse_date(getattr(title, "first_air_date", ""))
    days = (today - d).days if d else 9999
    title._freshness = (today, days)
    return days


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


def _build_profile_vector(profile_id, limit=30):
    # same recipe as train_ranker._profile_vec (the ranker's cosine feature must mean the same thing)
    acts = _interest_events(profile_id, limit)
    if not acts:
        return None

    embs = (
        TitleEmbedding.objects
        .filter(title_id__in={tid for tid, _ in acts}, model_name=MODEL_NAME)
        .values_list("title_id", "dim", "vector_blob")
    )
    by_id = {}
    for tid, dim, blob in embs:
        if blob:
            by_id[tid] = np.frombuffer(blob, dtype=np.float32, count=int(dim) if dim else -1)

    vecs, wsum = [], 0.0
    for tid, action in acts:
        v = by_id.get(tid)
        if v is None:
            continue
        w = PROFILE_ACTION_WEIGHTS[action]
        vecs.append(v.astype(np.float32) * w)
        wsum += w
    if not vecs:
        return None
    return np.sum(vecs, axis=0) / wsum


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
        .annotate(c=Count("profile", distinct=True))  # people, not plays (a binge = 1)
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

# Shared by every profile built in this process (build_home_snapshots builds them one after
# the other): global candidate lists (genres, hidden gems, new...) are the same for everyone.
EMB_CACHE_MAX = 60000          # title embeddings kept in memory (~1.5 KB each)
RANK_TITLES_TTL = 3600         # title fields used for ranking (popularity changes daily)
_emb_cache = {}                # title id -> float32 vector, or None (no embedding)
_rank_titles = {"at": 0.0, "by_id": {}}


def _embeddings(ids):
    missing = [tid for tid in ids if tid not in _emb_cache]
    if missing:
        if len(_emb_cache) + len(missing) > EMB_CACHE_MAX:
            _emb_cache.clear()
            missing = list(ids)
        for tid in missing:
            _emb_cache[tid] = None
        _bulk_fill_embeddings(_emb_cache, missing)
    return _emb_cache


def _rank_titles_for(profile, ids):
    """{id: Title (RANK_FIELDS)} the profile may see. Cached across profiles without an age limit."""
    if profile_max_level(profile) is not None:
        qs = Title.objects.filter(id__in=ids).filter(allowed_titles_q(profile)).only(*RANK_FIELDS)
        return {t.id: t for t in qs}
    now = time.monotonic()
    if now - _rank_titles["at"] > RANK_TITLES_TTL:
        _rank_titles.update(at=now, by_id={})
    by_id = _rank_titles["by_id"]
    missing = [tid for tid in ids if tid not in by_id]
    for i in range(0, len(missing), 5000):
        chunk = missing[i:i + 5000]
        for t in Title.objects.filter(id__in=chunk).only(*RANK_FIELDS):
            by_id[t.id] = t
        for tid in chunk:
            by_id.setdefault(tid, None)  # gone from the DB
    return {tid: by_id[tid] for tid in ids if by_id.get(tid) is not None}


def _score_candidates(profile, prof_vec, rank_model, ids, title_by_id, penalized_ids=frozenset()):
    """
    {title id: score} for every candidate, once per profile: the score doesn't depend on the row
    (position / row_hash are constants), so rows only pick their best unused titles from it.
    """
    ids = [tid for tid in ids if tid in title_by_id and _freshness_days(title_by_id[tid]) >= 0]
    if not ids:
        return {}
    embs = _embeddings(ids)

    # cosine(profile, title) for all candidates in one matrix product
    cos = np.zeros(len(ids), dtype=np.float32)
    if prof_vec is not None:
        pv = np.asarray(prof_vec, dtype=np.float32)
        pn = float(np.linalg.norm(pv))
        rows = [k for k, tid in enumerate(ids) if embs.get(tid) is not None and len(embs[tid]) == len(pv)]
        if rows and pn > 0:
            m = np.stack([embs[ids[k]] for k in rows]).astype(np.float32, copy=False)
            norms = np.linalg.norm(m, axis=1)
            with np.errstate(divide="ignore", invalid="ignore"):
                c = (m @ pv) / (norms * pn)
            cos[rows] = np.where(np.isfinite(c), c, 0.0)

    lang = getattr(profile, "language_preference", "") or ""
    X = np.zeros((len(ids), 11), dtype=np.float32)
    for k, tid in enumerate(ids):
        t = title_by_id[tid]
        kind = str(getattr(t, "type", "")).lower()
        # same columns, same order as train_ranker.FEATURES. position = 0: score every candidate
        # as if shown first (training position is the on-screen slot, unknown before ranking).
        X[k] = [
            cos[k],
            float(t.popularity or 0.0),
            float(t.vote_average or 0.0),
            math.log1p(float(t.vote_count or 0.0)),
            float(_freshness_days(t)),
            1.0 if (lang and t.original_language == lang) else 0.0,
            1.0,  # age_ok
            1.0 if kind == "movie" else 0.0,
            1.0 if kind == "tv" else 0.0,
            0.0,  # position
            0.0,  # row_hash
        ]

    scores = None
    if rank_model is not None:
        try:
            # probability of a click-through, not the 0/1 class
            scores = rank_model.predict_proba(X)[:, 1]
        except Exception:
            logger.exception("[reco-home] ranker failed, using heuristic scores")
    if scores is None:
        scores = (0.55 * X[:, 0]) + (0.25 * (X[:, 2] / 10.0)) + (0.20 * (X[:, 1] / 100.0))
        scores += 0.05 * X[:, 5]
        scores -= 0.00002 * X[:, 4]

    # titles similar to something the profile disliked go down every row
    return {
        tid: float(score) - (DISLIKE_PENALTY if tid in penalized_ids else 0.0)
        for tid, score in zip(ids, scores)
    }


def _pick_ids(cand_ids, k, exclude_ids, scores):
    """Best k scored candidates of a row that aren't excluded (seen / already in a row above)."""
    if not cand_ids:
        return [], set()
    uniq = list(dict.fromkeys(tid for tid in cand_ids if tid in scores and tid not in exclude_ids))
    if len(uniq) < 4:
        return [], set()
    picked = sorted(uniq, key=scores.__getitem__, reverse=True)[:k]  # stable: ties keep row order
    return picked, set(picked)


# views.py

# ============================================================
# "WHY THIS?" (reason shown on a card)
# ============================================================

WHY_FIELDS = ["vote_average", "vote_count", "release_date", "first_air_date", "original_language"]
LANG_NAMES = {
    "en": "English", "fr": "French", "es": "Spanish", "de": "German", "it": "Italian", "pt": "Portuguese",
    "ja": "Japanese", "ko": "Korean", "zh": "Chinese", "hi": "Hindi", "ru": "Russian", "tr": "Turkish",
    "ar": "Arabic", "nl": "Dutch", "sv": "Swedish", "da": "Danish", "no": "Norwegian", "pl": "Polish",
}


def _lang_name(code):
    return LANG_NAMES.get(code, (code or "").upper())


def _short_count(n):
    n = int(n or 0)
    if n >= 1000:
        return f"{n / 1000:.1f}k".replace(".0k", "k") if n < 10000 else f"{round(n / 1000)}k"
    return str(n)


def _explain_key(row_type, t, similar_to=None):
    """
    The card's reason as data, for the app to word in its language (frontend catalog:
    home.why.<key>): {"key": "similarTo", "title_id": 12, "title": "Heat", "liked": true},
    {"key": "ratedBy", "rating": 8.1, "votes": 21000}, {"key": "newRelease", "date": "2026-10"}...
    None = no reason (the row title already says it).
    """
    kind = row_type.split(":")[0]
    if kind == "for_you" and similar_to:
        name, liked, seed_id = (*similar_to, None)[:3]
        return {"key": "similarTo", "title": name, "title_id": seed_id, "liked": bool(liked)}
    if kind == "top_rated" and t.vote_average and t.vote_count:
        return {"key": "ratedBy", "rating": round(float(t.vote_average), 1), "votes": int(t.vote_count)}
    if kind == "hidden_gems" and t.vote_average:
        return {"key": "hiddenGem", "rating": round(float(t.vote_average), 1)}
    if kind == "tv_hits":
        return {"key": "popularNow"}
    if kind in ("new_movies", "fresh_for_you"):
        d = _parse_date(t.release_date) or _parse_date(t.first_air_date)
        return {"key": "newRelease", "date": d.strftime("%Y-%m")} if d else None
    return None


def _explain(row_type, t, similar_to=None):
    """Card reason in English, only where the row title doesn't already say it ("" = none)."""
    kind = row_type.split(":")[0]
    if kind == "for_you" and similar_to:
        name, liked = similar_to[:2]
        return f"Similar to {name}" + (", which you liked" if liked else "")
    if kind == "top_rated" and t.vote_average and t.vote_count:
        return f"Rated {t.vote_average:.1f}/10 by {_short_count(t.vote_count)} people"
    if kind == "hidden_gems" and t.vote_average:
        return f"Rated {t.vote_average:.1f}/10, but few people know it"
    if kind == "tv_hits":
        return "Popular right now"
    if kind in ("new_movies", "fresh_for_you"):
        d = _parse_date(t.release_date) or _parse_date(t.first_air_date)
        return f"New: out {d.strftime('%b %Y')}" if d else ""
    return ""


def _for_you_reasons(profile_id, seed_ids, picked_ids):
    """{picked title id: (name of the seed it is most similar to, seed was liked)}"""
    if not seed_ids or not picked_ids:
        return {}
    best = {}
    for sim_id, seed_id, score in (
        TitleSimilar.objects
        .filter(title_id__in=seed_ids, similar_id__in=picked_ids, model_name=MODEL_NAME)
        .values_list("similar_id", "title_id", "score")
    ):
        if sim_id not in best or score > best[sim_id][1]:
            best[sim_id] = (seed_id, score)
    names = dict(Title.objects.filter(id__in={seed for seed, _ in best.values()}).values_list("id", "title"))
    liked = set(
        TitleRating.objects.filter(profile_id=profile_id, value=TitleRating.LIKE, title_id__in=seed_ids)
        .values_list("title_id", flat=True)
    )
    return {sim: (names[seed], seed in liked, seed) for sim, (seed, _) in best.items() if seed in names}


def _row_items(row_type, objs, similar_to=None):
    """Serialized cards of a row, each with its "why" when there is one."""
    items = []
    for t, data in zip(objs, TitleHomeSerializer(objs, many=True).data):
        reason = (similar_to or {}).get(t.id)
        why = _explain(row_type, t, reason)
        why_key = _explain_key(row_type, t, reason)
        item = dict(data)
        if why:
            item["why"] = why  # English (older clients); the app words why_key itself
        if why_key:
            item["why_key"] = why_key
        items.append(item)
    return items


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

    # 1) recent positive actions + likes (seeds for "For you", genre/actor/studio rows; not dislikes)
    recent_action_ids = [tid for tid, _ in _interest_events(profile.id, 200)]
    # one entry per title, newest first (opening + playing the same show = 1 seed, not 2)
    recent_action_ids = list(dict.fromkeys(tid for tid in recent_action_ids if tid))
    t0 = _log_step("recent_actions", t0, n=len(recent_action_ids)) if do_logs else t0

    # 2) seen ids: watched / listed / rejected for good, only opened recently, shown recently.
    # Thumbs count by their current value (TitleRating), not by the log: an undone dislike can come back.
    click_since = timezone.now() - timedelta(days=CLICK_EXCLUDE_DAYS)
    seen_ids = set(
        TitleAction.objects
        .filter(profile_id=profile.id)
        .exclude(action__in=["like", "dislike"])
        .filter(~Q(action="click") | Q(created_at__gte=click_since))
        .order_by("-created_at")
        .values_list("title_id", flat=True)[:4000]
    )
    seen_ids.update(TitleRating.objects.filter(profile_id=profile.id).values_list("title_id", flat=True))
    rejected_ids = _rejected_ids(profile.id)
    seen_ids.update(rejected_ids)
    penalized_ids = _disliked_neighbors(profile.id)
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
            lambda: Title.objects.filter(vote_count__gte=TOP_RATED_MIN_VOTES)
            .order_by("-vote_average", "-vote_count").values_list("id", flat=True)[:1200]
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
            planned_rows.append(("in_lang", f"In {_lang_name(lang)}", list(in_lang_ids), 30))

    _plan_mark("cold_start", planned=len(planned_rows))

    # ---- normal reco (identique)
    seed_ids = []
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

        # "Because you watched X": only titles the profile pressed Play on (outbound) or saw
        # elsewhere (imported "watched"), not titles it just opened (click) or added to its list
        watched_ids = list(
            TitleAction.objects
            .filter(profile_id=profile.id, action__in=["outbound", "watched"])
            .order_by("-created_at")
            .values_list("title_id", flat=True)[:50]
        )
        seed2 = []
        seen_seed = set()
        for tid in watched_ids:
            if tid in seen_seed or tid in rejected_ids:  # watched it, then thumbed it down
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
        planned_rows.append(("lang_trending", f"Trending in {_lang_name(lang)}", lang_trend_ids, 30))
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

    title_by_id = _rank_titles_for(profile, all_cand_ids) if all_cand_ids else {}
    t0 = _log_step("fetch_titles", t0, fetched=len(title_by_id)) if do_logs else t0

    scores = _score_candidates(profile, prof_vec, rank_model, all_cand_ids, title_by_id, penalized_ids)
    t0 = _log_step("score_candidates", t0, scored=len(scores)) if do_logs else t0

    rows_plan = []
    picked_total = []

    for row_type, row_title, cand_ids, k in planned_rows:
        _row_t0 = time.perf_counter()

        picked_ids_list, picked_set = _pick_ids(cand_ids, k, exclude, scores)

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
        dqs = Title.objects.filter(id__in=picked_total).only(*DISPLAY_ONLY_FIELDS, *WHY_FIELDS)
        display_by_id = {t.id: t for t in dqs}

    rows = []
    for row_type, row_title, ids in rows_plan:
        objs = [display_by_id[i] for i in ids if i in display_by_id]
        similar_to = _for_you_reasons(profile.id, seed_ids, ids) if row_type == "for_you" else None
        rows.append({
            "row_type": row_type,
            "title": row_title,
            "items": _row_items(row_type, objs, similar_to),
        })

    payload = {"rows": rows}
    t0 = _log_step("finalize_payload", t0, rows=len(rows)) if do_logs else t0

    if do_logs:
        logger.info(f"[reco-home] done profile_id={profile.id} total_ms={_ms(time.perf_counter() - start_t):.1f} rows={len(rows)}")

    return payload



def _released_titles():
    """Titles that are already out (no release / first-air date in the future)."""
    today = timezone.localdate().isoformat()  # dates are stored as 'YYYY-MM-DD' strings
    return Title.objects.exclude(release_date__gt=today).exclude(first_air_date__gt=today)


def build_seed_home_payload(profile):
    rows_plan = []

    # 1) Popular
    popular_ids = _cached_ids(
        "popular_seed",
        lambda: _released_titles().order_by("-popularity", "-vote_average")
            .values_list("id", flat=True)[:1200]
    )
    rows_plan.append(("popular", "Popular right now", list(popular_ids)))

    # 2) Top rated
    top_ids = _cached_ids(
        "top_seed",
        lambda: _released_titles().filter(vote_count__gte=TOP_RATED_MIN_VOTES)
            .order_by("-vote_average", "-vote_count")
            .values_list("id", flat=True)[:1200]
    )
    rows_plan.append(("top_rated", "Top rated", list(top_ids)))

    # 3) Trending
    trend_ids = list(_cached_trending_ids(hours=72))[:1200]
    rows_plan.append(("trending", "Trending", trend_ids))

    # 4) Language row (si dispo)
    lang = getattr(profile, "language_preference", "") or ""
    if lang:
        in_lang_ids = _cached_ids(
            f"in_lang_seed:{lang}",
            lambda: _released_titles().filter(original_language=lang)
                .order_by("-popularity", "-vote_average")
                .values_list("id", flat=True)[:1200]
        )
        rows_plan.insert(1, ("in_lang", f"In {_lang_name(lang)}", list(in_lang_ids)))

    # age limit of the profile, then 30 per row
    if profile_max_level(profile) is not None:
        all_ids = {i for _, __, ids in rows_plan for i in ids}
        allowed = set(Title.objects.filter(id__in=all_ids).filter(allowed_titles_q(profile)).values_list("id", flat=True))
        rows_plan = [(rt, t, [i for i in ids if i in allowed]) for rt, t, ids in rows_plan]
    rows_plan = [(rt, t, ids[:30]) for rt, t, ids in rows_plan]

    # Fetch display fields en 1 query
    picked = []
    for _, __, ids in rows_plan:
        picked.extend(ids)
    picked = list(dict.fromkeys(picked))

    display_by_id = {}
    if picked:
        qs = Title.objects.filter(id__in=picked).only(*DISPLAY_ONLY_FIELDS, *WHY_FIELDS)
        display_by_id = {t.id: t for t in qs}

    rows = []
    for row_type, title, ids in rows_plan:
        objs = [display_by_id[i] for i in ids if i in display_by_id]
        rows.append({
            "row_type": row_type,
            "title": title,
            "items": _row_items(row_type, objs),
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
def _new_episodes_row():
    """Shows with an episode aired in the last NEW_EPISODES_DAYS days, most popular first."""
    ck = "reco:new_episodes:v1"
    row = cache.get(ck)
    if row is not None:
        return row

    today = timezone.localdate()
    latest = {}  # tv_id -> (air_date, season, episode) of its newest aired episode
    eps = (
        Episode.objects
        .filter(air_date__lte=today, air_date__gte=today - timedelta(days=NEW_EPISODES_DAYS))
        .order_by("-air_date", "-season__season_number", "-episode_number")
        .values_list("season__tv_id", "season__season_number", "episode_number", "air_date")
    )
    for tv_id, season, episode, air_date in eps:
        latest.setdefault(tv_id, (air_date, season, episode))

    titles = (
        Title.objects.filter(id__in=list(latest))
        .only(*DISPLAY_ONLY_FIELDS, "popularity")
        .order_by("-popularity")[:NEW_EPISODES_SIZE]
    )
    items = []
    for item in TitleHomeSerializer(titles, many=True).data:
        air_date, season, episode = latest[item["id"]]
        items.append({
            **item,
            "latest_episode": {"season": season, "episode": episode, "air_date": air_date.isoformat()},
        })

    row = {"row_type": "new_episodes", "title": "New episodes", "items": items}
    cache.set(ck, row, NEW_EPISODES_TTL)
    return row


def _continue_watching_row(profile):
    """Last movies / episodes this profile opened on the watch page, newest first."""
    since = timezone.now() - timedelta(days=CONTINUE_WATCHING_DAYS)
    progress = list(
        WatchProgress.objects
        .filter(profile=profile, hidden=False, updated_at__gte=since)
        .order_by("-updated_at")
        .values_list("title_id", "season_number", "episode_number", "position_seconds", "duration_seconds")[:CONTINUE_WATCHING_SIZE]
    )
    titles = {t.id: t for t in Title.objects.filter(id__in=[p[0] for p in progress]).only(*DISPLAY_ONLY_FIELDS)}
    items = []
    for title_id, season, episode, position, duration in progress:
        t = titles.get(title_id)
        if t is None:
            continue
        item = dict(TitleHomeSerializer(t).data)
        resume = {"season": season, "episode": episode} if season else {}
        if position:
            resume["position"] = position
            if duration:  # Row draws its progress bar from these two
                item["progress"] = position
                item["duration"] = f"{max(1, round(duration / 60))} min"
        items.append({**item, "resume": resume})
    return {"row_type": "continue_watching", "title": "Continue watching", "items": items}


def _apply_age_limit(payload, profile):
    """Drop titles above the profile's age limit from every row (snapshots may predate the limit)."""
    if profile_max_level(profile) is None:
        return payload
    ids = {item["id"] for row in payload.get("rows") or [] for item in row.get("items") or []}
    allowed = set(Title.objects.filter(id__in=ids).filter(allowed_titles_q(profile)).values_list("id", flat=True))
    rows = []
    for row in payload.get("rows") or []:
        items = [item for item in row.get("items") or [] if item["id"] in allowed]
        if items:
            rows.append({**row, "items": items})
    return {**payload, "rows": rows}


def _drop_rejected(payload, profile):
    """Remove disliked / "not interested" titles: the snapshot may predate the click."""
    rejected = _rejected_ids(profile.id)
    if not rejected:
        return payload
    rows = []
    for row in payload.get("rows") or []:
        items = [item for item in row.get("items") or [] if item["id"] not in rejected]
        if items:
            rows.append({**row, "items": items})
    return {**payload, "rows": rows}


def _row_params(row_type, profile):
    """
    What the app needs to word a row's title in its language (frontend catalog:
    home.rows.<kind>): "genre:comedy" -> {"genre": "comedy"}, "in_lang" -> {"language": "fr"}...
    The English title stays in "title" (fallback) and "analytics_title" (same in every language).
    """
    kind, _, arg = row_type.partition(":")
    if kind in ("in_lang", "lang_trending"):
        return {"language": to_app_language(profile.language_preference, "") or profile.language_preference or ""}
    if kind == "because" and arg.isdigit():
        return {"title_id": int(arg)}
    if kind == "genre":
        return {"genre": arg}
    if kind in ("studio", "network", "actor"):
        return {"name": str(arg).title()}
    if kind == "country":
        return {"country": str(arg).upper()}
    if kind == "kw":
        return {"keyword": arg}
    return {}


def _describe_rows(payload, profile):
    """Every row gets its params, cards their reason; titles named in them in the request's language."""
    lang = current_language()
    rows = []
    named = set()
    for row in payload.get("rows") or []:
        params = _row_params(row.get("row_type") or "", profile)
        if "title_id" in params:
            named.add(params["title_id"])
        for item in row.get("items") or []:
            why_key = item.get("why_key")
            if why_key and why_key.get("title_id"):
                named.add(why_key["title_id"])
        rows.append({**row, "params": params, "analytics_title": row.get("analytics_title") or row.get("title") or ""})
    if named:
        english = dict(Title.objects.filter(id__in=named).values_list("id", "title"))
        names = {**english, **title_names(named, lang)}
        for row in rows:
            tid = row["params"].get("title_id")
            if tid:
                row["params"]["title"] = names.get(tid, "")
            for item in row.get("items") or []:
                why_key = item.get("why_key")
                if why_key and why_key.get("title_id") in names:
                    item["why_key"] = {**why_key, "title": names[why_key["title_id"]]}
    return {**payload, "rows": rows}


def _with_live_rows(payload, profile):
    """Rows that must be fresh on every visit (the rest comes from the cron snapshot)."""
    # nothing liked / listed / played yet: the app offers the "pick what you like" page
    payload = {**payload, "needs_taste": not has_taste_signal(profile.id)}
    rows = list(payload.get("rows") or [])
    new_eps = _new_episodes_row()
    if new_eps["items"]:
        rows.insert(min(1, len(rows)), new_eps)  # right after the first personal row
    cont = _continue_watching_row(profile)
    if cont["items"]:
        rows.insert(0, cont)
    return _describe_rows(_apply_age_limit(_drop_rejected({**payload, "rows": rows}, profile), profile), profile)


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
            payload = _with_live_rows(snap.payload, profile)
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
            payload = _with_live_rows(seed.payload, profile)
            payload.setdefault("mode", "seed_snapshot")
            return Response(payload)

        # 3) ultime fallback (ne devrait plus arriver)
        return Response(_with_live_rows({"mode": "no_snapshot_yet", "rows": []}, profile))


# ============================================================
# EVENTS
# ============================================================

class LogImpressionView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = ImpressionInSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        items = serializer.validated_data["items"]

        # only log for the caller's own profiles (no writing into someone else's history)
        own_profile_ids = set(
            Profile.objects
            .filter(user=request.user, id__in={item["profile_id"] for item in items})
            .filter(history_paused=False)  # paused watch history: nothing about it is saved
            .values_list("id", flat=True)
        )
        items = [item for item in items if item["profile_id"] in own_profile_ids]

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
        profile = get_object_or_404(Profile, id=data["profile_id"], user=request.user)
        if profile.history_paused and data["action"] in WATCH_SIGNALS:
            return Response({"ok": True, "paused": True})  # what it opens / plays isn't saved
        TitleAction.objects.create(
            profile_id=data["profile_id"],
            title_id=data["title_id"],
            action=data["action"],
            session_id=data["session_id"],
            provider=data.get("provider", ""),
        )
        return Response({"ok": True})


# ============================================================
# CONTINUE WATCHING
# ============================================================

def _next_aired_episode(title, season, episode):
    """(season, episode) after this one that has aired, or None."""
    return (
        Episode.objects
        .filter(season__tv=title)
        .filter(Q(air_date__isnull=True) | Q(air_date__lte=timezone.localdate()))
        .filter(Q(season__season_number=season, episode_number__gt=episode) | Q(season__season_number__gt=season))
        .order_by("season__season_number", "episode_number")
        .values_list("season__season_number", "episode_number")
        .first()
    )


class WatchProgressView(APIView):
    """
    POST   /api/watch-progress/  {profile_id, title_id, season?, episode?}  watch page opened
    DELETE /api/watch-progress/?profileId=..&titleId=..                     remove from the row
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = WatchProgressInSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        profile = get_object_or_404(Profile, id=data["profile_id"], user=request.user)
        title = get_object_or_404(Title.objects.only("id", "type"), id=data["title_id"])
        if profile.history_paused:
            return Response({"ok": True, "finished": False, "paused": True})  # nothing saved
        is_tv = title.type == "tv"
        season = data.get("season") if is_tv else None
        episode = data.get("episode") if is_tv else None
        position, duration = data.get("position"), data.get("duration")
        record_watch(profile, title, season, episode)  # watch history: today's entry

        wp, _ = WatchProgress.objects.get_or_create(
            profile=profile, title=title, defaults={"season_number": season, "episode_number": episode}
        )
        if (wp.season_number, wp.episode_number) != (season, episode):
            # another episode: its own position
            wp.season_number, wp.episode_number = season, episode
            wp.position_seconds = wp.duration_seconds = None
        if position is not None:
            wp.position_seconds = position
        if duration:
            wp.duration_seconds = duration
        wp.hidden = False

        finished = data.get("finished") or bool(
            wp.position_seconds and wp.duration_seconds
            and wp.position_seconds >= wp.duration_seconds * WATCH_FINISHED_RATIO
        )
        if finished:
            nxt = _next_aired_episode(title, season, episode) if is_tv and season is not None else None
            if nxt:
                wp.season_number, wp.episode_number = nxt  # the row now offers the next episode
            else:
                wp.hidden = True  # movie done / show caught up: leaves "Continue watching"
            wp.position_seconds = wp.duration_seconds = None
        wp.save()
        return Response({"ok": True, "finished": finished})

    def delete(self, request):
        profile = get_object_or_404(Profile, id=request.query_params.get("profileId"), user=request.user)
        WatchProgress.objects.filter(profile=profile, title_id=request.query_params.get("titleId")).update(hidden=True)
        return Response({"ok": True})


# ============================================================
# MY LIST
# ============================================================

MY_LIST_FIELDS = ("id", "type", "title", "poster", "landscape_image", "description",
                  "release_date", "first_air_date", "rating", "genre")
MY_LIST_IMPORT_MAX = 500


class MyListView(APIView):
    """GET /api/my-list/?profileId=..  -> the profile's list, newest first (age limit applied)"""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        profile = get_object_or_404(Profile, id=request.query_params.get("profileId"), user=request.user)
        items = (
            MyListItem.objects
            .filter(profile=profile)
            .filter(allowed_titles_q(profile, prefix="title__"))
            .select_related("title")
            .order_by("-added_at")
        )
        return Response([{f: getattr(item.title, f) for f in MY_LIST_FIELDS} for item in items])


class MyListItemView(APIView):
    """PUT / DELETE /api/my-list/<title_id>/?profileId=..  add or remove one title"""
    permission_classes = [IsAuthenticated]

    def put(self, request, title_id):
        profile = get_object_or_404(Profile, id=request.query_params.get("profileId"), user=request.user)
        title = get_object_or_404(Title.objects.only("id"), id=title_id)
        MyListItem.objects.get_or_create(profile=profile, title=title)
        return Response({"in_list": True})

    def delete(self, request, title_id):
        profile = get_object_or_404(Profile, id=request.query_params.get("profileId"), user=request.user)
        MyListItem.objects.filter(profile=profile, title_id=title_id).delete()
        return Response({"in_list": False})


class MyListImportView(APIView):
    """
    POST /api/my-list/import/ {profile_id, title_ids}
    One-time move of the list the browser used to keep (localStorage). Oldest first,
    so they keep their order; titles already in the list are left as they are.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        profile = get_object_or_404(Profile, id=request.data.get("profile_id"), user=request.user)
        raw_ids = request.data.get("title_ids") or []
        ids = [int(i) for i in raw_ids if str(i).isdigit()][:MY_LIST_IMPORT_MAX]
        existing = set(Title.objects.filter(id__in=ids).values_list("id", flat=True))
        added = 0
        for tid in dict.fromkeys(ids):  # keeps order, drops duplicates
            if tid in existing:
                _, created = MyListItem.objects.get_or_create(profile=profile, title_id=tid)
                added += created
        return Response({"imported": added})


# ============================================================
# LIKE / DISLIKE
# ============================================================

RATING_VALUES = {"like": TitleRating.LIKE, "dislike": TitleRating.DISLIKE}
RATING_NAMES = {v: k for k, v in RATING_VALUES.items()}


class TitleRatingView(APIView):
    """
    GET /api/ratings/<title_id>/?profileId=..                 -> {"rating": "like" | "dislike" | null}
    PUT /api/ratings/<title_id>/?profileId=..  {"rating": .., "session_id": ..}   set (null clears it)
    """
    permission_classes = [IsAuthenticated]

    def get(self, request, title_id):
        profile = get_object_or_404(Profile, id=request.query_params.get("profileId"), user=request.user)
        value = TitleRating.objects.filter(profile=profile, title_id=title_id).values_list("value", flat=True).first()
        return Response({"rating": RATING_NAMES.get(value)})

    def put(self, request, title_id):
        profile = get_object_or_404(Profile, id=request.query_params.get("profileId"), user=request.user)
        title = get_object_or_404(Title.objects.only("id"), id=title_id)
        rating = request.data.get("rating")
        if rating is not None and rating not in RATING_VALUES:
            return Response({"detail": "rating must be like, dislike or null"}, status=400)

        if rating is None:
            TitleRating.objects.filter(profile=profile, title=title).delete()
        else:
            TitleRating.objects.update_or_create(profile=profile, title=title, defaults={"value": RATING_VALUES[rating]})
            # history for analytics / ranker training (recommendations read the current value above)
            TitleAction.objects.create(
                profile=profile, title=title, action=rating,
                session_id=str(request.data.get("session_id") or "")[:64], provider="thumb",
            )
        return Response({"rating": rating})


# ============================================================
# SMART PLAYBACK
# ============================================================

PLAYBACK_STATS_DAYS = 7
PLAYBACK_MIN_SAMPLES = 20   # below this, a provider has no success rate (keeps the admin priority)
PLAYBACK_STATS_TTL = 600    # 10 min


def provider_success_rates():
    """{provider_key: share of plays that worked} over the last days, all profiles together."""
    ck = "reco:provider_success:v1"
    rates = cache.get(ck)
    if rates is not None:
        return rates
    since = timezone.now() - timedelta(days=PLAYBACK_STATS_DAYS)
    rows = (
        PlaybackOutcome.objects.filter(created_at__gte=since)
        .values("provider_key")
        .annotate(n=Count("id"), ok=Count("id", filter=Q(worked=True)))
    )
    rates = {r["provider_key"]: r["ok"] / r["n"] for r in rows if r["n"] >= PLAYBACK_MIN_SAMPLES}
    cache.set(ck, rates, PLAYBACK_STATS_TTL)
    return rates


def _last_working_source(outcomes):
    """outcomes newest first [(provider_key, worked)]: the newest source that worked and
    hasn't failed since."""
    failed_since = set()
    for key, worked in outcomes:
        if not worked:
            failed_since.add(key)
        elif key not in failed_since:
            return key
    return None


class PlaybackView(APIView):
    """
    POST /api/playback/  {profile_id, title_id, provider, worked}        did this source play?
    GET  /api/playback/?profileId=..&titleId=..
         -> {"title": key | null, "profile": key | null}  source to open first: the one that last
            worked for this title, else the one that last worked for this profile
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        profile = get_object_or_404(Profile, id=request.data.get("profile_id"), user=request.user)
        title = get_object_or_404(Title.objects.only("id"), id=request.data.get("title_id"))
        key = str(request.data.get("provider") or "")
        if not Provider.objects.filter(key=key).exists():
            return Response({"detail": "unknown provider"}, status=400)
        if profile.history_paused:
            return Response({"ok": True, "paused": True})
        PlaybackOutcome.objects.create(profile=profile, title=title, provider_key=key, worked=bool(request.data.get("worked")))
        return Response({"ok": True})

    def get(self, request):
        profile = get_object_or_404(Profile, id=request.query_params.get("profileId"), user=request.user)
        enabled = set(Provider.objects.filter(enabled=True).values_list("key", flat=True))
        base = PlaybackOutcome.objects.filter(profile=profile, provider_key__in=enabled).order_by("-created_at")
        title_id = request.query_params.get("titleId")
        for_title = _last_working_source(base.filter(title_id=title_id).values_list("provider_key", "worked")[:50]) if title_id else None
        for_profile = _last_working_source(base.values_list("provider_key", "worked")[:200])
        return Response({"title": for_title, "profile": for_profile})


# ============================================================
# NEW EPISODE ALERTS
# ============================================================

class ShowFollowView(APIView):
    """GET / PUT / DELETE /api/follows/<title_id>/?profileId=..  "Notify me" on a show"""
    permission_classes = [IsAuthenticated]

    def _profile(self, request):
        return get_object_or_404(Profile, id=request.query_params.get("profileId"), user=request.user)

    def get(self, request, title_id):
        following = ShowFollow.objects.filter(profile=self._profile(request), title_id=title_id).exists()
        return Response({"following": following})

    def put(self, request, title_id):
        profile = self._profile(request)
        title = get_object_or_404(Title.objects.only("id"), id=title_id, type="tv")
        ShowFollow.objects.get_or_create(profile=profile, title=title)
        return Response({"following": True})

    def delete(self, request, title_id):
        ShowFollow.objects.filter(profile=self._profile(request), title_id=title_id).delete()
        return Response({"following": False})


class NotificationListView(APIView):
    """
    GET  /api/notifications/?profileId=..       -> {"unread": n, "items": [...]} newest first
    POST /api/notifications/read/?profileId=..  mark them all read
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        profile = get_object_or_404(Profile, id=request.query_params.get("profileId"), user=request.user)
        qs = Notification.objects.filter(profile=profile).filter(allowed_titles_q(profile, prefix="title__"))
        items = [
            {
                "id": n.id,
                "title_id": n.title_id,
                "show": n.title.title,
                "image": n.title.landscape_image or n.title.poster,
                "season": n.season_number,
                "episode": n.episode_number,
                "air_date": n.air_date.isoformat(),
                "read": n.read_at is not None,
            }
            for n in qs.select_related("title").order_by("-created_at")[:30]
        ]
        return Response({"unread": qs.filter(read_at__isnull=True).count(), "items": items})

    def post(self, request):
        profile = get_object_or_404(Profile, id=request.query_params.get("profileId"), user=request.user)
        Notification.objects.filter(profile=profile, read_at__isnull=True).update(read_at=timezone.now())
        return Response({"unread": 0})
