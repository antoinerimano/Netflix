from django.db import migrations, models

# Starting provider setup (as configured locally before the first prod deploy).
PROVIDERS = [
    # key, label, domain, movie_path, episode_path, priority, backup_domains
    ("videasy", "Videasy", "https://player.videasy.ws",
     "/embed/movie/{tmdb_id}", "/embed/tv/{tmdb_id}/{season}/{episode}?autonext=1", 20, ""),
    ("vidsrc", "Vidsrc", "https://vidsrc.mov",
     "/embed/movie/{imdb_id}", "/embed/tv/{tmdb_id}/{season}-{episode}", 30, ""),
    ("vidfast", "VidFast", "https://vidfast.vc",
     "/movie/{tmdb_id}", "/tv/{tmdb_id}/{season}/{episode}", 40, "https://vidfast.pro"),
    ("111movies", "111movies", "https://111movies.net",
     "/movie/{tmdb_id}", "/tv/{tmdb_id}/{season}/{episode}", 60, ""),
    ("cinesrc", "CineSrc", "https://cinesrc.st",
     "/embed/movie/{tmdb_id}", "/embed/tv/{tmdb_id}?s={season}&e={episode}&autonext=true", 70, ""),
    ("vidcore", "VidCore", "https://vidcore.org",
     "/embed/movie/{tmdb_id}?autoplay=true", "/embed/tv/{tmdb_id}/{season}/{episode}?autoplay=true", 80, ""),
]


def seed_providers(apps, schema_editor):
    Provider = apps.get_model("users", "Provider")
    for key, label, domain, movie_path, episode_path, priority, backup_domains in PROVIDERS:
        Provider.objects.update_or_create(
            key=key,
            defaults=dict(label=label, domain=domain, movie_path=movie_path, episode_path=episode_path,
                          priority=priority, backup_domains=backup_domains),
        )


class Migration(migrations.Migration):

    dependencies = [
        ("users", "0011_title_primary_genre_norm"),
    ]

    operations = [
        migrations.CreateModel(
            name="Provider",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("key", models.SlugField(max_length=40, unique=True)),
                ("label", models.CharField(max_length=80)),
                ("domain", models.CharField(help_text="e.g. https://vidfast.pro", max_length=200)),
                ("backup_domains", models.TextField(blank=True, default="", help_text="One per line. Tried in order by the health check when the main domain is down.")),
                ("movie_path", models.CharField(blank=True, default="", help_text="e.g. /movie/{tmdb_id}", max_length=500)),
                ("episode_path", models.CharField(blank=True, default="", help_text="e.g. /tv/{tmdb_id}/{season}/{episode}", max_length=500)),
                ("enabled", models.BooleanField(default=True)),
                ("priority", models.PositiveSmallIntegerField(default=100, help_text="Lower shows first.")),
                ("auto_switch", models.BooleanField(default=True, help_text="Let the health check move to a backup domain, or follow a redirect to a new domain.")),
                ("status", models.CharField(choices=[("up", "Up"), ("down", "Down"), ("unknown", "Unknown")], default="unknown", max_length=10)),
                ("status_detail", models.CharField(blank=True, default="", max_length=300)),
                ("checked_at", models.DateTimeField(blank=True, null=True)),
                ("suggested_domain", models.CharField(blank=True, default="", max_length=200)),
                ("domain_changed_at", models.DateTimeField(blank=True, null=True)),
            ],
            options={"ordering": ["priority", "id"]},
        ),
        migrations.RunPython(seed_providers, migrations.RunPython.noop),
    ]
