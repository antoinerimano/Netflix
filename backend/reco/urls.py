from django.urls import path
from .views import (
    LogImpressionView, LogActionView, RecoHomeView, WatchProgressView,
    MyListView, MyListItemView, MyListImportView, TitleRatingView, PlaybackView,
)

urlpatterns = [
    path("events/impressions/", LogImpressionView.as_view()),
    path("events/action/", LogActionView.as_view()),
    path("reco/home/", RecoHomeView.as_view()),
    path("watch-progress/", WatchProgressView.as_view()),
    path("my-list/", MyListView.as_view()),
    path("my-list/import/", MyListImportView.as_view()),
    path("my-list/<int:title_id>/", MyListItemView.as_view()),
    path("ratings/<int:title_id>/", TitleRatingView.as_view()),
    path("playback/", PlaybackView.as_view()),
]
