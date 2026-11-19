"""manage.py build_embeddings: the vectors are saved where the recommendations read them
(vector_blob), and --missing (nightly) only does the titles that have none, with their similar
titles among all. A fake sentence-transformers model: nothing is downloaded."""
import sys
import types
from io import StringIO
from unittest import mock

import numpy as np
from django.core.management import call_command
from django.test import TestCase

from users.models import JobRun, Title
from .models import TitleEmbedding, TitleSimilar


class FakeModel:
    """A 4-d vector from the title: "Space A" and "Space B" end up close, "Cooking" far."""

    encoded = []

    def __init__(self, name):
        pass

    def encode(self, texts, **kw):
        FakeModel.encoded.extend(texts)
        out = []
        for t in texts:
            v = np.array([1.0, 0.1, 0.0, 0.0]) if "Space" in t else np.array([0.0, 0.0, 1.0, 0.2])
            if t.startswith("Space B"):
                v = v + np.array([0.0, 0.2, 0.0, 0.0])
            out.append(v / np.linalg.norm(v))
        return np.asarray(out, dtype=np.float32)


class BuildEmbeddingsTests(TestCase):
    def setUp(self):
        FakeModel.encoded = []
        fake = types.ModuleType("sentence_transformers")
        fake.SentenceTransformer = FakeModel
        patcher = mock.patch.dict(sys.modules, {"sentence_transformers": fake})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.a = Title.objects.create(type="movie", title="Space A", tmdb_id=1)
        self.c = Title.objects.create(type="movie", title="Cooking", tmdb_id=2)

    def build(self, *args):
        call_command("build_embeddings", "--topk", "5", *args, stdout=StringIO())

    def blob(self, title):
        return np.frombuffer(bytes(TitleEmbedding.objects.get(title=title).vector_blob), dtype=np.float32)

    def test_full_build_saves_the_blob_the_recommendations_read(self):
        self.build()
        emb = TitleEmbedding.objects.get(title=self.a)
        self.assertEqual(emb.dim, 4)
        np.testing.assert_allclose(self.blob(self.a), np.asarray(emb.vector, dtype=np.float32))

    def test_missing_only_embeds_new_titles_and_finds_their_similar(self):
        self.build()
        b = Title.objects.create(type="movie", title="Space B", tmdb_id=3)
        FakeModel.encoded = []
        self.build("--missing")

        self.assertEqual(len(FakeModel.encoded), 1)  # only the new title
        self.assertTrue(FakeModel.encoded[0].startswith("Space B"))
        similar = list(TitleSimilar.objects.filter(title=b).order_by("-score").values_list("similar_id", flat=True))
        self.assertEqual(similar, [self.a.id, self.c.id])  # closest first, never itself
        self.assertEqual(TitleSimilar.objects.filter(title=self.a).count(), 1)  # the others: untouched until Sunday
        self.assertEqual(JobRun.objects.filter(name="build_embeddings", ok=True).count(), 2)

    def test_missing_also_redoes_a_title_saved_without_blob(self):
        self.build()
        TitleEmbedding.objects.filter(title=self.c).update(vector_blob=None)
        FakeModel.encoded = []
        self.build("--missing")
        self.assertEqual(len(FakeModel.encoded), 1)
        self.assertEqual(len(self.blob(self.c)), 4)

    def test_missing_with_nothing_to_do(self):
        self.build()
        FakeModel.encoded = []
        self.build("--missing")
        self.assertEqual(FakeModel.encoded, [])

    def test_a_second_full_build_replaces_the_lists(self):
        b = Title.objects.create(type="movie", title="Space B", tmdb_id=3)
        self.build()
        before = list(TitleSimilar.objects.order_by("title_id", "-score").values_list("title_id", "similar_id"))
        self.build()
        after = list(TitleSimilar.objects.order_by("title_id", "-score").values_list("title_id", "similar_id"))
        self.assertEqual(before, after)
        self.assertEqual(TitleEmbedding.objects.count(), 3)
        self.assertEqual(list(TitleSimilar.objects.filter(title=b).order_by("-score").values_list("similar_id", flat=True)),
                         [self.a.id, self.c.id])
