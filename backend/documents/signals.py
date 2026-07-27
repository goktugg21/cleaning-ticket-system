"""
Sprint 125 — auto-create the four default system folders whenever a new
`Customer` is created, so every live customer always has the Facturen /
Contracten / Overeenkomsten / Overig roots.

This hangs off the Customer `post_save` (created=True) signal — the SAME
un-bypassable path `customers/signals.py` uses to auto-create
`CustomerCompanyPolicy`. Any Customer creation route (the API serializer,
the Django admin, a shell `.create()`, a fixture load) triggers it, so the
default folders cannot be bypassed.

The matching one-time backfill for pre-existing customers lives in
`documents/migrations/0002_backfill_default_folders.py`. Both use the same
`ensure_system_folders` helper, and both are idempotent (`get_or_create`
keyed on the stable `system_slug`), so a customer that somehow already has
its folders is never duplicated.
"""
from __future__ import annotations

from django.db.models.signals import post_save
from django.dispatch import receiver

from customers.models import Customer

from .models import DocumentFolder, DocumentOrigin, SYSTEM_FOLDER_SPECS


def ensure_system_folders(customer, *, folder_model=DocumentFolder) -> None:
    """Create any missing system folders for `customer`. Idempotent: keyed
    on (customer, system_slug), so re-running never duplicates a folder.

    `folder_model` is a parameter so the data migration can pass its own
    historical `apps.get_model("documents", "DocumentFolder")` — a historical
    model has no access to module-level constants/choices, hence the explicit
    string origin value below rather than the enum member."""
    for slug, display_name in SYSTEM_FOLDER_SPECS:
        folder_model.objects.get_or_create(
            customer=customer,
            system_slug=slug,
            defaults={
                "name": display_name,
                "is_system": True,
                "parent": None,
                "origin": DocumentOrigin.PROVIDER.value,
                "created_by": None,
            },
        )


@receiver(
    post_save,
    sender=Customer,
    dispatch_uid="documents:auto_create_system_folders",
)
def _auto_create_system_folders(sender, instance, created, **kwargs):
    if not created:
        return
    ensure_system_folders(instance)
