"""
Site visitors: the app tells the server which page it shows (POST /api/events/visit/), the admin
dashboard counts unique visitors, visits, pages, sources and who is on the site right now.

  {"visitor_id": "<uuid>", "session_id": "...", "kind": "view" | "ping", "path": "/movies/42",
   "referrer": "https://www.google.com/..."}

- view: a page was opened (one PageView, the visitor's counters)
- ping: the page is still open (every minute while the tab is visible): keeps the visitor "live"

Private by design: no cookie, no IP address stored, the visitor id is random (frontend
analytics/visits.js), pages are stored as routes ("/movies/:id", never a search or a token),
and the app skips all of it when the browser asks not to be tracked (GPC / Do Not Track).
Not counted: staff accounts (your own visits), and bots / headless browsers.
"""
import datetime as dt
import re
from datetime import timedelta
from urllib.parse import urlsplit

from django.conf import settings
from django.db.models import Count, F
from django.db.models.functions import TruncDate
from django.utils import timezone
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.authentication import JWTAuthentication

from users.throttles import _IPRateThrottle
from .models import PageView, Visitor

VISITOR_ID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
BOT_RE = re.compile(r"bot|crawl|spider|slurp|headless|lighthouse|preview|facebookexternalhit|curl|wget|python-requests", re.I)

# app pages whose next part is an id or a token (App.jsx): stored without it
DYNAMIC = {
    "movies": 1, "tv": 1, "watch": 1, "actor": 1, "lists": 1, "l": 1, "collection": 1, "account": 1,
    "reset-password": 2, "confirm-email-change": 2,
}


class VisitRateThrottle(_IPRateThrottle):
    scope = "visit"


class OptionalJWTAuthentication(JWTAuthentication):
    """Signed in or not: an expired token counts the visit as signed out instead of a 401."""
    def authenticate(self, request):
        try:
            return super().authenticate(request)
        except Exception:  # noqa: BLE001 (any token problem: anonymous)
            return None


def route_of(path: str) -> str:
    """/movies/27205?x=1 -> /movies/:id ; /reset-password/u/t0k3n -> /reset-password/:id/:id"""
    path = (path or "/").split("?")[0].split("#")[0]
    parts = [p for p in path.split("/") if p][:6]
    out = []
    i = 0
    while i < len(parts):
        p = parts[i]
        n = DYNAMIC.get(p.lower()) if not out else None
        if n:
            out.append(p.lower())
            out.extend(":id" for _ in parts[i + 1:i + 1 + n])
            i += 1 + n
            continue
        # anything else that looks like an id (digits, long tokens) is not kept either
        out.append(":id" if re.search(r"\d", p) or len(p) > 32 else p.lower()[:32])
        i += 1
    return ("/" + "/".join(out))[:128]


def device_of(ua: str) -> str:
    ua = ua or ""
    if re.search(r"smart-?tv|tizen|web0?s|hbbtv|appletv|googletv|android tv|\baft[a-z]|bravia|crkey|netcast|viera", ua, re.I):
        return "tv"
    if re.search(r"ipad|tablet|kindle|silk/", ua, re.I) or (re.search(r"android", ua, re.I) and not re.search(r"mobile", ua, re.I)):
        return "tablet"
    if re.search(r"mobi|iphone|ipod|android", ua, re.I):
        return "mobile"
    return "desktop"


def _own_hosts(request) -> set:
    hosts = {request.get_host().split(":")[0].lower()}
    for url in (getattr(settings, "SITE_URL", ""), getattr(settings, "FRONTEND_URL", "")):
        h = (urlsplit(url).hostname or "").lower()
        if h:
            hosts.add(h)
    return hosts | {"www." + h for h in hosts} | {h[4:] for h in hosts if h.startswith("www.")}


def source_of(referrer: str, request) -> str:
    """The other site that sent the visitor ("google.com"), "" for direct / from inside the site."""
    host = (urlsplit(referrer or "").hostname or "").lower()
    if not host or host in _own_hosts(request) or host in ("localhost", "127.0.0.1"):
        return ""
    return (host[4:] if host.startswith("www.") else host)[:128]


class VisitView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = [OptionalJWTAuthentication]
    throttle_classes = [VisitRateThrottle]

    def post(self, request):
        data = request.data if isinstance(request.data, dict) else {}
        vid = str(data.get("visitor_id") or "").lower()
        kind = data.get("kind") or "view"
        if not VISITOR_ID_RE.match(vid) or kind not in ("view", "ping"):
            return Response({"detail": "bad visit"}, status=status.HTTP_400_BAD_REQUEST)

        ua = request.META.get("HTTP_USER_AGENT", "")
        user = request.user if getattr(request.user, "is_authenticated", False) else None
        if not ua or BOT_RE.search(ua) or (user and user.is_staff):
            return Response(status=status.HTTP_204_NO_CONTENT)  # not counted

        now = timezone.now()
        route = route_of(str(data.get("path") or "/"))

        if kind == "ping":
            Visitor.objects.filter(pk=vid).update(last_seen=now, last_route=route)
            return Response(status=status.HTTP_204_NO_CONTENT)

        device = device_of(ua)
        source = source_of(str(data.get("referrer") or ""), request)
        visitor, created = Visitor.objects.get_or_create(
            pk=vid,
            defaults={"first_seen": now, "last_seen": now, "device": device, "source": source},
        )
        updates = {"last_seen": now, "last_route": route, "device": device, "pageviews": F("pageviews") + 1}
        if user:
            updates["user"] = user
        Visitor.objects.filter(pk=visitor.pk).update(**updates)
        PageView.objects.create(
            visitor=visitor, signed_in=bool(user), session_id=str(data.get("session_id") or "")[:64],
            route=route, source=source, device=device,
        )
        return Response(status=status.HTTP_204_NO_CONTENT)


# ---------- numbers for the admin dashboard (users/dashboard.py) ----------
LIVE_MINUTES = 5   # the app pings every minute while its tab is visible
VISITOR_DAYS = 30


def _change(cur, prev):
    """+12 (%) against the period before, None when there was nothing before"""
    return round(100 * (cur - prev) / prev) if prev else None


def _uniques(start, end):
    return PageView.objects.filter(created_at__gte=start, created_at__lt=end).values("visitor").distinct().count()


def live_stats(now):
    """Who is on the site right now (last LIVE_MINUTES), and on which pages."""
    qs = Visitor.objects.filter(last_seen__gte=now - timedelta(minutes=LIVE_MINUTES))
    return {
        "live": qs.count(),
        "signed_in": qs.exclude(user=None).count(),
        "pages": list(qs.values("last_route").annotate(n=Count("pk")).order_by("-n", "last_route")[:8]),
        "devices": list(qs.values("device").annotate(n=Count("pk")).order_by("-n")),
        "minutes": LIVE_MINUTES,
    }


def visitor_stats(now):
    utc = dt.timezone.utc
    midnight = now.astimezone(utc).replace(hour=0, minute=0, second=0, microsecond=0)
    s7, s14, s30, s60 = (now - timedelta(days=d) for d in (7, 14, 30, 60))
    end = now + timedelta(seconds=1)

    week = PageView.objects.filter(created_at__gte=s7)
    u7, u7_prev = _uniques(s7, end), _uniques(s14, s7)
    u30, u30_prev = _uniques(s30, end), _uniques(s60, s30)
    views7, views7_prev = week.count(), PageView.objects.filter(created_at__gte=s14, created_at__lt=s7).count()
    visits7 = week.exclude(session_id="").values("session_id").distinct().count()
    returning7 = week.filter(visitor__first_seen__lt=s7).values("visitor").distinct().count()
    signed7 = week.filter(signed_in=True).values("visitor").distinct().count()

    # per day (UTC: MySQL can't convert time zones without its tz tables): new + returning = unique
    start = (midnight - timedelta(days=VISITOR_DAYS - 1))
    per_day = dict(
        PageView.objects.filter(created_at__gte=start)
        .annotate(day=TruncDate("created_at", tzinfo=utc)).values("day")
        .annotate(n=Count("visitor", distinct=True)).values_list("day", "n")
    )
    new_day = dict(
        Visitor.objects.filter(first_seen__gte=start)
        .annotate(day=TruncDate("first_seen", tzinfo=utc)).values("day")
        .annotate(n=Count("pk")).values_list("day", "n")
    )
    days = [(start + timedelta(days=i)).date() for i in range(VISITOR_DAYS)]
    top = max([per_day.get(d, 0) for d in days] + [1])
    chart = []
    for d in days:
        n = per_day.get(d, 0)
        new = min(new_day.get(d, 0), n)
        chart.append({"day": d, "n": n, "new": new, "returning": n - new,
                      "h_new": round(100 * new / top, 1), "h_ret": round(100 * (n - new) / top, 1)})

    pages = list(week.values("route").annotate(views=Count("pk"), visitors=Count("visitor", distinct=True))
                 .order_by("-visitors", "-views")[:10])
    sources = list(week.exclude(source="").values("source").annotate(visitors=Count("visitor", distinct=True))
                   .order_by("-visitors")[:8])
    from_sites = week.exclude(source="").values("visitor").distinct().count()
    devices = list(week.values("device").annotate(visitors=Count("visitor", distinct=True)).order_by("-visitors"))
    for rows, key in ((pages, "visitors"), (sources, "visitors"), (devices, "visitors")):
        most = max([r[key] for r in rows] + [1])
        for r in rows:
            r["width"] = round(100 * r[key] / most, 1)
            r["pct"] = round(100 * r[key] / u7) if u7 else 0

    return {
        "today": _uniques(midnight, end),
        "u7": u7, "u7_change": _change(u7, u7_prev),
        "u30": u30, "u30_change": _change(u30, u30_prev),
        "views7": views7, "views7_change": _change(views7, views7_prev),
        "visits7": visits7,
        "pages_per_visit": round(views7 / visits7, 1) if visits7 else None,
        "returning7_pct": round(100 * returning7 / u7) if u7 else None,
        "signed7_pct": round(100 * signed7 / u7) if u7 else None,
        "direct7": max(0, u7 - from_sites),
        "chart": chart, "chart_top": top, "chart_days": VISITOR_DAYS,
        "pages": pages, "sources": sources, "devices": devices,
        "total_visitors": Visitor.objects.count(),
        "first_day": Visitor.objects.order_by("first_seen").values_list("first_seen", flat=True).first(),
    }
