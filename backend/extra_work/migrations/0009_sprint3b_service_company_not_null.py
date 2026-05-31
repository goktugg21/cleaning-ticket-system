"""
Sprint 3B — flip `Service.company` to NOT NULL after the 0008
backfill has populated every row.

If 0008 aborted (cross-provider Service, no inferable owner), the
operator resolves the data manually and re-runs `migrate`. 0008
is idempotent so a clean run lands cleanly; only after every row
has a non-null `company` does the schema flip below succeed.

Schema-only — no data step.
"""
from __future__ import annotations

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("extra_work", "0008_sprint3b_service_company_backfill"),
    ]

    operations = [
        migrations.AlterField(
            model_name="service",
            name="company",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                related_name="services",
                to="companies.company",
                help_text=(
                    "Sprint 3B — provider company that owns this "
                    "catalog row. Required on every API-created "
                    "Service; pre-3B legacy rows are backfilled "
                    "via migration 0008."
                ),
            ),
        ),
    ]
