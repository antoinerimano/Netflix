import pickle
import numpy as np
from django.core.management.base import BaseCommand
from django.utils import timezone
from django.db.models import Exists, OuterRef
from datetime import timedelta

from users.models import Title, Profile
from reco.models import TitleEmbedding, TitleImpression, TitleAction, RecoModelArtifact

import lightgbm as lgb


FEATURES = [
    "cosine",
    "popularity",
    "vote_average",
    "log_vote_count",
    "freshness_days",
    "lang_match",
    "age_ok",
    "is_movie",
    "is_tv",
    "position",
    "row_hash",
]

def _safe_float(x, default=0.0):
    try: return float(x)
    except Exception: return default

def _log1p(x):
    try: return np.log1p(max(0.0, float(x)))
    except Exception: return 0.0

def _cosine(a, b):
    na = np.linalg.norm(a); nb = np.linalg.norm(b)
    if na == 0 or nb == 0: return 0.0
    return float(np.dot(a, b) / (na * nb))

def _freshness_days(t: Title) -> float:
    from datetime import datetime
    def parse(s):
        if not s: return None
        try: return datetime.strptime(s, "%Y-%m-%d").date()
        except: return None
    d = parse(t.release_date) or parse(t.first_air_date)
    if not d: return 9999.0
    return float((timezone.now().date() - d).days)

def _row_hash(row_type: str) -> float:
    return float(abs(hash(row_type)) % 1000) / 1000.0

def _profile_vec(profile_id: int, emb_map: dict, limit=30):
    strong = ["outbound", "add_to_list", "like", "click"]
    weights = {"outbound": 4.0, "add_to_list": 3.0, "like": 2.0, "click": 1.0}

    acts = (TitleAction.objects
            .filter(profile_id=profile_id, action__in=strong)
            .order_by("-created_at")
            .values_list("title_id", "action")[:limit])

    vecs = []
    wsum = 0.0
    for tid, a in acts:
        v = emb_map.get(tid)
        if v is None: 
            continue
        w = weights.get(a, 1.0)
        vecs.append(v * w)
        wsum += w
    if not vecs or wsum == 0:
        return None
    return np.sum(vecs, axis=0) / wsum


class Command(BaseCommand):
    help = "Train LightGBM ranker on impressions/actions and store model in DB."

    def add_arguments(self, p):
        p.add_argument("--days", type=int, default=30)
        p.add_argument("--name", type=str, default="lgbm_ranker_v1")
        p.add_argument("--model-name", type=str, default="all-MiniLM-L6-v2")
        p.add_argument("--max-rows", type=int, default=400000)

    def handle(self, *args, **o):
        days = o["days"]
        name = o["name"]
        model_name = o["model_name"]
        max_rows = o["max_rows"]

        since = timezone.now() - timedelta(days=days)

        # impressions dataset (limit for speed)
        imps = (TitleImpression.objects
                .filter(created_at__gte=since)
                .order_by("-created_at")
                .values("profile_id", "title_id", "row_type", "position", "session_id")[:max_rows])

        imps = list(imps)
        if not imps:
            self.stdout.write("No impressions found.")
            return

        title_ids = list({i["title_id"] for i in imps})
        prof_ids = list({i["profile_id"] for i in imps})

        # load titles + embeddings
        titles = {t.id: t for t in Title.objects.filter(id__in=title_ids)}
        emb_qs = TitleEmbedding.objects.filter(title_id__in=title_ids, model_name=model_name)
        emb_map = {e.title_id: np.asarray(e.vector, dtype=np.float32) for e in emb_qs if e.vector}

        # build profile vectors (cheap-ish)
        prof_vecs = {}
        for pid in prof_ids:
            v = _profile_vec(pid, emb_map)
            prof_vecs[pid] = v

        # label: outbound exists for same profile/title/session within 24h
        # (simple et robuste pour commencer)
        # we'll pre-index actions
        act_qs = (TitleAction.objects
                  .filter(created_at__gte=since, action="outbound")
                  .values_list("profile_id", "title_id", "session_id"))
        outbound_set = set(act_qs)

        X = []
        y = []

        for r in imps:
            pid = r["profile_id"]
            tid = r["title_id"]

            t = titles.get(tid)
            if not t:
                continue

            pvec = prof_vecs.get(pid)
            tvec = emb_map.get(tid)

            cosine = _cosine(pvec, tvec) if (pvec is not None and tvec is not None) else 0.0
            lang_match = 1.0  # si tu veux: compare Profile.language_preference vs Title.original_language
            # tu peux charger Profile si tu veux, mais on garde lightweight v1

            feats = [
                cosine,
                _safe_float(t.popularity, 0.0),
                _safe_float(t.vote_average, 0.0),
                float(_log1p(t.vote_count or 0)),
                _freshness_days(t),
                lang_match,
                1.0,  # age_ok
                1.0 if t.type == "movie" else 0.0,
                1.0 if t.type == "tv" else 0.0,
                float(r["position"] or 0),
                _row_hash(r["row_type"] or ""),
            ]

            label = 1 if (pid, tid, r["session_id"]) in outbound_set else 0
            X.append(feats)
            y.append(label)

        X = np.asarray(X, dtype=np.float32)
        y = np.asarray(y, dtype=np.int32)

        if len(np.unique(y)) < 2:
            self.stdout.write("Not enough positive/negative labels yet (need outbound events).")
            return

        schema = {FEATURES[i]: i for i in range(len(FEATURES))}

        model = lgb.LGBMClassifier(
            n_estimators=600,
            learning_rate=0.05,
            num_leaves=63,
            subsample=0.8,
            colsample_bytree=0.8,
            reg_lambda=1.0,
            random_state=42
        )
        model.fit(X, y)

        blob = pickle.dumps(model)
        RecoModelArtifact.objects.update_or_create(
            name=name,
            defaults={
                "model_blob": blob,
                "feature_schema": schema,
                "notes": f"trained on {len(y)} impressions, days={days}"
            }
        )
        self.stdout.write(self.style.SUCCESS(f"Trained+Saved {name} ({len(y)} rows)."))
