"""
Sprint 160 — the contract invoice FORECAST.

**This module writes nothing.** It is a pure function over a contract
and a year: given the start date, end date, billing period, billing
day, billing type and proration flag, it returns the invoice dates and
amounts that WOULD be raised, each with status `PLANNED`.

That is the whole point of its shape. Sprint 158 turns a due forecast
row into a real `invoicing.Invoice`; if this module already knew how to
write one, that sprint would be a rewrite instead of a small step. So:
no imports from `invoicing`, no model writes, no side effects. If you
find yourself editing `invoicing/` from here, stop.

--------------------------------------------------------------------
Money discipline
--------------------------------------------------------------------
`Decimal` throughout, quantized to 2dp with `ROUND_HALF_UP`, and never
through a `float` — the house rule the invoicing and extra-work money
paths already follow. Division (proration, monthly normalisation) is
Decimal division followed by one explicit quantize, never a chain of
implicit roundings.

--------------------------------------------------------------------
The rules this implements, stated plainly
--------------------------------------------------------------------

**Periods are CALENDAR-aligned.** A MONTHLY contract bills calendar
months, a QUARTERLY one bills Jan-Mar / Apr-Jun / Jul-Sep / Oct-Dec,
and a YEARLY one bills the calendar year. The contract's first period
is the calendar period CONTAINING `start_date` — not a period that
starts on the signing date. This is what makes "a contract starting on
the 12th bills a part month first" mean anything.

**Proration is by day count.** When `start_proration` is on, a period
the contract only partly covers bills
`period_amount * covered_days / period_days`, quantized once. The flag
governs BOTH ends: a contract starting mid-period bills a part period
first, and one ending mid-period bills a part period last. When the
flag is off, every period bills in full — including the first and the
last.

**The money for a period comes from the revision active at the period
START** (`revisions.active_revision`). A revision that takes effect
mid-period therefore governs from the NEXT period, not partway through
this one. That is a deliberate simplification and the defensible one:
splitting a period at a revision boundary would produce two invoices
for one billing period, which no billing setting here can express.

**Invoice date.** ADVANCE dates the invoice on `billing_day` of the
period's FIRST month — you are billing for the period ahead. ARREARS
dates it on `billing_day` of the month AFTER the period ends. In both
cases the FIRST invoice is never dated before the contract exists: if
the computed day precedes `start_date`, the start date is used.

**Which rows the preview shows.** The preview lists the invoices still
to come — it excludes the FIRST invoice, the one already raised when
the contract was signed. Implemented literally as
`invoice_date > first_invoice_date`, i.e. the rule the brief calls
"after the first invoice date", chosen over "on or after today"
because it is a property of the contract's own dates: it gives the
same answer on every run, where a today-relative rule would silently
shrink the preview as the year progressed and could not be tested
without freezing the clock.

**Yearly is NOT monthly x 12.** `yearly_amount` is the SUM OF THE
ACTUAL PERIOD AMOUNTS scheduled in the selected year, including the
first (prorated, and excluded from the displayed rows) one. With
proration on and a mid-period start the two figures differ by exactly
the prorated part; with proration off they agree. `tests/test_billing.py`
asserts both directions.
"""
from __future__ import annotations

from calendar import monthrange
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP
from typing import Optional

from django.utils import timezone

from .models import MONTHS_PER_PERIOD, PERIODS_PER_YEAR, BillingType
from .revisions import revision_totals


CENTS = Decimal("0.01")

# The status every forecast row carries. A forecast row is not an
# invoice and never becomes one by being read — Sprint 158 is what
# turns a due row into an `invoicing.Invoice`.
STATUS_PLANNED = "PLANNED"

# Hard bound on how many periods one call will walk. A forecast for a
# single year needs at most ~14; anything approaching this bound means
# a contract whose start_date is centuries away, and returning a
# truncated forecast beats spinning. Nothing legitimate reaches it.
MAX_PERIODS = 2000


def money(value) -> Decimal:
    """Quantize to 2dp, HALF_UP. The single rounding gate — every
    amount this module returns has passed through exactly one call.
    """
    if not isinstance(value, Decimal):
        value = Decimal(str(value))
    return value.quantize(CENTS, rounding=ROUND_HALF_UP)


@dataclass(frozen=True)
class ForecastRow:
    """One planned invoice."""

    invoice_date: date
    due_date: date
    period_start: date
    period_end: date
    amount: Decimal
    is_prorated: bool
    covered_days: int
    period_days: int
    status: str = STATUS_PLANNED


@dataclass
class Forecast:
    """The whole answer for one contract and one year.

    `rows` are the invoices still to come in `year` (the first invoice
    is excluded — see the module docstring). `rows_total` is their sum,
    which is the caption above the table. `yearly_amount` is the sum of
    EVERY period scheduled in the year including that excluded first
    one, which is why the two figures legitimately differ.
    """

    year: int
    rows: list = field(default_factory=list)
    rows_total: Decimal = Decimal("0.00")
    yearly_amount: Decimal = Decimal("0.00")
    monthly_amount: Decimal = Decimal("0.00")
    invoices_per_year: int = 0
    first_invoice_date: Optional[date] = None
    excluded_first_invoice: bool = False


# ---------------------------------------------------------------------
# Calendar-aligned period arithmetic (pure, no queries, no clock)
# ---------------------------------------------------------------------


def _months_per_period(contract) -> int:
    return MONTHS_PER_PERIOD[contract.billing_period]


def period_index(day: date, months: int) -> int:
    """The absolute index of the calendar period containing `day`.

    Months since year 0 divided by the period length. Indexable in O(1)
    in both directions, which is what keeps a forecast for one year of
    a 30-year-old contract from walking 360 periods to find its start.
    """
    return (day.year * 12 + day.month - 1) // months


def period_start_for_index(index: int, months: int) -> date:
    absolute_month = index * months
    return date(absolute_month // 12, absolute_month % 12 + 1, 1)


def period_end_for_index(index: int, months: int) -> date:
    """Last day of the period — the day before the next period starts."""
    return period_start_for_index(index + 1, months) - timedelta(days=1)


def add_months(day: date, months: int) -> date:
    """Shift a date by whole months, clamping the day to the target
    month's length. Only used on `billing_day` values (1..28, so the
    clamp never fires) and on month starts; the clamp is there so a
    later caller cannot introduce a February 30th.
    """
    absolute = day.year * 12 + (day.month - 1) + months
    year, month = absolute // 12, absolute % 12 + 1
    return date(year, month, min(day.day, monthrange(year, month)[1]))


def _invoice_date_for(contract, p_start: date, p_end: date, is_first: bool) -> date:
    """The date the invoice for this period carries. See the module
    docstring for the ADVANCE / ARREARS rule and the first-invoice
    clamp.
    """
    day = min(contract.billing_day, 28)
    if contract.billing_type == BillingType.ARREARS:
        anchor = add_months(date(p_end.year, p_end.month, 1), 1)
    else:
        anchor = date(p_start.year, p_start.month, 1)
    invoice_date = date(anchor.year, anchor.month, day)
    if is_first and invoice_date < contract.start_date:
        # Never date the contract's first invoice before the contract
        # exists. Later periods cannot trip this: their anchor month is
        # already past the start date.
        return contract.start_date
    return invoice_date


# ---------------------------------------------------------------------
# The forecast itself
# ---------------------------------------------------------------------


def _amount_for_period(contract, p_start: date, revisions) -> Decimal:
    """The full (unprorated) money for one period, from the revision
    active at `p_start`.

    `revisions` is the contract's revisions pre-fetched in resolution
    order (latest `effective_from` first, `-id` tie-break) so a
    multi-period forecast costs ONE query, not one per period. The
    selection rule is the same one `revisions.active_revision` applies
    — first row whose `effective_from <= target` — applied to the same
    ordering, rather than restated as a second expression that could
    drift from it.
    """
    for revision in revisions:
        if revision.effective_from <= p_start:
            return money(revision_totals(revision)["amount"])
    # No revision was in force when the period began: the contract had
    # no agreed scope yet. Zero, not "borrow the next revision".
    return Decimal("0.00")


def _prorate(amount: Decimal, covered_days: int, period_days: int) -> Decimal:
    if period_days <= 0 or covered_days >= period_days:
        return money(amount)
    return money(amount * Decimal(covered_days) / Decimal(period_days))


def build_forecast(contract, year: int, *, on: Optional[date] = None) -> Forecast:
    """Compute the planned invoices for `contract` in `year`.

    Pure: reads the contract's revisions and lines, writes nothing,
    and takes `on` (default today) only for the "Current Monthly"
    figure — every row and every total is a function of the contract's
    own dates, so the same call returns the same answer tomorrow.
    """
    today = on or timezone.localdate()
    months = _months_per_period(contract)

    # One query for the revisions, in resolution order; the lines come
    # with them so `revision_totals` does not go back to the database
    # per period.
    revisions = list(
        contract.revisions.order_by("-effective_from", "-id").prefetch_related(
            "lines"
        )
    )

    forecast = Forecast(
        year=year,
        invoices_per_year=PERIODS_PER_YEAR[contract.billing_period],
    )

    # "Current Monthly" — the ACTIVE revision's period money
    # normalised to one month. Independent of the selected year, which
    # is why it can legitimately disagree with `yearly / 12`.
    current_amount = _amount_for_period(contract, today, revisions)
    forecast.monthly_amount = money(current_amount / Decimal(months))

    first_index = period_index(contract.start_date, months)
    last_index = (
        period_index(contract.end_date, months)
        if contract.end_date is not None
        else None
    )

    def period_for(index: int):
        """(period_start, period_end, covered_days, period_days) for a
        period index, clipped to the contract's own life."""
        p_start = period_start_for_index(index, months)
        p_end = period_end_for_index(index, months)
        covered_start = max(p_start, contract.start_date)
        covered_end = (
            min(p_end, contract.end_date)
            if contract.end_date is not None
            else p_end
        )
        period_days = (p_end - p_start).days + 1
        covered_days = max(0, (covered_end - covered_start).days + 1)
        return p_start, p_end, covered_days, period_days

    def row_for(index: int) -> Optional[ForecastRow]:
        p_start, p_end, covered_days, period_days = period_for(index)
        if covered_days <= 0:
            return None
        base = _amount_for_period(contract, max(p_start, contract.start_date), revisions)
        if contract.start_proration:
            amount = _prorate(base, covered_days, period_days)
        else:
            amount = money(base)
        invoice_date = _invoice_date_for(
            contract, p_start, p_end, is_first=(index == first_index)
        )
        return ForecastRow(
            invoice_date=invoice_date,
            due_date=invoice_date + timedelta(days=contract.payment_terms_days),
            period_start=max(p_start, contract.start_date),
            period_end=(
                min(p_end, contract.end_date)
                if contract.end_date is not None
                else p_end
            ),
            amount=amount,
            is_prorated=(
                contract.start_proration and covered_days < period_days
            ),
            covered_days=covered_days,
            period_days=period_days,
        )

    first_row = row_for(first_index)
    if first_row is None:
        return forecast
    forecast.first_invoice_date = first_row.invoice_date

    # Which period indexes could possibly produce an invoice dated in
    # `year`? An ADVANCE invoice is dated inside its own period; an
    # ARREARS one in the month after it. One period of margin on each
    # side covers both, and every candidate is filtered by its actual
    # invoice date below — the window is an optimisation, never the
    # rule.
    window_start = period_index(date(year, 1, 1), months) - 1
    window_end = period_index(date(year, 12, 31), months) + 1
    scan_start = max(first_index, window_start)
    scan_end = window_end if last_index is None else min(window_end, last_index)
    if scan_end - scan_start > MAX_PERIODS:
        scan_end = scan_start + MAX_PERIODS

    scheduled: list = []
    for index in range(scan_start, scan_end + 1):
        row = row_for(index)
        if row is None:
            continue
        if row.invoice_date.year != year:
            continue
        scheduled.append(row)

    # Yearly = the sum of the ACTUAL period amounts scheduled in the
    # year, first invoice included. Never monthly * 12.
    forecast.yearly_amount = money(
        sum((row.amount for row in scheduled), Decimal("0.00"))
    )

    visible = [
        row
        for row in scheduled
        if forecast.first_invoice_date is None
        or row.invoice_date > forecast.first_invoice_date
    ]
    forecast.excluded_first_invoice = len(visible) != len(scheduled)
    forecast.rows = visible
    forecast.rows_total = money(
        sum((row.amount for row in visible), Decimal("0.00"))
    )
    return forecast
