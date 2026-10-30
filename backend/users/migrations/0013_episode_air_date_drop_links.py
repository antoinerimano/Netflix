from django.db import migrations, models


class Migration(migrations.Migration):
    """
    - Episode.air_date: varchar 'YYYY-MM-DD' / '' -> indexed DATE / NULL (for "new episodes" queries)
    - Drop the stored stream links: they are built from Provider templates now.
    """

    dependencies = [
        ("users", "0012_provider"),
    ]

    operations = [
        migrations.AlterField(
            model_name="episode",
            name="air_date",
            field=models.CharField(max_length=10, null=True, blank=True, default=""),
        ),
        migrations.RunSQL(
            "UPDATE users_episode SET air_date = NULL WHERE air_date = ''",
            "UPDATE users_episode SET air_date = '' WHERE air_date IS NULL",
        ),
        migrations.AlterField(
            model_name="episode",
            name="air_date",
            field=models.DateField(null=True, blank=True, db_index=True),
        ),

        migrations.RemoveField(model_name="title", name="video_url"),
        migrations.RemoveField(model_name="title", name="movie_link2"),
        migrations.RemoveField(model_name="title", name="movie_link3"),
        migrations.RemoveField(model_name="title", name="movie_link4"),
        migrations.RemoveField(model_name="title", name="movie_link5"),
        migrations.RemoveField(model_name="title", name="movie_link6"),
        migrations.RemoveField(model_name="episode", name="video_url"),
        migrations.RemoveField(model_name="episode", name="episode_link2"),
        migrations.RemoveField(model_name="episode", name="episode_link3"),
        migrations.RemoveField(model_name="episode", name="episode_link4"),
        migrations.RemoveField(model_name="episode", name="episode_link5"),
        migrations.RemoveField(model_name="episode", name="episode_link6"),
    ]
