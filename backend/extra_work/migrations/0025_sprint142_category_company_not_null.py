"""
Sprint 142 — flip `ServiceCategory.company` to NOT NULL after the 0024
backfill has populated every row.

If 0024 aborted (a category spanning two providers, a zero-service
category in a multi-company DB, or a normalized-name collision), the
operator resolves the data and re-runs `migrate`. 0024 is idempotent, so
a clean run lands cleanly; only once every row has a non-null `company`
does the flip below succeed.

Schema-only — no data step. Mirrors
`0009_sprint3b_service_company_not_null`.
"""
from __future__ import annotations

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("extra_work", "0024_sprint142_category_company_backfill"),
    ]

    operations = [
        migrations.AlterField(
            model_name="servicecategory",
            name="company",
            field=models.ForeignKey(
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
    ]
