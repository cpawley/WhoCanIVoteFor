# -*- coding: utf-8 -*-
# Generated by Django 1.10.7 on 2017-06-02 10:28
from __future__ import unicode_literals

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [("hustings", "0002_auto_20170601_2155")]

    operations = [
        migrations.AddField(
            model_name="husting",
            name="video_url",
            field=models.URLField(blank=True, null=True),
        )
    ]
