from django.urls import path
from .views import (
    LogImpressionView, LogActionView, RecoHomeView, WatchProgressView,
    MyListView, MyListItemView, MyListImportView, TitleRatingView, PlaybackView,
    ShowFollowView, NotificationListView,
)
from .taste import TasteView
from .imports import ImportFilesView
from .calendar import CalendarView
from .history import HistoryView, HistoryItemView, HistoryPauseView, HistoryExportView
from .stats import StatsView
from .collections import CollectionView
from .lists import ListsView, ListView, ListItemView, PublicListView, PublicListCopyView

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
    path("calendar/", CalendarView.as_view()),
    path("history/", HistoryView.as_view()),
    path("history/pause/", HistoryPauseView.as_view()),
    path("history/export/", HistoryExportView.as_view()),
    path("history/<int:event_id>/", HistoryItemView.as_view()),
    path("stats/", StatsView.as_view()),
    path("collections/<int:collection_id>/", CollectionView.as_view()),
    path("lists/", ListsView.as_view()),
    path("lists/<int:list_id>/", ListView.as_view()),
    path("lists/<int:list_id>/items/<int:title_id>/", ListItemView.as_view()),
    path("public-lists/<slug:share_id>/", PublicListView.as_view()),
    path("public-lists/<slug:share_id>/copy/", PublicListCopyView.as_view()),
]
