from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('users', '0027_title_trailer_clip_for'),
    ]

    operations = [
        migrations.AddField(
            model_name='profile',
            name='appearance',
            field=models.JSONField(blank=True, default=dict),
        ),
    ]
