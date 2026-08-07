# Sprint 152.3 — backfill `HourType.standard_slot` on existing rows.
#
# `0002` added the column with `default=""`, so every pre-existing row
# reads as "custom" until this runs. On crmtest that is 6 rows, all
# created by the standard-set button, so all six are expected to attach.
#
# The derivation is IMPORTED, not reimplemented. A migration that
# hardcoded its own copy of the twelve names would be a second source of
# truth that stops matching `standard_set.py` the first time a slot's
# wording is adjusted — and, being a migration, it would keep claiming to
# have applied the rule correctly. The usual argument against importing
# app code into a migration is that the code may drift from the schema
# this migration expects; that does not apply here, because
# `slot_for_name` reads a name and returns a string, touching no model
# and no column that could change underneath it.
from django.db import migrations

from timesheets.standard_set import slot_for_name


def backfill_standard_slot(apps, schema_editor):
    """Attach every recognisable existing row to its slot.

    Uses the HISTORICAL model (`apps.get_model`) and a queryset
    `.update()` per row rather than `instance.save()`: the historical
    model has no custom `save()`, so the derivation has to be applied
    explicitly here anyway, and `.update()` avoids firing the audit
    signals — a backfill is a schema operation with no operator behind
    it, and `AuditLog` rows attributed to nobody for a change nobody made
    would be noise in the one place that must stay readable.
    """
    HourType = apps.get_model("timesheets", "HourType")
    for hour_type in HourType.objects.all().iterator():
        slot = slot_for_name(hour_type.name)
        if slot != hour_type.standard_slot:
            HourType.objects.filter(pk=hour_type.pk).update(standard_slot=slot)


def clear_standard_slot(apps, schema_editor):
    """Reverse: every row back to custom.

    A real reverse rather than `noop`, so `migrate timesheets 0002` puts
    the table in the state 0002 actually describes. The column still
    exists after this — dropping it is 0002's job — and no data is lost,
    because the value is derived: re-running forwards reconstructs it
    exactly.
    """
    HourType = apps.get_model("timesheets", "HourType")
    HourType.objects.exclude(standard_slot="").update(standard_slot="")


class Migration(migrations.Migration):

    dependencies = [
        ("timesheets", "0002_hourtype_standard_slot"),
    ]

    operations = [
        migrations.RunPython(backfill_standard_slot, clear_standard_slot),
    ]
