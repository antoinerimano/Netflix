from django.db import migrations, models

# The 6 providers as they were stored on Title/Episode rows (checked against the DB).
VIDPLUS_MOVIE_QS = (
    "?autoplay=false&poster=true&title=true&watchparty=false&chromecast=true&servericon=true"
    "&setting=true&pip=true&icons=netflix&primarycolor=FF6161&secondarycolor=000000"
    "&iconcolor=CB4848&font=Roboto&fontcolor=FFFFFF&fontsize=20&opacity=0.5"
)
VIDPLUS_TV_QS = (
    "?autoplay=false&autonext=false&nextbutton=false&poster=true&title=true&watchparty=false"
    "&chromecast=true&episodelist=true&servericon=true&setting=true&pip=true&icons=netflix"
    "&primarycolor=FF6161&secondarycolor=000000&iconcolor=CB4848&font=Roboto&fontcolor=FFFFFF"
    "&fontsize=20&opacity=0.5"
)

PROVIDERS = [
    # key, label, domain, movie_path, episode_path
    ("vidking", "Vidking", "https://www.vidking.net",
     "/embed/movie/{tmdb_id}", "/embed/tv/{tmdb_id}/{season}/{episode}"),
    ("videasy", "Videasy", "https://player.videasy.net",
     "/movie/{tmdb_id}", "/tv/{tmdb_id}/{season}/{episode}"),
    ("vidsrc", "Vidsrc", "https://vidsrc.xyz",
     "/embed/movie/{imdb_id}", "/embed/tv/{tmdb_id}/{season}-{episode}"),
    ("vidfast", "VidFast", "https://vidfast.pro",
     "/movie/{tmdb_id}", "/tv/{tmdb_id}/{season}/{episode}"),
    ("vidplus", "VidPlus", "https://player.vidplus.to",
     "/embed/movie/{tmdb_id}" + VIDPLUS_MOVIE_QS, "/embed/tv/{tmdb_id}/{season}/{episode}" + VIDPLUS_TV_QS),
    ("111movies", "111movies", "https://111movies.com",
     "/movie/{tmdb_id}", "/tv/{tmdb_id}/{season}/{episode}"),
]


def seed_providers(apps, schema_editor):
    Provider = apps.get_model("users", "Provider")
    for priority, (key, label, domain, movie_path, episode_path) in enumerate(PROVIDERS, 1):
        Provider.objects.update_or_create(
            key=key,
            defaults=dict(label=label, domain=domain, movie_path=movie_path,
                          episode_path=episode_path, priority=priority * 10),
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
