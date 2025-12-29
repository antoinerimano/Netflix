from rest_framework.decorators import api_view, permission_classes, action
from rest_framework.response import Response
from rest_framework import viewsets, status
from rest_framework.views import APIView
from rest_framework.pagination import PageNumberPagination
from django.utils.decorators import method_decorator
from django.views.decorators.cache import cache_page
import re
from django.db.models import Q
from django.db import models
from django.db.models import Q
from django.conf import settings
from django.shortcuts import get_object_or_404
from django.contrib.auth.hashers import make_password, check_password
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.token_blacklist.models import BlacklistedToken, OutstandingToken
from rest_framework_simplejwt.exceptions import TokenError, InvalidToken
from datetime import timedelta
from rest_framework.permissions import SAFE_METHODS, BasePermission, AllowAny, IsAuthenticated
from django.contrib.auth.tokens import default_token_generator
from django.core.mail import send_mail
from django.utils.http import urlsafe_base64_encode, urlsafe_base64_decode
from django.utils.encoding import force_bytes, force_str
from django.core.signing import TimestampSigner, BadSignature, SignatureExpired
from django.utils import timezone
from urllib.parse import quote

from django.core.mail import send_mail
from django.template.loader import render_to_string
from django.utils.html import strip_tags

from .models import (
    Actor, User, Subscription, Profile, PaymentHistory,
    Title, Season, Episode, TVShowExtras
)
from .serializers import (
    UserSerializer, SubscriptionSerializer,
    ProfileSerializer, PaymentHistorySerializer, TitleSerializer,
    EpisodeSerializer, SeasonSerializer, TVExtrasSerializer, TitleListSerializer
)

signer = TimestampSigner()


from rest_framework.permissions import AllowAny
from rest_framework_simplejwt.views import (
    TokenObtainPairView as _BaseTokenObtainPairView,
    TokenRefreshView as _BaseTokenRefreshView,
)
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer


def norm_name(s: str) -> str:
    s = (s or "").strip().lower()
    s = re.sub(r"[^a-z0-9]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


# Optional: customize token payload (keep or remove as you like)
class _AppTokenObtainPairSerializer(TokenObtainPairSerializer):
    @classmethod
    def get_token(cls, user):
        token = super().get_token(user)
        # add any custom claims you want in the JWT:
        token["user_id"] = str(user.id)
        token["email"] = getattr(user, "email", "")
        token["is_staff"] = getattr(user, "is_staff", False)
        return token

# Export views under the exact names your urls.py expects
class TokenObtainPairView(_BaseTokenObtainPairView):
    permission_classes = [AllowAny]
    serializer_class = _AppTokenObtainPairSerializer

class TokenRefreshView(_BaseTokenRefreshView):
    permission_classes = [AllowAny]



# ------------------ Permissions ------------------

class IsAdminOrReadOnly(BasePermission):
    """Anyone can read; only staff can write."""
    def has_permission(self, request, view):
        if request.method in SAFE_METHODS:
            return True
        return bool(request.user and request.user.is_staff)


class IsSelfOrAdmin(BasePermission):
    """Users can act on self; admins on anyone."""
    def has_object_permission(self, request, view, obj):
        if request.method in SAFE_METHODS:
            return True
        if request.user and request.user.is_staff:
            return True
        return obj == request.user


# ------------------ Users ------------------

class UserViewSet(viewsets.ModelViewSet):
    queryset = User.objects.all()
    serializer_class = UserSerializer
    lookup_field = 'id'
    permission_classes = [IsAuthenticated, IsSelfOrAdmin]

    @action(detail=False, methods=['post'], permission_classes=[AllowAny], url_path='register')
    def register(self, request):
        data = request.data.copy()
        email = data.get('email')
        password = data.get('password')

        if not email:
            return Response({'error': 'Email is required'}, status=status.HTTP_400_BAD_REQUEST)
        if not password:
            return Response({'error': 'Password is required'}, status=status.HTTP_400_BAD_REQUEST)
        if User.objects.filter(email=email).exists():
            return Response({'error': 'This email is already registered'}, status=status.HTTP_400_BAD_REQUEST)

        data['password'] = make_password(password)
        serializer = self.get_serializer(data=data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()
        refresh = RefreshToken.for_user(user)
        return Response({
            'refresh': str(refresh),
            'access': str(refresh.access_token),
            'user': serializer.data,
        }, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=['post'], permission_classes=[IsAuthenticated], url_path='subscribe')
    def subscribe(self, request, id=None):
        """
        No Stripe, no PaymentMethod table.
        - Premium: create local Subscription + optional PaymentHistory entry.
        - Basic: create local Subscription without billing.
        """
        user = self.get_object()
        plan_type = (request.data.get('plan_type') or 'Premium').capitalize()  # 'Premium' or 'Basic'
        plan_id = request.data.get('plan_id') or plan_type

        # Optional policy: prevent duplicate active for same type
        if Subscription.objects.filter(user=user, plan_type=plan_type, status="Active").exists():
            return Response({'error': f'You already have an active {plan_type} subscription.'},
                            status=status.HTTP_400_BAD_REQUEST)

        # Create subscription
        start = timezone.now()
        renewal = None if plan_type == 'Basic' else start + timedelta(days=30)

        sub = Subscription.objects.create(
            user=user,
            plan_id=plan_id,
            plan_type=plan_type,
            start_date=start,
            renewal_date=renewal,
            status="Active",
            is_trial=False,
            
        )

        # Optionally log a local (fake) payment for Premium
        if plan_type == 'Premium':
            from uuid import uuid4
            PaymentHistory.objects.create(
                id=str(uuid4()),
                user=user,
                date=timezone.now(),
                amount=request.data.get('amount', 9.99),
                currency=request.data.get('currency', 'USD'),
                plan_type='Premium',
                transaction_id=request.data.get('transaction_id', f'LOCAL-{uuid4()}'),
                status='Succeeded'
            )

        return Response(
            {'message': f'{plan_type} subscription created!', 'subscription_id': sub.id},
            status=status.HTTP_201_CREATED
        )

    @action(detail=False, methods=['post'], permission_classes=[AllowAny], url_path='login')
    def login(self, request):
        email = request.data.get('email')
        password = request.data.get('password')

        try:
            user = User.objects.get(email=email)
        except User.DoesNotExist:
            return Response({"error": "User not found"}, status=status.HTTP_404_NOT_FOUND)

        if not check_password(password, user.password):
            return Response({"error": "Invalid credentials"}, status=status.HTTP_400_BAD_REQUEST)

        # Blacklist existing refresh tokens
        for t in OutstandingToken.objects.filter(user=user):
            BlacklistedToken.objects.get_or_create(token=t)

        refresh = RefreshToken.for_user(user)

        default_profile = (
            Profile.objects
            .filter(user=user)
            .order_by("id")   # ou "created_at" si tu as ce champ
            .first()
        )
        
        return Response({
            'refresh': str(refresh),
            'access': str(refresh.access_token),
            'user': UserSerializer(user).data,
            'default_profile_id': default_profile.id if default_profile else None
        })
    
    
    @action(detail=True, methods=['post'], permission_classes=[IsAuthenticated], url_path='request-email-change')
    def request_email_change(self, request, id=None):
        user = self.get_object()
        new_email = request.data.get("new_email")

        if not new_email:
            return Response({"error": "New email is required"}, status=status.HTTP_400_BAD_REQUEST)

        if User.objects.filter(email=new_email).exists():
            return Response({"error": "Email already in use"}, status=status.HTTP_400_BAD_REQUEST)

        # Generate a signed token link
       
        raw_token = signer.sign(new_email)
        token = quote(raw_token, safe="")
        confirm_url = f"{settings.FRONTEND_URL}/confirm-email-change/{user.id}/{token}"

          # Render HTML and plain text
        context = {
            "user": user,
            "new_email": new_email,
            "confirm_url": confirm_url,
            "support_email": "support@yourdomain.com",
            "company_name": "Taurus",  # <- customize
        }
        subject = "Confirm your new email address"

        html_message = render_to_string("emails/email_change.html", context)
        plain_message = strip_tags(html_message)

        send_mail(
            subject,
            plain_message,
            settings.DEFAULT_FROM_EMAIL,
            [new_email],
            html_message=html_message,
            fail_silently=False,
        )

        return Response({"message": "Confirmation email sent"}, status=status.HTTP_200_OK)

    @action(
    detail=True,
    methods=['post'],
    url_path='confirm-email-change',
    permission_classes=[AllowAny],
)
    def confirm_email_change(self, request, id=None):
        user = get_object_or_404(User, id=id)  # lookup by UUID, not via self.get_object()
        token = (request.data.get("token") or "").strip()
        if not token:
            return Response({"error": "Token is required"}, status=status.HTTP_400_BAD_REQUEST)

        try:
            new_email = signer.unsign(token, max_age=60*60*24)  # 24h validity
        except SignatureExpired:
            return Response({"error": "Token expired"}, status=status.HTTP_400_BAD_REQUEST)
        except BadSignature:
            return Response({"error": "Invalid token"}, status=status.HTTP_400_BAD_REQUEST)

        # prevent collisions
        if User.objects.filter(email=new_email).exclude(id=user.id).exists():
            return Response({"error": "Email already taken"}, status=status.HTTP_400_BAD_REQUEST)

        user.email = new_email
        user.save(update_fields=["email"])
        return Response({"message": "Email updated successfully"}, status=status.HTTP_200_OK)    


# ------------------ Subscriptions ------------------

class SubscriptionViewSet(viewsets.ModelViewSet):
    serializer_class = SubscriptionSerializer
    queryset = Subscription.objects.all()

    def get_queryset(self):
        qs = super().get_queryset().filter(user_id=self.kwargs['user_id'])
        return qs.order_by(
            models.Case(models.When(status='Active', then=0), default=1, output_field=models.IntegerField()),
            '-start_date'
        )

    def create(self, request, *args, **kwargs):
        """
        Client can send: plan_id, plan_type ('Basic' or 'Premium').
        """
        user_id = self.kwargs.get('user_id')
        plan_type = (request.data.get('plan_type') or 'Basic').capitalize()
        start = timezone.now()
        renewal = None if plan_type == 'Basic' else start + timedelta(days=30)

        # Optional: remove previous subs to ensure single active
        Subscription.objects.filter(user_id=user_id).delete()

        sub = Subscription.objects.create(
            user_id=user_id,
            plan_id=request.data.get('plan_id') or plan_type,
            plan_type=plan_type,
            start_date=start,
            renewal_date=renewal,
            status="Active",
            is_trial=False,
        )
        return Response(SubscriptionSerializer(sub).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=['put'], url_path='cancel')
    def cancel(self, request, user_id=None, pk=None):
        sub = self.get_object()
        if sub.status == 'Canceled':
            return Response({"error": "Subscription already canceled"}, status=400)
        sub.status = 'Canceled'
        sub.renewal_date = timezone.now()
        sub.save()
        return Response(UserSerializer(sub.user, context={'request': request}).data, status=status.HTTP_200_OK)


# ------------------ Profiles & Payments history ------------------

class ProfileViewSet(viewsets.ModelViewSet):
    serializer_class = ProfileSerializer

    def get_queryset(self):
        return Profile.objects.filter(user__id=self.kwargs.get('user_id'))

    def create(self, request, *args, **kwargs):
        user_id = self.kwargs.get('user_id')

        if Profile.objects.filter(user__id=user_id).count() >= 4:
            return Response({"detail": "Maximum of 4 profiles per account allowed."},
                            status=status.HTTP_400_BAD_REQUEST)

        # 1) crée le profile normalement
        response = super().create(request, *args, **kwargs)

        # 2) seed snapshot tout de suite (home jamais vide)
        try:
            profile_id = response.data.get("id")
            if profile_id:
                from reco.views import upsert_seed_snapshot  # tu crées ce fichier reco/seed.py
                p = Profile.objects.get(id=profile_id)
                upsert_seed_snapshot(p, hours=6)
        except Exception:
            # on ne bloque pas la création du profil si le seed échoue
            pass

        return response


class PaymentHistoryViewSet(viewsets.ModelViewSet):
    serializer_class = PaymentHistorySerializer

    def get_queryset(self):
        return PaymentHistory.objects.filter(user__id=self.kwargs.get('user_id'))


# ------------------ Auth utils ------------------

class LogoutView(APIView):
    def post(self, request):
        refresh_token = request.data.get("refresh")
        if not refresh_token:
            return Response({"error": "Refresh token is required"}, status=status.HTTP_400_BAD_REQUEST)
        try:
            token = RefreshToken(refresh_token)
            token.blacklist()
            return Response(status=status.HTTP_205_RESET_CONTENT)
        except (TokenError, InvalidToken) as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)


@api_view(['POST'])
@permission_classes([AllowAny])
def request_password_reset(request):
    email = request.data.get('email')
    if not email:
        return Response({'error': 'Email is required'}, status=status.HTTP_400_BAD_REQUEST)

    try:
        user = User.objects.get(email=email)
    except User.DoesNotExist:
        return Response({'error': 'User not found'}, status=status.HTTP_404_NOT_FOUND)

    token = default_token_generator.make_token(user)
    uid = urlsafe_base64_encode(force_bytes(user.pk))
    reset_link = f"{settings.FRONTEND_URL}/reset-password/{uid}/{token}"

    # Build context for template
    context = {
        "user": user,
        "reset_link": reset_link,
        "support_email": "support@yourdomain.com",
        "company_name": "Taurus",  # change to your branding
    }

    subject = "Reset your password"
    html_message = render_to_string("emails/password_reset.html", context)
    plain_message = strip_tags(html_message)

    send_mail(
        subject,
        plain_message,
        settings.DEFAULT_FROM_EMAIL,
        [email],
        html_message=html_message,
        fail_silently=False,
    )
    return Response({'message': 'Password reset link sent'}, status=status.HTTP_200_OK)


@api_view(['POST'])
@permission_classes([AllowAny])
def confirm_password_reset(request):
    uidb64 = request.data.get('uid')
    token = request.data.get('token')
    new_password = request.data.get('new_password')

    if not uidb64 or not token or not new_password:
        return Response({'error': 'All fields are required'}, status=status.HTTP_400_BAD_REQUEST)

    try:
        uid = force_str(urlsafe_base64_decode(uidb64))
        user = User.objects.get(pk=uid)
    except (User.DoesNotExist, ValueError):
        return Response({'error': 'Invalid reset link'}, status=status.HTTP_400_BAD_REQUEST)

    if not default_token_generator.check_token(user, token):
        return Response({'error': 'Invalid or expired token'}, status=status.HTTP_400_BAD_REQUEST)

    user.set_password(new_password)
    user.save()
    return Response({'message': 'Password reset successfully'}, status=status.HTTP_200_OK)


# ------------------ Movies/TV content ------------------

class MovieList(APIView):
    serializer_class = TitleSerializer
    permission_classes = [IsAdminOrReadOnly]

    def get(self, request):
        qs = Title.objects.filter(type="movie").only(
            "id","type","title","poster","landscape_image",
            "release_year","vote_average","popularity"
        ).order_by("-popularity","-vote_average","-id")

        paginator = PageNumberPagination()
        paginator.page_size = int(request.query_params.get("page_size", 40))
        page = paginator.paginate_queryset(qs, request)
        return paginator.get_paginated_response(TitleListSerializer(page, many=True).data)

    def post(self, request):
        data = request.data.copy()
        data["type"] = "movie"
        ser = TitleSerializer(data=data)
        ser.is_valid(raise_exception=True)
        ser.save()
        return Response(ser.data, status=status.HTTP_201_CREATED)


class MovieDetail(APIView):
    serializer_class = TitleSerializer
    permission_classes = [IsAdminOrReadOnly]

    def get(self, request, pk):
        try:
            movie = Title.objects.get(pk=pk, type="movie")
        except Title.DoesNotExist:
            return Response({"error": "Movie not found"}, status=status.HTTP_404_NOT_FOUND)
        return Response(TitleSerializer(movie).data)

    def put(self, request, pk):
        try:
            movie = Title.objects.get(pk=pk, type="movie")
        except Title.DoesNotExist:
            return Response({"error": "Movie not found"}, status=status.HTTP_404_NOT_FOUND)
        ser = TitleSerializer(movie, data=request.data)
        ser.is_valid(raise_exception=True)
        ser.save()
        return Response(ser.data)

    def delete(self, request, pk):
        try:
            movie = Title.objects.get(pk=pk, type="movie")
        except Title.DoesNotExist:
            return Response({"error": "Movie not found"}, status=status.HTTP_404_NOT_FOUND)
        movie.delete()
        return Response({"message": "Movie deleted successfully"}, status=status.HTTP_204_NO_CONTENT)


class TitleViewSet(viewsets.ModelViewSet):
    permission_classes = [IsAdminOrReadOnly]

    def get_queryset(self):
        qs = Title.objects.only(
            "id",
            "type",
            "title",
            "poster",
            "release_year",
            "vote_average",
            "popularity"
        )

        params = self.request.query_params

        # type=movie|tv
        t = params.get("type")
        if t in ("movie", "tv"):
            qs = qs.filter(type=t)

        # query (TVShows.js utilise "query", ton code existant utilisait "q")
        q = (params.get("query") or params.get("q") or "").strip()
        if q:
            qs = qs.filter(
                Q(title__istartswith=q) |
                Q(original_title__istartswith=q) |
                Q(tagline__istartswith=q)
            )

        # genre (texte CSV)
        genre = (params.get("genre") or "").strip()
        if genre:
            g = re.escape(genre.strip())
            # match: début OU ", " + genre, puis fin OU ","
            qs = qs.filter(genre__iregex=rf"(^|,\s*){g}(\s*,|$)")

        # director
        director = (params.get("director") or "").strip()
        if director:
            qs = qs.filter(director__istartswith=director)

        # actor (cast est JSONField list) -> fallback icontains (pas parfait mais fonctionne)
        actor = (params.get("actor") or "").strip()
        if actor:
            a = norm_name(actor)
            # performant (prefix) + utilise ton name_norm indexé
            qs = qs.filter(actors__name_norm__istartswith=a).distinct()

        # ratingMin (sur vote_average)
        rating_min = params.get("ratingMin")
        if rating_min not in (None, "", "null"):
            try:
                qs = qs.filter(vote_average__gte=float(rating_min))
            except ValueError:
                pass

        # yearMin/yearMax:
        # - movie: release_year
        # - tv: on utilise release_year aussi si tu l’as rempli, sinon tu peux filtrer via first_air_date (string)
        year_min = params.get("yearMin")
        if year_min not in (None, "", "null"):
            try:
                ymin = int(year_min)
                qs = qs.filter(release_year__gte=ymin)
            except ValueError:
                pass

        year_max = params.get("yearMax")
        if year_max not in (None, "", "null"):
            try:
                ymax = int(year_max)
                qs = qs.filter(release_year__lte=ymax)
            except ValueError:
                pass

        return qs.order_by("-popularity", "-vote_average", "-id")

        
    def get_serializer_class(self):
        if self.action == "list":
            return TitleListSerializer
        return TitleSerializer
    

    @action(detail=True, methods=["get"])
    @method_decorator(cache_page(60*60))
    def seasons(self, request, pk=None):
        title = self.get_object()
        qs = title.seasons.all().order_by("season_number")
        return Response(SeasonSerializer(qs, many=True, context=self.get_serializer_context()).data)
    @action(detail=False, methods=["get"])
    @method_decorator(cache_page(60*60))
    def genres(self, request):
        # Option 1: genres distincts depuis la DB (si genre est un string "A, B, C")
        qs = Title.objects.all()

        t = request.query_params.get("type")
        if t in ("movie", "tv"):
            qs = qs.filter(type=t)

        genres_set = set()
        for g in qs.values_list("genre", flat=True):
            if not g:
                continue
            parts = [p.strip() for p in str(g).split(",") if p.strip()]
            genres_set.update(parts)

        return Response(sorted(genres_set))

    @action(detail=False, methods=["get"])
    @method_decorator(cache_page(60*60))
    def search(self, request):
        """
        /api/titles/search/?q=bat&type=movie|tv|all&limit=15
        """
        q = (request.query_params.get("q") or "").strip()
        t = (request.query_params.get("type") or "all").strip()
        limit = request.query_params.get("limit") or "15"

        try:
            limit = max(1, min(int(limit), 30))
        except ValueError:
            limit = 15

        if not q:
            return Response([])

        qs = Title.objects.all()

        if t in ("movie", "tv"):
            qs = qs.filter(type=t)

        qs = qs.filter(
            Q(title__istartswith=q) |
            Q(original_title__istartswith=q)
        ).order_by("-popularity", "-vote_average", "-id")[:limit]

        # serializer liste léger (inclut trailer_url si tu l’as ajouté)
        data = TitleListSerializer(qs, many=True, context=self.get_serializer_context()).data
        return Response(data)
    
class SeasonViewSet(viewsets.ModelViewSet):
    serializer_class = SeasonSerializer
    permission_classes = [IsAdminOrReadOnly]

    def get_queryset(self):
        qs = Season.objects.select_related("tv")
        title_id = self.kwargs.get("title_pk")
        if title_id:
            qs = qs.filter(tv_id=title_id)
        number = self.request.query_params.get("number")
        if number and number.isdigit():
            qs = qs.filter(season_number=int(number))
        return qs.order_by("season_number", "id")

    def perform_create(self, serializer):
        title_id = self.kwargs.get("title_pk")
        if title_id:
            tv = get_object_or_404(Title, pk=title_id, type="tv")
            serializer.save(tv=tv)
        else:
            serializer.save()


class EpisodeViewSet(viewsets.ModelViewSet):
    serializer_class = EpisodeSerializer

    def get_queryset(self):
        qs = Episode.objects.select_related('season', 'season__tv')
        season_id = self.kwargs.get('season_pk')  # from nested router
        title_id = self.kwargs.get('title_pk')    # parent nested lookup

        if season_id:
            qs = qs.filter(season_id=season_id)
        if title_id:
            qs = qs.filter(season__tv_id=title_id)

        # optional: allow direct query param fallback for testing
        season_id_qp = self.request.query_params.get('season_id')
        if season_id_qp and not season_id:
            qs = qs.filter(season_id=season_id_qp)

        return qs.order_by('episode_number')


class TVShowExtrasViewSet(viewsets.ModelViewSet):
    serializer_class = TVExtrasSerializer
    permission_classes = [IsAdminOrReadOnly]

    def get_queryset(self):
        qs = TVShowExtras.objects.select_related("title")
        title_id = self.request.query_params.get("title")
        if title_id:
            qs = qs.filter(title_id=title_id)
        return qs.order_by("title_id")


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def titles_by_actor(request):
    """
    GET /api/actors/titles/?tmdb_id=1234
    Returns: { "results": [ ...TitleListSerializer... ] }
    """
    tmdb_id = request.query_params.get("tmdb_id")
    if not tmdb_id:
        return Response({"detail": "tmdb_id is required"}, status=400)

    try:
        tmdb_id_int = int(tmdb_id)
    except (TypeError, ValueError):
        return Response({"detail": "tmdb_id must be an integer"}, status=400)

    # titles linked to this actor (your schema is Actor(title_id, tmdb_id, ...))
    title_ids = (
        Actor.objects
        .filter(tmdb_id=tmdb_id_int)
        .values_list("title_id", flat=True)
        .distinct()
    )

    # Fetch titles and return as list cards
    qs = (
        Title.objects
        .filter(id__in=title_ids)
        .order_by("-popularity", "-vote_average", "-id")
    )

    return Response({"results": TitleListSerializer(qs, many=True).data})