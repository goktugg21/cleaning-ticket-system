# Generated for Sprint 28 Batch 11 — STAFF completion routing.
#
# Adds the `staff_completion_routes_to_customer` boolean to
# BuildingStaffVisibility. Default is False so every existing row
# backfills to the conservative "route through manager review" path
# — preserving the new Batch 11 default and matching the spec.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("buildings", "0003_buildingstaffvisibility_visibility_level"),
    ]

    operations = [
        migrations.AddField(
            model_name="buildingstaffvisibility",
            name="staff_completion_routes_to_customer",
            field=models.BooleanField(
                default=False,
                help_text=(
                    "Sprint 28 Batch 11 — per-staff-per-building routing flag. "
                    "False (default): STAFF completion goes to manager review "
                    "(WAITING_MANAGER_REVIEW); BM accepts → WAITING_CUSTOMER_APPROVAL "
                    "or rejects → IN_PROGRESS. True: STAFF completion goes directly "
                    "to WAITING_CUSTOMER_APPROVAL (skips manager review)."
                ),
            ),
        ),
    ]
