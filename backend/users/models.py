from django.db import models
from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin
import uuid


class UserManager(BaseUserManager):
    def create_user(self, email, name, password=None, **extra_fields):
        if not email:
            raise ValueError('The Email field must be set')
        email = self.normalize_email(email)
        user = self.model(email=email, name=name, **extra_fields)
        user.set_password(password)  # This will hash the password
        user.save(using=self._db)
        return user

    def create_superuser(self, email, name, password=None, **extra_fields):
        extra_fields.setdefault('is_staff', True)
        extra_fields.setdefault('is_superuser', True)

        if extra_fields.get('is_staff') is not True:
            raise ValueError('Superuser must have is_staff=True.')
        if extra_fields.get('is_superuser') is not True:
            raise ValueError('Superuser must have is_superuser=True.')

        return self.create_user(email, name, password, **extra_fields)

class User(AbstractBaseUser, PermissionsMixin):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)  # UUID as primary key
    name = models.CharField(max_length=255)
    email = models.EmailField(unique=True)
    password = models.CharField(max_length=255)  # Django expects a 'password' field for authentication
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)
    stripe_customer_id = models.CharField(max_length=255, blank=True, null=True)

    objects = UserManager()

    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = ['name']  # Fields required when using createsuperuser

    def __str__(self):
        return self.email

class Subscription(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    plan_id = models.CharField(max_length=100)
    plan_type = models.CharField(max_length=50)
    start_date = models.DateTimeField(auto_now_add=True)
    renewal_date = models.DateTimeField(null=True, blank=True)  # Allow null values
    status = models.CharField(max_length=50)
    is_trial = models.BooleanField(default=False)

class Profile(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    name = models.CharField(max_length=255)
    age_restriction = models.CharField(max_length=10)
    avatar_url = models.CharField(max_length=255, blank=True, null=True)
    language_preference = models.CharField(max_length=10)

class PaymentHistory(models.Model):
    id = models.CharField(max_length=255, primary_key=True)
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    date = models.DateTimeField()
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    currency = models.CharField(max_length=10)
    plan_type = models.CharField(max_length=50)
    transaction_id = models.CharField(max_length=255)
    status = models.CharField(max_length=50)

# ============ Unified Title + TV structure ============

class Title(models.Model):
    MOVIE = "movie"
    TV = "tv"
    TITLE_TYPES = [(MOVIE, "Movie"), (TV, "TV")]

    id = models.AutoField(primary_key=True)

    # unified type
    type = models.CharField(max_length=10, choices=TITLE_TYPES, default=MOVIE, db_index=True)

    # external IDs
    imdb_code = models.CharField(max_length=20, unique=True, null=True, blank=True)
    tmdb_id = models.IntegerField(null=True, blank=True, db_index=True)

    # names
    title = models.CharField(max_length=255)                    # movies: title, tv: name
    original_title = models.CharField(max_length=255, blank=True, default="")
    original_language = models.CharField(max_length=8, blank=True, default="")

    # dates (movie vs tv)
    release_date = models.CharField(max_length=10, blank=True, default="")  # movie (yyyy-mm-dd)
    release_year = models.IntegerField(null=True, blank=True)               # convenience
    first_air_date = models.CharField(max_length=10, blank=True, default="")# tv (yyyy-mm-dd)

    # durations
    runtime_minutes = models.IntegerField(null=True, blank=True)            # movie; tv episodes have runtime on Episode

    # content
    description = models.TextField(blank=True, default="")
    tagline = models.CharField(max_length=255, blank=True, default="")
    status = models.CharField(max_length=64, blank=True, default="")        # e.g. Released/Ended/Returning

    # scores/popularity
    rating = models.CharField(max_length=10, blank=True, default="")
    vote_average = models.FloatField(null=True, blank=True)
    vote_count = models.IntegerField(null=True, blank=True)
    popularity = models.FloatField(null=True, blank=True)

    # artwork
    poster = models.URLField(blank=True, default="")
    landscape_image = models.URLField(blank=True, default="")

    # playback
    video_url = models.URLField(blank=True, default="")
    movie_link2 = models.URLField(blank=True, default="")
    movie_link3 = models.URLField(blank=True, default="")

    movie_link4 = models.TextField(blank=True, default="")  # vidfast
    movie_link5 = models.TextField(blank=True, default="")  # vidplus
    movie_link6 = models.TextField(blank=True, default="")  # 111movies

    trailer_url = models.URLField(blank=True, default="")
    trailer_clip_url = models.URLField(blank=True, default="")

    # taxonomy / people
    genre = models.CharField(max_length=255, blank=True, default="")
    # users/models.py (dans class Title)
    primary_genre_norm = models.CharField(max_length=32, db_index=True, blank=True, default="")

    keywords = models.JSONField(default=list, blank=True)
    production_companies = models.JSONField(default=list, blank=True)
    production_countries = models.JSONField(default=list, blank=True)
    spoken_languages = models.JSONField(default=list, blank=True)
    belongs_to_collection = models.JSONField(null=True, blank=True)

    director = models.CharField(max_length=255, blank=True, default="")
    cast = models.JSONField(default=list, blank=True)

    class Meta:
        constraints = [
            # Allow same tmdb_id across different types, but prevent duplicates per type.
            models.UniqueConstraint(fields=["type", "tmdb_id"], name="uniq_title_type_tmdbid"),
        ]
        indexes = [
            models.Index(fields=["type", "popularity", "vote_average", "id"]),
            models.Index(fields=["type", "release_year"]),
            models.Index(fields=["title"]),
            models.Index(fields=["original_title"]),
        ]

    def __str__(self):
        return f"{self.title} [{self.type}]"


class TVShowExtras(models.Model):
    """ One-to-one extras for TV series-level info. """
    title = models.OneToOneField(Title, on_delete=models.CASCADE, primary_key=True, related_name="tv_extras")
    number_of_seasons = models.IntegerField(default=0)
    number_of_episodes = models.IntegerField(default=0)
    in_production = models.BooleanField(default=False)
    episode_run_time = models.JSONField(default=list, blank=True)  # TMDB returns list
    network_names = models.JSONField(default=list, blank=True)     # optional

    def __str__(self):
        return f"TV extras for {self.title_id}"


class Season(models.Model):
    tv = models.ForeignKey(Title, on_delete=models.CASCADE, related_name="seasons")  # tv.type must be 'tv'
    tmdb_id = models.IntegerField(db_index=True, null=True, blank=True)
    season_number = models.IntegerField()
    name = models.CharField(max_length=200, blank=True, default="")
    overview = models.TextField(blank=True, default="")
    air_date = models.CharField(max_length=10, blank=True, default="")
    poster = models.CharField(max_length=300, blank=True, default="")

    class Meta:
        unique_together = [("tv", "season_number")]

    def __str__(self):
        return f"{self.tv.title} – S{self.season_number}"


# users/models.py  (only the Episode class shown)
class Episode(models.Model):
    season = models.ForeignKey(Season, on_delete=models.CASCADE, related_name="episodes")
    tmdb_id = models.IntegerField(db_index=True, null=True, blank=True)
    episode_number = models.IntegerField()
    name = models.CharField(max_length=300, blank=True, default="")
    overview = models.TextField(blank=True, default="")
    air_date = models.CharField(max_length=10, blank=True, default="")
    still_path = models.CharField(max_length=300, blank=True, default="")
    vote_average = models.FloatField(null=True, blank=True)
    vote_count = models.IntegerField(null=True, blank=True)
    runtime = models.IntegerField(null=True, blank=True)

    # external + embeds (3 links)
    imdb_code = models.CharField(max_length=20, blank=True, null=True)
    video_url = models.URLField(blank=True, default="")        # vidking
    episode_link2 = models.URLField(blank=True, default="")    # videasy
    episode_link3 = models.URLField(blank=True, default="")    # vidsrc

    episode_link4 = models.TextField(blank=True, default="")    # vidfast
    episode_link5 = models.TextField(blank=True, default="")    # vidplus
    episode_link6 = models.TextField(blank=True, default="")    #111movies

    class Meta:
        unique_together = [("season", "episode_number")]



class Actor(models.Model):
    title = models.ForeignKey(Title, on_delete=models.CASCADE, related_name="actors", db_index=True)

    name = models.CharField(max_length=255)
    name_norm = models.CharField(max_length=255, db_index=True)

    tmdb_id = models.IntegerField(null=True, blank=True, db_index=True)
    profile_path = models.CharField(max_length=255, null=True, blank=True)

    character = models.CharField(max_length=255, blank=True, default="")

    class Meta:
        indexes = [
            models.Index(fields=["name_norm"]),
            models.Index(fields=["tmdb_id"]),
            models.Index(fields=["title", "name_norm"]),
        ]
        constraints = [
        models.UniqueConstraint(fields=["title", "name_norm"], name="uniq_actor_per_title"),
        ]

    def __str__(self):
        return f"{self.name} (title={self.title_id})"



class TitleKeyword(models.Model):
    title = models.ForeignKey(Title, on_delete=models.CASCADE, related_name="keywords_rel")
    keyword_norm = models.CharField(max_length=120, db_index=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["title", "keyword_norm"], name="uniq_title_keyword"),
        ]
        indexes = [
            models.Index(fields=["keyword_norm", "title"]),
            models.Index(fields=["title"]),
        ]

    def __str__(self):
        return f"{self.title_id} kw {self.keyword_norm}"


class TitleCompany(models.Model):
    title = models.ForeignKey(Title, on_delete=models.CASCADE, related_name="companies_rel")
    company_norm = models.CharField(max_length=160, db_index=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["title", "company_norm"], name="uniq_title_company"),
        ]
        indexes = [
            models.Index(fields=["company_norm", "title"]),
            models.Index(fields=["title"]),
        ]

    def __str__(self):
        return f"{self.title_id} comp {self.company_norm}"


class TitleCountry(models.Model):
    title = models.ForeignKey(Title, on_delete=models.CASCADE, related_name="countries_rel")
    # si tu peux: ISO2 "US", "CA"... sinon remplace par country_norm max_length=80
    country_code = models.CharField(max_length=2, db_index=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["title", "country_code"], name="uniq_title_country"),
        ]
        indexes = [
            models.Index(fields=["country_code", "title"]),
            models.Index(fields=["title"]),
        ]

    def __str__(self):
        return f"{self.title_id} country {self.country_code}"


class TitleNetwork(models.Model):
    # tes networks sont dans TVShowExtras.network_names (JSONField) :contentReference[oaicite:1]{index=1}
    title = models.ForeignKey(Title, on_delete=models.CASCADE, related_name="networks_rel")
    network_norm = models.CharField(max_length=160, db_index=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["title", "network_norm"], name="uniq_title_network"),
        ]
        indexes = [
            models.Index(fields=["network_norm", "title"]),
            models.Index(fields=["title"]),
        ]

    def __str__(self):
        return f"{self.title_id} net {self.network_norm}"

