"""
Sprint 185 E §2 — splitting one building's work across its tenants.

A building shared by several customers is the ordinary case, and until
this sprint the system held no weight at all: whoever's name was on the
Extra Work got the whole bill, and the real division lived in somebody's
head. `buildings.BuildingCostShare` records the division; this module is
the money side of it.

## The two rules that make it safe

**1. A building with NO shares behaves exactly as it always has.**
Absence means "not shared", never "shared 0%". `share_amounts_for`
returns the full earned amounts unchanged, and every existing invoice is
byte-identical to what it was. That is the property the whole item rests
on, and it is why the lookup is "are there shares?" rather than "what is
this customer's share, defaulting to zero".

**2. The parts sum EXACTLY to the whole.** Three customers at 33.33% of
EUR 100 cannot produce EUR 99.99. That is not a rounding preference, it
is the difference between an invoice run that balances and one that
quietly loses a cent per shared job per month.

## The rounding rule, stated once

Every part is floored to two decimals, and **the remainder goes to the
LARGEST share**; ties are broken by the lowest customer id so the answer
never depends on row order, query order, or which customer's invoice run
happens to go first. EUR 100 across three equal 33.33% shares becomes
33.34 / 33.33 / 33.33.

The allocation is recomputed FROM THE WHOLE SHARE SET every time, for
every customer. That is what makes it order-independent: customer B's
part is the same number whether B is invoiced before or after A, on the
same day or three weeks later on B's own billing day. A part computed as
"my percentage of the total, rounded on its own" would not have that
property — it is exactly how you get 99.99.

## VAT is computed on each PART, not split from the whole

Each customer's invoice must be arithmetically self-consistent on its
own face: its VAT has to be its own subtotal times its own rate, because
that is the document a tax authority reads. Splitting a single VAT
figure across parts can leave an invoice whose VAT is a cent away from
its own subtotal times its own rate, which is indefensible on the
document even though the sum across documents would be tidier.

The consequence, stated rather than discovered: the sum of the parts'
VAT can differ by a cent from the VAT computed on the undivided whole.
The subtotals always sum exactly; the VAT figures are each correct for
their own invoice.
"""
from __future__ import annotations

from decimal import ROUND_DOWN, ROUND_HALF_UP, Decimal

_TWO_PLACES = Decimal("0.01")
_HUNDRED = Decimal("100")


def shares_for_buildings(building_ids) -> dict[int, list[tuple[int, Decimal]]]:
    """`{building_id: [(customer_id, share_pct), ...]}` for the buildings
    that HAVE shares. Buildings with none are absent from the mapping,
    which is how callers tell "not shared" from "shared".

    ONE query for every building in a run, not one per row: an invoice
    run touches many Extra Works across a handful of buildings, and a
    per-row lookup would be the N+1 the query-count tests exist to catch.
    """
    from buildings.models import BuildingCostShare

    if not building_ids:
        return {}
    out: dict[int, list[tuple[int, Decimal]]] = {}
    rows = BuildingCostShare.objects.filter(
        building_id__in=list(building_ids)
    ).values_list("building_id", "customer_id", "share_pct")
    for building_id, customer_id, share_pct in rows:
        out.setdefault(building_id, []).append((customer_id, share_pct))
    return out


def allocate(amount: Decimal, shares: list[tuple[int, Decimal]]) -> dict[int, Decimal]:
    """Split `amount` across `shares`, exactly.

    Returns `{customer_id: part}` where the parts sum to `amount` to the
    cent. See the module docstring for the rule; the invariant this
    function exists to hold is `sum(result.values()) == amount`.

    `shares` are the raw percentages, which sum to 100 by the write
    path's own guarantee. This does NOT re-derive them from each other —
    if a caller ever hands in a set that does not sum to 100 the parts
    still sum to `amount`, because the remainder is handed out at the
    end; the money is never wrong, even when the data is.
    """
    if not shares:
        return {}
    amount = Decimal(amount or 0).quantize(_TWO_PLACES)

    parts: dict[int, Decimal] = {}
    for customer_id, pct in shares:
        # Floor, deliberately: flooring every part and handing the
        # remainder out ONCE cannot overshoot, whereas rounding each part
        # half-up can produce a set that sums to a cent MORE than the
        # whole — and money appearing is worse than money moving.
        parts[customer_id] = (amount * Decimal(pct) / _HUNDRED).quantize(
            _TWO_PLACES, rounding=ROUND_DOWN
        )

    remainder = amount - sum(parts.values())
    if remainder:
        # Largest share absorbs it; ties break on the lowest customer id
        # so the result never depends on row order or on which customer's
        # run happens to go first.
        winner = sorted(shares, key=lambda s: (-Decimal(s[1]), s[0]))[0][0]
        parts[winner] = parts[winner] + remainder
    return parts


def share_amounts_for(
    customer_id: int,
    building_id: int,
    earned: tuple[Decimal | None, Decimal | None, Decimal | None],
    shares_by_building: dict[int, list[tuple[int, Decimal]]],
) -> tuple[Decimal, Decimal, Decimal] | None:
    """This customer's (subtotal, vat, total) for one Extra Work.

    `earned` is the EW's undivided `(subtotal, vat, total)`.

    Returns the earned amounts UNCHANGED when the building has no shares
    — the unshared path is not a special case bolted on, it is the same
    function returning what it was given.

    Returns `None` when the building IS shared and this customer holds no
    share of it: the customer is not billed for that work at all, and the
    caller drops the row rather than writing a zero line. A zero line
    would be a claim on work this customer never owed anything for.
    """
    shares = shares_by_building.get(building_id)
    subtotal, vat, total = (
        Decimal(earned[0] or 0),
        Decimal(earned[1] or 0),
        Decimal(earned[2] or 0),
    )
    if not shares:
        return subtotal, vat, total

    part = allocate(subtotal, shares).get(customer_id)
    if part is None:
        return None

    # VAT on the PART — see the module docstring. The rate comes from the
    # whole (it is the same rate for every part of the same job), and is
    # applied to this part's own subtotal so the invoice is consistent
    # with itself.
    rate = (vat / subtotal) if subtotal else Decimal("0")
    part_vat = (part * rate).quantize(_TWO_PLACES, rounding=ROUND_HALF_UP)
    return part, part_vat, (part + part_vat).quantize(_TWO_PLACES)
