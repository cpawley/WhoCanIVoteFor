# Generated by Django 2.2.20 on 2021-06-04 12:45

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("people", "0036_auto_20191213_1028"),
    ]

    operations = [
        migrations.AddField(
            model_name="personpost",
            name="party_description_text",
            field=models.CharField(
                blank=True,
                help_text="The party description at the time of the candidacy",
                max_length=255,
            ),
        ),
        migrations.AddField(
            model_name="personpost",
            name="party_name",
            field=models.CharField(
                default="",
                help_text="The name of the party at the time of the candidacy",
                max_length=255,
            ),
            preserve_default=False,
        ),
    ]
