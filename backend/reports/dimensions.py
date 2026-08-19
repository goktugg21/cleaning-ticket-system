"""
Sprint 5 — tickets-by-{type,customer,building} report dimensions.

Each endpoint:
- reuses the existing scope helpers (resolve_scope, tickets_for_scope,
  parse_date_range, date_range_to_aware_bounds);
- applies common filters (from / to / status) plus per-endpoint extras
  (company_id / building_id / customer_id / type aliases for company /
  building / customer / type);
- aggregates BEFORE serialisation so no role can see counts in scopes
  it cannot read tickets in;
- emits a `buckets` list ordered by `count` descending.

The CSV / PDF exporters reuse `compute_*` from this module so the JSON
view, CSV, and PDF cannot drift apart.

Hierarchy rules (Sprint 3.6):
- `Customer` is a customer-LOCATION, not a CustomerAccount.
- tickets-by-customer groups by `Customer.id`. Two customer rows that
  happen to share `name` at different buildings remain distinct
  because the response always carries `building_id` + `building_name`.
"""
from __future__ import annotations

import calendar
from datetime import date as date_type
from decimal import Decimal
from typing import Optional

from django.db.models import Case, CharField, Count, F, Q, Value, When
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied, ValidationError

from accounts.models import UserRole
from buildings.models import Building, BuildingManagerAssignment
from companies.models import Company, CompanyUserMembership
from customers.models import Customer, CustomerUserMembership, Department, WorkType
from extra_work.billing import billing_month, build_ticket_map, earned_at, is_earned
from extra_work.models import ExtraWorkStatus
from tickets.models import Ticket, TicketStatus, TicketType

from .scoping import (
    ResolvedScope,
    date_range_to_aware_bounds,
    extra_work_for_scope,
    parse_date_range,
    resolve_scope,
    tickets_for_scope,
)


# ---------------------------------------------------------------------------
# Filter parsing
# ---------------------------------------------------------------------------


def _first_param(qp, *names) -> Optional[str]:
    """Return the first non-empty value among the listed query-param names."""
    for name in names:
        v = qp.get(name)
        if v not in (None, ""):
            return v
    return None


def _parse_int(raw, field_name: str) -> Optional[int]:
    if raw is None or raw == "":
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        raise ValidationError({field_name: "Must be an integer."})


def _validate_status(raw: Optional[str]) -> Optional[str]:
    if raw is None or raw == "":
        return None
    if raw not in TicketStatus.values:
        raise ValidationError(
            {"status": f"Unknown status '{raw}'."}
        )
    return raw


def _validate_type(raw: Optional[str]) -> Optional[str]:
    if raw is None or raw == "":
        return None
    if raw not in TicketType.values:
        raise ValidationError(
            {"type": f"Unknown ticket type '{raw}'."}
        )
    return raw


# ---------------------------------------------------------------------------
# Ticket origin separation (Sprint 14A — Part A)
#
# Each operational Ticket is classified into exactly one origin. The
# classification is mutually exclusive and DB-side (a Case/When annotation),
# evaluated top-down so the FIRST matching branch wins:
#   CONVERTED  -> status == CONVERTED_TO_EXTRA_WORK (terminal; status wins
#                 even when the ticket also carries an extra_work_request).
#   EXTRA_WORK -> spawned from an ExtraWorkRequest (and not converted).
#   PLANNED    -> spawned from a PlannedOccurrence (and not the above).
#   NORMAL     -> ad-hoc ticket with no special origin.
# ---------------------------------------------------------------------------

ORIGIN_NORMAL = "NORMAL"
ORIGIN_EXTRA_WORK = "EXTRA_WORK"
ORIGIN_CONVERTED = "CONVERTED"
ORIGIN_PLANNED = "PLANNED"

# Fixed bucket-emission order (pinned by the Sprint 14A test). Buckets are
# emitted in this order; only origins with a non-zero count appear.
ORIGIN_ORDER = (
    ORIGIN_NORMAL,
    ORIGIN_EXTRA_WORK,
    ORIGIN_CONVERTED,
    ORIGIN_PLANNED,
)

ORIGIN_LABELS = {
    ORIGIN_NORMAL: "Normal",
    ORIGIN_EXTRA_WORK: "Extra Work",
    ORIGIN_CONVERTED: "Converted to Extra Work",
    ORIGIN_PLANNED: "Planned / recurring",
}


def _origin_case() -> Case:
    """DB-side Case/When that stamps the `origin` axis. Order matters:
    CONVERTED is checked before the EXTRA_WORK link so a converted ticket
    that also carries an extra_work_request classifies as CONVERTED."""
    return Case(
        When(status=TicketStatus.CONVERTED_TO_EXTRA_WORK, then=Value(ORIGIN_CONVERTED)),
        When(extra_work_request_id__isnull=False, then=Value(ORIGIN_EXTRA_WORK)),
        When(planned_occurrence_id__isnull=False, then=Value(ORIGIN_PLANNED)),
        default=Value(ORIGIN_NORMAL),
        output_field=CharField(),
    )


def _origin_filter_q(origin: str) -> Q:
    """Inverse Q matching the rows the `origin` annotation would stamp with
    `origin`. Mirrors `_origin_case` branch-by-branch so the ?origin= filter
    on the by-type/customer/building reports is byte-consistent with the
    standalone by-origin breakdown."""
    converted = Q(status=TicketStatus.CONVERTED_TO_EXTRA_WORK)
    if origin == ORIGIN_CONVERTED:
        return converted
    if origin == ORIGIN_EXTRA_WORK:
        return ~converted & Q(extra_work_request_id__isnull=False)
    if origin == ORIGIN_PLANNED:
        return (
            ~converted
            & Q(extra_work_request_id__isnull=True)
            & Q(planned_occurrence_id__isnull=False)
        )
    # NORMAL: none of the special origins.
    return (
        ~converted
        & Q(extra_work_request_id__isnull=True)
        & Q(planned_occurrence_id__isnull=True)
    )


class OriginInvalid(Exception):
    """Raised for an unrecognised ?origin= value. Carries the stable
    `origin_invalid` code; the dimension views render it as a clean
    400 body `{"detail": ..., "code": "origin_invalid"}` with the code
    as a plain string (DRF would otherwise wrap dict values in lists)."""

    code = "origin_invalid"

    def __init__(self, raw: str):
        self.raw = raw
        super().__init__(f"Unknown origin '{raw}'.")


def _validate_origin(raw: Optional[str]) -> Optional[str]:
    if raw is None or raw == "":
        return None
    if raw not in ORIGIN_ORDER:
        raise OriginInvalid(raw)
    return raw


def _customer_in_scope(actor, customer: Customer) -> bool:
    """
    Check whether `customer` is within the actor's allowed customer scope.
    Mirrors `tickets_for_scope` so the customer filter cannot be used to
    leak data from outside the actor's scope.
    """
    if actor.role == UserRole.SUPER_ADMIN:
        return True
    if actor.role == UserRole.COMPANY_ADMIN:
        company_ids = set(
            CompanyUserMembership.objects.filter(user=actor).values_list(
                "company_id", flat=True
            )
        )
        return customer.company_id in company_ids
    if actor.role == UserRole.BUILDING_MANAGER:
        building_ids = set(
            BuildingManagerAssignment.objects.filter(user=actor).values_list(
                "building_id", flat=True
            )
        )
        return customer.building_id in building_ids
    if actor.role == UserRole.CUSTOMER_USER:
        # CUSTOMER_USER is rejected at the permission layer
        # (IsReportsConsumer); this branch is defensive.
        return CustomerUserMembership.objects.filter(
            user=actor, customer_id=customer.id
        ).exists()
    return False


def _scoped_label_name(actor, model, label_id: int) -> Optional[str]:
    """Resolve a Department/WorkType `name` for a scope echo, but ONLY when
    the label's own customer is inside the actor's allowed scope — else
    `None`.

    Sprint 131 follow-up: the original version did an unscoped `.filter(id=
    ...).first()`, so an out-of-scope id (e.g. a competitor's department)
    still echoed that customer's real label name in `scope.department_name`
    even though the row filter (`ew_qs.filter(department_id=...)`) already
    silently matched zero rows for it. Deliberately `None`, not a 403: a
    403 would tell the caller the id EXISTS (an enumeration oracle) for a
    narrowing filter that the row-level query already treats as "matches
    nothing" rather than "forbidden" — the echo should agree with that, not
    diverge into a harder failure mode. This mirrors `_customer_in_scope`,
    the same check `_resolve_customer` uses; `customer` gets a 403 instead
    because it is scope-WIDENING (it selects what data the whole report
    covers), not a narrowing filter within an already-resolved scope, so a
    hard denial is the right response there and not here.
    """
    label = model.objects.filter(id=label_id).select_related("customer").first()
    if label is None or not _customer_in_scope(actor, label.customer):
        return None
    return label.name


def _resolve_customer(actor, raw: Optional[str]) -> Optional[Customer]:
    customer_id = _parse_int(raw, "customer")
    if customer_id is None:
        return None
    customer = Customer.objects.filter(id=customer_id).first()
    if customer is None or not _customer_in_scope(actor, customer):
        raise PermissionDenied("Forbidden.")
    return customer


# ---------------------------------------------------------------------------
# Common filter resolution shared across the three endpoints
# ---------------------------------------------------------------------------


class DimensionFilters:
    """
    Resolved + scope-validated filter set for a tickets-by-* endpoint.
    Exists so JSON / CSV / PDF views read the same parsed values from
    one place.
    """

    def __init__(self, actor, query_params, *, accept_customer: bool, accept_type: bool):
        self.actor = actor
        scope_company_raw = _first_param(query_params, "company", "company_id")
        scope_building_raw = _first_param(query_params, "building", "building_id")
        self.scope: ResolvedScope = resolve_scope(
            actor, scope_company_raw, scope_building_raw
        )

        self.from_date, self.to_date = parse_date_range(
            query_params.get("from"), query_params.get("to")
        )
        self.bound_lo, self.bound_hi = date_range_to_aware_bounds(
            self.from_date, self.to_date
        )

        self.status: Optional[str] = _validate_status(query_params.get("status"))

        if accept_customer:
            customer_raw = _first_param(query_params, "customer", "customer_id")
            self.customer: Optional[Customer] = _resolve_customer(actor, customer_raw)
        else:
            self.customer = None

        if accept_type:
            self.type: Optional[str] = _validate_type(query_params.get("type"))
        else:
            self.type = None

        # Sprint 14A — optional ?origin= filter, additive across every
        # dimension report. Absent => no narrowing (default behaviour
        # of the existing reports is unchanged). Invalid => OriginInvalid
        # (rendered as 400 / `origin_invalid` by the view).
        self.origin: Optional[str] = _validate_origin(query_params.get("origin"))

    def filtered_qs(self):
        qs = tickets_for_scope(self.actor, self.scope).filter(
            created_at__gte=self.bound_lo, created_at__lt=self.bound_hi
        )
        if self.status is not None:
            qs = qs.filter(status=self.status)
        if self.customer is not None:
            qs = qs.filter(customer_id=self.customer.id)
        if self.type is not None:
            qs = qs.filter(type=self.type)
        if self.origin is not None:
            qs = qs.filter(_origin_filter_q(self.origin))
        return qs

    def scope_summary(self) -> dict:
        out = self.scope.to_dict()
        out["customer_id"] = self.customer.id if self.customer is not None else None
        out["customer_name"] = self.customer.name if self.customer is not None else None
        out["type"] = self.type
        out["status"] = self.status
        out["origin"] = self.origin
        return out


# ---------------------------------------------------------------------------
# Per-endpoint aggregate computations
# ---------------------------------------------------------------------------


def _label_for_type(value: str) -> str:
    return dict(TicketType.choices).get(value, value)


def compute_tickets_by_type(filters: DimensionFilters) -> dict:
    qs = filters.filtered_qs()
    rows = (
        qs.values("type")
        .annotate(count=Count("id"))
        .order_by("-count", "type")
    )
    buckets = [
        {
            "ticket_type": str(row["type"]),
            "ticket_type_label": _label_for_type(str(row["type"])),
            "count": int(row["count"]),
        }
        for row in rows
    ]
    return _wrap(filters, buckets)


def compute_tickets_by_origin(filters: DimensionFilters) -> dict:
    qs = filters.filtered_qs().annotate(origin=_origin_case())
    rows = qs.values("origin").annotate(count=Count("id"))
    counts = {str(row["origin"]): int(row["count"]) for row in rows}
    # Emit buckets in the pinned ORIGIN_ORDER; only non-zero origins
    # appear. Order is stable and independent of count (the test pins
    # the fixed-order contract).
    buckets = [
        {
            "origin": origin,
            "origin_label": ORIGIN_LABELS[origin],
            "count": counts[origin],
        }
        for origin in ORIGIN_ORDER
        if counts.get(origin, 0) > 0
    ]
    return _wrap(filters, buckets)


def compute_tickets_by_customer(filters: DimensionFilters) -> dict:
    qs = filters.filtered_qs()
    rows = (
        qs.values(
            "customer_id",
            "building_id",
            "company_id",
            customer_name=F("customer__name"),
            building_name=F("building__name"),
            company_name=F("company__name"),
        )
        .annotate(count=Count("id"))
        .order_by("-count", "customer_name", "building_name")
    )
    # `Customer` is a customer-LOCATION, not a CustomerAccount. Always
    # include building_id + building_name so two `Customer` rows that
    # share a name at different buildings remain visibly distinct.
    buckets = [
        {
            "customer_id": int(row["customer_id"]),
            "customer_name": row["customer_name"],
            "building_id": int(row["building_id"]),
            "building_name": row["building_name"],
            "company_id": int(row["company_id"]),
            "company_name": row["company_name"],
            "count": int(row["count"]),
        }
        for row in rows
    ]
    return _wrap(filters, buckets)


def compute_tickets_by_building(filters: DimensionFilters) -> dict:
    qs = filters.filtered_qs()
    rows = (
        qs.values(
            "building_id",
            "company_id",
            building_name=F("building__name"),
            company_name=F("company__name"),
        )
        .annotate(count=Count("id"))
        .order_by("-count", "building_name")
    )
    buckets = [
        {
            "building_id": int(row["building_id"]),
            "building_name": row["building_name"],
            "company_id": int(row["company_id"]),
            "company_name": row["company_name"],
            "count": int(row["count"]),
        }
        for row in rows
    ]
    return _wrap(filters, buckets)


def _wrap(filters: DimensionFilters, buckets: list) -> dict:
    return {
        "from": filters.from_date.isoformat(),
        "to": filters.to_date.isoformat(),
        "scope": filters.scope_summary(),
        "buckets": buckets,
        "total": sum(b["count"] for b in buckets),
        "generated_at": timezone.now().isoformat(),
    }


# ===========================================================================
# Sprint 14A — Part B: Extra Work revenue states.
#
# Each in-scope ExtraWorkRequest is classified into EXACTLY ONE revenue
# state, and an amount is picked per the rules below. The four states are
# mutually exclusive; every in-scope row lands in exactly one.
#
# State classification (one spawned operational ticket per EW, linked via
# Ticket.extra_work_request):
#   t = first non-deleted spawned ticket (or None).
#   EARNED          : `extra_work.billing.is_earned(t)` — t.status == CLOSED,
#                     OR (Sprint W1-B, the billing cutoff) t.status ==
#                     WAITING_CUSTOMER_APPROVAL with `sent_for_approval_at`
#                     stamped. Called, never re-tested here: billing and
#                     revenue reporting have to mean the same thing by
#                     `earned`, and the only way to guarantee that is one
#                     function. WAITING_MANAGER_REVIEW is in neither arm.
#   LOST            : t.status in {REJECTED, CONVERTED_TO_EXTRA_WORK}, OR
#                     (t is None AND ew.status in {CUSTOMER_REJECTED,
#                      CANCELLED}).
#   IN_PROGRESS     : t is not None and not terminal (any other status), OR
#                     (t is None AND ew.status in {CUSTOMER_APPROVED,
#                      IN_PROGRESS, COMPLETED}).
#   QUOTED_PIPELINE : t is None AND ew.status in {REQUESTED, UNDER_REVIEW,
#                     PRICING_PROPOSED}.
#
# Amount selection:
#   EARNED / IN_PROGRESS prefer the FINAL amounts (final_subtotal_amount /
#     final_vat_amount / final_total_amount) — the actual billable figure
#     frozen at approval — and fall back to the estimate (subtotal_amount /
#     vat_amount / total_amount) ONLY when final_total_amount is NULL
#     (legacy / fixed-price rows that never ran recompute_final_amounts).
#   QUOTED_PIPELINE / LOST use the estimate amounts (the quoted value of a
#     pipeline opportunity / lost deal — there is no final figure).
#
# Date window: anchored on `requested_at` (the EW creation timestamp),
# the Extra Work analogue of the dimension reports' `created_at` anchor.
# ===========================================================================

_REVENUE_STATES = ("earned", "in_progress", "quoted_pipeline", "lost")

_EW_TERMINAL_NO_TICKET_LOST = {
    ExtraWorkStatus.CUSTOMER_REJECTED,
    ExtraWorkStatus.CANCELLED,
}
_EW_NO_TICKET_IN_PROGRESS = {
    ExtraWorkStatus.CUSTOMER_APPROVED,
    ExtraWorkStatus.IN_PROGRESS,
    ExtraWorkStatus.COMPLETED,
}
_EW_NO_TICKET_PIPELINE = {
    ExtraWorkStatus.REQUESTED,
    ExtraWorkStatus.UNDER_REVIEW,
    ExtraWorkStatus.PRICING_PROPOSED,
}


def _classify_extra_work(ew, ticket) -> str:
    """Return the revenue state for one EW + its (optional) spawned ticket."""
    if ticket is not None:
        # ONE definition of earned, shared with the invoice run — see the
        # block comment above and `extra_work/billing.py`.
        if is_earned(ticket):
            return "earned"
        if ticket.status in (
            TicketStatus.REJECTED,
            TicketStatus.CONVERTED_TO_EXTRA_WORK,
        ):
            return "lost"
        # Any other (non-terminal) spawned-ticket status.
        return "in_progress"
    # No spawned ticket — classify on the EW's own lifecycle status.
    if ew.status in _EW_TERMINAL_NO_TICKET_LOST:
        return "lost"
    if ew.status in _EW_NO_TICKET_IN_PROGRESS:
        return "in_progress"
    # REQUESTED / UNDER_REVIEW / PRICING_PROPOSED (or any other) -> pipeline.
    return "quoted_pipeline"


def _amounts_for_state(ew, state: str):
    """Pick (subtotal, vat, total) Decimals for the EW given its state.

    EARNED / IN_PROGRESS prefer the FINAL amounts and fall back to the
    estimate only when final_total_amount is NULL. PIPELINE / LOST always
    use the estimate."""
    prefer_final = state in ("earned", "in_progress")
    if prefer_final and ew.final_total_amount is not None:
        return (
            ew.final_subtotal_amount,
            ew.final_vat_amount,
            ew.final_total_amount,
        )
    return (ew.subtotal_amount, ew.vat_amount, ew.total_amount)


def _money(value) -> str:
    """Render a Decimal money value as a 2dp string (canonical wire shape)."""
    if value is None:
        value = Decimal("0.00")
    return str(value.quantize(Decimal("0.01")))


def _resolve_extra_work_revenue_rows(actor, query_params):
    """Sprint 124 — shared scope/customer/date-window resolution + the
    exact in-scope `ExtraWorkRequest` queryset + spawned-ticket map,
    factored out of `compute_extra_work_revenue` so it can be reused
    verbatim by `compute_extra_work_revenue_by_building`. Both callers
    then run the SAME `_classify_extra_work` / `_amounts_for_state`
    functions per row — only the accumulation (by state vs. by
    building) differs. This is deliberate: the money calculation must
    exist in exactly one place, so a future change to billing_period /
    invoice_status / scope handling cannot silently diverge between the
    flat report and the by-building one and break the "buckets sum to
    the total" invariant.

    Returns (ew_qs, tickets_by_ew, from_date, to_date, scope, customer).
    """
    scope_company_raw = _first_param(query_params, "company", "company_id")
    scope_building_raw = _first_param(query_params, "building", "building_id")
    scope = resolve_scope(actor, scope_company_raw, scope_building_raw)

    # #109 Part H — optional additive `customer` (+ `customer_id` alias),
    # scope-checked with the SAME in-scope mirror the ticket dimension
    # reports use: out-of-scope / nonexistent -> 403 (PermissionDenied),
    # non-integer -> 400 (ValidationError). Honored in BOTH modes below.
    customer_raw = _first_param(query_params, "customer", "customer_id")
    customer = _resolve_customer(actor, customer_raw)

    billing_period_raw = query_params.get("billing_period")
    invoice_status_raw = query_params.get("invoice_status")

    if billing_period_raw:
        # M4 billing-month mode: anchor on COALESCE(invoice_date,
        # spawned-ticket completion date) via extra_work.billing — the
        # SAME logic the invoice run and the EW list filter use —
        # restricted to EARNED EW. Bypasses the requested_at window; the
        # payload period reflects the billing month so the CSV/PDF
        # filenames + headers track it.
        try:
            _yr, _mo = billing_period_raw.split("-")
            year, month = int(_yr), int(_mo)
            if not (1 <= month <= 12):
                raise ValueError
            # Build the month's date range INSIDE the try so a parseable but
            # out-of-range year (e.g. 0000-05, 10000-05) raises ValueError ->
            # the same 400, not an uncaught 500.
            from_date = date_type(year, month, 1)
            to_date = date_type(year, month, calendar.monthrange(year, month)[1])
        except (ValueError, AttributeError):
            raise ValidationError({"billing_period": "Expected YYYY-MM."})

        # Fail closed on a provided-but-unknown invoice_status (a typo like
        # "complete") instead of silently dropping the filter and mixing
        # invoiced + not-yet-invoiced totals in the export.
        if invoice_status_raw and invoice_status_raw not in (
            "completed",
            "invoiced",
        ):
            raise ValidationError(
                {"invoice_status": "Expected 'completed' or 'invoiced'."}
            )

        base_qs = extra_work_for_scope(actor, scope)
        if customer is not None:
            base_qs = base_qs.filter(customer_id=customer.id)
        _ew_list = list(base_qs)
        _ticket_map = build_ticket_map([e.id for e in _ew_list])

        def _bills_in_month(e):
            t = _ticket_map.get(e.id)
            if not is_earned(t) or billing_month(e, t) != (year, month):
                return False
            if invoice_status_raw == "invoiced":
                return e.is_invoiced
            if invoice_status_raw == "completed":
                return not e.is_invoiced
            return True

        ew_qs = base_qs.filter(
            id__in=[e.id for e in _ew_list if _bills_in_month(e)]
        )
    else:
        from_date, to_date = parse_date_range(
            query_params.get("from"), query_params.get("to")
        )
        bound_lo, bound_hi = date_range_to_aware_bounds(from_date, to_date)
        ew_qs = extra_work_for_scope(actor, scope).filter(
            requested_at__gte=bound_lo, requested_at__lt=bound_hi
        )
        if customer is not None:
            ew_qs = ew_qs.filter(customer_id=customer.id)

    # One spawned operational ticket per EW (linked via
    # Ticket.extra_work_request). Map ew_id -> ticket so the classifier
    # does not issue a query per row.
    ew_ids = list(ew_qs.values_list("id", flat=True))
    tickets_by_ew: dict = {}
    if ew_ids:
        for t in (
            Ticket.objects.filter(
                extra_work_request_id__in=ew_ids, deleted_at__isnull=True
            )
            # `closed_at` / `sent_for_approval_at`: the two `earned_at`
            # anchors, both read per row below (state classification and
            # the Completed At column). Deferring either turns this into
            # one extra query per Extra Work on a whole-month report.
            .only(
                "id",
                "status",
                "closed_at",
                "sent_for_approval_at",
                "extra_work_request_id",
            )
            .order_by("id")
        ):
            # `.first()` semantics: keep the lowest-id ticket per EW.
            tickets_by_ew.setdefault(t.extra_work_request_id, t)

    return ew_qs, tickets_by_ew, from_date, to_date, scope, customer


def compute_extra_work_revenue(actor, query_params) -> dict:
    ew_qs, tickets_by_ew, from_date, to_date, scope, customer = (
        _resolve_extra_work_revenue_rows(actor, query_params)
    )

    acc = {
        s: {
            "count": 0,
            "subtotal": Decimal("0.00"),
            "vat": Decimal("0.00"),
            "total": Decimal("0.00"),
        }
        for s in _REVENUE_STATES
    }

    for ew in ew_qs:
        ticket = tickets_by_ew.get(ew.id)
        state = _classify_extra_work(ew, ticket)
        subtotal, vat, total = _amounts_for_state(ew, state)
        bucket = acc[state]
        bucket["count"] += 1
        bucket["subtotal"] += subtotal or Decimal("0.00")
        bucket["vat"] += vat or Decimal("0.00")
        bucket["total"] += total or Decimal("0.00")

    states = {
        s: {
            "count": acc[s]["count"],
            "subtotal": _money(acc[s]["subtotal"]),
            "vat": _money(acc[s]["vat"]),
            "total": _money(acc[s]["total"]),
        }
        for s in _REVENUE_STATES
    }
    totals = {
        "count": sum(acc[s]["count"] for s in _REVENUE_STATES),
        "subtotal": _money(sum((acc[s]["subtotal"] for s in _REVENUE_STATES), Decimal("0.00"))),
        "vat": _money(sum((acc[s]["vat"] for s in _REVENUE_STATES), Decimal("0.00"))),
        "total": _money(sum((acc[s]["total"] for s in _REVENUE_STATES), Decimal("0.00"))),
    }

    scope_dict = scope.to_dict()
    if customer is not None:
        # Mirror DimensionFilters.scope_summary so exports._scope_summary_
        # lines renders "Customer: <name>" in the PDF and JSON consumers
        # can echo the customer the totals were scoped to.
        scope_dict["customer_id"] = customer.id
        scope_dict["customer_name"] = customer.name

    return {
        "from": from_date.isoformat(),
        "to": to_date.isoformat(),
        "scope": scope_dict,
        "states": states,
        "totals": totals,
        "generated_at": timezone.now().isoformat(),
    }


# ===========================================================================
# Sprint 124 — Extra Work revenue grouped by BUILDING (one customer's
# revenue split across that customer's buildings).
#
# Reuses `_resolve_extra_work_revenue_rows` (the exact same in-scope
# ExtraWorkRequest queryset, ticket map, scope/customer/date-window
# resolution as the flat `compute_extra_work_revenue`) and the exact same
# `_classify_extra_work` / `_amounts_for_state` per-row functions — the
# ONLY difference from the flat report is the accumulator key (building_id
# instead of revenue state). This is what guarantees
# sum(bucket.total for bucket in buckets) == the flat report's totals.total
# for the same filters: both reports classify + sum the identical set of
# rows, just partitioned differently.
#
# A building with zero in-scope revenue for the period is OMITTED, not
# emitted as a padded zero row — mirroring `compute_tickets_by_building`'s
# own GROUP-BY-implied behaviour (a building with zero matching tickets
# never appears there either). The customer Reports chart already has to
# stay readable at 18+ buildings (the dev seed's "B Amsterdam" customer),
# and a zero-revenue bar for every building with no activity in the
# selected period would make that worse for no informational gain; the
# grand total is identical either way since an omitted zero bucket
# contributes nothing to the sum.
# ===========================================================================


def compute_extra_work_revenue_by_building(actor, query_params) -> dict:
    ew_qs, tickets_by_ew, from_date, to_date, scope, customer = (
        _resolve_extra_work_revenue_rows(actor, query_params)
    )

    acc_by_building: dict = {}
    building_meta: dict = {}
    # select_related avoids an N+1 for building/company name lookups —
    # ExtraWorkRequest.building and .company are both direct FKs (not
    # reached through the ticket), so this is a single extra JOIN.
    for ew in ew_qs.select_related("building", "company"):
        ticket = tickets_by_ew.get(ew.id)
        state = _classify_extra_work(ew, ticket)
        subtotal, vat, total = _amounts_for_state(ew, state)
        b_id = ew.building_id
        if b_id not in acc_by_building:
            acc_by_building[b_id] = {
                "count": 0,
                "subtotal": Decimal("0.00"),
                "vat": Decimal("0.00"),
                "total": Decimal("0.00"),
            }
            building_meta[b_id] = {
                "building_name": ew.building.name,
                "company_id": ew.company_id,
                "company_name": ew.company.name,
            }
        bucket = acc_by_building[b_id]
        bucket["count"] += 1
        bucket["subtotal"] += subtotal or Decimal("0.00")
        bucket["vat"] += vat or Decimal("0.00")
        bucket["total"] += total or Decimal("0.00")

    # Highest revenue first (the chart's natural reading order — the
    # building that earned the most money is the headline), tie-broken by
    # name for a stable order. Sorted on the Decimal accumulator, not the
    # stringified 2dp value, so ordering is exact.
    ordered_ids = sorted(
        acc_by_building.keys(),
        key=lambda b_id: (
            -acc_by_building[b_id]["total"],
            building_meta[b_id]["building_name"],
        ),
    )
    buckets = [
        {
            "building_id": b_id,
            "building_name": building_meta[b_id]["building_name"],
            "company_id": building_meta[b_id]["company_id"],
            "company_name": building_meta[b_id]["company_name"],
            "count": acc_by_building[b_id]["count"],
            "subtotal": _money(acc_by_building[b_id]["subtotal"]),
            "vat": _money(acc_by_building[b_id]["vat"]),
            "total": _money(acc_by_building[b_id]["total"]),
        }
        for b_id in ordered_ids
    ]

    totals = {
        "count": sum(acc_by_building[b_id]["count"] for b_id in acc_by_building),
        "subtotal": _money(
            sum(
                (acc_by_building[b_id]["subtotal"] for b_id in acc_by_building),
                Decimal("0.00"),
            )
        ),
        "vat": _money(
            sum(
                (acc_by_building[b_id]["vat"] for b_id in acc_by_building),
                Decimal("0.00"),
            )
        ),
        "total": _money(
            sum(
                (acc_by_building[b_id]["total"] for b_id in acc_by_building),
                Decimal("0.00"),
            )
        ),
    }

    scope_dict = scope.to_dict()
    if customer is not None:
        scope_dict["customer_id"] = customer.id
        scope_dict["customer_name"] = customer.name

    return {
        "from": from_date.isoformat(),
        "to": to_date.isoformat(),
        "scope": scope_dict,
        "buckets": buckets,
        "totals": totals,
        "generated_at": timezone.now().isoformat(),
    }


# ===========================================================================
# Sprint 131 — Extra Work revenue grouped Building -> Department -> Work
# Type, one level deeper than Sprint 124's by-building report. Reproduces
# the owner's father's reference "Extra Works by Department" report.
#
# Reuses `_resolve_extra_work_revenue_rows` + the per-row `_classify_
# extra_work` / `_amounts_for_state` functions VERBATIM — same guarantee as
# `compute_extra_work_revenue_by_building`: summing every leaf bucket's
# `total` reproduces `compute_extra_work_revenue`'s flat total for the same
# filters, because both reports classify + sum the identical row set, only
# partitioned differently (three keys deep here instead of one).
#
# An EW with no department, or no work type, is NOT dropped: it lands in an
# explicit untagged bucket (department_id=None / work_type_id=None,
# department_name=None / work_type_name=None — the frontend/PDF render the
# localized "No department" / "No work type" label for a None id). Every
# existing EW predates the Sprint 127 labels, so today EVERY row lands in
# the untagged bucket for both levels — that is the expected starting
# state, not a bug, and it is exactly why the untagged bucket must exist:
# silently dropping unlabeled rows would make this report disagree with
# the flat revenue total for every customer that has not finished tagging
# their history yet.
#
# `department` / `work_type` (optional, additive) narrow the SAME already-
# scoped `ew_qs`: because both are columns on `ExtraWorkRequest` itself
# (not a scope-widening parameter like `customer`), filtering by an
# out-of-scope id simply matches zero rows — no separate scope check is
# needed for the ROW filter the way `_resolve_customer` validates
# `customer`. The scope ECHO is a different story: resolving an id's
# `name` for the response touches a row the actor may not be allowed to
# see even though the EW filter above never leaks its data, so THAT half
# is scope-checked via `_scoped_label_name` (below) — a real gap in an
# earlier version of this function, closed once found.
#
# Detail rows carry "Completed At" / "Week No": the spawned operational
# ticket's `closed_at`, localized to the project timezone — the SAME field
# `extra_work.billing.billing_month` anchors on, and the field the EARNED
# revenue state is defined by (`_classify_extra_work`). Populated ONLY for
# EARNED rows (ticket CLOSED); "Week No" is the ISO-8601 week number of
# that local date (verified against the reference report's own WK27/WK27
# for 30-06 and 01-07). Non-earned rows (in_progress / quoted_pipeline /
# lost) have no completion date — both fields are None — but the row STILL
# contributes to every count/subtotal/vat/total figure at every level,
# exactly like `compute_extra_work_revenue_by_building`; the sum invariant
# holds across all four revenue states, not an earned-only subset.
# ===========================================================================


def _empty_money_acc() -> dict:
    return {
        "count": 0,
        "subtotal": Decimal("0.00"),
        "vat": Decimal("0.00"),
        "total": Decimal("0.00"),
    }


def _accumulate(acc: dict, subtotal: Decimal, vat: Decimal, total: Decimal) -> None:
    acc["count"] += 1
    acc["subtotal"] += subtotal
    acc["vat"] += vat
    acc["total"] += total


def _money_dict(acc: dict) -> dict:
    return {
        "count": acc["count"],
        "subtotal": _money(acc["subtotal"]),
        "vat": _money(acc["vat"]),
        "total": _money(acc["total"]),
    }


def compute_extra_work_by_department(actor, query_params) -> dict:
    ew_qs, tickets_by_ew, from_date, to_date, scope, customer = (
        _resolve_extra_work_revenue_rows(actor, query_params)
    )

    department_id = _parse_int(query_params.get("department"), "department")
    work_type_id = _parse_int(query_params.get("work_type"), "work_type")
    if department_id is not None:
        ew_qs = ew_qs.filter(department_id=department_id)
    if work_type_id is not None:
        ew_qs = ew_qs.filter(work_type_id=work_type_id)

    building_acc: dict = {}
    building_meta: dict = {}
    dept_acc: dict = {}
    dept_meta: dict = {}
    wt_acc: dict = {}
    wt_meta: dict = {}
    detail_rows: dict = {}

    for ew in ew_qs.select_related(
        "building", "company", "department", "work_type"
    ):
        ticket = tickets_by_ew.get(ew.id)
        state = _classify_extra_work(ew, ticket)
        subtotal, vat, total = _amounts_for_state(ew, state)
        subtotal = subtotal or Decimal("0.00")
        vat = vat or Decimal("0.00")
        total = total or Decimal("0.00")

        b_id = ew.building_id
        d_id = ew.department_id
        w_id = ew.work_type_id
        d_key = (b_id, d_id)
        w_key = (b_id, d_id, w_id)

        if b_id not in building_acc:
            building_acc[b_id] = _empty_money_acc()
            building_meta[b_id] = {
                "building_name": ew.building.name,
                "company_id": ew.company_id,
                "company_name": ew.company.name,
            }
        _accumulate(building_acc[b_id], subtotal, vat, total)

        if d_key not in dept_acc:
            dept_acc[d_key] = _empty_money_acc()
            dept_meta[d_key] = {
                "department_id": d_id,
                "department_name": ew.department.name if d_id is not None else None,
            }
        _accumulate(dept_acc[d_key], subtotal, vat, total)

        if w_key not in wt_acc:
            wt_acc[w_key] = _empty_money_acc()
            wt_meta[w_key] = {
                "work_type_id": w_id,
                "work_type_name": ew.work_type.name if w_id is not None else None,
            }
        _accumulate(wt_acc[w_key], subtotal, vat, total)

        completed_at = None
        week_no = None
        # Same anchor `billing_month` buckets on: `closed_at` for a
        # closed ticket, `sent_for_approval_at` for one earned under the
        # cutoff arm. Reading `closed_at` directly would leave every
        # cutoff-earned row with a blank Completed At on a report that
        # counts its money.
        _earned_on = earned_at(ticket) if state == "earned" else None
        if _earned_on is not None:
            completed_date = timezone.localtime(_earned_on).date()
            completed_at = completed_date.isoformat()
            week_no = completed_date.isocalendar()[1]

        detail_rows.setdefault(w_key, []).append(
            {
                "extra_work_id": ew.id,
                "title": ew.title,
                "week_no": week_no,
                "completed_at": completed_at,
                "subtotal": _money(subtotal),
                "vat": _money(vat),
                "total": _money(total),
                "state": state,
            }
        )

    # Alphabetical at every level (name, then id for a stable tie-break) —
    # unlike Sprint 124's by-building revenue ranking, this is a drill-down
    # statement the customer re-reads period over period, so a fixed,
    # predictable order matters more than a money-first headline. The
    # untagged bucket (name=None) has no real name to sort by; it sorts
    # LAST at its level so labelled data is scanned before the catch-all.
    def _name_sort_key(name):
        return (1, "") if name is None else (0, name)

    ordered_building_ids = sorted(
        building_acc.keys(),
        key=lambda b_id: (building_meta[b_id]["building_name"], b_id),
    )

    buildings_out = []
    for b_id in ordered_building_ids:
        dept_keys_for_building = sorted(
            (k for k in dept_acc if k[0] == b_id),
            key=lambda k: (*_name_sort_key(dept_meta[k]["department_name"]), k[1] or 0),
        )
        departments_out = []
        for d_key in dept_keys_for_building:
            wt_keys_for_dept = sorted(
                (k for k in wt_acc if k[0] == d_key[0] and k[1] == d_key[1]),
                key=lambda k: (*_name_sort_key(wt_meta[k]["work_type_name"]), k[2] or 0),
            )
            work_types_out = []
            for w_key in wt_keys_for_dept:
                rows = sorted(
                    detail_rows[w_key],
                    key=lambda r: (r["completed_at"] or "", r["extra_work_id"]),
                )
                work_types_out.append(
                    {
                        **wt_meta[w_key],
                        **_money_dict(wt_acc[w_key]),
                        "rows": rows,
                    }
                )
            departments_out.append(
                {
                    **dept_meta[d_key],
                    **_money_dict(dept_acc[d_key]),
                    "work_types": work_types_out,
                }
            )
        buildings_out.append(
            {
                "building_id": b_id,
                **building_meta[b_id],
                **_money_dict(building_acc[b_id]),
                "departments": departments_out,
            }
        )

    # Sum the building-level accumulators directly (NOT via `_accumulate`,
    # which adds exactly one row's contribution — these are already
    # multi-row bucket totals being merged, a different operation).
    totals = _money_dict(
        {
            "count": sum(acc["count"] for acc in building_acc.values()),
            "subtotal": sum(
                (acc["subtotal"] for acc in building_acc.values()), Decimal("0.00")
            ),
            "vat": sum(
                (acc["vat"] for acc in building_acc.values()), Decimal("0.00")
            ),
            "total": sum(
                (acc["total"] for acc in building_acc.values()), Decimal("0.00")
            ),
        }
    )

    scope_dict = scope.to_dict()
    if customer is not None:
        scope_dict["customer_id"] = customer.id
        scope_dict["customer_name"] = customer.name
    if department_id is not None:
        # Direct lookup (not a scan of `dept_meta`) so the echoed name is
        # correct even when the filter matches zero rows in this period —
        # `dept_meta` only carries names for departments that survived the
        # date-window filter above. SCOPED via `_customer_in_scope` (the
        # id itself is just an echo of the caller's own input and leaks
        # nothing; resolving its NAME touches another tenant's row, so
        # that part must be scope-checked like every other cross-tenant
        # lookup in this module).
        scope_dict["department_id"] = department_id
        scope_dict["department_name"] = _scoped_label_name(
            actor, Department, department_id
        )
    if work_type_id is not None:
        scope_dict["work_type_id"] = work_type_id
        scope_dict["work_type_name"] = _scoped_label_name(
            actor, WorkType, work_type_id
        )

    return {
        "from": from_date.isoformat(),
        "to": to_date.isoformat(),
        "scope": scope_dict,
        "buildings": buildings_out,
        "totals": totals,
        "generated_at": timezone.now().isoformat(),
    }
