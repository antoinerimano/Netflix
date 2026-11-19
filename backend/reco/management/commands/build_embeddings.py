from django.core.management.base import BaseCommand
from django.db import transaction
from users.models import Title
from reco.models import TitleEmbedding, TitleSimilar, TitleTags
from reco.tags import embedding_text

from pathlib import Path
import os
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

import numpy as np
from users.jobs import tracked


def _join(x):
    if not x:
        return ""
    if isinstance(x, str):
        return x
    try:
        return " ".join([str(i) for i in x])
    except Exception:
        return ""


def title_text(ti, tags) -> str:
    return " | ".join([
        ti.title or "",
        ti.original_title or "",
        (ti.description or "")[:1500],
        ti.genre or "",
        _join(ti.keywords),
        _join(ti.cast),
        ti.director or "",
        ti.original_language or "",
        _join(ti.production_countries),
        embedding_text(tags),
    ]).strip()


TEXT_FIELDS = ("id", "title", "original_title", "description", "genre", "keywords",
               "cast", "director", "original_language", "production_countries")


def save_embeddings(ids, emb, model_name):
    """vector_blob (float32 bytes) is what the recommendations read (reco/views.py); vector (JSON)
    is still read by train_ranker."""
    dim = int(emb.shape[1])
    with transaction.atomic():
        for i, tid in enumerate(ids):
            TitleEmbedding.objects.update_or_create(
                title_id=tid,
                defaults={"dim": dim, "vector": emb[i].tolist(), "vector_blob": emb[i].tobytes(),
                          "model_name": model_name},
            )


def top_similar(src_ids, src_emb, all_ids, all_emb, topk, model_name):
    """TitleSimilar rows: the topk closest titles of each source title (cosine: vectors normalized)."""
    rows = []
    k = min(topk, len(all_ids) - 1)
    if k <= 0:
        return rows
    pos = {tid: i for i, tid in enumerate(all_ids)}
    all_T = all_emb.T
    for start in range(0, len(src_ids), 600):
        sims = src_emb[start:start + 600] @ all_T
        for bi, src_id in enumerate(src_ids[start:start + 600]):
            row = sims[bi]
            if src_id in pos:
                row[pos[src_id]] = -1.0
            idx = np.argpartition(-row, k)[:k] if k < len(row) else np.arange(len(row))
            idx = idx[np.argsort(-row[idx])]
            for j in idx:
                if all_ids[j] != src_id:
                    rows.append(TitleSimilar(title_id=src_id, similar_id=all_ids[j],
                                             score=float(row[j]), model_name=model_name))
    return rows


class Command(BaseCommand):
    help = "Compute embeddings and store topK similar titles in DB."

    def add_arguments(self, p):
        p.add_argument("--type", choices=["movie", "tv", "all"], default="all")
        p.add_argument("--topk", type=int, default=80)
        p.add_argument("--model-name", type=str, default="all-MiniLM-L6-v2")
        p.add_argument("--missing", action="store_true",
                       help="Nightly: only the titles with no embedding yet (new titles), and their similar "
                            "titles; the weekly full run rebuilds everything.")

    @tracked("build_embeddings")  # JobRun: shown on the admin dashboard
    def handle(self, *args, **o):
        if o["missing"]:
            return self.handle_missing(o["topk"], o["model_name"])

        t = o["type"]
        topk = o["topk"]
        model_name = o["model_name"]

        qs = Title.objects.all()
        if t in ("movie", "tv"):
            qs = qs.filter(type=t)

        titles = list(qs.only(*TEXT_FIELDS))

        # AI moods / themes / pacing (manage.py tag_titles), when the title has them
        tagged = {tt.title_id: tt for tt in TitleTags.objects.only("title_id", "moods", "themes", "pacing")}

        ids = [ti.id for ti in titles]
        texts = [title_text(ti, tagged.get(ti.id)) for ti in titles]

        from sentence_transformers import SentenceTransformer
        model = SentenceTransformer(model_name)
        emb = model.encode(texts, batch_size=64, show_progress_bar=True, normalize_embeddings=True)
        emb = np.asarray(emb, dtype=np.float32)

        save_embeddings(ids, emb, model_name)

        # rebuild similar
        TitleSimilar.objects.filter(model_name=model_name).delete()
        with transaction.atomic():
            for start in range(0, len(ids), 600):
                TitleSimilar.objects.bulk_create(
                    top_similar(ids[start:start + 600], emb[start:start + 600], ids, emb, topk, model_name),
                    batch_size=5000)

        self.stdout.write(self.style.SUCCESS(f"Embeddings + Similar done: {len(ids)} titles."))

    def handle_missing(self, topk, model_name):
        have_blob = TitleEmbedding.objects.filter(model_name=model_name, vector_blob__isnull=False)             .exclude(vector_blob=b"").values("title_id")
        titles = list(Title.objects.exclude(id__in=have_blob).only(*TEXT_FIELDS))
        self.stdout.write(f"[embeddings] titles without an embedding: {len(titles)}")
        if not titles:
            return

        tagged = {tt.title_id: tt for tt in TitleTags.objects.filter(title_id__in=[ti.id for ti in titles])
                  .only("title_id", "moods", "themes", "pacing")}
        new_ids = [ti.id for ti in titles]

        from sentence_transformers import SentenceTransformer
        model = SentenceTransformer(model_name)
        new_emb = np.asarray(model.encode([title_text(ti, tagged.get(ti.id)) for ti in titles], batch_size=64,
                                          normalize_embeddings=True), dtype=np.float32)
        save_embeddings(new_ids, new_emb, model_name)

        # their similar titles, among every title that has an embedding (them included)
        all_ids, vecs = [], []
        dim = int(new_emb.shape[1])
        for tid, blob in TitleEmbedding.objects.filter(model_name=model_name, vector_blob__isnull=False)                 .values_list("title_id", "vector_blob").iterator(chunk_size=5000):
            if blob and len(blob) == dim * 4:
                all_ids.append(tid)
                vecs.append(np.frombuffer(bytes(blob), dtype=np.float32))
        all_emb = np.vstack(vecs)
        rows = top_similar(new_ids, new_emb, all_ids, all_emb, topk, model_name)
        with transaction.atomic():
            TitleSimilar.objects.filter(model_name=model_name, title_id__in=new_ids).delete()
            TitleSimilar.objects.bulk_create(rows, batch_size=5000)
        self.stdout.write(self.style.SUCCESS(
            f"[embeddings] done: {len(new_ids)} new titles, {len(rows)} similar rows (among {len(all_ids)} titles)"))
