from rest_framework import serializers
from django.db import models
from .models import User, Subscription, Profile, PaymentHistory, Title, TVShowExtras, Season, Episode, Actor

class UserSerializer(serializers.ModelSerializer):
    subscription = serializers.SerializerMethodField()

    def get_subscription(self, obj):
        # newest active first
        qs = (Subscription.objects
            .filter(user=obj)
            .order_by(
                models.Case(
                    models.When(status='Active', then=0),  # Active first
                    default=1,
                    output_field=models.IntegerField()
                ),
                '-start_date',
                '-id',            # tie-breaker
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

    class Meta:
        model = Actor
        fields = ["id", "name", "tmdb_id", "profile_path", "photo", "character"]

    def get_photo(self, obj):
        if not obj.profile_path:
            return None
        return f"https://image.tmdb.org/t/p/w185{obj.profile_path}"
    
    
class TitleSerializer(serializers.ModelSerializer):
    tv_extras = TVExtrasSerializer(read_only=True)
    seasons = SeasonSerializer(many=True, read_only=True)
    actors = ActorSerializer(many=True, read_only=True)

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
            "release_year",   # si tu l'as en DB (sinon enlève)
            "rating",
            "description",
            "trailer_clip_url"
        )