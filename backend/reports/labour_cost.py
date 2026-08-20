"""W3-H / W4-R — labour cost. The ONE place it is computed, and it is here.

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

## W4-R: there IS a rate now, and it is per person and dated

W3-H shipped one deployment-wide rate and named the seam a real one
would land in: "when a real per-person rate lands, it lands in
`resolve_hourly_rate` and nothing else in the codebase changes." That
happened, and it landed exactly there.

`reports.models.EmployeeHourlyRate` is one row per (employee, company,
`valid_from`), open-ended and superseded rather than edited. The rate
that costs an hour is the row in force **on the DATE OF THAT HOUR** —
latest `valid_from` at or before it, ties by `-id`, the same resolution
shape `extra_work.pricing.resolve_price` and `timesheets.ContractHours`
use.

**A raise never re-prices the past.** March's new row is dated March;
January's hours keep resolving January's row, so January's cost figure
is the same number the day after the raise as the day before. That is
the whole reason the rate is time-ranged instead of snapshotted onto
the hour: a snapshot would need a money column on `TimeEntry`, which is
a `timesheets` model, which is the one place a rate may never appear.
The full argument is in `reports/models.py`.

## The resolution order, in one place

  1. the employee's own rate in force on the hour's date;
  2. failing that, `LABOUR_COST_HOURLY_RATE_EUR` — the deployment-wide
     fallback W3-H shipped, still here and still the answer for anyone
     with no personal rate;
  3. failing that, **nothing**. `hourly_rate` is None and every cost
     figure derived from hours is None. The screen says so. **It never
     prints a zero**: a labour cost of EUR 0,00 would say "this job cost
     us nothing", which is a different and false claim.

Callers must not read the setting or the model themselves — a second
reader is a second rule.

## Partial knowledge is not a total

A crew of three where one person has no rate and there is no fallback
produces no `hours_cost` and no `total_cost` at all, not a total over
the two who do. A figure that silently covers two thirds of a job is
the number an operator would read as the job's cost and act on.
`unrated_weighted_hours` says how much is missing, so the absence has a
reason rather than being a blank.

## Weighted hours, not raw hours

`multiplier_snapshot` is copied onto the entry at write time, so an
hour booked last year costs what the rate said then multiplied by the
weight it carried then. Using the live `HourType.multiplier` would
silently re-price history — the same failure the dated rate prevents on
the other axis.

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

from datetime import date as date_cls
from decimal import Decimal
from typing import Iterable, NamedTuple, Optional

from django.conf import settings


#: The deployment-wide fallback hourly rate, in euros. Unset means "no
#: fallback", which is a state the API and the UI both render rather
#: than paper over. It is a FALLBACK now, not the only rate: a person
#: with an `EmployeeHourlyRate` row in force is costed at theirs.
HOURLY_RATE_SETTING = "LABOUR_COST_HOURLY_RATE_EUR"

#: What `rate_source` says when a rate came from that setting. A named
#: constant because the frontend branches on it and a typo would read
#: as "no rate" on a deployment that has one.
RATE_SOURCE_DEPLOYMENT = "deployment_setting"

#: ...and when it came from the person's own dated rate row.
RATE_SOURCE_EMPLOYEE = "employee_rate"

#: ...and when a single job drew on more than one of the above, or on
#: two different per-person rates. There is then no ONE rate to name, so
#: `hourly_rate` comes back None while `hours_cost` is still exact —
#: it was summed per person, per day, at each one's own rate.
RATE_SOURCE_MIXED = "mixed"

_CENTS = Decimal("0.01")


class HourSegment(NamedTuple):
    """One block of weighted hours, attributable to one person on one day.

    The unit the cost is computed over, and it has to be this fine:
    the rate depends on WHO worked and on WHEN, so a total of weighted
    hours with neither attached cannot be priced. `extra_work_hours`
    already groups its entries at exactly this grain for the grid, so
    the segments fall out of the aggregate it was running anyway.
    """

    employee_id: Optional[int]
    on_date: Optional[date_cls]
    weighted_hours: Decimal


def _money(value: Decimal) -> str:
    """A money amount on the wire: a fixed 2dp string, never a float.

    Same shape `reports.dimensions` and `reports.hours_comparison`
    already put money on the wire in, so a client formats one kind of
    string for every report.
    """
    return str(Decimal(value).quantize(_CENTS))


def _hours(value: Decimal) -> str:
    return str(Decimal(value or 0).quantize(_CENTS))


def resolve_deployment_hourly_rate() -> Decimal | None:
    """The deployment-wide fallback rate, or None when none is set.

    The ONLY reader of `LABOUR_COST_HOURLY_RATE_EUR` in the codebase.

    A rate of zero is refused as "not configured" on purpose. Zero is a
    legal PRICE (Sprint 188 argues that at length for what we charge);
    it is not a legal WAGE, and a deployment that typed 0 has almost
    certainly typed a placeholder rather than stated that its people
    work for nothing. `EmployeeHourlyRate` refuses zero at the field
    validator for the same reason, and the two must agree.
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


class RateBook:
    """Every dated rate row for a set of people in one company, loaded once.

    ONE query for a whole crew, then pure in-memory resolution per
    (person, day). Costing a ten-person job that ran over forty days is
    otherwise four hundred point lookups — the N+1 the `assertNumQueries`
    tests in this app exist to catch.

    Rows arrive newest-first (`Meta.ordering` is `-valid_from, -id`), so
    "the row in force on this day" is the FIRST one whose `valid_from`
    is at or before it. The `-id` tie-break is inherited rather than
    re-stated: two rows cannot share a (company, employee, valid_from)
    anyway — a unique constraint says so — and the ordering is kept
    identical to `resolve_price` so this repo has one idiom.
    """

    __slots__ = ("_by_employee",)

    def __init__(self, by_employee: dict):
        self._by_employee = by_employee

    @classmethod
    def load(cls, company_id: int | None, employee_ids: Iterable[int]) -> "RateBook":
        ids = {eid for eid in employee_ids if eid is not None}
        if not ids or company_id is None:
            # No people to price, or no tenant to price them in. Either
            # way there is nothing to fetch, and an unfiltered read would
            # be a cross-tenant one.
            return cls({})

        from .models import EmployeeHourlyRate

        by_employee: dict[int, list] = {}
        rows = EmployeeHourlyRate.objects.filter(
            company_id=company_id, employee_id__in=ids
        ).values_list("employee_id", "valid_from", "hourly_rate")
        for employee_id, valid_from, rate in rows:
            by_employee.setdefault(employee_id, []).append((valid_from, rate))
        for entries in by_employee.values():
            entries.sort(key=lambda item: item[0], reverse=True)
        return cls(by_employee)

    def rate_on(self, employee_id: int | None, on_date) -> Decimal | None:
        """This person's own rate on this day, or None if they have none.

        None is not an error and not a zero — it means the fallback gets
        its turn. A date of None (an unattributed block of hours) also
        resolves to None: without a day there is no way to say which of
        somebody's rates applied, and guessing "the current one" is the
        silent re-pricing this model exists to prevent.
        """
        if employee_id is None or on_date is None:
            return None
        for valid_from, rate in self._by_employee.get(employee_id, ()):
            if valid_from <= on_date:
                return Decimal(rate)
        return None


def resolve_hourly_rate(
    *,
    employee_id: int | None = None,
    on_date=None,
    company_id: int | None = None,
) -> tuple[Decimal | None, str | None]:
    """The rate to cost ONE person's hours on ONE day at, and where it came from.

    The seam W3-H named, now carrying the per-person answer. Returns
    `(rate, source)`; `(None, None)` means no rate is knowable, which
    callers render as an absence and never as zero.

    Single-lookup convenience over `RateBook`. A caller costing more
    than one person, or one person across more than one day, should load
    a `RateBook` instead — this issues a query per call by design, and
    the batch path exists so nobody has to.
    """
    rate = RateBook.load(company_id, [employee_id]).rate_on(employee_id, on_date)
    if rate is not None:
        return rate, RATE_SOURCE_EMPLOYEE

    fallback = resolve_deployment_hourly_rate()
    if fallback is not None:
        return fallback, RATE_SOURCE_DEPLOYMENT
    return None, None


def _company_has_any_rate(company_id: int | None) -> bool:
    """Whether this tenant has recorded any per-person rate at all.

    Asked ONLY for a job with no hours on it. With hours, the question
    that matters is whether the people who worked have rates, and the
    `RateBook` has already answered it. With no hours there is nobody to
    ask about, and a company that has set up its rates should not read
    "no rate configured" on an empty job merely because nobody has
    booked an hour to it yet.
    """
    if company_id is None:
        return False

    from .models import EmployeeHourlyRate

    return EmployeeHourlyRate.objects.filter(company_id=company_id).exists()


def labour_cost(
    *,
    segments: Iterable[HourSegment],
    travel_costs: Decimal | None = None,
    company_id: int | None = None,
) -> dict:
    """Cost these segments, each at the rate of its own person and day.

    Returns a wire-ready block:

        {"hourly_rate": "25.00"|None, "rate_source": str|None,
         "rate_configured": bool, "hours_cost": "281.25"|None,
         "unrated_weighted_hours": "0.00", "travel_costs": "12.50",
         "total_cost": "293.75"|None}

    Every money value is a fixed 2dp STRING and every None means "not
    knowable", never zero. The caller renders the None; it does not
    substitute for it.

    `hourly_rate` names ONE rate only when one rate did all the work.
    Two people on different rates, or one on a personal rate and one on
    the deployment fallback, leave it None with `rate_source` "mixed" —
    there is no single figure to print, and printing either of the two
    would be a wrong answer rather than a partial one. `hours_cost`
    stays exact either way: it is summed per segment, at each segment's
    own rate, and quantized ONCE at the end.
    """
    travel = Decimal(travel_costs or 0)
    segments = list(segments)
    book = RateBook.load(company_id, (seg.employee_id for seg in segments))
    fallback = resolve_deployment_hourly_rate()

    hours_cost = Decimal("0")
    unrated_weighted = Decimal("0")
    # Counted separately from the hours above, and it has to be. An hour
    # type can carry a multiplier of 0.00 — unpaid leave is recorded as
    # hours worked zero times, which `HourType.multiplier` documents as
    # a legal value. Such a segment adds nothing to `unrated_weighted`,
    # so keying "is anything unpriced" off the HOURS would call a job of
    # nothing but unpaid leave fully priced and report a confident
    # EUR 0,00 for a company that has never set a rate. The cost of zero
    # weighted hours is genuinely zero; whether we KNOW a rate is a
    # different question, and this is the one that answers it.
    unrated_segments = 0
    rates_seen: set[Decimal] = set()
    sources_seen: set[str] = set()

    for segment in segments:
        weighted = Decimal(segment.weighted_hours or 0)
        rate = book.rate_on(segment.employee_id, segment.on_date)
        source = RATE_SOURCE_EMPLOYEE
        if rate is None:
            rate, source = fallback, RATE_SOURCE_DEPLOYMENT
        if rate is None:
            # Nobody's rate covers these hours. They are counted, named
            # and excluded from the total rather than costed at zero.
            unrated_segments += 1
            unrated_weighted += weighted
            continue
        hours_cost += weighted * rate
        rates_seen.add(rate)
        sources_seen.add(source)

    if not segments:
        # An empty job. There are no hours to cost, so the honest
        # `hours_cost` is 0.00 — but only if a rate exists at all;
        # otherwise this is the same "we cannot know" the unrated branch
        # reports, and 0.00 would read as "it was free".
        if fallback is not None:
            rates_seen.add(fallback)
            sources_seen.add(RATE_SOURCE_DEPLOYMENT)
        elif _company_has_any_rate(company_id):
            # Rates exist but no hour picked one, so there is no single
            # figure to name — the same answer a mixed crew gets.
            sources_seen.add(RATE_SOURCE_EMPLOYEE)
        else:
            return _unknown(travel)

    if unrated_segments:
        return _unknown(travel, unrated_weighted=unrated_weighted)

    return {
        # One rate did all of this, or there is no one rate to name.
        "hourly_rate": _money(next(iter(rates_seen))) if len(rates_seen) == 1 else None,
        # "mixed" when more than one PROVENANCE was involved (a personal
        # rate for one person, the deployment fallback for another) AND
        # when one provenance produced more than one FIGURE (two people
        # on two personal rates, or one person across a raise). Both are
        # the same fact from the reader's side: no single rate explains
        # this cost, so do not name one.
        "rate_source": (
            next(iter(sources_seen))
            if len(sources_seen) == 1 and len(rates_seen) <= 1
            else RATE_SOURCE_MIXED
        ),
        "rate_configured": True,
        "hours_cost": _money(hours_cost),
        "unrated_weighted_hours": _hours(Decimal("0")),
        "travel_costs": _money(travel),
        # Quantized ONCE, at the end, from the unrounded product. Two
        # roundings on one figure is how the reference system's totals
        # came to disagree by cents with themselves.
        "total_cost": _money(hours_cost + travel),
    }


def _unknown(travel: Decimal, *, unrated_weighted: Decimal = Decimal("0")) -> dict:
    """The block for "we cannot say what this cost".

    Its own function so the two ways of getting here — no rate anywhere,
    and a rate for some of the crew but not all of it — produce the
    byte-identical shape. A caller that had to tell them apart from the
    field set would be a caller that gets it wrong once.
    """
    return {
        "hourly_rate": None,
        "rate_source": None,
        "rate_configured": False,
        "hours_cost": None,
        # How much of the work nobody's rate covers. 0.00 with
        # `rate_configured` false means there is no rate at all; a
        # positive number means part of the crew is priced and the total
        # is withheld because part of it is not.
        "unrated_weighted_hours": _hours(unrated_weighted),
        # Real money that was really claimed. It needs no rate, so a
        # missing rate does not hide it.
        "travel_costs": _money(travel),
        # NOT the travel figure. A "total" that silently excludes
        # labour is a number an operator would read as the job's cost
        # and act on.
        "total_cost": None,
    }
