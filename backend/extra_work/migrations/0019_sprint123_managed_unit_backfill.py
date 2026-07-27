"""
Sprint 123 — backfill `ManagedUnit` rows from existing free-text
`custom_unit_label` values, per provider company, then point the
originating `Service` / `CustomerCustomPrice` rows at them.

Scope: `Service` (direct `company` FK) and `CustomerCustomPrice`
(company reached via `customer.company`) ONLY. `ProposalLine` is
deliberately excluded — see `extra_work/models.py::ManagedUnit`'s
docstring; a Proposal is a frozen customer-facing document and its
`unit_type`/label are explicitly denormalised at create time.

Algorithm, per company:
  1. Collect every non-blank `custom_unit_label` from `unit_type=OTHER`
     rows on BOTH models owned by this company (Service directly,
     CustomerCustomPrice via `customer__company`), each tagged with its
     raw spelling + `created_at`.
  2. Group by a normalized dedupe key: `label.strip().lower()` — the
     SAME normalization the model's `Lower(Trim("label"))` DB
     constraint enforces, so the backfill and the constraint can never
     disagree about what counts as "the same unit".
  3. For each group with 2+ distinct raw spellings, pick ONE winner to
     become the new `ManagedUnit.label` (the original text on existing
     rows is untouched either way): the MOST FREQUENT raw spelling
     (by row count across both models); ties broken by the EARLIEST
     `created_at` among that spelling's rows; further ties (identical
     timestamps) broken by plain string sort, so the outcome is fully
     deterministic given the same DB state.
  4. Create one `ManagedUnit` per normalized key (skipping any that
     already exist for this company under an equivalent normalized
     label — idempotent re-apply), then set `managed_unit` on every
     contributing row that doesn't already have one set.

The original `custom_unit_label` text is NEVER cleared or rewritten —
this migration only ADDS the FK. Safe on an empty DB (both queries
return nothing; the per-company loop is a no-op for a company with no
OTHER rows).
"""
from __future__ import annotations

from collections import Counter, defaultdict

from django.db import migrations


def _normalize(label: str) -> str:
    return label.strip().lower()


def backfill_managed_units(apps, schema_editor):
    Company = apps.get_model("companies", "Company")
    Service = apps.get_model("extra_work", "Service")
    CustomerCustomPrice = apps.get_model("extra_work", "CustomerCustomPrice")
    ManagedUnit = apps.get_model("extra_work", "ManagedUnit")

    for company in Company.objects.all():
        service_rows = list(
            Service.objects.filter(company=company, unit_type="OTHER")
            .exclude(custom_unit_label="")
            .only("id", "custom_unit_label", "created_at", "managed_unit_id")
        )
        ccp_rows = list(
            CustomerCustomPrice.objects.filter(
                customer__company=company, unit_type="OTHER"
            )
            .exclude(custom_unit_label="")
            .only("id", "custom_unit_label", "created_at", "managed_unit_id")
        )
        if not service_rows and not ccp_rows:
            continue

        # Reuse any ManagedUnit rows this company already has (idempotent
        # re-apply, and defensive in case a unit was hand-created between
        # migration runs).
        key_to_unit = {
            _normalize(u.label): u
            for u in ManagedUnit.objects.filter(company=company)
        }

        # occurrences[normalized_key] = [(raw_label, created_at), ...]
        occurrences = defaultdict(list)
        for row in service_rows + ccp_rows:
            key = _normalize(row.custom_unit_label)
            if key:
                occurrences[key].append((row.custom_unit_label, row.created_at))

        for norm_key, occ in occurrences.items():
            if norm_key in key_to_unit:
                continue
            freq = Counter(raw for raw, _created in occ)
            max_freq = max(freq.values())
            tied = sorted(raw for raw, count in freq.items() if count == max_freq)
            if len(tied) == 1:
                winner = tied[0]
            else:
                earliest = {}
                for raw, created_at in occ:
                    if raw in tied and (
                        raw not in earliest or created_at < earliest[raw]
                    ):
                        earliest[raw] = created_at
                winner = min(tied, key=lambda r: (earliest[r], r))
            key_to_unit[norm_key] = ManagedUnit.objects.create(
                company=company, label=winner, is_active=True,
            )

        for row in service_rows:
            if row.managed_unit_id is None:
                key = _normalize(row.custom_unit_label)
                row.managed_unit = key_to_unit[key]
                row.save(update_fields=["managed_unit"])
        for row in ccp_rows:
            if row.managed_unit_id is None:
                key = _normalize(row.custom_unit_label)
                row.managed_unit = key_to_unit[key]
                row.save(update_fields=["managed_unit"])


def reverse_noop(apps, schema_editor):
    # Intentional no-op — mirrors 0008_sprint3b_service_company_backfill's
    # reverse. Nulling managed_unit + deleting ManagedUnit rows back out on
    # rollback is risky once operators have created/edited units via the API.
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("extra_work", "0018_managedunit_customercustomprice_managed_unit_and_more"),
    ]

    operations = [
        migrations.RunPython(
            backfill_managed_units,
            reverse_noop,
        ),
    ]
