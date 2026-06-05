"""
SoT Addendum A.1 — make Customer Company Admin a COMPANY-WIDE membership
flag instead of a per-building access_role.

Two operations:

  1. AddField `is_company_admin` (BooleanField, default False) on
     CustomerUserMembership. Additive + back-compat — every existing row
     defaults to False.

  2. Forward-only data migration that COLLAPSES the legacy per-building
     CUSTOMER_COMPANY_ADMIN access rows into the new flag:
       * Any CustomerUserMembership that has >= 1
         CustomerUserBuildingAccess row at
         access_role=CUSTOMER_COMPANY_ADMIN (ANY is_active state) gets
         `is_company_admin=True`.
       * Those CCA-role CUBA rows are then DELETED — the flag supersedes
         them. Any per-building permission_overrides that sat on a CCA
         row are intentionally dropped (Addendum A.1: a company-wide CCA
         is admin everywhere; per-building rows do not apply to them).
       * Non-CCA CUBA rows (CUSTOMER_USER / CUSTOMER_LOCATION_MANAGER) are
         left untouched.

Reverse is a no-op: the collapse is forward-only. Reversing the AddField
drops the column, which is the only state the reverse needs to restore.
"""
from django.db import migrations, models


def collapse_cca_rows(apps, schema_editor):
    CustomerUserMembership = apps.get_model("customers", "CustomerUserMembership")
    CustomerUserBuildingAccess = apps.get_model(
        "customers", "CustomerUserBuildingAccess"
    )

    CCA = "CUSTOMER_COMPANY_ADMIN"

    membership_ids = list(
        CustomerUserBuildingAccess.objects.filter(access_role=CCA)
        .values_list("membership_id", flat=True)
        .distinct()
    )

    collapsed = 0
    if membership_ids:
        collapsed = CustomerUserMembership.objects.filter(
            id__in=membership_ids
        ).update(is_company_admin=True)

    deleted, _ = CustomerUserBuildingAccess.objects.filter(
        access_role=CCA
    ).delete()

    if collapsed or deleted:
        print(
            f"[customers.0010] collapsed {collapsed} memberships to "
            f"company-admin, deleted {deleted} CCA access rows"
        )


class Migration(migrations.Migration):

    dependencies = [
        ("customers", "0009_backfill_contact_building_links"),
    ]

    operations = [
        migrations.AddField(
            model_name="customerusermembership",
            name="is_company_admin",
            field=models.BooleanField(
                default=False,
                help_text=(
                    "Company-wide Customer Company Admin: admin across ALL "
                    "the customer's buildings; per-building access rows do "
                    "not apply."
                ),
            ),
        ),
        migrations.RunPython(collapse_cca_rows, migrations.RunPython.noop),
    ]
