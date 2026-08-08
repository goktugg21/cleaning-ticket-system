"""
Sprint 27C — customers app signals.

Auto-creates a `CustomerCompanyPolicy` row whenever a new `Customer`
is created so the rest of the codebase can assume `customer.policy`
always exists for any live customer.

The matching one-time backfill for pre-existing customers is in
`migrations/0006_backfill_customer_company_policy.py`.

Sprint 154 §I.7 adds a second auto-provision on the same hook: one
`Department` and one `WorkType` both named "Algemeen", so a customer can
never have an EMPTY label list. Its backfill lives in
`migrations/0017_sprint154_default_labels.py`.
"""
from __future__ import annotations

from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import Customer, CustomerCompanyPolicy, Department, WorkType


# Sprint 154 §I.7 — the always-present fallback label.
#
# Dutch, and ONE operator-typed name column, following the Sprint 152.3
# HourType precedent: these are operator vocabulary that a provider may
# rename, not UI chrome, so they are NOT translated per language and
# there is no per-language column. If a tenant renames it, the renamed
# row is simply the one they see.
DEFAULT_LABEL_NAME = "Algemeen"


@receiver(
    post_save,
    sender=Customer,
    dispatch_uid="customers:auto_create_policy",
)
def _auto_create_policy(sender, instance, created, **kwargs):
    """Create a CustomerCompanyPolicy row with the safe defaults +
    a 1:1 copy of the legacy show_assigned_staff_* values from the
    parent Customer row. No-op on UPDATE.

    The visibility values are copied (not just defaulted to True)
    so a Customer created via `.create(show_assigned_staff_name=False)`
    immediately has the matching policy row pre-populated — the
    Sprint 27C test
    `test_customer_company_policy_backfills_existing_assigned_staff_visibility_fields`
    pins this contract.
    """
    if not created:
        return
    # `get_or_create` defensively in case a future migration / fixture
    # pre-creates the policy row in the same transaction.
    CustomerCompanyPolicy.objects.get_or_create(
        customer=instance,
        defaults={
            "show_assigned_staff_name": instance.show_assigned_staff_name,
            "show_assigned_staff_email": instance.show_assigned_staff_email,
            "show_assigned_staff_phone": instance.show_assigned_staff_phone,
        },
    )


def ensure_default_labels(customer) -> tuple:
    """Sprint 154 §I.7 — guarantee this customer has an "Algemeen"
    Department and WorkType, and return the pair.

    Idempotent and safe to call on an existing customer: the model's
    `UniqueConstraint(Lower(Trim(name)), customer)` means a
    case-insensitive match already exists or does not, so we look the row
    up the same way the constraint would rather than blindly creating a
    second one that the DB would reject.

    Why this matters beyond convenience: §I.7 makes the two labels
    mandatory on the Extra Work form, and a customer with an EMPTY label
    list is exactly the case that would make a required field
    un-fillable. Guaranteeing the row is what makes "required" a safe
    thing to ask for.
    """
    created_rows = []
    for model in (Department, WorkType):
        row = (
            model.objects.filter(customer=customer, name__iexact=DEFAULT_LABEL_NAME)
            .order_by("id")
            .first()
        )
        if row is None:
            row = model.objects.create(
                customer=customer,
                name=DEFAULT_LABEL_NAME,
                description="",
            )
        created_rows.append(row)
    return tuple(created_rows)


@receiver(
    post_save,
    sender=Customer,
    dispatch_uid="customers:auto_create_default_labels",
)
def _auto_create_default_labels(sender, instance, created, **kwargs):
    """Provision the "Algemeen" Department + WorkType on customer
    creation. No-op on UPDATE, exactly like the policy receiver above."""
    if not created:
        return
    ensure_default_labels(instance)
