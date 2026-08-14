"""Sprint 180 §3 — `ExtraWorkRequest.billed_to`.

Additive, non-null, with `default="BUILDING"`. The default IS the
backfill and is the correct historical answer, not a placeholder: every
pre-180 row was charged to the building, which is also why it is the
default for new rows (the owner: the building, 99% of the time). No
separate data migration is needed because the new column carries the
same meaning for old rows as for new ones.
"""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("extra_work", "0030_extraworkrequest_deadline_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="extraworkrequest",
            name="billed_to",
            field=models.CharField(
                choices=[("BUILDING", "Building"), ("CUSTOMER", "Customer")],
                default="BUILDING",
                help_text=(
                    "Sprint 180 — who the finished work is charged to: the "
                    "BUILDING (default) or the CUSTOMER organisation."
                ),
                max_length=16,
            ),
        ),
    ]
