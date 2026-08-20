"""W3-H — labour cost. The ONE place it is computed, and it is here.

    plan §2.8 / decision 12: "Where labour cost is computed — in
    `reports/`, not `timesheets/`."

## Why not in `timesheets/`

`timesheets` has a written rule and this module exists to keep it. Its
own docstring: "the module records HOURS and WEIGHTED hours
(`hours * multiplier_snapshot`). It never holds a wage, never multiplies
by one, and never computes money." `HourType.multiplier` says so again
at the field: "a WEIGHT, not a rate: nothing here computes money."

That rule is worth keeping because it is what lets a provider run its
timesheets without running its payroll here, and because the moment a
rate appears next to an hour, every screen that shows hours becomes a
screen that shows salaries — with a privacy story nobody designed.

`reports/` is the app that may read across modules (`hour_sources.py`
and `hours_comparison.py` already do), so cost belongs here. The
multiplication happens in this file and in no other.

## What a rate is, and the honest answer about ours

**There is no wage anywhere in this system.** Not on `User`, not on
`StaffProfile`, not on `HourType`, not on `Company` — grep for
`hourly_rate` and the only hits are the three files that say the module
must not have one. That is a deliberate absence, not an oversight, and
inventing a field to fill it would be a payroll feature nobody asked
for, in an app this sprint does not own.

So the rate is a DEPLOYMENT SETTING, `LABOUR_COST_HOURLY_RATE_EUR`,
unset by default:

  * unset -> `hourly_rate` is None, and every cost figure derived from
    hours is None. The screen says so. **It never prints a zero**: a
    labour cost of EUR 0,00 would say "this job cost us nothing", which
    is a different and false claim.
  * set   -> one rate for the deployment, applied to WEIGHTED hours so
    an overtime hour costs what its multiplier says.

One seam, named on purpose: when a real per-person rate lands, it lands
in `resolve_hourly_rate` and nothing else in the codebase changes.

## Weighted hours, not raw hours

`multiplier_snapshot` is copied onto the entry at write time, so an
hour booked last year costs what the rate said then multiplied by the
weight it carried then. Using the live `HourType.multiplier` would
silently re-price history.

## Travel costs are real money that already exists

`TimeEntry.travel_costs` is an actual euro amount somebody claimed for
an actual day. It needs no rate, so it is summed and reported whether
or not one is configured — and it is reported SEPARATELY. It is never
folded into an hours cost, and `total_cost` stays None while the rate
is missing rather than quietly becoming "travel only", which would be a
total that is not a total.

## This is not the billing rule

`rowAmounts()` in `frontend/src/lib/billing.ts` and its server-side
mirror remain the ONE rule for what a customer is charged. Nothing
here reaches an invoice, a proposal, a revenue report or an
`ExtraWorkRequest` amount field: this is what the work COST US, which
is the opposite side of the ledger from what it EARNS. Two numbers that
must never be added together, and never are.
"""
from __future__ import annotations

from decimal import Decimal

from django.conf import settings


#: The deployment-wide hourly labour rate, in euros. Unset means "no
#: rate configured", which is a state the API and the UI both render
#: rather than paper over.
HOURLY_RATE_SETTING = "LABOUR_COST_HOURLY_RATE_EUR"

#: What `rate_source` says when a rate came from that setting. A named
#: constant because the frontend branches on it and a typo would read
#: as "no rate" on a deployment that has one.
RATE_SOURCE_DEPLOYMENT = "deployment_setting"

_CENTS = Decimal("0.01")


def _money(value: Decimal) -> str:
    """A money amount on the wire: a fixed 2dp string, never a float.

    Same shape `reports.dimensions` and `reports.hours_comparison`
    already put money on the wire in, so a client formats one kind of
    string for every report.
    """
    return str(Decimal(value).quantize(_CENTS))


def resolve_hourly_rate(company_id: int | None = None) -> Decimal | None:
    """The hourly labour rate to cost hours at, or None when none is set.

    `company_id` is accepted and deliberately unused: it is the seam. A
    per-company or per-employee rate is the obvious next step, and
    having every caller already pass the tenant means that change is
    confined to this function's body. Callers must not read the setting
    themselves — a second reader is a second rule.

    A rate of zero is refused as "not configured" on purpose. Zero is a
    legal PRICE (Sprint 188 argues that at length for what we charge);
    it is not a legal WAGE, and a deployment that typed 0 has almost
    certainly typed a placeholder rather than stated that its people
    work for nothing.
    """
    raw = getattr(settings, HOURLY_RATE_SETTING, None)
    if raw in (None, ""):
        return None
    try:
        rate = Decimal(str(raw))
    except Exception:  # pragma: no cover - defensive, a typo in .env
        return None
    if rate <= 0:
        return None
    return rate


def labour_cost(
    *,
    weighted_hours: Decimal,
    travel_costs: Decimal | None = None,
    company_id: int | None = None,
) -> dict:
    """Cost `weighted_hours` at the configured rate. The whole rule.

    Returns a wire-ready block:

        {"hourly_rate": "25.00"|None, "rate_source": str|None,
         "hours_cost": "281.25"|None, "travel_costs": "12.50",
         "total_cost": "293.75"|None, "rate_configured": bool}

    Every money value is a fixed 2dp STRING and every None means "not
    knowable", never zero. The caller renders the None; it does not
    substitute for it.
    """
    rate = resolve_hourly_rate(company_id)
    travel = Decimal(travel_costs or 0)

    if rate is None:
        return {
            "hourly_rate": None,
            "rate_source": None,
            "rate_configured": False,
            "hours_cost": None,
            # Real money that was really claimed. It needs no rate, so a
            # missing rate does not hide it.
            "travel_costs": _money(travel),
            # NOT the travel figure. A "total" that silently excludes
            # labour is a number an operator would read as the job's
            # cost and act on.
            "total_cost": None,
        }

    hours_cost = Decimal(weighted_hours) * rate
    return {
        "hourly_rate": _money(rate),
        "rate_source": RATE_SOURCE_DEPLOYMENT,
        "rate_configured": True,
        "hours_cost": _money(hours_cost),
        "travel_costs": _money(travel),
        # Quantized ONCE, at the end, from the unrounded product. Two
        # roundings on one figure is how the reference system's totals
        # came to disagree by cents with themselves.
        "total_cost": _money(hours_cost + travel),
    }
