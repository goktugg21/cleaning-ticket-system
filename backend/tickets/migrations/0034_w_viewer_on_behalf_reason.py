"""W-VIEWER §10 — the reason an operator closed somebody else's slot.

Additive and nullable-by-default (`blank`, `default=""`), so every
existing row reads as "nobody acted on anybody's behalf here", which is
what those rows mean: before this field the on-behalf route asked for no
reason at all, so there is nothing to backfill and inventing one would
be worse than an empty string.
"""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("tickets", "0033_w_late_part_windows"),
    ]

    operations = [
        migrations.AddField(
            model_name="ticketstaffassignment",
            name="completed_on_behalf_reason",
            field=models.TextField(blank=True, default=""),
        ),
    ]
