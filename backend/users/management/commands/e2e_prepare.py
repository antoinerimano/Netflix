# users/management/commands/e2e_prepare.py
"""
Database for the end-to-end tests (e2e/, Playwright): created if missing, migrated, emptied and
filled with the same small catalog every run, so the tests always see the same app.

  DB_NAME=taurus_e2e python manage.py e2e_prepare

Refuses to run on a database whose name doesn't contain "e2e": it deletes everything in it.
Test account (also in e2e/fixtures.js): e2e@example.test / E2e-pass-1234!
"""
import MySQLdb
from django.conf import settings
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from django.db import connection

E2E_EMAIL = "e2e@example.test"
E2E_PASSWORD = "E2e-pass-1234!"

# players: domains the tests intercept (e2e/fixtures.js serves a fake player for them)
PROVIDERS = [
    dict(key="e2eplayer", label="E2E Player", domain="https://player.e2e.test",
         movie_path="/movie/{tmdb_id}", episode_path="/tv/{tmdb_id}/{season}/{episode}", priority=1),
    dict(key="cinesrc", label="CineSrc", domain="https://cinesrc.st",
         movie_path="/embed/movie/{tmdb_id}", episode_path="/embed/tv/{tmdb_id}/{season}/{episode}",
         sends_events=True, priority=2),
]

MOVIES = [
    # title, tmdb_id, year, genre, popularity, rating, original language, (fr title, fr overview)
    ("The Godfather", 238, 1972, "Crime, Drama", 99, 8.7, "en", ("Le Parrain", "Le patriarche d'une dynastie du crime organisé...")),
    ("Inception", 27205, 2010, "Science Fiction, Action", 95, 8.4, "en", ("Inception", "Dom Cobb vole des secrets dans les rêves.")),
    ("Spirited Away", 129, 2001, "Animation, Family, Fantasy", 90, 8.5, "ja", ("Le Voyage de Chihiro", "Chihiro découvre un monde d'esprits.")),
    ("Heat", 949, 1995, "Crime, Thriller", 85, 7.9, "en", None),
    ("Amélie", 194, 2001, "Comedy, Romance", 80, 7.9, "fr", ("Le Fabuleux Destin d'Amélie Poulain", "Amélie décide de changer la vie des autres.")),
    ("Interstellar", 157336, 2014, "Science Fiction, Adventure", 88, 8.4, "en", None),
    ("Toy Story", 862, 1995, "Animation, Family, Comedy", 75, 8.0, "en", None),
    ("Parasite", 496243, 2019, "Thriller, Drama", 87, 8.5, "ko", None),
]


class Command(BaseCommand):
    help = "Create / migrate / reset the end-to-end test database and fill it with a fixed catalog."

    def handle(self, *args, **opts):
        db = settings.DATABASES["default"]
        name = db["NAME"]
        if "e2e" not in name.lower():
            raise CommandError(f'Refusing to reset "{name}": the database name must contain "e2e" (DB_NAME=taurus_e2e).')

        self._create_database(db)
        call_command("migrate", interactive=False, verbosity=0)
        call_command("flush", interactive=False, verbosity=0)
        self._seed()
        self.stdout.write(self.style.SUCCESS(f"{name} ready: {E2E_EMAIL}"))

    @staticmethod
    def _create_database(db):
        conn = MySQLdb.connect(host=db["HOST"] or "localhost", port=int(db["PORT"] or 3306), user=db["USER"], passwd=db["PASSWORD"])
        try:
            conn.cursor().execute(
                f"CREATE DATABASE IF NOT EXISTS `{db['NAME']}` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
            )
        finally:
            conn.close()
        connection.close()  # reconnect to the new database

    def _seed(self):
        from reco.views import upsert_seed_snapshot
        from users.models import (
            Episode, Profile, Provider, Season, Title, TitleTranslation, TVShowExtras, User,
        )

        Provider.objects.all().delete()
        for p in PROVIDERS:
            Provider.objects.create(**p)

        for i, (title, tmdb_id, year, genre, popularity, rating, lang, fr) in enumerate(MOVIES):
            t = Title.objects.create(
                type="movie", title=title, original_title=title, tmdb_id=tmdb_id, original_language=lang,
                release_date=f"{year}-06-01", release_year=year, runtime_minutes=100 + i * 7,
                description=f"{title}: the English synopsis.", genre=genre, primary_genre_norm=genre.split(",")[0].lower(),
                popularity=popularity, vote_average=rating, vote_count=10000 + i, rating=str(rating),
                director="E2E Director", cast=["Actor One", "Actor Two"],
                # artwork URLs (the tests block the downloads): the banner only picks titles with art
                poster=f"https://image.tmdb.org/t/p/w500/e2e-{tmdb_id}.jpg",
                landscape_image=f"https://image.tmdb.org/t/p/w780/e2e-{tmdb_id}-wide.jpg",
            )
            if fr:
                TitleTranslation.objects.create(title=t, language="fr", name=fr[0], overview=fr[1])

        show = Title.objects.create(
            type="tv", title="Breaking Bad", original_title="Breaking Bad", tmdb_id=1396, original_language="en",
            first_air_date="2008-01-20", release_year=2008, description="A chemistry teacher turns to crime.",
            genre="Drama, Crime", primary_genre_norm="drama", popularity=98, vote_average=8.9, vote_count=15000,
            rating="8.9", poster="https://image.tmdb.org/t/p/w500/e2e-1396.jpg",
            landscape_image="https://image.tmdb.org/t/p/w780/e2e-1396-wide.jpg",
        )
        TVShowExtras.objects.create(title=show, number_of_seasons=2, number_of_episodes=6)
        for s in (1, 2):
            season = Season.objects.create(tv=show, season_number=s, name=f"Season {s}", air_date=f"{2007 + s}-01-20")
            for e in (1, 2, 3):
                Episode.objects.create(
                    season=season, episode_number=e, name=f"S{s} episode {e}",
                    overview=f"What happens in season {s}, episode {e}.", air_date=f"{2007 + s}-0{e}-20", runtime=47,
                )
        TitleTranslation.objects.create(title=show, language="fr", name="Breaking Bad", overview="Un professeur de chimie bascule dans le crime.")

        # a show still on air, dates relative to the run (the "Upcoming" calendar): one episode
        # 12 days ago (outside "New episodes" and "out this past week"), then in 3 and 10 days
        from datetime import timedelta
        from django.utils import timezone
        today = timezone.localdate()
        airing = Title.objects.create(
            type="tv", title="Night Shift", original_title="Night Shift", tmdb_id=900001, original_language="en",
            first_air_date="2024-01-10", release_year=2024, description="Night nurses, long shifts.",
            genre="Drama", primary_genre_norm="drama", popularity=40, vote_average=7.5, vote_count=2000,
            rating="7.5", status="Returning Series", poster="https://image.tmdb.org/t/p/w500/e2e-900001.jpg",
            landscape_image="https://image.tmdb.org/t/p/w780/e2e-900001-wide.jpg",
        )
        TVShowExtras.objects.create(title=airing, number_of_seasons=1, number_of_episodes=3, in_production=True)
        season = Season.objects.create(tv=airing, season_number=1, name="Season 1", air_date="2024-01-10")
        for e, days in ((1, -12), (2, 3), (3, 10)):
            Episode.objects.create(season=season, episode_number=e, name=f"Shift {e}", overview=f"Night {e}.",
                                   air_date=today + timedelta(days=days), runtime=45)

        user = User.objects.create_user(E2E_EMAIL, "E2E User", E2E_PASSWORD)
        profiles = [
            Profile.objects.create(user=user, name="Alex", language_preference="en", age_restriction="NC-17"),
            Profile.objects.create(user=user, name="Camille", language_preference="fr", age_restriction="NC-17"),
            Profile.objects.create(user=user, name="Kids", language_preference="en", age_restriction="G", is_kids=True),
            # a brand-new profile: nothing liked yet, so the app offers "What do you like?" (/taste)
            Profile.objects.create(user=user, name="Sam", language_preference="en", age_restriction="NC-17"),
        ]
        for p in profiles:
            upsert_seed_snapshot(p)  # home rows right away (the cron builds them in production)
        # profiles in use already liked something: no "pick what you like" banner on their home
        from reco.models import TitleRating
        heat = Title.objects.get(title="Heat")
        for p in profiles[:3]:
            TitleRating.objects.create(profile=p, title=heat, value=TitleRating.LIKE)
