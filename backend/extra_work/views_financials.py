"""Sprint W1-C (`docs/planning/ew-gap-closing-plan.md` §2.4) — the Extra
Work money strip.

FOUR figures, and only four. Each one answers a question an operator
would otherwise have to ask somebody:

  1. `quoted_not_started`     the customer agreed the price and nothing
                              operational has begun. Money committed,
                              not yet earned.
  2. `in_progress`            work has started and is not finished.
                              Money that lands when it does.
  3. `done_this_period`       work finished inside the billing month.
  4. `invoiced_this_period`   of (3), the part actually billed.

(1) and (2) are STOCKS — where the open book stands right now, no
period. (3) and (4) are FLOWS inside one billing month, and (4) is a
SUBSET of (3), not a fifth thing beside it, so the strip adds up on
screen the way the sentence "of that, how much has been billed" says it
should.

## The one money rule

Every figure goes through `reports.dimensions._amounts_for_state`, the
server-side mirror of `rowAmounts()` in `frontend/src/lib/billing.ts`:
prefer the final (actual-hours) amounts, fall back to the quoted
estimate only when `final_total_amount` is NULL. NOTHING here computes
money. The names imported from `reports.dimensions` are private to it on
purpose — importing them IS the point, because the alternative is a
second copy of the rule, and a second copy is exactly the defect this
sprint exists to avoid (the reference system computes a work total six
ways with three rounding points and two of them disagree by cents on
the same record).

Every row the strip reads is one the shared classifier calls `earned` or
`in_progress`, and `_amounts_for_state` prefers the final amounts for
BOTH, so one uniform rule covers the whole strip — identical to
`rowAmounts()`, with no state-dependent branch of our own.

## Which rows land where

The classification is likewise not ours. `is_billable`
(`extra_work.billing`) decides "may this be invoiced at all" — it rules
out CANCELLED and CUSTOMER_REJECTED work and then asks `is_earned`;
`billing_month` decides which month; `_classify_extra_work` decides the
rest. The billing-cutoff sprint (W1-B) widens `is_earned`, and because
this endpoint CALLS it rather than restating it, that widening arrives
here on its own.

The only judgement this module adds is the split of the classifier's
`in_progress` state into figures 1 and 2, on one question: has anybody
actually started? A spawned ticket still at OPEN has not, so it counts
as committed-not-started alongside the (rare, and per Sprint 180 §1(b)
anomalous) approved-with-no-ticket row. Figures 1 and 2 therefore sum to
the revenue report's `in_progress` bucket, less work that was called off
(`is_billable`'s two statuses, which that report still counts because it
classifies on the ticket). `test_w1c_financial_summary` asserts both
halves of that sentence.

## Two queries, not one per row

SQL narrows to a SUPERSET of the rows that can contribute (see
`_candidate_filter`); Python classifies. That is the house pattern —
`extra_work.filters.filter_billing_period` and
`reports.dimensions._resolve_extra_work_revenue_rows` both do exactly
this — and it is the only shape that can REUSE `is_billable` /
`billing_month` / `_amounts_for_state` instead of transliterating them
into SQL. The cost is two queries in total, constant in the number of
rows: one for the Extra Work rows, one for `build_ticket_map`.
`test_w1c_financial_summary` pins that with `assertNumQueries` at two
different row counts, so an N+1 cannot creep in unnoticed.

## Who may ask

Provider management only (SUPER_ADMIN / COMPANY_ADMIN /
BUILDING_MANAGER), via
`accounts.permissions.is_provider_management_role` — the same admit set
the frontend's `isProviderManagementRole` gates the strip on. Rows come
from `scope_extra_work_for`, so a COMPANY_ADMIN sees their company and a
BUILDING_MANAGER their buildings, and no new scoping helper exists to
drift from the old one. STAFF and CUSTOMER_USER get 403: a customer must
never see another customer's money, and their own already has a
customer-facing surface — a provider's commercial roll-up is not
something to hand them by accident.
"""
from __future__ import annotations

import calendar
from datetime import date as date_type, datetime, time, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from django.conf import settings
from django.db.models import (
    BooleanField,
    Case,
    Exists,
    OuterRef,
    Q,
    Subquery,
    When,
    Value,
)
from django.utils import timezone
from rest_framework import status as http_status
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.permissions import (
    IsAuthenticatedAndActive,
    is_provider_management_role,
)
from tickets.models import TERMINAL_TICKET_STATUSES, Ticket, TicketStatus

from .billing import (
    NON_BILLABLE_STATUSES,
    billing_month,
    build_ticket_map,
    is_billable,
)
from .models import (
    ExtraWorkPricingLineItem,
    ExtraWorkRequestItem,
    ExtraWorkRoutingDecision,
    Proposal,
    ProposalLine,
    ProposalStatus,
)
from .scoping import scope_extra_work_for


#: The four figures, in the order they are read on screen. An ORDERED
#: EXPORTED CONSTANT rather than a literal repeated per consumer — the
#: Sprint 126/130 lesson in CLAUDE.md: a second array maintained beside
#: the first is what left a permission group rendering headerless and
#: invisible for three sprints.
FIGURE_KEYS = (
    "quoted_not_started",
    "in_progress",
    "done_this_period",
    "invoiced_this_period",
)

ZERO = Decimal("0.00")


def is_priced_expression():
    """"Has anyone put a price on this Extra Work yet?" as ONE ORM
    expression, over any `ExtraWorkRequest` queryset.

    Lifted out of `ExtraWorkRequestViewSet.get_queryset` (Sprint 188) so
    the list and this aggregate cannot answer it differently; `views.py`
    imports it from here now. Three EXISTS subqueries for the whole page,
    and the resolution order mirrors `final_amounts.active_priced_lines`
    exactly — approved proposal wins, then the cart for an INSTANT route,
    then the legacy rows — because a display that disagreed with the
    money rule would be worse than no display at all.

    ZERO IS A LEGAL PRICE. This is not `total_amount == 0`: free work and
    a goodwill line are ordinary business, and "nobody has priced this"
    has to read as an absence.
    """
    priced_proposal = ProposalLine.objects.filter(
        proposal__extra_work_request_id=OuterRef("pk"),
        proposal__status=ProposalStatus.CUSTOMER_APPROVED,
        is_approved_for_spawn=True,
    )
    any_approved_proposal = Proposal.objects.filter(
        extra_work_request_id=OuterRef("pk"),
        status=ProposalStatus.CUSTOMER_APPROVED,
    )
    # W-FIX1 A3 (audit F3) — a SENT proposal that carries lines IS a
    # price on the record: the customer is looking at it. Before this,
    # PRICING_PROPOSED read "Not priced yet" in the header beside
    # "Priced. Confirm the pricing below" in WHAT NEXT — one status, two
    # answers — because only an APPROVED proposal counted. Zero is still
    # a legal price: this asks whether a line EXISTS, never what it costs.
    sent_proposal_line = ProposalLine.objects.filter(
        proposal__extra_work_request_id=OuterRef("pk"),
        proposal__status=ProposalStatus.SENT,
    )
    cart_rows = ExtraWorkRequestItem.objects.filter(
        extra_work_request_id=OuterRef("pk")
    )
    # NB the FK on the legacy row is `extra_work`, not
    # `extra_work_request` like the other two.
    legacy_rows = ExtraWorkPricingLineItem.objects.filter(
        extra_work_id=OuterRef("pk")
    )
    return Case(
        When(Exists(any_approved_proposal), then=Exists(priced_proposal)),
        When(Exists(sent_proposal_line), then=Value(True)),
        When(
            routing_decision=ExtraWorkRoutingDecision.INSTANT,
            then=Exists(cart_rows),
        ),
        default=Exists(legacy_rows),
        output_field=BooleanField(),
    )


def _parse_period(raw) -> tuple[int, int]:
    """`YYYY-MM`, defaulting to the CURRENT month in the project
    timezone. Fail closed on anything unparseable — a strip quietly
    showing the wrong month is worse than a 400."""
    if not raw:
        today = timezone.localdate()
        return today.year, today.month
    try:
        year_s, month_s = str(raw).split("-")
        year, month = int(year_s), int(month_s)
        if not (1 <= month <= 12):
            raise ValueError
        # Inside the try, so a parseable but impossible year (0000,
        # 10000) raises here and becomes the same 400, not a 500.
        date_type(year, month, 1)
    except (ValueError, AttributeError):
        raise ValidationError({"billing_period": "Expected YYYY-MM."})
    return year, month


def _period_bounds(year: int, month: int):
    """(first_day, last_day, aware_lo, aware_hi) for the month.

    The aware bounds are LOCAL midnights, matching `billing_month`'s
    `timezone.localtime(ticket.closed_at).date()`: a ticket closed 00:30
    local on the 1st is 22:30 UTC the previous day, and a naive UTC
    comparison would drop it out of the month it actually bills in
    (#109 Part C).
    """
    last_day = calendar.monthrange(year, month)[1]
    first = date_type(year, month, 1)
    last = date_type(year, month, last_day)
    tz = ZoneInfo(settings.TIME_ZONE)
    lo = datetime.combine(first, time.min, tzinfo=tz)
    hi = datetime.combine(last + timedelta(days=1), time.min, tzinfo=tz)
    return first, last, lo, hi


def _parse_optional_id(raw, field: str):
    if raw in (None, ""):
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        raise ValidationError({field: "Expected an integer id."})


def _candidate_filter(period_first, period_last, period_lo, period_hi) -> Q:
    """A SUPERSET of the rows that can contribute to any figure.

    Keep a row when:

      * it has no spawned operational ticket — no history can hide here,
        the set is open commercial work; or
      * its spawned ticket is not terminal — still open operational work.
        This is also what keeps a WAITING_CUSTOMER_APPROVAL row in scope
        for W1-B's billing cutoff, which will start calling such work
        earned; or
      * its billing anchor falls inside the period — the only way
        `billing_month` can return this month, since it returns
        `invoice_date`'s month when that is set and the LOCAL month of
        the first ticket's `closed_at` otherwise.

    What that drops is exactly the rows with a terminal ticket anchored
    outside the period: finished-and-billed history, which no figure
    reads. Nothing else is excluded, and
    `test_w1c_financial_summary.NarrowingLosesNothingTests` proves it by
    comparing the endpoint against a brute-force walk of every row in
    scope.
    """
    return (
        Q(first_ticket_status__isnull=True)
        | ~Q(first_ticket_status__in=sorted(TERMINAL_TICKET_STATUSES))
        | Q(invoice_date__gte=period_first, invoice_date__lte=period_last)
        | Q(
            invoice_date__isnull=True,
            first_ticket_closed_at__gte=period_lo,
            first_ticket_closed_at__lt=period_hi,
        )
    )


def figures_for(ew, ticket, period, state) -> tuple[str, ...]:
    """The figure keys this row contributes to — zero, one or two of
    them.

    `is_billable` is asked FIRST, and that is what keeps the buckets
    mutually exclusive: when W1-B widens `is_earned` to cover work
    waiting on a customer before the cutoff, such a row MOVES from
    figure 2 to figure 3 rather than appearing in both.

    Two keys come back for invoiced work, because figure 4 is a subset
    of figure 3 rather than a bucket beside it.
    """
    if is_billable(ew, ticket):
        if billing_month(ew, ticket) != period:
            # Earned, but in some other month. No figure reads it: (3)
            # and (4) are this period, (1) and (2) are unfinished work.
            return ()
        if ew.is_invoiced:
            return ("done_this_period", "invoiced_this_period")
        return ("done_this_period",)
    if ew.status in NON_BILLABLE_STATUSES:
        # Called off. `is_billable` already refused it above, but the
        # shared classifier reads the TICKET, and a CANCELLED or
        # CUSTOMER_REJECTED Extra Work whose already-spawned ticket runs
        # on still classifies as `in_progress`. Left alone, the strip
        # would promise money for work we told the customer was
        # cancelled — the same hole `is_billable` was written to close on
        # the invoice side, one bucket over.
        return ()
    if state != "in_progress":
        # `quoted_pipeline` is not committed money — nobody has approved
        # it yet — and `lost` never will be. Neither belongs in a strip
        # about work that is going to be billed.
        return ()
    # The one split this module owns: has anybody actually started?
    if ticket is None or ticket.status == TicketStatus.OPEN:
        return ("quoted_not_started",)
    return ("in_progress",)


def _empty_bucket() -> dict:
    return {
        "count": 0,
        "unpriced_count": 0,
        "subtotal": ZERO,
        "vat": ZERO,
        "total": ZERO,
    }


def _add(bucket: dict, ew, amounts) -> None:
    subtotal, vat, total = amounts
    bucket["count"] += 1
    # DISPLAY ONLY, and deliberately NOT a change to the sum: an unpriced
    # row contributes zero because zero is what it contributes
    # (`billing.ts` says so in as many words, and `sumRows` there is
    # untouched for the same reason). What the count buys the strip is
    # the difference between "this bucket costs nothing" and "nobody has
    # priced any of it" — two facts that must not render the same.
    if getattr(ew, "annotated_is_priced", True) is False:
        bucket["unpriced_count"] += 1
    bucket["subtotal"] += subtotal if subtotal is not None else ZERO
    bucket["vat"] += vat if vat is not None else ZERO
    bucket["total"] += total if total is not None else ZERO


def _render(bucket: dict) -> dict:
    return {
        "count": bucket["count"],
        "unpriced_count": bucket["unpriced_count"],
        "subtotal": str(bucket["subtotal"].quantize(Decimal("0.01"))),
        "vat": str(bucket["vat"].quantize(Decimal("0.01"))),
        "total": str(bucket["total"].quantize(Decimal("0.01"))),
    }


def compute_financial_summary(actor, query_params) -> dict:
    """The four figures for `actor`, scoped by `scope_extra_work_for`.

    Two queries, constant in the row count. See the module docstring.
    """
    # Local import: `reports.dimensions` imports `extra_work.billing` at
    # module level, and `extra_work.urls` imports this module at startup.
    # Keeping the edge inside the call keeps the import graph acyclic
    # whatever `reports` grows next.
    from reports.dimensions import _amounts_for_state, _classify_extra_work

    year, month = _parse_period(query_params.get("billing_period"))
    period = (year, month)
    period_first, period_last, period_lo, period_hi = _period_bounds(year, month)

    customer_id = _parse_optional_id(query_params.get("customer"), "customer")
    building_id = _parse_optional_id(query_params.get("building"), "building")

    qs = scope_extra_work_for(actor)
    # Narrowing only: the scope helper ran first, so a filter can never
    # widen what the actor may see (the list endpoint's rule).
    if customer_id is not None:
        qs = qs.filter(customer_id=customer_id)
    if building_id is not None:
        qs = qs.filter(building_id=building_id)

    # The lowest-id non-deleted spawned ticket — the same row
    # `build_ticket_map` picks. Two scalar subqueries, so the narrowing
    # below runs in SQL without a second round trip.
    first_ticket = Ticket.objects.filter(
        extra_work_request_id=OuterRef("pk"), deleted_at__isnull=True
    ).order_by("id")

    rows = list(
        qs.annotate(
            first_ticket_status=Subquery(first_ticket.values("status")[:1]),
            first_ticket_closed_at=Subquery(
                first_ticket.values("closed_at")[:1]
            ),
            annotated_is_priced=is_priced_expression(),
        )
        .filter(
            _candidate_filter(period_first, period_last, period_lo, period_hi)
        )
        .only(
            "id",
            "status",
            "invoice_date",
            "is_invoiced",
            "subtotal_amount",
            "vat_amount",
            "total_amount",
            "final_subtotal_amount",
            "final_vat_amount",
            "final_total_amount",
        )
    )
    tickets_by_ew = build_ticket_map([r.id for r in rows])

    buckets = {key: _empty_bucket() for key in FIGURE_KEYS}
    for ew in rows:
        ticket = tickets_by_ew.get(ew.id)
        state = _classify_extra_work(ew, ticket)
        amounts = _amounts_for_state(ew, state)
        for key in figures_for(ew, ticket, period, state):
            _add(buckets[key], ew, amounts)

    return {
        "period": f"{year:04d}-{month:02d}",
        "figures": {key: _render(buckets[key]) for key in FIGURE_KEYS},
    }


class ExtraWorkFinancialSummaryView(APIView):
    """GET /api/extra-work/financial-summary/

    Query params, all optional:
      billing_period  YYYY-MM, default the current month
      customer        narrow to one customer id
      building        narrow to one building id
    """

    permission_classes = [IsAuthenticatedAndActive]

    def get(self, request):
        if not is_provider_management_role(request.user):
            raise PermissionDenied(
                "Only provider management may read the Extra Work "
                "financial summary."
            )
        return Response(
            compute_financial_summary(request.user, request.query_params),
            status=http_status.HTTP_200_OK,
        )
