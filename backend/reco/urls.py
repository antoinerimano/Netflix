from django.urls import path
from .views import LogImpressionView, LogActionView, RecoHomeView

urlpatterns = [
    path("events/impressions/", LogImpressionView.as_view()),
    path("events/action/", LogActionView.as_view()),
    path("reco/home/", RecoHomeView.as_view())
]
