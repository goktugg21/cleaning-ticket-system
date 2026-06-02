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

from datetime import date as date_type
from decimal import Decimal
from typing import Optional

from django.db.models import Case, CharField, Count, F, Q, Value, When
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied, ValidationError

from accounts.models import UserRole
from buildings.models import Building, BuildingManagerAssignment
from companies.models import Company, CompanyUserMembership
from customers.models import Customer, CustomerUserMembership
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
#   EARNED          : t.status == CLOSED.
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
        if ticket.status == TicketStatus.CLOSED:
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


def compute_extra_work_revenue(actor, query_params) -> dict:
    scope_company_raw = _first_param(query_params, "company", "company_id")
    scope_building_raw = _first_param(query_params, "building", "building_id")
    scope = resolve_scope(actor, scope_company_raw, scope_building_raw)

    from_date, to_date = parse_date_range(
        query_params.get("from"), query_params.get("to")
    )
    bound_lo, bound_hi = date_range_to_aware_bounds(from_date, to_date)

    ew_qs = extra_work_for_scope(actor, scope).filter(
        requested_at__gte=bound_lo, requested_at__lt=bound_hi
    )

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
            .only("id", "status", "extra_work_request_id")
            .order_by("id")
        ):
            # `.first()` semantics: keep the lowest-id ticket per EW.
            tickets_by_ew.setdefault(t.extra_work_request_id, t)

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

    return {
        "from": from_date.isoformat(),
        "to": to_date.isoformat(),
        "scope": scope.to_dict(),
        "states": states,
        "totals": totals,
        "generated_at": timezone.now().isoformat(),
    }
