"""
Sprint 8B — final billable-amount computation for Extra Work.

A finished Extra Work job is billed on the ACTUAL work performed, not
on the originally-ordered quantity. For HOURS-unit lines the provider
enters `actual_hours` after the work is done; the final amount uses
those hours instead of the ordered `quantity`. Every other unit type
(FIXED / ITEM / SQUARE_METERS / OTHER) bills at the ordered quantity.

The fragmented Extra Work pricing surface means "the lines that
produced the operational ticket" differs by route:

  * PROPOSAL route   -> the approved Proposal's lines (the operator-
                        typed `unit_price` / `vat_pct`).
  * INSTANT route    -> the cart `ExtraWorkRequestItem` rows (their
                        `snapshot_unit_price` / `snapshot_vat_pct`).
  * legacy route     -> the `ExtraWorkPricingLineItem` rows
                        (`unit_price` / `vat_rate`).

`active_priced_lines` resolves which set is authoritative for a given
EW; the per-line price/vat/unit-type accessors below paper over the
model differences. None of these helpers EVER mutate `quantity`,
`unit_price`, `snapshot_*`, `vat_*` — they only read.
"""
from __future__ import annotations

from decimal import Decimal
from typing import List, Tuple

from .models import (
    ExtraWorkPricingUnitType,
    ExtraWorkRequest,
    ProposalStatus,
    _two_places,
)


# Stable `kind` tags returned by `active_priced_lines`.
KIND_PROPOSAL = "proposal"
KIND_CART = "cart"
KIND_LEGACY = "legacy"


def _line_unit_type(line) -> str:
    """Read the line's denormalised unit type as a plain string. All
    three line models carry `unit_type` (cart + proposal) or, for the
    legacy pricing line, `unit_type` as well."""
    return str(getattr(line, "unit_type", ""))


def _line_unit_price(kind: str, line) -> Decimal:
    """Per-line unit price, normalised across the three line models.

    A cart line that never resolved to a contract (NEEDS_PROVIDER_PRICING
    / AD_HOC) carries `snapshot_unit_price is None`. That case never
    occurs on the INSTANT branch (INSTANT requires every line to resolve
    to a contract), but we guard defensively and treat a None price as
    contributing 0 to the subtotal."""
    if kind == KIND_CART:
        price = line.snapshot_unit_price
        return price if price is not None else Decimal("0")
    # proposal + legacy both expose `unit_price`.
    return line.unit_price


def _line_vat_pct(kind: str, line) -> Decimal:
    """Per-line VAT percent, normalised across the three line models."""
    if kind == KIND_CART:
        vat = line.snapshot_vat_pct
        return vat if vat is not None else Decimal("0")
    if kind == KIND_LEGACY:
        return line.vat_rate
    return line.vat_pct  # proposal


def billable_quantity(line) -> Decimal:
    """Quantity to bill for `line`.

    HOURS-unit lines with `actual_hours` set bill the actual hours;
    everything else bills the ordered `quantity`. NEVER mutates the
    line.

    All three line models carry `actual_hours` since P-13 I (the
    legacy `ExtraWorkPricingLineItem` deliberately lacked it under the
    Sprint 8B brief; the owner approved the additive column on
    2026-09-02). The `getattr` default stays as a guard for any
    non-model line object handed in by tests."""
    actual_hours = getattr(line, "actual_hours", None)
    if (
        _line_unit_type(line) == ExtraWorkPricingUnitType.HOURS
        and actual_hours is not None
    ):
        return actual_hours
    return line.quantity


def active_priced_lines(ew: ExtraWorkRequest) -> Tuple[str, List]:
    """Resolve the line set that produced (or will produce) the EW's
    operational ticket, plus a stable `kind` tag.

    Resolution order:
      1. A `CUSTOMER_APPROVED` Proposal exists -> its
         `is_approved_for_spawn` lines (latest approved proposal wins).
      2. `routing_decision == INSTANT` -> the cart line items.
      3. otherwise -> the legacy `ExtraWorkPricingLineItem` rows.
    """
    from .models import ExtraWorkRoutingDecision

    approved_proposal = (
        ew.proposals.filter(status=ProposalStatus.CUSTOMER_APPROVED)
        .order_by("-customer_decided_at", "-id")
        .first()
    )
    if approved_proposal is not None:
        lines = list(
            approved_proposal.lines.filter(is_approved_for_spawn=True).order_by(
                "id"
            )
        )
        return KIND_PROPOSAL, lines

    if ew.routing_decision == ExtraWorkRoutingDecision.INSTANT:
        return KIND_CART, list(ew.line_items.all().order_by("id"))

    return KIND_LEGACY, list(ew.pricing_line_items.all().order_by("id"))


def recompute_final_amounts(ew: ExtraWorkRequest) -> None:
    """Recompute and persist `ew.final_subtotal_amount` /
    `final_vat_amount` / `final_total_amount` from the active priced-
    line set, honouring `actual_hours` on hourly lines.

    Per-line: subtotal += two_places(billable_quantity * unit_price);
    vat += two_places(line_subtotal * vat_pct / 100). The totals are
    each quantized to 2 places. Mirrors `ExtraWorkRequest.recompute_
    totals` / the per-line `save()` rounding so the final amount lines
    up with the displayed quote when actual_hours == quantity.
    """
    kind, lines = active_priced_lines(ew)

    subtotal = Decimal("0.00")
    vat = Decimal("0.00")
    for line in lines:
        unit_price = _line_unit_price(kind, line)
        vat_pct = _line_vat_pct(kind, line)
        line_subtotal = _two_places(billable_quantity(line) * unit_price)
        line_vat = _two_places(line_subtotal * vat_pct / Decimal("100"))
        subtotal += line_subtotal
        vat += line_vat

    ew.final_subtotal_amount = _two_places(subtotal)
    ew.final_vat_amount = _two_places(vat)
    ew.final_total_amount = _two_places(subtotal + vat)
    ew.save(
        update_fields=[
            "final_subtotal_amount",
            "final_vat_amount",
            "final_total_amount",
            "updated_at",
        ]
    )


def quoted_totals(
    ew: ExtraWorkRequest,
) -> Tuple[Decimal, Decimal, Decimal]:
    """Sprint 187 §1 — the QUOTED `(subtotal, vat, total)` for `ew`,
    computed and returned, never written.

    Split out from `recompute_quoted_totals` so the backfill command can
    show an operator what a `--dry-run` would write without writing it,
    from THIS function rather than from a second copy of the formula.
    """
    kind, lines = active_priced_lines(ew)

    subtotal = Decimal("0.00")
    vat = Decimal("0.00")
    for line in lines:
        unit_price = _line_unit_price(kind, line)
        vat_pct = _line_vat_pct(kind, line)
        # ORDERED quantity — never `billable_quantity(line)`. See the
        # docstring on `recompute_quoted_totals` below for why.
        line_subtotal = _two_places(line.quantity * unit_price)
        line_vat = _two_places(line_subtotal * vat_pct / Decimal("100"))
        subtotal += line_subtotal
        vat += line_vat

    return (
        _two_places(subtotal),
        _two_places(vat),
        _two_places(subtotal + vat),
    )


def recompute_quoted_totals(ew: ExtraWorkRequest) -> None:
    """Sprint 187 §1 — recompute and persist `ew.subtotal_amount` /
    `vat_amount` / `total_amount` from the active priced-line set.

    ## Why this exists

    Those three columns are the QUOTE cache that every list, widget,
    report KPI, CSV export and detail header reads (through
    `rowAmounts()` in `frontend/src/lib/billing.ts`, whose quoted
    fallback is exactly `total_amount`). Until this function they were
    written by ONE thing — `ExtraWorkRequest.recompute_totals()`, driven
    only from the legacy `/pricing-items/` views. The Proposal route
    never touched them, so an Extra Work priced at EUR 484.00 through a
    Proposal, approved by the customer and spawned into a ticket, read
    EUR 0,00 on every one of those surfaces.

    The fix belongs here and not in the reader: `rowAmounts()` is the ONE
    billing-total rule (CLAUDE.md §2A) and invoicing reads the same
    columns server-side, so a frontend-only fallback would desync the
    two the moment an invoice was generated.

    ## The one line that differs from `recompute_final_amounts`

    This uses the ORDERED `line.quantity`; `recompute_final_amounts`
    uses `billable_quantity(line)`, which substitutes `actual_hours` on
    hourly lines. That is the whole distinction between the two
    functions, and it is deliberate: **a quote is what was ordered, a
    final amount is what was delivered.** Using `billable_quantity` here
    would silently rewrite the customer's agreed quote to whatever hours
    the provider later entered.

    Everything else — the three-route line resolution, the per-line
    price and VAT accessors, the two-places rounding — is shared, so the
    quote and the final amount cannot round differently.
    """
    subtotal, vat, total = quoted_totals(ew)
    ew.subtotal_amount = subtotal
    ew.vat_amount = vat
    ew.total_amount = total
    ew.save(
        update_fields=[
            "subtotal_amount",
            "vat_amount",
            "total_amount",
            "updated_at",
        ]
    )


def ew_has_unfinalized_hourly_lines(ew: ExtraWorkRequest) -> bool:
    """True iff any active priced line is HOURS-unit with
    `actual_hours is None`. Used by the ticket completion gate
    (`tickets.state_machine.apply_transition`) to block sending an EW
    operational ticket for customer approval before the hours are in."""
    _kind, lines = active_priced_lines(ew)
    for line in lines:
        # P-13 I — legacy `ExtraWorkPricingLineItem` rows now carry
        # `actual_hours` too, so an hourly legacy line gates the
        # completion transition exactly like its cart/proposal twins.
        # The hasattr guard stays for non-model line objects in tests.
        if not hasattr(line, "actual_hours"):
            continue
        if (
            _line_unit_type(line) == ExtraWorkPricingUnitType.HOURS
            and line.actual_hours is None
        ):
            return True
    return False
