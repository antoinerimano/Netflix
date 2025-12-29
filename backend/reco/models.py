from datetime import timezone
from django.db import models
from users.models import Title, Profile


class TitleEmbedding(models.Model):
    title = models.OneToOneField(Title, on_delete=models.CASCADE, related_name="embedding")
    dim = models.IntegerField(default=0)
    vector = models.JSONField(default=list)  # legacy
    vector_blob = models.BinaryField(null=True, blank=True)  # ✅ new (float32 bytes)
    model_name = models.CharField(max_length=64, default="all-MiniLM-L6-v2")
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=["model_name", "title"]),
        ]  

class TitleSimilar(models.Model):
    title = models.ForeignKey(Title, on_delete=models.CASCADE, related_name="similar_out")
    similar = models.ForeignKey(Title, on_delete=models.CASCADE, related_name="similar_in")
    score = models.FloatField(default=0.0)
    model_name = models.CharField(max_length=64, default="all-MiniLM-L6-v2")

    class Meta:
        unique_together = [("title", "similar", "model_name")]
        indexes = [
            models.Index(fields=["model_name", "title", "-score"]),
            models.Index(fields=["model_name", "similar"]),
        ]
        

class TitleImpression(models.Model):
    profile = models.ForeignKey(Profile, on_delete=models.CASCADE)
    title = models.ForeignKey(Title, on_delete=models.CASCADE)

    row_type = models.CharField(max_length=64, blank=True, default="")
    position = models.IntegerField(default=0)
    session_id = models.CharField(max_length=64, db_index=True)

    country = models.CharField(max_length=8, blank=True, default="")  # CA / QC etc
    device = models.CharField(max_length=16, blank=True, default="")  # tv/mobile/desktop

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=["profile", "-created_at"]),
            models.Index(fields=["title", "-created_at"]),
            models.Index(fields=["session_id", "-created_at"]),
        ]


class TitleAction(models.Model):
    ACTIONS = [
        ("click", "click"),
        ("outbound", "outbound"),            # label principal
        ("like", "like"),
        ("dislike", "dislike"),
        ("add_to_list", "add_to_list"),
        ("not_interested", "not_interested"),
        ("search_click", "search_click"),
    ]

    profile = models.ForeignKey(Profile, on_delete=models.CASCADE)
    title = models.ForeignKey(Title, on_delete=models.CASCADE)

    action = models.CharField(max_length=32, choices=ACTIONS)
    session_id = models.CharField(max_length=64, db_index=True)

    provider = models.CharField(max_length=255, blank=True, default="")  # link1/link2/link3/trailer
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=["profile", "-created_at"]),
            models.Index(fields=["profile", "title"]),
            models.Index(fields=["profile", "action", "-created_at"]),
            models.Index(fields=["title", "action", "-created_at"]),
            models.Index(fields=["session_id", "action", "-created_at"]),
        ]


class EditorialCollection(models.Model):
    name = models.CharField(max_length=200)
    slug = models.SlugField(max_length=220, unique=True)
    country = models.CharField(max_length=8, blank=True, default="")
    language = models.CharField(max_length=8, blank=True, default="")
    active = models.BooleanField(default=True)
    titles = models.ManyToManyField(Title, related_name="editorial_collections")
    created_at = models.DateTimeField(auto_now_add=True)


class RecoModelArtifact(models.Model):
    name = models.CharField(max_length=64, unique=True, default="lgbm_ranker_v1")
    model_blob = models.BinaryField()
    feature_schema = models.JSONField(default=dict)  # {feature_name: idx}
    trained_at = models.DateTimeField(auto_now_add=True)
    notes = models.CharField(max_length=255, blank=True, default="")

class RecoHomeSnapshot(models.Model):
    profile = models.OneToOneField(Profile, on_delete=models.CASCADE, related_name="home_snapshot")

    algo_version = models.CharField(max_length=32, default="home_v1", db_index=True)
    payload = models.JSONField(default=dict)  # {"rows":[...]} comme aujourd'hui

    built_at = models.DateTimeField(auto_now=True)
    expires_at = models.DateTimeField(db_index=True)

    # optionnel: pour debug
    last_error = models.TextField(blank=True, default="")

    class Meta:
        indexes = [
            models.Index(fields=["algo_version", "expires_at"]),
        ]

    def is_valid(self, now=None):
        now = now or timezone.now()
        return bool(self.payload) and self.expires_at and self.expires_at > now