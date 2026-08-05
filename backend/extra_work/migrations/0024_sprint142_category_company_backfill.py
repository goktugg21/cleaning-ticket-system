"""
Sprint 142 — backfill `ServiceCategory.company` for legacy rows.

The data step between 0023 (nullable column + per-company uniqueness
constraint) and 0025 (NOT NULL). Shaped after
`0019_sprint123_managed_unit_backfill` and
`0008_sprint3b_service_company_backfill`, including their central rule:
**abort on ambiguity, never guess.**

Backfill rules, per pending (company IS NULL) category:

  1. Collect the DISTINCT `company_id`s of the category's `Service`
     rows.
       * Exactly ONE → assign it.
       * TWO OR MORE → **abort** with `RuntimeError`. A category holding
         two providers' services has no single owner, and picking one
         would silently hand the other provider's services to a catalog
         grouping they cannot see, edit, or archive. The operator splits
         it manually (one category per provider, repoint each Service),
         then re-runs `migrate`.
       * ZERO services → pin to the sole `Company` if the DB has exactly
         one; otherwise **abort**. A zero-service category carries no
         ownership signal at all, so with 2+ companies there is nothing
         to infer from.

  2. Already-assigned categories are skipped, so the function is
     idempotent and a re-run after a manual fix lands cleanly.

Why guessing is wrong here rather than merely imprecise: `company` is
not a label, it is the SCOPE boundary. `filter_categories_for` reads it
to decide who may see the row, and `_enforce_catalog_management` reads
it to decide who may archive it — and Sprint 138's archive CASCADES to
every service inside. A wrong guess therefore both hides a category from
its real owner and hands a working "deactivate all these services"
button to a different provider. There is no post-hoc signal that would
reveal the mistake; the row simply looks like it always belonged to
whoever the migration picked. An abort costs one manual `UPDATE`.

Collision pre-check: pre-142 `name` was unique platform-wide by EXACT
match, while the new constraint normalizes with `Lower(Trim(...))`. So
"Cleaning" and "cleaning " could both exist legally before this
migration and would collide the moment they land in the same company.
That is checked up front, per company, and reported as a clean abort
naming both rows — otherwise Postgres would surface a bare
`IntegrityError` on the constraint added in 0023, which tells the
operator nothing about which two rows to reconcile.

Reverse is a no-op, mirroring 0008 / 0019: nulling the column back out
is risky once operators have created categories through the API.
"""
from __future__ import annotations

from collections import defaultdict

from django.db import migrations


def _abort(message: str) -> RuntimeError:
    """Stable preamble so operators can grep for `[Sprint 142 backfill]`
    to find this migration from a failed `migrate` run."""
    return RuntimeError(
        "[Sprint 142 backfill] " + message + " Reconcile the data "
        "manually, then re-run `python manage.py migrate`."
    )


def _normalize(name: str) -> str:
    """The SAME normalization the DB constraint applies
    (`Lower(Trim(name))`), so this pre-check and the constraint can
    never disagree about what counts as a collision."""
    return (name or "").strip().lower()


def backfill_category_company(apps, schema_editor):
    ServiceCategory = apps.get_model("extra_work", "ServiceCategory")
    Service = apps.get_model("extra_work", "Service")
    Company = apps.get_model("companies", "Company")

    pending = list(
        ServiceCategory.objects.filter(company_id__isnull=True).only(
            "id", "name"
        )
    )
    if not pending:
        return

    company_ids = list(Company.objects.values_list("id", flat=True))
    if not company_ids:
        # Category rows but zero Company rows — only reachable if
        # migrations are reordered. Abort rather than fabricate one.
        raise _abort(
            "ServiceCategory rows exist but no Company rows. Create at "
            "least one Company before applying this migration."
        )

    # Pass 1 — resolve an owner for every pending category, or abort.
    resolved: dict[int, int] = {}
    for category in pending:
        owner_ids = set(
            Service.objects.filter(category_id=category.id)
            .values_list("company_id", flat=True)
            .distinct()
        )
        owner_ids.discard(None)

        if len(owner_ids) == 1:
            resolved[category.id] = next(iter(owner_ids))
            continue

        if len(owner_ids) >= 2:
            raise _abort(
                f"ServiceCategory id={category.id} ({category.name!r}) "
                f"holds Service rows owned by {len(owner_ids)} different "
                f"Companies ({sorted(owner_ids)}). Split it manually — "
                "one category per provider, repoint each Service — "
                "before re-running."
            )

        # Zero services: no ownership signal on the row itself.
        if len(company_ids) == 1:
            resolved[category.id] = company_ids[0]
            continue
        raise _abort(
            f"ServiceCategory id={category.id} ({category.name!r}) has "
            f"no Service rows and the DB has {len(company_ids)} Company "
            "rows, so its owner cannot be inferred. Pin it to a Company "
            "manually (or delete it if it is unused)."
        )

    # Pass 2 — collision pre-check BEFORE writing anything. Compare each
    # resolved assignment against both its new siblings and any category
    # already sitting in that company.
    by_company: dict[int, dict[str, str]] = defaultdict(dict)
    for existing in ServiceCategory.objects.filter(
        company_id__isnull=False
    ).only("id", "name", "company_id"):
        by_company[existing.company_id][_normalize(existing.name)] = (
            f"id={existing.id} ({existing.name!r})"
        )
    for category in pending:
        company_id = resolved[category.id]
        key = _normalize(category.name)
        clash = by_company[company_id].get(key)
        if clash is not None:
            raise _abort(
                f"ServiceCategory id={category.id} ({category.name!r}) "
                f"and {clash} would both land in Company id="
                f"{company_id} and collide under the new "
                "case/whitespace-insensitive per-company uniqueness "
                "constraint. Rename or merge one of them "
                "(pre-142 uniqueness was EXACT-match platform-wide, so "
                "both were legal)."
            )
        by_company[company_id][key] = f"id={category.id} ({category.name!r})"

    # Pass 3 — write. Per-row `save()` (not a queryset `.update()`):
    # historical models fire no signals either way, but the per-row shape
    # matches 0008/0019 and keeps the abort semantics above meaningful.
    for category in pending:
        category.company_id = resolved[category.id]
        category.save(update_fields=["company"])


def reverse_noop(apps, schema_editor):
    # Intentional no-op — see module docstring.
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("extra_work", "0023_sprint142_category_company_nullable"),
    ]

    operations = [
        migrations.RunPython(
            backfill_category_company,
            reverse_noop,
        ),
    ]
