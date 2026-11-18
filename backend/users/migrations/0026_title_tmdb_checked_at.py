from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('users', '0025_ai_translations'),
    ]

    operations = [
        migrations.AddField(
            model_name='title',
            name='tmdb_checked_at',
            field=models.DateTimeField(blank=True, db_index=True, null=True),
        ),
    ]
