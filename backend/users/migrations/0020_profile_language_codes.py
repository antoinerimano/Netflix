# Profile.language_preference: one code per language, the app's (users/i18n.py).
# "jp" -> "ja", "zh-CN" -> "zh", "fr-FR" -> "fr", "" / unknown -> "en". Also matches TMDB's
# original_language codes, which the recommendations compare it with ("jp" never matched).
from django.db import migrations

APP_LANGUAGES = ("en", "fr", "es", "de", "it", "ja", "zh")
ALIASES = {"jp": "ja", "cn": "zh"}


def normalize(code):
    c = (code or "").strip().lower().replace("_", "-")
    c = ALIASES.get(c, c)
    base = ALIASES.get(c.split("-")[0], c.split("-")[0])
    return base if base in APP_LANGUAGES else "en"


def forwards(apps, schema_editor):
    Profile = apps.get_model("users", "Profile")
    for profile in Profile.objects.only("id", "language_preference").iterator():
        code = normalize(profile.language_preference)
        if code != profile.language_preference:
            Profile.objects.filter(id=profile.id).update(language_preference=code)


class Migration(migrations.Migration):
    dependencies = [("users", "0019_catalog_translations")]

    operations = [migrations.RunPython(forwards, migrations.RunPython.noop)]
