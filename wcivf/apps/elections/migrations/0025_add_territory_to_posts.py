from __future__ import unicode_literals

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [("elections", "0024_default_for_has_by_elections")]

    operations = [
        migrations.AddField(
            model_name="post",
            name="territory",
            field=models.CharField(blank=True, max_length=3, serialize=True),
        )
    ]
