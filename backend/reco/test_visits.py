"""Site visitors: what the app reports (reco/visits.py) and the admin dashboard's Visitors panel."""
import uuid
from datetime import timedelta

from django.conf import settings
from django.core.cache import cache
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import AccessToken

from users.models import User
from .models import PageView, Visitor
from .visits import device_of, route_of

CHROME = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36"
IPHONE = "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 Mobile/15E148"
TIZEN = "Mozilla/5.0 (SMART-TV; LINUX; Tizen 6.0) AppleWebKit/537.36 SamsungBrowser/4.0 TV Safari/537.36"


class VisitTests(TestCase):
    def setUp(self):
        cache.clear()
        self.client = APIClient(HTTP_USER_AGENT=CHROME)
        self.vid = str(uuid.uuid4())

    def visit(self, path="/", kind="view", vid=None, referrer="", **extra):
        return self.client.post("/api/events/visit/", {
            "visitor_id": vid or self.vid, "session_id": "s1", "kind": kind, "path": path, "referrer": referrer,
        }, format="json", **extra)

    def test_a_page_view_without_storing_ids_tokens_or_searches(self):
        self.assertEqual(self.visit("/movies/27205?q=private", referrer="https://www.google.com/search?q=x").status_code, 204)
        self.visit("/reset-password/MjQ/abc-secret-token")
        self.visit("/search")
        v = Visitor.objects.get(pk=self.vid)
        self.assertEqual(v.pageviews, 3)
        self.assertEqual(v.source, "google.com")  # the site, not the address
        self.assertEqual(sorted(PageView.objects.values_list("route", flat=True)),
                         ["/movies/:id", "/reset-password/:id/:id", "/search"])
        self.assertEqual(route_of("/"), "/")
        self.assertEqual(route_of("/l/AbC9xYz"), "/l/:id")

    def test_links_inside_the_site_are_not_a_source(self):
        self.visit("/", referrer="http://testserver/movies/1")
        self.assertEqual(Visitor.objects.get(pk=self.vid).source, "")

    def test_ping_keeps_a_visitor_live_without_a_page_view(self):
        self.visit("/")
        Visitor.objects.filter(pk=self.vid).update(last_seen=timezone.now() - timedelta(minutes=30))
        self.visit("/tv/1396", kind="ping")
        v = Visitor.objects.get(pk=self.vid)
        self.assertGreater(v.last_seen, timezone.now() - timedelta(minutes=1))
        self.assertEqual(v.last_route, "/tv/:id")
        self.assertEqual(PageView.objects.count(), 1)
        self.visit("/", kind="ping", vid=str(uuid.uuid4()))  # unknown visitor: nothing created
        self.assertEqual(Visitor.objects.count(), 1)

    def test_bots_staff_and_bad_ids_are_not_counted(self):
        self.visit("/", HTTP_USER_AGENT="Googlebot/2.1 (+http://www.google.com/bot.html)")
        self.visit("/", HTTP_USER_AGENT="Mozilla/5.0 HeadlessChrome/130.0")
        admin = User.objects.create_superuser("admin@example.com", "Admin", "pw-admin-123!")
        self.visit("/", HTTP_AUTHORIZATION=f"Bearer {AccessToken.for_user(admin)}")
        self.assertEqual(Visitor.objects.count(), 0)
        self.assertEqual(self.visit("/", vid="not-a-uuid").status_code, 400)

    def test_signed_in_or_with_an_expired_token(self):
        user = User.objects.create_user("v@example.com", "V", "pw-v-123456!")
        self.visit("/", HTTP_AUTHORIZATION=f"Bearer {AccessToken.for_user(user)}")
        self.assertEqual(Visitor.objects.get(pk=self.vid).user, user)
        self.assertTrue(PageView.objects.get().signed_in)
        # a broken / expired token: still counted (signed out), never a 401 the app would see
        self.assertEqual(self.visit("/movies", HTTP_AUTHORIZATION="Bearer nonsense").status_code, 204)
        self.assertEqual(PageView.objects.filter(signed_in=False).count(), 1)

    def test_devices(self):
        self.assertEqual(device_of(CHROME), "desktop")
        self.assertEqual(device_of(IPHONE), "mobile")
        self.assertEqual(device_of(TIZEN), "tv")
        self.assertEqual(device_of("Mozilla/5.0 (Linux; Android 13; SM-X200) AppleWebKit/537.36 Safari/537.36"), "tablet")


class VisitorsDashboardTests(TestCase):
    def setUp(self):
        cache.clear()
        self.admin = User.objects.create_superuser("admin@example.com", "Admin", "pw-admin-123!")
        now = timezone.now()
        # a returning visitor (first came 20 days ago), seen today and live; a new one today on a phone
        old = Visitor.objects.create(pk=str(uuid.uuid4()), first_seen=now - timedelta(days=20), last_seen=now,
                                     last_route="/movies/:id", device="desktop")
        new = Visitor.objects.create(pk=str(uuid.uuid4()), first_seen=now, last_seen=now - timedelta(hours=1),
                                     last_route="/", device="mobile", source="google.com")
        for v, route, source in ((old, "/", ""), (old, "/movies/:id", ""), (new, "/", "google.com")):
            PageView.objects.create(visitor=v, route=route, source=source, device=v.device, session_id=v.pk[:8])
        pv = PageView.objects.create(visitor=old, route="/", session_id="older")
        PageView.objects.filter(pk=pv.pk).update(created_at=now - timedelta(days=10))  # the week before

    def test_staff_sees_unique_visitors_and_progress(self):
        self.client.force_login(self.admin)
        res = self.client.get("/" + settings.ADMINADMIN_URL + "dashboard/")
        self.assertEqual(res.status_code, 200)
        v = res.context["visitors"]
        self.assertEqual(v["today"], 2)            # 3 page views today, 2 different visitors
        self.assertEqual(v["u7"], 2)
        self.assertEqual(v["u7_change"], 100)      # 1 visitor the week before
        self.assertEqual(v["views7"], 3)
        self.assertEqual(v["returning7_pct"], 50)  # the old one came before these 7 days
        self.assertEqual(v["direct7"], 1)
        self.assertEqual(v["sources"][0]["source"], "google.com")
        today = v["chart"][-1]
        self.assertEqual((today["n"], today["new"], today["returning"]), (2, 1, 1))
        self.assertEqual(res.context["live"]["live"], 1)  # seen in the last 5 minutes
        self.assertContains(res, "Unique visitors per day")

        live = self.client.get("/" + settings.ADMINADMIN_URL + "dashboard/live/").json()
        self.assertEqual(live["live"], 1)
        self.assertEqual(live["pages"], [{"last_route": "/movies/:id", "n": 1}])

    def test_not_for_visitors_or_members(self):
        member = User.objects.create_user("m@example.com", "M", "pw-m-123456!")
        self.client.force_login(member)
        for url in ("dashboard/", "dashboard/live/"):
            res = self.client.get("/" + settings.ADMINADMIN_URL + url)
            self.assertIn(res.status_code, (302, 403))  # refused: the admin sign-in, or forbidden
