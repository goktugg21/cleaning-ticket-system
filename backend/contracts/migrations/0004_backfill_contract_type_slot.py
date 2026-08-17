"""
Sprint 169 §4 — backfill `ContractType.standard_slot`.

Required rather than optional: the column carries a meaning its default
(`""`) does not express. `""` means "a company's own custom type", so
leaving every pre-existing row at the default would claim that the four
seeded standard types are custom — and they would render their stored
Dutch names to an English reader, which is the exact defect this change
exists to fix.

Uses the SAME `slot_for_name` the model's `save()` uses, imported
rather than reimplemented, so the backfilled value and every future
write agree by construction. Reversing is a no-op: the column is
derived, so dropping back to `""` loses nothing that a later save would
not recompute.
"""
from django.db import migrations

from contracts.standard_types import slot_for_name


def backfill(apps, schema_editor):
    ContractType = apps.get_model("contracts", "ContractType")
    # `.save()` on a historical model does NOT run the real model's
    # save(), so the derivation is applied explicitly here — the same
    # function, called directly.
    for row in ContractType.objects.all().iterator():
        slot = slot_for_name(row.name)
        if slot != row.standard_slot:
            row.standard_slot = slot
            row.save(update_fields=["standard_slot"])


def unbackfill(apps, schema_editor):
    """Deliberately a no-op. The column is derived; clearing it would
    only mean the next save recomputes it."""


class Migration(migrations.Migration):
    dependencies = [
        ("contracts", "0003_contracttype_standard_slot"),
    ]

    operations = [
        migrations.RunPython(backfill, unbackfill),
    ]
