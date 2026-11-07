"""Lists a profile makes, and sharing them (reco/lists.py, users/seo.py list_page)."""
import tempfile
from pathlib import Path
from unittest import mock

from django.core.cache import cache
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from users.models import Profile, Title, User
from .models import UserList, UserListItem


class ListTests(TestCase):
    def setUp(self):
        cache.clear()
        self.client = APIClient()
        self.user = User.objects.create_user("alice@example.com", "Alice", "pw-alice-123!")
        self.other = User.objects.create_user("bob@example.com", "Bob", "pw-bob-123!")
        self.profile = Profile.objects.create(user=self.user, name="Sam", age_restriction="NC-17", language_preference="en")
        self.kid = Profile.objects.create(user=self.user, name="K", age_restriction="PG", is_kids=True, language_preference="en")
        self.bob = Profile.objects.create(user=self.other, name="Bob", age_restriction="NC-17", language_preference="en")
        self.client.force_authenticate(self.user)
        self.heat = Title.objects.create(type="movie", title="Heat", poster="https://img/heat.jpg", maturity=3)
        self.toy = Title.objects.create(type="movie", title="Toy Story", poster="https://img/toy.jpg", maturity=0)
        self.show = Title.objects.create(type="tv", title="Night Shift", maturity=1)

    def url(self, path, profile=None):
        return f"/api/{path}?profileId={(profile or self.profile).id}"

    def create(self, name="Heist night", **extra):
        return self.client.post(self.url("lists/"), {"name": name, **extra}, format="json")

    def test_create_list_add_remove_and_read(self):
        res = self.create("  Heist   night ", description="Big scores", title_id=self.heat.id)
        self.assertEqual(res.status_code, 201)
        lid = res.data["id"]
        self.assertEqual((res.data["name"], res.data["is_public"], len(res.data["share_id"])), ("Heist night", False, 10))
        self.client.put(self.url(f"lists/{lid}/items/{self.toy.id}/"))
        self.client.put(self.url(f"lists/{lid}/items/{self.toy.id}/"))  # twice: once
        d = self.client.get(self.url(f"lists/{lid}/")).data
        self.assertEqual([i["title"]["title"] for i in d["items"]], ["Heat", "Toy Story"])  # added order
        self.assertEqual((d["count"], d["covers"]), (2, ["https://img/heat.jpg", "https://img/toy.jpg"]))
        self.client.delete(self.url(f"lists/{lid}/items/{self.heat.id}/"))
        self.assertEqual(self.client.get(self.url(f"lists/{lid}/")).data["count"], 1)

    def test_lists_say_which_contain_a_title(self):
        a = self.create("A", title_id=self.heat.id).data["id"]
        self.create("B")
        lists = self.client.get(self.url("lists/") + f"&titleId={self.heat.id}").data["lists"]
        self.assertEqual({l["name"]: l["contains"] for l in lists}, {"A": True, "B": False})
        self.assertEqual(next(l for l in lists if l["id"] == a)["count"], 1)

    def test_rename_describe_delete_and_bad_names(self):
        lid = self.create().data["id"]
        res = self.client.patch(self.url(f"lists/{lid}/"), {"name": "Heists", "description": "x" * 400}, format="json")
        self.assertEqual((res.data["name"], len(res.data["description"])), ("Heists", 300))
        self.assertEqual(self.client.patch(self.url(f"lists/{lid}/"), {"name": "  "}, format="json").status_code, 400)
        self.assertEqual(self.create("").status_code, 400)
        self.assertEqual(self.client.delete(self.url(f"lists/{lid}/")).status_code, 204)
        self.assertFalse(UserList.objects.exists())

    def test_limits(self):
        with mock.patch("reco.lists.MAX_LISTS", 2):
            self.create("1")
            self.create("2")
            self.assertEqual(self.create("3").data["code"], "too_many")
        lid = UserList.objects.first().id
        with mock.patch("reco.lists.MAX_ITEMS", 1):
            self.client.put(self.url(f"lists/{lid}/items/{self.heat.id}/"))
            self.assertEqual(self.client.put(self.url(f"lists/{lid}/items/{self.toy.id}/")).data["code"], "too_many")

    def test_private_until_shared_then_anyone_can_read_it(self):
        lid = self.create(title_id=self.heat.id).data["id"]
        share = UserList.objects.get(id=lid).share_id
        anon = APIClient()
        self.assertEqual(anon.get(f"/api/public-lists/{share}/").status_code, 404)
        self.client.patch(self.url(f"lists/{lid}/"), {"is_public": True}, format="json")
        res = anon.get(f"/api/public-lists/{share}/")
        self.assertEqual(res.status_code, 200)
        self.assertEqual((res.data["name"], res.data["owner"], res.data["count"]), ("Heist night", "Sam", 1))
        self.assertEqual(res.data["items"][0]["title"]["title"], "Heat")

    def test_save_a_copy(self):
        lid = self.create(title_id=self.heat.id).data["id"]
        self.client.put(self.url(f"lists/{lid}/items/{self.toy.id}/"))
        self.client.patch(self.url(f"lists/{lid}/"), {"is_public": True}, format="json")
        share = UserList.objects.get(id=lid).share_id
        self.client.force_authenticate(self.other)
        res = self.client.post(self.url(f"public-lists/{share}/copy/", self.bob))
        self.assertEqual(res.status_code, 201)
        copy = UserList.objects.get(id=res.data["id"])
        self.assertEqual((copy.profile, copy.is_public, copy.name), (self.bob, False, "Heist night"))
        self.assertEqual(list(copy.items.order_by("id").values_list("title__title", flat=True)), ["Heat", "Toy Story"])

    def test_other_accounts_and_kids(self):
        lid = self.create(title_id=self.heat.id).data["id"]
        self.client.put(self.url(f"lists/{lid}/items/{self.toy.id}/"))
        UserList.objects.filter(id=lid).update(profile=self.kid)
        # the kid's view of its own list follows its age limit
        d = self.client.get(self.url(f"lists/{lid}/", self.kid)).data
        self.assertEqual([i["title"]["title"] for i in d["items"]], ["Toy Story"])
        self.client.force_authenticate(self.other)
        self.assertEqual(self.client.get(self.url(f"lists/{lid}/", self.bob)).status_code, 404)
        self.assertEqual(self.client.put(self.url(f"lists/{lid}/items/{self.show.id}/", self.bob)).status_code, 404)
        self.assertEqual(self.client.get(self.url(f"lists/{lid}/", self.kid)).status_code, 404)  # not Bob's profile
        self.assertEqual(UserListItem.objects.count(), 2)

    def test_shared_list_page_for_search_engines_and_previews(self):
        lid = self.create(title_id=self.heat.id).data["id"]
        share = UserList.objects.get(id=lid).share_id
        with tempfile.TemporaryDirectory() as d:
            index = Path(d) / "index.html"
            index.write_text("<!DOCTYPE html><html><head><title>x</title></head><body></body></html>", encoding="utf-8")
            with override_settings(FRONTEND_INDEX_FILE=str(index), SITE_URL="https://tauruss.top"):
                self.assertEqual(self.client.get(f"/l/{share}").status_code, 404)  # private: nothing to show
                UserList.objects.filter(id=lid).update(is_public=True)
                res = self.client.get(f"/l/{share}")
        self.assertEqual(res.status_code, 200)
        page = res.content.decode()
        self.assertIn("<title>Heist night | Tauruss</title>", page)
        self.assertIn("Sam: Heat", page)
        self.assertIn("https://img/heat.jpg", page)
        self.assertIn('"@type": "ItemList"', page)
