from django.contrib import admin

from .models import PlaybackReport


@admin.register(PlaybackReport)
class PlaybackReportAdmin(admin.ModelAdmin):
    """"Playback problem?" reports (ROADMAP 9.8) and the provider scout's re-check of each."""
    list_display = ("created_at", "title", "season_number", "episode_number", "provider_key", "problem",
                    "profile", "checked_at", "check_result")
    list_filter = ("problem", "provider_key", "checked_at")
    search_fields = ("title__title", "provider_key")
    raw_id_fields = ("title", "profile")
    date_hierarchy = "created_at"
