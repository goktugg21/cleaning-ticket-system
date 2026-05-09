"""
Sprint 14 — data backfill: preserve pre-Sprint-14 customer/user visibility.

Two RunPython operations seed the new M:N tables from the legacy data:

1. For every existing Customer with a non-null `building`, create one
   CustomerBuildingMembership(customer, customer.building). This makes
   the new M:N source of truth match the legacy single-building anchor.

2. For every existing CustomerUserMembership whose customer has a
   legacy `building`, create one CustomerUserBuildingAccess(membership,
   customer.building). This means every pilot customer-user keeps
   visibility of exactly the building they had under the old model —
   no regression.

Both operations are idempotent (use bulk_create with ignore_conflicts)
so re-running the migration on partially-migrated data is safe.

Reverse migration is a no-op: removing the rows would orphan any
data the operator added through the new admin UI between the
forward migration and a subsequent rollback. A rollback should
re-create the legacy `building` FK on Customer (the schema
migration's reverse takes care of that), and the M:N rows can stay
in place — they will simply be unused. If a clean rollback is
needed, the operator can DELETE FROM the two tables manually.
"""
from django.db import migrations


def backfill_customer_building_memberships(apps, schema_editor):
    Customer = apps.get_model("customers", "Customer")
    CustomerBuildingMembership = apps.get_model(
        "customers", "CustomerBuildingMembership"
    )

    rows = []
    for customer in Customer.objects.filter(building_id__isnull=False).iterator():
        rows.append(
            CustomerBuildingMembership(
                customer_id=customer.id, building_id=customer.building_id
            )
        )
    if rows:
        CustomerBuildingMembership.objects.bulk_create(rows, ignore_conflicts=True)


def backfill_customer_user_building_access(apps, schema_editor):
    Customer = apps.get_model("customers", "Customer")
    CustomerUserMembership = apps.get_model(
        "customers", "CustomerUserMembership"
    )
    CustomerUserBuildingAccess = apps.get_model(
        "customers", "CustomerUserBuildingAccess"
    )

    # Pre-fetch legacy building per customer to avoid one query per
    # membership when the dataset grows.
    customer_building_map = {
        c["id"]: c["building_id"]
        for c in Customer.objects.values("id", "building_id")
        if c["building_id"] is not None
    }

    rows = []
    for membership in CustomerUserMembership.objects.iterator():
        legacy_building_id = customer_building_map.get(membership.customer_id)
        if legacy_building_id is None:
            # Customer never had a legacy building (only possible if a
            # row was created post-Sprint-14 with building=NULL). Such
            # memberships start with NO building access; the operator
            # must grant access explicitly via the new admin UI.
            continue
        rows.append(
            CustomerUserBuildingAccess(
                membership_id=membership.id,
                building_id=legacy_building_id,
            )
        )
    if rows:
        CustomerUserBuildingAccess.objects.bulk_create(rows, ignore_conflicts=True)


def noop_reverse(apps, schema_editor):
    # Intentional no-op. See module docstring.
    pass


class Migration(migrations.Migration):
    dependencies = [
        ("customers", "0002_customer_building_membership_and_user_building_access"),
    ]

    operations = [
        migrations.RunPython(
            backfill_customer_building_memberships,
            reverse_code=noop_reverse,
        ),
        migrations.RunPython(
            backfill_customer_user_building_access,
            reverse_code=noop_reverse,
        ),
    ]
