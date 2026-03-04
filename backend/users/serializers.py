from rest_framework import serializers
from django.db import models
from django.db.models import Count
from .models import User, Subscription, Profile, PaymentHistory, Title, TVShowExtras, Season, Episode, Actor
import time

class UserSerializer(serializers.ModelSerializer):
    subscription = serializers.SerializerMethodField()

    def get_subscription(self, obj):
        qs = (Subscription.objects
            .filter(user=obj)
            .order_by(
                models.Case(
                    models.When(status='Active', then=0),
                    default=1,
                    output_field=models.IntegerField()
                ),
                '-start_date',
                '-id',
            ))
        sub = qs.first()
        return SubscriptionSerializer(sub).data if sub else None

    class Meta:
        model = User
        fields = '__all__'

class SubscriptionSerializer(serializers.ModelSerializer):
    class Meta:
        model = Subscription
        fields = '__all__'

class ProfileSerializer(serializers.ModelSerializer):
    class Meta:
        model = Profile
        fields = '__all__'

class PaymentHistorySerializer(serializers.ModelSerializer):
    class Meta:
        model = PaymentHistory
        fields = '__all__'

class EpisodeSerializer(serializers.ModelSerializer):
    class Meta:
        model = Episode
        fields = (
            "id", "tmdb_id", "episode_number", "name", "overview",
            "air_date", "still_path", "vote_average", "vote_count", "runtime",
            "imdb_code", "video_url", "episode_link2", "episode_link3", "episode_link4", "episode_link5", "episode_link6"
        )


class SeasonSerializer(serializers.ModelSerializer):
    episodes = EpisodeSerializer(many=True, read_only=True)
    class Meta:
        model = Season
        fields = ("season_number", "name", "overview", "air_date", "poster", "episodes")

class TVExtrasSerializer(serializers.ModelSerializer):
    class Meta:
        model = TVShowExtras
        fields = ("number_of_seasons", "number_of_episodes", "in_production", "episode_run_time", "network_names")


class ActorSerializer(serializers.ModelSerializer):
    photo = serializers.SerializerMethodField()
    appearances = serializers.IntegerField(read_only=True, default=0)

    class Meta:
        model = Actor
        fields = ["id", "name", "tmdb_id", "profile_path", "photo", "character", "appearances"]

    def get_photo(self, obj):
        if not obj.profile_path:
            return None
        return f"https://image.tmdb.org/t/p/w185{obj.profile_path}"


# In-process cache: rebuild at most once every 5 minutes
_appearance_cache = {"data": {}, "ts": 0.0}
_CACHE_TTL = 300

def _get_actor_appearance_counts():
    """
    Returns {tmdb_id: count} showing how many titles each actor appears in globally.
    Cached for 5 min — one simple COUNT query, no subqueries.
    """
    now = time.time()
    if now - _appearance_cache["ts"] < _CACHE_TTL and _appearance_cache["data"]:
        return _appearance_cache["data"]
    rows = (
        Actor.objects
        .exclude(tmdb_id__isnull=True)
        .values('tmdb_id')
        .annotate(n=Count('id'))
    )
    result = {row['tmdb_id']: row['n'] for row in rows}
    _appearance_cache["data"] = result
    _appearance_cache["ts"] = now
    return result


class TitleSerializer(serializers.ModelSerializer):
    tv_extras = TVExtrasSerializer(read_only=True)
    seasons = SeasonSerializer(many=True, read_only=True)
    actors = serializers.SerializerMethodField()

    def get_actors(self, obj):
        counts = _get_actor_appearance_counts()
        actors_sorted = sorted(
            obj.actors.all(),
            key=lambda a: counts.get(a.tmdb_id, 0),
            reverse=True
        )
        for a in actors_sorted:
            a.appearances = counts.get(a.tmdb_id, 0)
        return ActorSerializer(actors_sorted, many=True).data

    class Meta:
        model = Title
        fields = "__all__"

class TitleListSerializer(serializers.ModelSerializer):
    class Meta:
        model = Title
        fields = (
            "id", "type",
            "title",
            "poster", "landscape_image",
            "release_date",
            "genre", "rating",
            "director", "cast", "trailer_clip_url", "description"
        )

class TitleHomeSerializer(serializers.ModelSerializer):
    class Meta:
        model = Title
        fields = (
            "id", "type",
            "title",
            "landscape_image",
            "release_year",
            "rating",
            "description",
            "trailer_clip_url"
        )