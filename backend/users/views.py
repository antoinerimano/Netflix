from rest_framework.decorators import api_view, permission_classes, action, throttle_classes
from rest_framework.response import Response
from rest_framework import viewsets, status
from rest_framework.views import APIView
from rest_framework.pagination import PageNumberPagination
from django.utils.decorators import method_decorator
from django.views.decorators.cache import cache_page
from django.views.decorators.vary import vary_on_headers
import re
from django.db.models import Q
from django.db import models
from django.conf import settings
from django.utils.translation import gettext as _
from django.shortcuts import get_object_or_404
from django.contrib.auth.hashers import make_password, check_password
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.token_blacklist.models import BlacklistedToken, OutstandingToken
from rest_framework_simplejwt.exceptions import TokenError, InvalidToken
from datetime import timedelta
from rest_framework.permissions import SAFE_METHODS, BasePermission, AllowAny, IsAuthenticated
from django.contrib.auth.tokens import default_token_generator
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.utils.http import urlsafe_base64_encode, urlsafe_base64_decode
from django.utils.encoding import force_bytes, force_str
from django.core.signing import TimestampSigner, BadSignature, SignatureExpired
from django.utils import timezone
from urllib.parse import quote


from .models import (
    Actor, User, Subscription, Profile, PaymentHistory,
    Title, Season, Episode, TVShowExtras, Provider
)
from .throttles import AuthRateThrottle, PasswordResetRateThrottle
from .maturity import allowed_titles_q, request_profile
from .emails import send_templated_email
from .search import search_titles
from .i18n import current_language
from .localize import title_names
from .serializers import (
    UserSerializer, SubscriptionSerializer,
    ProfileSerializer, PaymentHistorySerializer, TitleSerializer,
    EpisodeSerializer, SeasonSerializer, TVExtrasSerializer, TitleListSerializer
)

signer = TimestampSigner()


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
    throttle_classes = [AuthRateThrottle]
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


class IsOwnerOrAdmin(BasePermission):
    """For /api/users/<user_id>/... nested routes: only that user (or staff)."""
    def has_permission(self, request, view):
        user = request.user
        if not (user and user.is_authenticated):
            return False
        if user.is_staff:
            return True
        return str(view.kwargs.get('user_id')) == str(user.id)


# ------------------ Users ------------------

class UserViewSet(viewsets.ModelViewSet):
    queryset = User.objects.all()
    serializer_class = UserSerializer
    lookup_field = 'id'
    permission_classes = [IsAuthenticated, IsSelfOrAdmin]

    def get_queryset(self):
        # non-staff users can only see / act on their own account
        qs = User.objects.order_by("created_at")
        if not self.request.user.is_staff:
            qs = qs.filter(id=self.request.user.id)
        return qs

    @action(detail=False, methods=['post'], permission_classes=[AllowAny],
            throttle_classes=[AuthRateThrottle], url_path='register')
    def register(self, request):
        data = request.data.copy()
        email = data.get('email')
        password = data.get('password')

        if not email:
            return Response({'error': _('Email is required.'), 'code': 'email_required'}, status=status.HTTP_400_BAD_REQUEST)
        if not password:
            return Response({'error': _('Password is required.'), 'code': 'password_required'}, status=status.HTTP_400_BAD_REQUEST)
        if User.objects.filter(email=email).exists():
            return Response({'error': _('This email is already registered.'), 'code': 'email_taken'}, status=status.HTTP_400_BAD_REQUEST)
        # same rules as a password reset (settings.AUTH_PASSWORD_VALIDATORS)
        try:
            validate_password(password, User(email=email))
        except ValidationError as e:
            # Django's validators answer in the request's language already
            return Response({'error': ' '.join(e.messages), 'code': 'password_invalid'}, status=status.HTTP_400_BAD_REQUEST)

        serializer = self.get_serializer(data=data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save(password=make_password(password))
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
            return Response({'error': _('You already have an active %(plan)s subscription.') % {'plan': plan_type}},
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
            # amount/currency are fixed server-side: never trust the client for billing data
            PaymentHistory.objects.create(
                id=str(uuid4()),
                user=user,
                date=timezone.now(),
                amount=settings.PREMIUM_PRICE,
                currency=settings.PREMIUM_CURRENCY,
                plan_type='Premium',
                transaction_id=f'LOCAL-{uuid4()}',
                status='Succeeded'
            )

        return Response(
            {'message': _('%(plan)s subscription created!') % {'plan': plan_type}, 'subscription_id': sub.id},
            status=status.HTTP_201_CREATED
        )

    @action(detail=False, methods=['post'], permission_classes=[AllowAny],
            throttle_classes=[AuthRateThrottle], url_path='login')
    def login(self, request):
        email = request.data.get('email')
        password = request.data.get('password')

        # same answer for unknown email, wrong password or disabled account,
        # so the endpoint can't be used to find out who has an account
        user = User.objects.filter(email=email).first()
        if not user or not user.is_active or not check_password(password, user.password):
            return Response({"error": _("Invalid credentials."), "code": "invalid_credentials"}, status=status.HTTP_400_BAD_REQUEST)

        user.last_login = timezone.now()
        user.save(update_fields=["last_login"])    

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
            return Response({"error": _("New email is required."), "code": "email_required"}, status=status.HTTP_400_BAD_REQUEST)

        if User.objects.filter(email=new_email).exists():
            return Response({"error": _("This email is already in use."), "code": "email_taken"}, status=status.HTTP_400_BAD_REQUEST)

        # Generate a signed token link
       
        raw_token = signer.sign(new_email)
        token = quote(raw_token, safe="")
        confirm_url = f"{settings.FRONTEND_URL}/confirm-email-change/{user.id}/{token}"

        send_templated_email(
            _("Confirm your new email address"),
            "email_change",
            {"user": user, "new_email": new_email, "confirm_url": confirm_url},
            [new_email],
        )

        return Response({"message": _("Confirmation email sent.")}, status=status.HTTP_200_OK)

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
            return Response({"error": _("This confirmation link is incomplete."), "code": "invalid_link"}, status=status.HTTP_400_BAD_REQUEST)

        try:
            new_email = signer.unsign(token, max_age=60*60*24)  # 24h validity
        except SignatureExpired:
            return Response({"error": _("This confirmation link has expired."), "code": "link_expired"}, status=status.HTTP_400_BAD_REQUEST)
        except BadSignature:
            return Response({"error": _("This confirmation link is not valid."), "code": "invalid_link"}, status=status.HTTP_400_BAD_REQUEST)

        # prevent collisions
        if User.objects.filter(email=new_email).exclude(id=user.id).exists():
            return Response({"error": _("This email is already in use."), "code": "email_taken"}, status=status.HTTP_400_BAD_REQUEST)

        user.email = new_email
        user.save(update_fields=["email"])
        return Response({"message": _("Email updated.")}, status=status.HTTP_200_OK)    


# ------------------ Subscriptions ------------------

class SubscriptionViewSet(viewsets.ModelViewSet):
    serializer_class = SubscriptionSerializer
    permission_classes = [IsOwnerOrAdmin]
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
            return Response({"error": _("This subscription is already canceled.")}, status=400)
        sub.status = 'Canceled'
        sub.renewal_date = timezone.now()
        sub.save()
        return Response(UserSerializer(sub.user, context={'request': request}).data, status=status.HTTP_200_OK)


# ------------------ Profiles & Payments history ------------------
import logging
logger = logging.getLogger(__name__)

class ProfileViewSet(viewsets.ModelViewSet):
    serializer_class = ProfileSerializer
    permission_classes = [IsOwnerOrAdmin]

    def get_queryset(self):
        return Profile.objects.filter(user__id=self.kwargs.get('user_id'))

    def perform_create(self, serializer):
        # owner comes from the URL, not from the request body
        serializer.save(user_id=self.kwargs.get('user_id'))

    def perform_update(self, serializer):
        before = (serializer.instance.is_kids, serializer.instance.age_restriction)
        profile = serializer.save()
        if (profile.is_kids, profile.age_restriction) != before:
            # age limit changed: the home page built for the old limit would be mostly filtered out,
            # so give it a starter page built for the new one until the snapshot cron runs
            try:
                from reco.views import upsert_seed_snapshot
                upsert_seed_snapshot(profile, hours=24)
            except Exception:
                logger.exception("[seed] rebuild after age limit change failed for profile_id=%s", profile.id)

    def create(self, request, *args, **kwargs):
        response = super().create(request, *args, **kwargs)

        profile_id = response.data.get("id")
        if profile_id:
            try:
                from reco.views import upsert_seed_snapshot  # ou reco.seed, mais il faut que ça match ton vrai fichier
                p = Profile.objects.get(id=profile_id)
                upsert_seed_snapshot(p, hours=24*365*10)
                logger.info("[seed] snapshot created for profile_id=%s", profile_id)
            except Exception as e:
                logger.exception("[seed] FAILED for profile_id=%s error=%s", profile_id, e)

        return response


class PaymentHistoryViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = PaymentHistorySerializer
    permission_classes = [IsOwnerOrAdmin]

    def get_queryset(self):
        return PaymentHistory.objects.filter(user__id=self.kwargs.get('user_id')).order_by("-date")


# ------------------ Auth utils ------------------

class LogoutView(APIView):
    # only needs the refresh token; must work even if the access token expired
    permission_classes = [AllowAny]

    def post(self, request):
        refresh_token = request.data.get("refresh")
        if not refresh_token:
            return Response({"error": _("Refresh token is required.")}, status=status.HTTP_400_BAD_REQUEST)
        try:
            token = RefreshToken(refresh_token)
            token.blacklist()
            return Response(status=status.HTTP_205_RESET_CONTENT)
        except (TokenError, InvalidToken) as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)


@api_view(['POST'])
@permission_classes([AllowAny])
@throttle_classes([PasswordResetRateThrottle])
def request_password_reset(request):
    email = request.data.get('email')
    if not email:
        return Response({'error': _('Email is required.'), 'code': 'email_required'}, status=status.HTTP_400_BAD_REQUEST)

    # always answer the same way so the endpoint doesn't reveal which emails exist
    sent_response = Response(
        {'message': _('If an account exists for this email, a reset link has been sent.')},
        status=status.HTTP_200_OK,
    )
    user = User.objects.filter(email=email, is_active=True).first()
    if not user:
        return sent_response

    token = default_token_generator.make_token(user)
    uid = urlsafe_base64_encode(force_bytes(user.pk))
    reset_link = f"{settings.FRONTEND_URL}/reset-password/{uid}/{token}"

    send_templated_email(_("Reset your password"), "password_reset", {"user": user, "reset_link": reset_link}, [email])
    return sent_response


@api_view(['POST'])
@permission_classes([AllowAny])
@throttle_classes([PasswordResetRateThrottle])
def confirm_password_reset(request):
    uidb64 = request.data.get('uid')
    token = request.data.get('token')
    new_password = request.data.get('new_password')

    if not uidb64 or not token or not new_password:
        return Response({'error': _('All fields are required.')}, status=status.HTTP_400_BAD_REQUEST)

    try:
        uid = force_str(urlsafe_base64_decode(uidb64))
        user = User.objects.get(pk=uid)
    except (User.DoesNotExist, ValueError):
        return Response({'error': _('This reset link is not valid.'), 'code': 'invalid_link'}, status=status.HTTP_400_BAD_REQUEST)

    if not default_token_generator.check_token(user, token):
        return Response({'error': _('This reset link has expired or was already used.'), 'code': 'invalid_link'}, status=status.HTTP_400_BAD_REQUEST)

    try:
        validate_password(new_password, user)
    except ValidationError as e:
        return Response({'error': ' '.join(e.messages), 'code': 'password_invalid'}, status=status.HTTP_400_BAD_REQUEST)

    user.set_password(new_password)
    user.save()
    return Response({'message': _('Your password has been changed.')}, status=status.HTTP_200_OK)


# ------------------ Movies/TV content ------------------

class TitleViewSet(viewsets.ModelViewSet):
    permission_classes = [IsAdminOrReadOnly]

    def get_queryset(self):
        if self.action == "list":
            # load exactly what the list serializer outputs (a missing field = 1 query per row)
            qs = Title.objects.only(*TitleListSerializer.Meta.fields)
        else:
            # detail serializer outputs every field + seasons/episodes/actors:
            # load them up front instead of one query per deferred field / season
            qs = Title.objects.select_related("tv_extras").prefetch_related("seasons__episodes", "actors")

        # age rating of the active profile (Kids profile / age limit)
        qs = qs.filter(allowed_titles_q(request_profile(self.request)))

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

        # yearMin / yearMax: release_year; shows rarely have it (186 of 18,636 matched "2020 or
        # later"), so for them fall back to first_air_date ("yyyy-mm-dd" strings compare in order)
        def year_q(op, year):
            q = Q(**{f"release_year__{op}": year})
            bound = f"{year}-01-01" if op == "gte" else f"{year}-12-31"
            return q | Q(release_year__isnull=True, **{f"first_air_date__{op}": bound}) & ~Q(first_air_date="")

        for key, op in (("yearMin", "gte"), ("yearMax", "lte")):
            value = params.get(key)
            if value in (None, "", "null"):
                continue
            try:
                qs = qs.filter(year_q(op, int(value)))
            except ValueError:
                pass

        # sort: popular (default) | rating | newest | title
        sort = params.get("sort") or "popular"
        if sort == "rating":
            # enough votes for the average to mean something
            return qs.filter(vote_count__gte=1000).order_by("-vote_average", "-popularity", "-id")
        if sort == "newest":
            today = timezone.now().date().isoformat()
            if t == "tv":
                return qs.exclude(first_air_date="").filter(first_air_date__lte=today).order_by("-first_air_date", "-id")
            return qs.exclude(release_date="").filter(release_date__lte=today).order_by("-release_date", "-id")
        if sort == "title":
            return qs.exclude(title__regex=r"^\W*$").order_by("title", "id")  # no blank / symbol-only titles

        return qs.order_by("-popularity", "-vote_average", "-id")

        
    def get_serializer_class(self):
        if self.action == "list":
            return TitleListSerializer
        return TitleSerializer
    

    @action(detail=True, methods=["get"])
    @method_decorator(cache_page(60*60))
    @method_decorator(vary_on_headers("X-Profile-Id"))  # kids and adults get different answers
    def seasons(self, request, pk=None):
        title = self.get_object()
        qs = title.seasons.all().order_by("season_number")
        return Response(SeasonSerializer(qs, many=True, context=self.get_serializer_context()).data)
    @action(detail=True, methods=["get"])
    @method_decorator(cache_page(60*60))
    @method_decorator(vary_on_headers("X-Profile-Id"))  # kids and adults get different answers
    def similar(self, request, pk=None):
        """'More like this' on detail pages: nearest titles by embedding (reco.TitleSimilar,
        built by build_embeddings), best first, within the active profile's age limit."""
        from reco.models import TitleSimilar  # reco depends on users: import here
        from reco.views import MODEL_NAME

        try:
            limit = max(1, min(int(request.query_params.get("limit", 18)), 30))
        except ValueError:
            limit = 18
        ids = list(
            TitleSimilar.objects.filter(title_id=pk, model_name=MODEL_NAME)
            .order_by("-score")
            .values_list("similar_id", flat=True)[: limit * 3]  # room for the age filter
        )
        titles = (
            Title.objects.only(*TitleListSerializer.Meta.fields)
            .filter(id__in=ids)
            .exclude(id=pk)
            .filter(allowed_titles_q(request_profile(request)))
        )
        rank = {tid: i for i, tid in enumerate(ids)}
        ordered = sorted(titles, key=lambda t: rank.get(t.id, len(rank)))[:limit]
        return Response(TitleListSerializer(ordered, many=True, context=self.get_serializer_context()).data)

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
    @method_decorator(vary_on_headers("X-Profile-Id"))  # kids and adults get different answers
    def search(self, request):
        """
        /api/titles/search/?q=bat&type=movie|tv|all&limit=15
        Titles, actors, directors, keywords, typos and queries like "90s crime shows like CSI"
        (users/search.py). Each result has "match": why it was found ("" for a plain title match).
        """
        q = (request.query_params.get("q") or "").strip()
        t = (request.query_params.get("type") or "all").strip()
        limit = request.query_params.get("limit") or "15"

        try:
            limit = max(1, min(int(limit), 60))  # 60: the search results page; the navbar asks 15
        except ValueError:
            limit = 15

        if not q:
            return Response([])

        lang = current_language()
        results = search_titles(q, profile=request_profile(request), kind=t, limit=limit, language=lang)
        titles = [title for title, _r, _k in results]
        data = TitleListSerializer(titles, many=True, context=self.get_serializer_context()).data
        # "match": English sentence (older clients); "match_key": the reason as data, worded by the
        # app in its language. A title named in it ("like X") in the request's language.
        named = {k["title_id"] for _t, _r, k in results if k and k.get("title_id")}
        names = title_names(named, lang)
        out = []
        for item, (_t, reason, key) in zip(data, results):
            if key and key.get("title_id") in names:
                key = {**key, "title": names[key["title_id"]]}
            out.append({**item, "match": reason, "match_key": key})
        return Response(out)
    
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
    permission_classes = [IsAdminOrReadOnly]

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


UNKNOWN_SUCCESS_RATE = 0.5  # providers without enough data rank like an average one


@api_view(["GET"])
@permission_classes([AllowAny])
def provider_list(request):
    """
    GET /api/providers/
    Enabled stream providers; the client builds links as domain + path template
    ({tmdb_id} {imdb_id} {season} {episode}). Order: down last, then success rate (smart playback),
    then admin priority.
    """
    from reco.views import provider_success_rates

    rates = provider_success_rates()
    providers = list(Provider.objects.filter(enabled=True).values(
        "key", "label", "domain", "movie_path", "episode_path", "start_param", "sends_events", "status", "priority"
    ))
    for p in providers:
        p["success_rate"] = rates.get(p["key"])  # None until enough plays were recorded
    # down last, then the ones that play most often for everyone, then the admin priority
    data = sorted(providers, key=lambda p: (
        p["status"] == Provider.DOWN,
        -(p["success_rate"] if p["success_rate"] is not None else UNKNOWN_SUCCESS_RATE),
        p.pop("priority"),
    ))
    response = Response(data)
    response["Cache-Control"] = "public, max-age=60"
    return response


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

    # one Actor row per title the person is in (name, photo, character there)
    rows = list(
        Actor.objects.filter(tmdb_id=tmdb_id_int).values("title_id", "name", "profile_path", "character")
    )
    title_ids = {r["title_id"] for r in rows}
    roles = {r["title_id"]: r["character"] for r in rows if r["character"]}
    # the actor page header: the most common spelling of the name, any photo
    names = [r["name"] for r in rows if r["name"]]
    person = {
        "tmdb_id": tmdb_id_int,
        "name": max(set(names), key=names.count) if names else "",
        "profile_path": next((r["profile_path"] for r in rows if r["profile_path"]), None),
    }

    # Fetch titles and return as list cards
    qs = (
        Title.objects
        .filter(id__in=title_ids)
        .filter(allowed_titles_q(request_profile(request)))
        .order_by("-popularity", "-vote_average", "-id")
    )

    results = TitleListSerializer(qs, many=True).data
    for item in results:
        item["character"] = roles.get(item["id"], "")
    return Response({"actor": person, "results": results})


class ActorListView(APIView):
    """
    GET /api/actors/
    Returns paginated list of unique actors (by tmdb_id).
    Public read access.
    """
    permission_classes = [IsAdminOrReadOnly]

    def get(self, request):
        tmdb_ids = (
            Actor.objects
            .filter(tmdb_id__isnull=False)
            .values_list('tmdb_id', flat=True)
            .distinct()
            .order_by('tmdb_id')
        )
        paginator = PageNumberPagination()
        paginator.page_size = int(request.query_params.get("page_size", 200))
        page = paginator.paginate_queryset(list(tmdb_ids), request)
        data = [{"tmdb_id": tid} for tid in page]
        return paginator.get_paginated_response(data)    