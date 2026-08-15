"""Sprint 182 §6 — `billed_to` becomes nullable, and the provider gets a
date of its own.

TWO changes, one migration, because they are both additive column work on
the same table and splitting them would mean two locks for no gain.

## `billed_to`: non-null BUILDING -> nullable, existing rows to NULL

NULL means "follow the customer's setting"; a set value overrides it for
that one job.

The backfill is the whole point of the migration and it is a DOWNGRADE
of information, deliberately. Sprint 180 created the column non-null
with `default="BUILDING"`, so every row that existed then says BUILDING —
but none of those rows RECORDED A DECISION, they took a default while
nothing read the column. Sprint 182 makes invoice generation read it. If
the existing values were left in place, every customer configured for
one-invoice-per-customer would silently start being invoiced per
building, because their extra works all say BUILDING.

So: every row is set to NULL. That is not data loss, it is the correct
statement — "nobody chose, ask the customer" — and it is what makes
"nobody's behaviour changes" true.

REVERSIBLE, and the reverse is honest about what it cannot know: going
back re-imposes the non-null column, so NULLs have to become something,
and BUILDING is what they were before this migration ran.

## `provider_planned_date`

Purely additive, nullable, no default and no backfill: an extra work
nobody has planned must stay distinguishable from one planned for today.
`preferred_date` (the customer's wish) is untouched.
"""
from django.db import migrations, models


def billed_to_to_null(apps, schema_editor):
    """Every pre-182 value was a default, not a decision. See the module
    docstring."""
    ExtraWorkRequest = apps.get_model("extra_work", "ExtraWorkRequest")
    ExtraWorkRequest.objects.update(billed_to=None)


def billed_to_back_to_building(apps, schema_editor):
    """Reverse: the column becomes non-null again, so every NULL needs a
    value. BUILDING is what they held before this migration."""
    ExtraWorkRequest = apps.get_model("extra_work", "ExtraWorkRequest")
    ExtraWorkRequest.objects.filter(billed_to__isnull=True).update(
        billed_to="BUILDING"
    )


class Migration(migrations.Migration):

    dependencies = [
        ("extra_work", "0031_sprint180_extraworkrequest_billed_to"),
    ]

    operations = [
        migrations.AlterField(
            model_name="extraworkrequest",
            name="billed_to",
            field=models.CharField(
                blank=True,
                choices=[("BUILDING", "Building"), ("CUSTOMER", "Customer")],
                default=None,
                help_text=(
                    "Who the finished work is charged to: the BUILDING or "
                    "the CUSTOMER organisation. NULL means follow the "
                    "customer's own setting; a value set here overrides it "
                    "for this job."
                ),
                max_length=16,
                null=True,
            ),
        ),
        # AFTER the AlterField: the column has to accept NULL before the
        # rows can be set to it.
        migrations.RunPython(
            billed_to_to_null,
            billed_to_back_to_building,
        ),
        migrations.AddField(
            model_name="extraworkrequest",
            name="provider_planned_date",
            field=models.DateField(
                blank=True,
                default=None,
                help_text=(
                    "Sprint 182 — the day the PROVIDER plans to do the "
                    "work. Distinct from `preferred_date` (the customer's "
                    "wish) and from `deadline` (when it must be "
                    "finished). NULL means nobody has planned it yet."
                ),
                null=True,
            ),
        ),
    ]
