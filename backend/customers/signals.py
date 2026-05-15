"""
Sprint 27C — customers app signals.

Auto-creates a `CustomerCompanyPolicy` row whenever a new `Customer`
is created so the rest of the codebase can assume `customer.policy`
always exists for any live customer.

The matching one-time backfill for pre-existing customers is in
`migrations/0006_backfill_customer_company_policy.py`.
"""
from __future__ import annotations

from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import Customer, CustomerCompanyPolicy


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
