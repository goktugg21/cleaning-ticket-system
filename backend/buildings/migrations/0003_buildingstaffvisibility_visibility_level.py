# Generated for Sprint 28 Batch 10 — staff per-building granularity.
#
# Adds the `visibility_level` enum to BuildingStaffVisibility with a
# default of `BUILDING_READ`. The default preserves the existing
# behaviour: a BSV row created without an explicit `visibility_level=`
# (today's call sites + every Sprint 23-28 STAFF test fixture) continues
# to grant building-wide read access, which is what today's
# `scope_tickets_for` STAFF branch produces. Existing rows on the DB
# are backfilled by the AddField default — no data migration needed.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("buildings", "0002_buildingstaffvisibility"),
    ]

    operations = [
        migrations.AddField(
            model_name="buildingstaffvisibility",
            name="visibility_level",
            field=models.CharField(
                choices=[
                    ("ASSIGNED_ONLY", "Assigned only"),
                    ("BUILDING_READ", "Building read"),
                    (
                        "BUILDING_READ_AND_ASSIGN",
                        "Building read and assign",
                    ),
                ],
                default="BUILDING_READ",
                max_length=32,
            ),
        ),
    ]
