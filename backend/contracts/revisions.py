"""
Sprint 160 — resolving WHICH revision of a contract is in force on a
date.

One public function, `active_revision(contract, on=None)`, plus the
queryset-level helpers the list endpoints use so a page of contracts
does not resolve N revisions with N queries.

The resolution rule, and why it is this one:

    The active revision is the one with the LATEST `effective_from`
    that is still <= the target date. Ties (two revisions authored for
    the same day) break on `-id`, so the most recently created row
    wins.

That is the same discipline `extra_work.pricing.resolve_price` applies
to `CustomerServicePrice` validity windows, and it is copied
deliberately rather than reinvented: "the latest agreement at or before
this date is the current agreement" is a rule operators already rely on
elsewhere in this system, and two different answers to the same
question would be a bug that only shows up in money.

It imports nothing from `extra_work`. Different module, different
entity, same discipline.

**There is no `is_active` flag and there must never be one.** A stored
flag can contradict the dates; a derived answer cannot. This is the
same reasoning `Contract.lifecycle` follows for EXPIRED.

A date BEFORE the contract's first revision resolves to `None` — not
to the first revision. That is a real answer, not a failure: the
contract had no agreed scope before it was agreed, and a forecast for
such a date must produce nothing rather than silently borrow the
future's prices.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Optional

from django.db.models import Count, DecimalField, Sum
from django.db.models.functions import Coalesce
from django.utils import timezone

from .models import ContractRevision


def active_revision(contract, on: Optional[date] = None):
    """The `ContractRevision` in force for `contract` on `on`
    (default: today, in the deployment's local timezone).

    Returns `None` when the date precedes every revision.
    """
    target = on or timezone.localdate()
    return (
        ContractRevision.objects.filter(
            contract=contract, effective_from__lte=target
        )
        .order_by("-effective_from", "-id")
        .first()
    )


def display_revision(contract, on: Optional[date] = None):
    """The revision the UI should SHOW for a contract — the active one,
    or the earliest one when the contract has not started yet.

    Deliberately a SECOND function rather than a softening of
    `active_revision`, because the two answer different questions and
    only one of them is allowed to be generous:

      * `active_revision` answers "what was agreed as of this date",
        and money is computed against it. It must return `None` before
        the first revision — a period the contract did not yet cover
        earns nothing, and borrowing the future's prices would silently
        invent revenue. `contracts/billing.py` depends on that.
      * this one answers "what should the contract's header card say",
        and a contract signed today to start in March is worth
        something to an operator looking at it now. Returning nothing
        there would show a real contract as EUR 0.00.

    Keeping them apart is what lets the strict rule stay strict.
    """
    resolved = active_revision(contract, on=on)
    if resolved is not None:
        return resolved
    return (
        ContractRevision.objects.filter(contract=contract)
        .order_by("effective_from", "id")
        .first()
    )


def display_revision_ids(contract_ids, on: Optional[date] = None) -> dict:
    """`{contract_id: revision_id}` for the DISPLAY rule, in one query.

    The batch form of `display_revision`, used by the list page for the
    same reason `active_revision_ids` exists: one query for the page
    instead of one per row.
    """
    ids = list(contract_ids)
    if not ids:
        return {}
    target = on or timezone.localdate()
    resolved: dict = dict(active_revision_ids(ids, on=target))
    missing = [cid for cid in ids if cid not in resolved]
    if not missing:
        return resolved
    # Contracts that have not started yet: fall back to the EARLIEST
    # revision. Same one-ordered-fetch shape as `active_revision_ids`,
    # with the ordering reversed.
    for rev_id, contract_id in (
        ContractRevision.objects.filter(contract_id__in=missing)
        .order_by("contract_id", "effective_from", "id")
        .values_list("id", "contract_id")
    ):
        resolved.setdefault(contract_id, rev_id)
    return resolved


def active_revision_ids(contract_ids, on: Optional[date] = None) -> dict:
    """`{contract_id: revision_id}` for many contracts in ONE query.

    The list endpoints resolve every row's active revision through this
    rather than calling `active_revision` per contract — the difference
    between a constant query count and a per-row one. The selection
    rule is identical (latest `effective_from` <= date, `-id` tie-break)
    because it is applied to the same ordering in Python, over one
    ordered fetch, rather than restated as a second SQL expression that
    could drift from the first.
    """
    ids = list(contract_ids)
    if not ids:
        return {}
    target = on or timezone.localdate()
    resolved: dict = {}
    for rev_id, contract_id in (
        ContractRevision.objects.filter(
            contract_id__in=ids, effective_from__lte=target
        )
        .order_by("contract_id", "-effective_from", "-id")
        .values_list("id", "contract_id")
    ):
        # First row seen per contract wins — the ordering above already
        # put the latest effective_from (then highest id) first.
        resolved.setdefault(contract_id, rev_id)
    return resolved


def annotate_revision_totals(queryset):
    """Annotate a `ContractRevision` queryset with its line totals.

    `annotated_amount` (money for one billing period),
    `annotated_hours`, `annotated_line_count`. Computed from the lines
    on every read — never stored. A stored total is a second copy of a
    number that already exists, and the copy is what drifts.

    `Coalesce(..., 0)` so a revision with no lines annotates 0.00 and
    not NULL: the API contract is a number, and a caller should not
    have to know the difference between "no lines" and "unknown".
    """
    return queryset.annotate(
        annotated_amount=Coalesce(
            Sum("lines__amount"),
            Decimal("0.00"),
            output_field=DecimalField(max_digits=14, decimal_places=2),
        ),
        annotated_hours=Coalesce(
            Sum("lines__hours"),
            Decimal("0.00"),
            output_field=DecimalField(max_digits=12, decimal_places=2),
        ),
        annotated_line_count=Count("lines", distinct=True),
    )


def revision_totals(revision) -> dict:
    """The same three totals for ONE already-loaded revision.

    Reads the annotations when `annotate_revision_totals` put them
    there, and falls back to an aggregate otherwise, so a caller that
    holds a plain instance gets the same numbers as a caller that came
    through the annotated queryset.
    """
    if revision is None:
        return {
            "amount": Decimal("0.00"),
            "hours": Decimal("0.00"),
            "line_count": 0,
        }
    if hasattr(revision, "annotated_amount"):
        return {
            "amount": revision.annotated_amount,
            "hours": revision.annotated_hours,
            "line_count": revision.annotated_line_count,
        }
    agg = revision.lines.aggregate(
        amount=Coalesce(
            Sum("amount"),
            Decimal("0.00"),
            output_field=DecimalField(max_digits=14, decimal_places=2),
        ),
        hours=Coalesce(
            Sum("hours"),
            Decimal("0.00"),
            output_field=DecimalField(max_digits=12, decimal_places=2),
        ),
        line_count=Count("id", distinct=True),
    )
    return agg


def contract_has_been_invoiced(contract_id) -> bool:
    """Has any period of this contract ever been billed?

    One existence query. `ContractInvoice` is the claim the generator
    writes, so this is the same fact the generator uses to refuse a
    second run — not a second opinion about it.
    """
    from .models import ContractInvoice

    return ContractInvoice.objects.filter(contract_id=contract_id).exists()


def is_locked(
    revision,
    on: Optional[date] = None,
    *,
    contract_invoiced: Optional[bool] = None,
) -> bool:
    """True when `revision` may no longer be edited.

    Two conditions, and W11 added the second one after the first ate the
    feature.

    A future-dated revision stays open. That is the whole point of being
    able to author one ahead of time, and it is unchanged.

    A revision whose date has ARRIVED closes ONCE THE CONTRACT HAS BEEN
    INVOICED. The reason the rule exists is that money has been computed
    against what was agreed; before the first invoice, no money has been
    computed, so there is nothing for an edit to contradict.

    Closing on the date alone — which is what this did — made the app
    unusable in its most ordinary case and was reported as two separate
    bugs for six waves:

      * A contract starts today, so its first revision is effective
        today, so it is born locked. No line can ever be added to it and
        the contract is permanently worth EUR 0.00. Reported as "a
        Project cannot be added to a new contract".
      * The detail page only edits the revision in force TODAY. A
        revision authored for next month is correctly open but is not in
        force, so the page looks identical after creating one. Reported
        as "Create Revision does nothing".

    Both are this one line. The protection is not weakened: the moment a
    period is billed, every past-dated revision of that contract closes
    exactly as before, and the correction path is still a new revision.

    `contract_invoiced` lets a caller that already knows the answer for a
    whole contract pass it in, so serializing N revisions is one query
    rather than N.
    """
    if revision is None:
        return False
    target = on or timezone.localdate()
    if revision.effective_from > target:
        return False
    if contract_invoiced is None:
        contract_invoiced = contract_has_been_invoiced(revision.contract_id)
    return contract_invoiced
