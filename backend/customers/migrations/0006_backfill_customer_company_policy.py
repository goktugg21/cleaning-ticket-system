"""
Sprint 27C — data migration: backfill CustomerCompanyPolicy for every
existing Customer and copy the legacy `show_assigned_staff_*` values
into the new policy row.

After this migration runs:
  * Every pre-existing Customer has exactly one CustomerCompanyPolicy
    row (OneToOneField).
  * The three visibility booleans on the policy row mirror what was
    on the Customer row at migration time.
  * The four new permission-policy booleans take their defaults
    (all True) from the model.

The legacy Customer.show_assigned_staff_* fields are intentionally
left in place — the existing ticket serializer still reads them.
Switching the read path is a separate, lower-risk migration that
ships once the editor UI lands and a release window is available.

Reverse migration: just delete every CustomerCompanyPolicy row.
Customer's legacy fields are untouched in either direction.
"""
from django.db import migrations


def backfill_policy_rows(apps, schema_editor):
    Customer = apps.get_model("customers", "Customer")
    CustomerCompanyPolicy = apps.get_model("customers", "CustomerCompanyPolicy")

    rows_to_create = []
    for customer in Customer.objects.all().iterator():
        if CustomerCompanyPolicy.objects.filter(customer=customer).exists():
            # Defensive: respect any row created by a parallel path
            # (e.g. the auto-create signal we wire up in this sprint).
            continue
        rows_to_create.append(
            CustomerCompanyPolicy(
                customer=customer,
                show_assigned_staff_name=customer.show_assigned_staff_name,
                show_assigned_staff_email=customer.show_assigned_staff_email,
                show_assigned_staff_phone=customer.show_assigned_staff_phone,
                # Permission-policy fields take their model defaults
                # (all True). Explicit assignment here would be
                # redundant; leaving them implicit keeps this
                # backfill a pure "mirror the visibility state"
                # operation.
            )
        )

    if rows_to_create:
        CustomerCompanyPolicy.objects.bulk_create(rows_to_create)


def reverse_backfill(apps, schema_editor):
    CustomerCompanyPolicy = apps.get_model("customers", "CustomerCompanyPolicy")
    CustomerCompanyPolicy.objects.all().delete()


class Migration(migrations.Migration):

    dependencies = [
        ("customers", "0005_customercompanypolicy"),
    ]

    operations = [
        migrations.RunPython(backfill_policy_rows, reverse_backfill),
    ]
