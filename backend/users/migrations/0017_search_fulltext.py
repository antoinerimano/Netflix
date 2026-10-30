from django.db import migrations

# MySQL FULLTEXT indexes for search (users/search.py): word / prefix matching in a few ms
# instead of scanning every title (and 700k+ actor rows) with LIKE '%...%'.


class Migration(migrations.Migration):

    dependencies = [
        ("users", "0016_provider_sends_events"),
    ]

    operations = [
        migrations.RunSQL(
            "ALTER TABLE users_title ADD FULLTEXT INDEX title_name_ft (title, original_title)",
            "ALTER TABLE users_title DROP INDEX title_name_ft",
        ),
        migrations.RunSQL(
            "ALTER TABLE users_title ADD FULLTEXT INDEX title_director_ft (director)",
            "ALTER TABLE users_title DROP INDEX title_director_ft",
        ),
        migrations.RunSQL(
            "ALTER TABLE users_actor ADD FULLTEXT INDEX actor_name_ft (name)",
            "ALTER TABLE users_actor DROP INDEX actor_name_ft",
        ),
    ]
