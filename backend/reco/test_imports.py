"""History import (reco/imports.py): Letterboxd / IMDb files, what becomes what."""
import io
import zipfile
from datetime import datetime, timezone as dt_timezone
from unittest import mock

from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from rest_framework.test import APIClient

from users.models import Profile, Title, User
from .models import MyListItem, RecoHomeSnapshot, TitleAction, TitleRating

LETTERBOXD_RATINGS = (
    "Date,Name,Year,Letterboxd URI,Rating\n"
    "2021-03-04,The Godfather,1972,https://boxd.it/a,5\n"     # 10/10 -> like
    "2022-05-06,Heat,1995,https://boxd.it/b,1.5\n"             # 3/10 -> dislike
    "2023-01-02,Inception,2010,https://boxd.it/c,3\n"          # 6/10 -> watched only
    "2023-01-03,Not A Real Film,1999,https://boxd.it/d,4\n"    # not in the catalog
)
LETTERBOXD_WATCHLIST = "Date,Name,Year,Letterboxd URI\n2024-02-02,Amélie,2001,https://boxd.it/e\n"
LETTERBOXD_HEARTS = "Date,Name,Year,Letterboxd URI\n2020-01-01,Toy Story,1995,https://boxd.it/f\n"
IMDB_RATINGS = (
    "Const,Your Rating,Date Rated,Title,Original Title,URL,Title Type,IMDb Rating,Runtime (mins),Year\n"
    "tt0068646,9,2019-07-08,The Godfather,The Godfather,u,Movie,9.2,175,1972\n"
    "tt0903747,8,2020-08-09,Breaking Bad,Breaking Bad,u,TV Series,9.5,49,2008\n"
    "tt0959621,10,2020-08-10,Pilot,Pilot,u,TV Episode,9,58,2008\n"  # episodes are skipped
)


def upload(name, text):
    return SimpleUploadedFile(name, text.encode("utf-8"), content_type="text/csv")


class ImportTestCase(TestCase):
    def setUp(self):
        cache.clear()
        self.client = APIClient()
        self.user = User.objects.create_user("alice@example.com", "Alice", "pw-alice-123!")
        self.other = User.objects.create_user("bob@example.com", "Bob", "pw-bob-123!")
        self.profile = Profile.objects.create(user=self.user, name="A", age_restriction="NC-17", language_preference="en")
        self.bob_profile = Profile.objects.create(user=self.other, name="B", age_restriction="NC-17", language_preference="en")
        self.client.force_authenticate(self.user)

        def mk(title, year, kind="movie", **kw):
            return Title.objects.create(type=kind, title=title, release_year=year, popularity=50, vote_count=1000, **kw)

        self.godfather = mk("The Godfather", 1972, imdb_code="tt0068646", tmdb_id=238)
        self.godfather_remake = mk("The Godfather", 1990)  # same name, other year: not picked
        self.heat = mk("Heat", 1995, tmdb_id=949)
        self.inception = mk("Inception", 2010)
        self.amelie = mk("Le Fabuleux Destin d'Amélie Poulain", 2001, original_title="Amélie")
        self.toy = mk("Toy Story", 1995)
        self.bb = mk("Breaking Bad", 2008, kind="tv", imdb_code="tt0903747", tmdb_id=1396)

    def post_files(self, *files, profile=None):
        profile = profile or self.profile
        return self.client.post(f"/api/import/files/?profileId={profile.id}", {"files": list(files)}, format="multipart")

    def liked(self):
        return set(TitleRating.objects.filter(profile=self.profile, value=TitleRating.LIKE).values_list("title_id", flat=True))

    def watched(self):
        return set(TitleAction.objects.filter(profile=self.profile, action="watched").values_list("title_id", flat=True))


class FileImportTests(ImportTestCase):
    def test_letterboxd_files_become_likes_dislikes_watched_and_my_list(self):
        # the rebuilt home page (the test catalog has no similarity data to build a real one)
        rebuilt = {"rows": [{"row_type": "for_you", "title": "For you", "items": [{"id": self.godfather_remake.id}]}]}
        with mock.patch("reco.views.build_home_payload_exact", return_value=rebuilt):
            res = self.post_files(
                upload("ratings.csv", LETTERBOXD_RATINGS), upload("watchlist.csv", LETTERBOXD_WATCHLIST),
                upload("films.csv", LETTERBOXD_HEARTS),
            )
        self.assertEqual(res.status_code, 200, res.data)
        self.assertEqual(res.data["sources"], ["letterboxd"])
        self.assertEqual(self.liked(), {self.godfather.id, self.toy.id})  # 5 stars, and a heart
        self.assertTrue(TitleRating.objects.filter(profile=self.profile, title=self.heat, value=TitleRating.DISLIKE).exists())
        self.assertFalse(TitleRating.objects.filter(title=self.godfather_remake).exists())  # matched by year
        self.assertEqual(self.watched(), {self.godfather.id, self.heat.id, self.inception.id, self.toy.id})
        self.assertEqual(list(MyListItem.objects.filter(profile=self.profile).values_list("title_id", flat=True)), [self.amelie.id])
        self.assertEqual(res.data["not_found"], 1)
        self.assertEqual(res.data["not_found_examples"], ["Not A Real Film (1999)"])
        self.assertEqual((res.data["liked"], res.data["disliked"], res.data["watched"], res.data["listed"]), (2, 1, 4, 1))
        self.assertEqual(res.data["home"], "rebuilt")
        self.assertTrue(RecoHomeSnapshot.objects.filter(profile=self.profile, algo_version="home_v1").exists())

    def test_dates_are_kept(self):
        self.post_files(upload("ratings.csv", LETTERBOXD_RATINGS))
        rating = TitleRating.objects.get(profile=self.profile, title=self.godfather)
        self.assertEqual(rating.updated_at, datetime(2021, 3, 4, tzinfo=dt_timezone.utc))
        action = TitleAction.objects.get(profile=self.profile, title=self.inception, action="watched")
        self.assertEqual(action.created_at, datetime(2023, 1, 2, tzinfo=dt_timezone.utc))

    def test_letterboxd_zip_export(self):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("ratings.csv", LETTERBOXD_RATINGS)
            zf.writestr("watchlist.csv", LETTERBOXD_WATCHLIST)
            zf.writestr("likes/films.csv", LETTERBOXD_HEARTS)
            zf.writestr("deleted/ratings.csv", "Date,Name,Year,Letterboxd URI,Rating\n2020-01-01,Inception,2010,x,5\n")
            zf.writestr("profile.csv", "Username,Given Name\nalice,Alice\n")
        res = self.post_files(SimpleUploadedFile("letterboxd-alice.zip", buf.getvalue(), content_type="application/zip"))
        self.assertEqual(res.status_code, 200, res.data)
        self.assertEqual(self.liked(), {self.godfather.id, self.toy.id})  # deleted/ is ignored (Inception stays 6/10)
        self.assertTrue(MyListItem.objects.filter(profile=self.profile, title=self.amelie).exists())

    def test_imdb_ratings_match_by_imdb_id_and_skip_episodes(self):
        res = self.post_files(upload("ratings.csv", IMDB_RATINGS))
        self.assertEqual(res.status_code, 200, res.data)
        self.assertEqual(res.data["sources"], ["imdb"])
        self.assertEqual(self.liked(), {self.godfather.id, self.bb.id})
        self.assertEqual(res.data["not_found"], 0)

    def test_what_the_profile_did_here_wins(self):
        TitleRating.objects.create(profile=self.profile, title=self.heat, value=TitleRating.LIKE)
        MyListItem.objects.create(profile=self.profile, title=self.amelie)
        self.post_files(upload("ratings.csv", LETTERBOXD_RATINGS), upload("watchlist.csv", LETTERBOXD_WATCHLIST))
        self.assertEqual(TitleRating.objects.get(profile=self.profile, title=self.heat).value, TitleRating.LIKE)
        self.assertEqual(MyListItem.objects.filter(profile=self.profile).count(), 1)

    def test_importing_twice_adds_nothing_twice(self):
        self.post_files(upload("ratings.csv", LETTERBOXD_RATINGS))
        res = self.post_files(upload("ratings.csv", LETTERBOXD_RATINGS))
        self.assertEqual((res.data["liked"], res.data["disliked"], res.data["watched"]), (0, 0, 0))
        self.assertEqual(len(self.watched()), 3)  # Godfather, Heat, Inception: once each
        self.assertEqual(res.data["home"], "unchanged")

    def test_unknown_or_missing_files_are_refused(self):
        self.assertEqual(self.post_files().status_code, 400)
        res = self.post_files(upload("notes.csv", "a,b\n1,2\n"))
        self.assertEqual(res.status_code, 400)
        self.assertEqual(res.data["code"], "unknown_format")

    def test_other_users_profile_is_refused(self):
        res = self.post_files(upload("ratings.csv", LETTERBOXD_RATINGS), profile=self.bob_profile)
        self.assertEqual(res.status_code, 404)
        self.assertFalse(TitleRating.objects.exists())

