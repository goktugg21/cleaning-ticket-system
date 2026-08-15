"""
Sprint 182 §3 — split the billing TARGET from the invoice SPLIT.

Additive: two new columns, both with defaults, plus a data migration that
backfills them from the existing `invoice_granularity_default`. That column
is NOT dropped — `Invoice.granularity` records it per invoice and
`invoicing.state_machine._resync_invoice_group_labels` keys off its
vocabulary, so it stays as a derived mirror.

**Nobody's behaviour changes.** The mapping is exhaustive over the three
values the old dropdown could hold:

    invoice_granularity_default        -> target    + split
    ---------------------------------------------------------------
    CUSTOMER                           -> CUSTOMER  + NONE
    PER_BUILDING                       -> BUILDING  + NONE
    PER_BUILDING_DEPARTMENT_WORK_TYPE  -> BUILDING  + DEPARTMENT_WORK_TYPE

Anything else (a value written before the choices were widened, or by
hand) lands on CUSTOMER + NONE, which is the same fallback
`generate_draft_invoices` has always applied to an unrecognised
granularity string — so such a row keeps behaving exactly as it did.

The reverse migration recomputes `invoice_granularity_default` from the
pair before the columns are dropped, so a rollback cannot strand a
customer on a granularity that disagrees with the controls they last saw.
"""
from django.db import migrations, models


# The forward map. Written out here rather than imported from
# `invoicing.billing_target` on purpose: a migration must keep meaning what
# it meant on the day it ran, and application code is free to change.
_GRANULARITY_TO_PAIR = {
    "CUSTOMER": ("CUSTOMER", "NONE"),
    "PER_BUILDING": ("BUILDING", "NONE"),
    "PER_BUILDING_DEPARTMENT_WORK_TYPE": ("BUILDING", "DEPARTMENT_WORK_TYPE"),
}

_PAIR_TO_GRANULARITY = {
    ("CUSTOMER", "NONE"): "CUSTOMER",
    ("BUILDING", "NONE"): "PER_BUILDING",
    ("BUILDING", "DEPARTMENT_WORK_TYPE"): "PER_BUILDING_DEPARTMENT_WORK_TYPE",
}


def backfill_target_and_split(apps, schema_editor):
    Customer = apps.get_model("customers", "Customer")
    for granularity, (target, split) in _GRANULARITY_TO_PAIR.items():
        Customer.objects.filter(
            invoice_granularity_default=granularity
        ).update(invoice_billing_target=target, invoice_split=split)
    # Everything the map does not cover -> the CUSTOMER + NONE fallback,
    # matching `generate_draft_invoices`' long-standing behaviour for an
    # unrecognised granularity. Excluded rather than defaulted so the three
    # known values above are never overwritten by this sweep.
    Customer.objects.exclude(
        invoice_granularity_default__in=list(_GRANULARITY_TO_PAIR)
    ).update(invoice_billing_target="CUSTOMER", invoice_split="NONE")


def restore_granularity(apps, schema_editor):
    """Reverse: fold the pair back into the single legacy column.

    Application code keeps the two in step, so this is normally a no-op —
    but a customer edited through the new controls on a database that is
    then rolled back would otherwise keep a stale granularity, and the
    rollback would silently change how they are invoiced.
    """
    Customer = apps.get_model("customers", "Customer")
    for (target, split), granularity in _PAIR_TO_GRANULARITY.items():
        Customer.objects.filter(
            invoice_billing_target=target, invoice_split=split
        ).update(invoice_granularity_default=granularity)


class Migration(migrations.Migration):

    dependencies = [
        ("customers", "0017_sprint154_default_labels"),
    ]

    operations = [
        migrations.AddField(
            model_name="customer",
            name="invoice_billing_target",
            field=models.CharField(
                choices=[
                    ("BUILDING", "The building"),
                    ("CUSTOMER", "The customer organisation"),
                ],
                default="CUSTOMER",
                help_text=(
                    "Who the invoice is addressed to: the building, or the "
                    "customer organisation. An Extra Work with its own "
                    "`billed_to` set overrides this for that row."
                ),
                max_length=16,
            ),
        ),
        migrations.AddField(
            model_name="customer",
            name="invoice_split",
            field=models.CharField(
                choices=[
                    ("NONE", "One invoice"),
                    (
                        "DEPARTMENT_WORK_TYPE",
                        "Split by department and work type",
                    ),
                ],
                default="NONE",
                help_text=(
                    "Whether the target's work lands on one invoice or is "
                    "split by department and work type."
                ),
                max_length=32,
            ),
        ),
        migrations.AlterField(
            model_name="customer",
            name="invoice_granularity_default",
            field=models.CharField(
                choices=[
                    ("CUSTOMER", "Customer-level"),
                    ("PER_BUILDING", "Per building"),
                    (
                        "PER_BUILDING_DEPARTMENT_WORK_TYPE",
                        "Per building, department & work type",
                    ),
                ],
                default="CUSTOMER",
                help_text=(
                    "DEPRECATED (Sprint 182 §3) as an INPUT — read "
                    "`invoice_billing_target` + `invoice_split` instead. "
                    "Still written, kept exactly in step with the pair by "
                    "`billing_target.sync_legacy_granularity`, because "
                    "`Invoice.granularity` records it per invoice and "
                    "`state_machine._resync_invoice_group_labels` keys off "
                    "that vocabulary. Do not read it to decide behaviour; "
                    "do not let it drift."
                ),
                max_length=40,
            ),
        ),
        migrations.RunPython(backfill_target_and_split, restore_granularity),
    ]
