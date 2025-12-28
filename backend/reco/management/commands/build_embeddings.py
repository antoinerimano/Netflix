from django.core.management.base import BaseCommand
from django.db import transaction
from users.models import Title
from reco.models import TitleEmbedding, TitleSimilar

from pathlib import Path
import os
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

import numpy as np


def _join(x):
    if not x:
        return ""
    if isinstance(x, str):
        return x
    try:
        return " ".join([str(i) for i in x])
    except Exception:
        return ""


class Command(BaseCommand):
    help = "Compute embeddings and store topK similar titles in DB."

    def add_arguments(self, p):
        p.add_argument("--type", choices=["movie", "tv", "all"], default="all")
        p.add_argument("--topk", type=int, default=80)
        p.add_argument("--model-name", type=str, default="all-MiniLM-L6-v2")

    def handle(self, *args, **o):
        t = o["type"]
        topk = o["topk"]
        model_name = o["model_name"]

        qs = Title.objects.all()
        if t in ("movie", "tv"):
            qs = qs.filter(type=t)

        titles = list(qs.only(
            "id","title","original_title","description","genre","keywords",
            "cast","director","original_language","production_countries"
        ))

        texts, ids = [], []
        for ti in titles:
            ids.append(ti.id)
            texts.append(" | ".join([
                ti.title or "",
                ti.original_title or "",
                (ti.description or "")[:1500],
                ti.genre or "",
                _join(ti.keywords),
                _join(ti.cast),
                ti.director or "",
                ti.original_language or "",
                _join(ti.production_countries),
            ]).strip())

        from sentence_transformers import SentenceTransformer
        model = SentenceTransformer(model_name)
        emb = model.encode(texts, batch_size=64, show_progress_bar=True, normalize_embeddings=True)
        emb = np.asarray(emb, dtype=np.float32)
        dim = int(emb.shape[1])

        with transaction.atomic():
            for i, tid in enumerate(ids):
                TitleEmbedding.objects.update_or_create(
                    title_id=tid,
                    defaults={"dim": dim, "vector": emb[i].tolist(), "model_name": model_name}
                )

        # rebuild similar
        TitleSimilar.objects.filter(model_name=model_name).delete()

        batch = 600
        emb_T = emb.T
        with transaction.atomic():
            for start in range(0, len(ids), batch):
                end = min(start + batch, len(ids))
                sims = emb[start:end] @ emb_T  # cosine because normalized

                bulk_all = []
                for bi in range(end - start):
                    src_idx = start + bi
                    row = sims[bi]
                    row[src_idx] = -1.0
                    idx = np.argpartition(-row, topk)[:topk]
                    idx = idx[np.argsort(-row[idx])]

                    src_id = ids[src_idx]
                    for j in idx:
                        bulk_all.append(TitleSimilar(
                            title_id=src_id,
                            similar_id=ids[j],
                            score=float(row[j]),
                            model_name=model_name
                        ))

                TitleSimilar.objects.bulk_create(bulk_all, batch_size=5000)

        self.stdout.write(self.style.SUCCESS("Embeddings + Similar done."))
