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
migrations there would be an ADDITIONAL window in which the table has no
name uniqueness of any kind — not even the old one — so keeping them
together is strictly better than not.

It does NOT eliminate the window, and this docstring previously read as
if it did. Be honest about what remains:

  Between 0023 applied and 0025 applied, every pre-existing row has
  `company IS NULL`. Postgres never treats rows with a NULL in an
  indexed column as duplicates of each other, which is exactly why the
  new constraint is safe to ADD here — every legacy row passes it — but
  it is the same property that makes the constraint toothless for those
  rows in the interval. A row inserted against a NULL-company neighbour
  is not blocked. The old platform-wide `unique=True` is already gone by
  then, so nothing else is guarding the name either.

  Normally that interval is the few milliseconds between three
  operations of one `migrate` run. It becomes PERMANENT if 0024 ABORTS —
  which is not an edge case but a designed outcome: 0024 raises on an
  ambiguous or colliding backfill and expects the operator to reconcile
  the data by hand and re-run. The DB then sits at 0023 for as long as
  that takes, with a nullable company column and no effective name
  uniqueness.

  This is acceptable because the deploy takes downtime and the write
  paths are admin-only, not because the window is absent. If this ever
  has to run against live traffic, the interval needs a real guard (a
  partial unique index on `name WHERE company_id IS NULL`, or a
  maintenance lock), not a re-reading of this paragraph.

The constraint starts biting the moment 0024 assigns companies — which
is intentional, and why 0024 pre-checks for normalized-name collisions
itself rather than letting Postgres surface a bare IntegrityError.
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
