"""
Sprint 142 — schema step 1 of 3 for per-company service categories.

Mirrors the `Service.company` precedent exactly (`0007` nullable →
`0008` backfill → `0009` NOT NULL), for the same reason: a NOT NULL FK
cannot be added to a table that already has rows.

Three operations, and the ORDER matters:

  1. `AddField` `ServiceCategory.company`, **nullable** — 0024 fills it,
     0025 flips it NOT NULL.
  2. `AlterField` `name` to drop `unique=True`. This is a FIELD-level
     `unique=True`, not a `Meta.constraints` entry, so Django emits an
     `AlterField` that drops the implicit
     `extra_work_servicecategory_name_key` — NOT a `RemoveConstraint`.
  3. `AddConstraint` the per-company replacement.

(2) and (3) are in the SAME migration deliberately. Split across two
migrations there would be a window — however brief, and permanent if a
`migrate` run is interrupted between them — in which the table has NO
name uniqueness at all and two providers could insert colliding rows
that the new constraint could then never be applied over.

The new constraint is safe to add while `company` is still NULL on every
existing row: Postgres never treats rows with a NULL in an indexed
column as duplicates of each other, so every legacy row passes. It
starts biting the moment 0024 assigns companies — which is intentional,
and why 0024 pre-checks for normalized-name collisions itself rather
than letting Postgres surface a bare IntegrityError.
"""
from __future__ import annotations

import django.db.models.deletion
import django.db.models.functions.text
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("companies", "0005_company_logo"),
        ("extra_work", "0022_extraworkrequestitem_snapshot_customer_custom_price"),
    ]

    operations = [
        migrations.AddField(
            model_name="servicecategory",
            name="company",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="service_categories",
                to="companies.company",
                help_text=(
                    "Sprint 142 — provider company that owns this "
                    "category. Pre-142 rows are backfilled from the "
                    "single company of their services by migration 0024."
                ),
            ),
        ),
        migrations.AlterField(
            model_name="servicecategory",
            name="name",
            field=models.CharField(max_length=128),
        ),
        migrations.AddConstraint(
            model_name="servicecategory",
            constraint=models.UniqueConstraint(
                django.db.models.functions.text.Lower(
                    django.db.models.functions.text.Trim("name")
                ),
                models.F("company"),
                name="uniq_service_category_name_per_company_ci",
            ),
        ),
    ]
