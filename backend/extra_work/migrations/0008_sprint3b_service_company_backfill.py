"""
Sprint 3B — backfill `Service.company` for legacy rows.

Pre-Sprint-3B the service catalog was global (no provider FK).
Sprint 3B introduces `Service.company` so every catalog row is
owned by exactly one provider company. This migration is the
data step between:

  * 0007 — schema: add nullable `Service.company`, drop the old
    global `(category, name)` UNIQUE, add the new
    `(company, category, name)` UNIQUE.
  * 0009 — schema: flip `Service.company` to NOT NULL after this
    backfill has succeeded (or aborted clean).

Backfill rules (mirrored verbatim in `forwards` below):

  1. If exactly ONE `Company` row exists in the DB, assign every
     legacy Service to that single Company. This is the expected
     production state (single-tenant pilot).

  2. Otherwise, infer per-row from `CustomerServicePrice`:
       * If a Service has CSP rows for customers under exactly ONE
         Company → assign that Company.
       * If a Service has CSP rows for customers under TWO OR MORE
         Companies → **abort** with `RuntimeError`. The cross-
         provider Service must be resolved manually (duplicate the
         Service per provider and remap each CSP). The migration
         must not pick a winner autonomously.
       * If a Service has NO CSP rows AND the DB has TWO OR MORE
         Companies → **abort** with `RuntimeError`. There is no
         deterministic owner; an operator must manually pin the
         Service to a Company before re-running the migration.

  3. Already-assigned Services (company already non-null) are
     skipped — the function is idempotent on re-apply.

A clean abort is preferred over a silent wrong assignment. The
operator can fix the data (e.g. manual `UPDATE extra_work_service
SET company_id = N WHERE id = M`), then `python manage.py migrate`
re-runs this step and lands cleanly.

Reverse migration is a no-op (mirrors the prior data-migration
shape in this app): nulling the column back out on rollback is
risky once operators have started creating Services via the API
with company set.
"""
from __future__ import annotations

from django.db import migrations


def _ambiguous(message: str) -> RuntimeError:
    """Build a RuntimeError with a stable preamble so operators can
    grep for `[Sprint 3B backfill]` to find the migration source."""
    return RuntimeError(
        "[Sprint 3B backfill] " + message + " Reconcile the data "
        "manually, then re-run `python manage.py migrate`."
    )


def backfill_service_company(apps, schema_editor):
    Service = apps.get_model("extra_work", "Service")
    CustomerServicePrice = apps.get_model(
        "extra_work", "CustomerServicePrice"
    )
    Company = apps.get_model("companies", "Company")

    pending = list(
        Service.objects.filter(company_id__isnull=True).only(
            "id", "name", "category_id"
        )
    )
    if not pending:
        return

    company_ids = list(Company.objects.values_list("id", flat=True))
    if len(company_ids) == 1:
        # Single-tenant fast path: pin every legacy Service to the
        # only provider company.
        single_id = company_ids[0]
        for service in pending:
            service.company_id = single_id
        Service.objects.bulk_update(pending, ["company_id"])
        return

    if not company_ids:
        # The DB has Service rows but zero Company rows — extreme
        # edge case (only reachable if migrations are reordered).
        # Abort rather than fabricate a Company.
        raise _ambiguous(
            "Service rows exist but no Company rows. Create at "
            "least one Company before applying this migration."
        )

    # Multi-tenant inference path: ask CustomerServicePrice for each
    # pending Service which Companies its customers fall under.
    for service in pending:
        customer_company_ids = set(
            CustomerServicePrice.objects.filter(service_id=service.id)
            .values_list("customer__company_id", flat=True)
            .distinct()
        )
        # Drop any spurious None caused by raw SQL inserts during
        # migrations (shouldn't happen, but be defensive).
        customer_company_ids.discard(None)

        if len(customer_company_ids) == 1:
            service.company_id = next(iter(customer_company_ids))
            service.save(update_fields=["company"])
            continue

        if len(customer_company_ids) >= 2:
            raise _ambiguous(
                f"Service id={service.id} ({service.name!r}) has "
                f"CustomerServicePrice rows for customers under "
                f"{len(customer_company_ids)} different Companies "
                f"({sorted(customer_company_ids)}). Split the row "
                "manually (one Service per provider, remap each "
                "CustomerServicePrice) before re-running."
            )

        # No CSP rows for this Service: zero-signal multi-tenant
        # case. Cannot infer.
        raise _ambiguous(
            f"Service id={service.id} ({service.name!r}) has no "
            f"CustomerServicePrice rows and the DB has "
            f"{len(company_ids)} Company rows. The owner cannot "
            "be inferred."
        )


def reverse_noop(apps, schema_editor):
    # Intentional no-op. See module docstring.
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("extra_work", "0007_sprint3b_service_company_nullable"),
    ]

    operations = [
        migrations.RunPython(
            backfill_service_company,
            reverse_noop,
        ),
    ]
