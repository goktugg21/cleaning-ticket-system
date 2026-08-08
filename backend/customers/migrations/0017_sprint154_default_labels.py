"""Sprint 154 §I.7 — every customer gets an "Algemeen" Department and
WorkType.

Data-only. The forward pass provisions the pair for every EXISTING
customer that is missing either one; `customers.signals
._auto_create_default_labels` covers every customer created afterwards.

Why this backfill is required and not merely tidy: §I.7 makes both
labels mandatory on the Extra Work form. A customer whose label list is
EMPTY is precisely the case that makes a required field un-fillable, so
without this pass the change would brick Extra Work creation for every
customer that had never had labels defined — which, per the Sprint 127
notes, is most of them (one real customer has twelve departments and
ZERO work types).

Case-insensitive existence check, matching the model's
`UniqueConstraint(Lower(Trim(name)), customer)`: a customer that already
calls their catch-all "algemeen" or "Algemeen " keeps that row and does
not gain a duplicate the constraint would reject.

The reverse pass is deliberately a NO-OP. Deleting the labels on reverse
would either fail against `ExtraWorkRequest`'s PROTECT (once anything
references them) or silently strip a label an operator has since renamed
and adopted as their own. Un-applying this migration leaves the rows in
place, which is harmless.
"""
from django.db import migrations


DEFAULT_LABEL_NAME = "Algemeen"


def provision_default_labels(apps, schema_editor):
    Customer = apps.get_model("customers", "Customer")
    Department = apps.get_model("customers", "Department")
    WorkType = apps.get_model("customers", "WorkType")

    for model in (Department, WorkType):
        # One query per model for the "already has one" set, rather than
        # one query per customer per model.
        have_it = set(
            model.objects.filter(name__iexact=DEFAULT_LABEL_NAME).values_list(
                "customer_id", flat=True
            )
        )
        missing = Customer.objects.exclude(id__in=have_it).values_list(
            "id", flat=True
        )
        model.objects.bulk_create(
            [
                model(customer_id=customer_id, name=DEFAULT_LABEL_NAME, description="")
                for customer_id in missing
            ],
            batch_size=500,
        )


def noop_reverse(apps, schema_editor):
    """See the module docstring: reversing must not delete labels."""


class Migration(migrations.Migration):

    dependencies = [
        ("customers", "0016_alter_customer_invoice_granularity_default"),
    ]

    operations = [
        migrations.RunPython(provision_default_labels, noop_reverse),
    ]
