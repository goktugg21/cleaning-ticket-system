"""
Sprint 125 — backfill the four default system folders for every EXISTING
customer (new customers get them from the `post_save` signal in
`documents/signals.py`).

Idempotent: keyed on (customer, system_slug) via `get_or_create`, so a
customer that somehow already has some or all of its system folders is never
duplicated — safe to re-run.

The four specs + the PROVIDER origin string are inlined (not imported from
`documents.models`) so this migration stays frozen even if the module
constant later changes. Runs on the historical model, so no post_save signal
and no audit rows fire here — exactly the system-write semantics we want.
"""
from __future__ import annotations

from django.db import migrations


# (system_slug, initial display name). Slug is stable forever; name renamable.
_SYSTEM_FOLDER_SPECS = (
    ("facturen", "Facturen"),
    ("contracten", "Contracten"),
    ("overeenkomsten", "Overeenkomsten"),
    ("overig", "Overig"),
)


def backfill_default_folders(apps, schema_editor):
    Customer = apps.get_model("customers", "Customer")
    DocumentFolder = apps.get_model("documents", "DocumentFolder")
    for customer in Customer.objects.all().iterator():
        for slug, display_name in _SYSTEM_FOLDER_SPECS:
            DocumentFolder.objects.get_or_create(
                customer=customer,
                system_slug=slug,
                defaults={
                    "name": display_name,
                    "is_system": True,
                    "parent": None,
                    "origin": "PROVIDER",
                    "created_by": None,
                },
            )


def reverse_noop(apps, schema_editor):
    # Intentional no-op — mirrors the reverse of other backfills in this repo
    # (e.g. extra_work/0019). Deleting the system folders on rollback is risky
    # once operators / customers have filed documents under them.
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("documents", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(backfill_default_folders, reverse_noop),
    ]
