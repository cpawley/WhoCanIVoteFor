# Generated by Django 3.2.7 on 2021-11-05 15:53

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("parties", "0010_localparty_is_local"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="party",
            name="emblem",
        ),
        migrations.AddField(
            model_name="party",
            name="emblem_url",
            field=models.URLField(blank=True, null=True),
        ),
    ]
