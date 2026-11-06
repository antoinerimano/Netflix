from django.urls import path
from .views import (
    LogImpressionView, LogActionView, RecoHomeView, WatchProgressView,
    MyListView, MyListItemView, MyListImportView, TitleRatingView, PlaybackView,
    ShowFollowView, NotificationListView,
)
from .taste import TasteView
from .imports import ImportFilesView

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
    path("follows/<int:title_id>/", ShowFollowView.as_view()),
    path("notifications/", NotificationListView.as_view()),
    path("notifications/read/", NotificationListView.as_view()),
    path("taste/", TasteView.as_view()),
    path("import/files/", ImportFilesView.as_view()),
]
