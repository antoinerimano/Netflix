# streaming_backend/urls.py
from django.contrib import admin
from django.urls import path, include
from rest_framework_nested import routers
from users import views
from users.views import (
    LogoutView,
    request_password_reset,
    confirm_password_reset,
    # ViewSets you should have in users/views.py
    # TitleViewSet, SeasonViewSet, EpisodeViewSet
)

from rest_framework_simplejwt.views import (
    TokenObtainPairView,
    TokenRefreshView,
)

# Base router
router = routers.SimpleRouter()
router.register(r'users', views.UserViewSet, basename='user')
router.register(r'titles', views.TitleViewSet, basename='title')  # <— NEW

# Nested: /api/users/<user_id>/*
users_router = routers.NestedSimpleRouter(router, r'users', lookup='user')
users_router.register(r'subscriptions', views.SubscriptionViewSet, basename='user-subscription')
users_router.register(r'profiles', views.ProfileViewSet, basename='user-profile')
users_router.register(r'payment_history', views.PaymentHistoryViewSet, basename='user-paymenthistory')

# Nested: /api/titles/<title_id>/seasons/*
titles_router = routers.NestedSimpleRouter(router, r'titles', lookup='title')
titles_router.register(r'seasons', views.SeasonViewSet, basename='title-seasons')

# Nested: /api/titles/<title_id>/seasons/<season_id>/episodes/*
seasons_router = routers.NestedSimpleRouter(titles_router, r'seasons', lookup='season')
seasons_router.register(r'episodes', views.EpisodeViewSet, basename='season-episodes')

urlpatterns = [
    path('super-admin-7b0e/', admin.site.urls),

    # ✅ Use the imported views directly (not views.TokenObtainPairView)
    path('api/token/', TokenObtainPairView.as_view(), name='token_obtain_pair'),
    path('api/token/refresh/', TokenRefreshView.as_view(), name='token_refresh'),
    path('api/logout/', LogoutView.as_view(), name='logout'),

    path('api/', include(router.urls)),
    path('api/', include(users_router.urls)),
    path('api/', include(titles_router.urls)),
    path('api/', include(seasons_router.urls)),

    path("api/actors/titles/", views.titles_by_actor),

    path('api/password-reset/', request_password_reset, name='password-reset'),
    path('api/password-reset-confirm/', confirm_password_reset, name='password-reset-confirm'),

    path('api/users/confirm-email-change/', views.UserViewSet.as_view({'post': 'confirm_email_change'}), name='confirm-email-change'),
    path('api/users/<uuid:id>/request-email-change/', views.UserViewSet.as_view({'post': 'request_email_change'}), name='request-email-change'),

    path("api/", include("reco.urls")),

]
