"""
Sprint 170 §5 — backfill `WorkType.standard_slot`.

Required rather than optional, for the reason the contract-type backfill
gave: `""` means "a company's own custom type", so leaving the four rows
Sprint 168 seeded at the default would claim they are custom, and they
would keep rendering their Dutch names to an English reader — the exact
defect this change exists to remove.

Uses the same `slot_for_name` the model's `save()` uses, imported rather
than reimplemented, so the backfilled value and every future write agree
by construction.
"""
from django.db import migrations

from timesheets.serializers_work_types import slot_for_name


def backfill(apps, schema_editor):
    WorkType = apps.get_model("timesheets", "WorkType")
    # A historical model's `.save()` does NOT run the real model's
    # save(), so the derivation is applied explicitly — same function.
    for row in WorkType.objects.all().iterator():
        slot = slot_for_name(row.name)
        if slot != row.standard_slot:
            row.standard_slot = slot
            row.save(update_fields=["standard_slot"])


def unbackfill(apps, schema_editor):
    """A no-op: the column is derived, so clearing it would only mean
    the next save recomputes it."""


class Migration(migrations.Migration):
    dependencies = [
        ("timesheets", "0006_worktype_standard_slot"),
    ]

    operations = [
        migrations.RunPython(backfill, unbackfill),
    ]
