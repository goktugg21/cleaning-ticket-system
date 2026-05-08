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
from typing import Optional

from django.db.models import Count, F
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied, ValidationError

from accounts.models import UserRole
from buildings.models import Building, BuildingManagerAssignment
from companies.models import Company, CompanyUserMembership
from customers.models import Customer, CustomerUserMembership
from tickets.models import Ticket, TicketStatus, TicketType

from .scoping import (
    ResolvedScope,
    date_range_to_aware_bounds,
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
        return qs

    def scope_summary(self) -> dict:
        out = self.scope.to_dict()
        out["customer_id"] = self.customer.id if self.customer is not None else None
        out["customer_name"] = self.customer.name if self.customer is not None else None
        out["type"] = self.type
        out["status"] = self.status
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
