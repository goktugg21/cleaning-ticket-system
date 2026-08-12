from collections import OrderedDict
from datetime import date, timedelta
from decimal import Decimal

from django.db.models import Count
from django.db.models.functions import TruncDate
from django.http import HttpResponse
from django.utils import timezone
from rest_framework import status as http_status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.models import UserRole
from buildings.models import BuildingManagerAssignment
from companies.models import CompanyUserMembership
from tickets.models import TicketStatus

from .dimensions import (
    DimensionFilters,
    OriginInvalid,
    _first_param,
    _resolve_customer,
    compute_extra_work_by_department,
    compute_extra_work_revenue,
    compute_extra_work_revenue_by_building,
    compute_tickets_by_building,
    compute_tickets_by_customer,
    compute_tickets_by_origin,
    compute_tickets_by_type,
)
from .exports import (
    build_extra_work_by_department_csv,
    build_extra_work_by_department_pdf,
    build_extra_work_revenue_by_building_csv,
    build_extra_work_revenue_by_building_pdf,
    build_extra_work_revenue_csv,
    build_extra_work_revenue_pdf,
    build_tickets_by_building_csv,
    build_tickets_by_building_pdf,
    build_tickets_by_customer_csv,
    build_tickets_by_customer_pdf,
    build_tickets_by_origin_csv,
    build_tickets_by_origin_pdf,
    build_tickets_by_type_csv,
    build_tickets_by_type_pdf,
)
from .permissions import IsReportsConsumer, IsRevenueReportConsumer
from .scoping import (
    date_range_to_aware_bounds,
    parse_date_range,
    resolve_scope,
    tickets_for_scope,
)


OPEN_STATUSES = [
    s
    for s in TicketStatus.values
    # Sprint 7B — CONVERTED_TO_EXTRA_WORK is terminal: a converted ticket
    # is superseded and must not be counted as open/active in age buckets.
    if s
    not in (
        TicketStatus.APPROVED,
        TicketStatus.REJECTED,
        TicketStatus.CONVERTED_TO_EXTRA_WORK,
    )
]


AGE_BUCKETS = [
    {"key": "0_1", "label": "0-1 day", "min_days": 0, "max_days": 1},
    {"key": "2_7", "label": "2-7 days", "min_days": 2, "max_days": 7},
    {"key": "8_30", "label": "8-30 days", "min_days": 8, "max_days": 30},
    {"key": "31_plus", "label": "31+ days", "min_days": 31, "max_days": None},
]


class _ReportView(APIView):
    permission_classes = [IsAuthenticated, IsReportsConsumer]

    def _resolved_scope(self, request):
        return resolve_scope(
            request.user,
            request.query_params.get("company"),
            request.query_params.get("building"),
        )


class StatusDistributionView(_ReportView):
    def get(self, request):
        scope = self._resolved_scope(request)
        qs = tickets_for_scope(request.user, scope)
        # #109 Part H — optional customer narrowing (same _resolve_customer
        # 403/400 contract as the dimension reports).
        customer = _resolve_customer(
            request.user,
            _first_param(request.query_params, "customer", "customer_id"),
        )
        if customer is not None:
            qs = qs.filter(customer_id=customer.id)
        counts = dict(qs.values_list("status").annotate(c=Count("id")))
        buckets = [
            {
                "status": str(value),
                "label": label,
                "count": int(counts.get(value, 0)),
            }
            for value, label in TicketStatus.choices
        ]
        return Response(
            {
                "as_of": timezone.now().isoformat(),
                "scope": scope.to_dict(),
                "buckets": buckets,
                "total": sum(b["count"] for b in buckets),
            }
        )


def _pick_granularity(from_date: date, to_date: date) -> str:
    span_days = (to_date - from_date).days + 1
    if span_days <= 30:
        return "day"
    if span_days <= 180:
        return "week"
    return "month"


def _bucket_start(d: date, granularity: str) -> date:
    if granularity == "day":
        return d
    if granularity == "week":
        # Monday of the week containing d
        return d - timedelta(days=d.weekday())
    if granularity == "month":
        return d.replace(day=1)
    raise ValueError(f"Unknown granularity {granularity}")


def _next_bucket_start(period_start: date, granularity: str) -> date:
    if granularity == "day":
        return period_start + timedelta(days=1)
    if granularity == "week":
        return period_start + timedelta(days=7)
    if granularity == "month":
        # First day of next month, accounting for year rollover.
        if period_start.month == 12:
            return date(period_start.year + 1, 1, 1)
        return date(period_start.year, period_start.month + 1, 1)
    raise ValueError(f"Unknown granularity {granularity}")


def _bucket_series(from_date: date, to_date: date, granularity: str, day_counts: dict):
    """
    Build the contiguous series from the bucket containing from_date through
    the bucket containing to_date (inclusive). day_counts maps date -> count
    (one entry per day with at least one ticket).
    """
    series = []
    current = _bucket_start(from_date, granularity)
    end_exclusive = _next_bucket_start(_bucket_start(to_date, granularity), granularity)
    while current < end_exclusive:
        nxt = _next_bucket_start(current, granularity)
        bucket_count = sum(
            count for d, count in day_counts.items() if current <= d < nxt
        )
        series.append({"period_start": current.isoformat(), "count": int(bucket_count)})
        current = nxt
    return series


class TicketsOverTimeView(_ReportView):
    def get(self, request):
        scope = self._resolved_scope(request)
        from_date, to_date = parse_date_range(
            request.query_params.get("from"), request.query_params.get("to")
        )
        granularity = _pick_granularity(from_date, to_date)
        bound_lo, bound_hi = date_range_to_aware_bounds(from_date, to_date)

        qs = tickets_for_scope(request.user, scope).filter(
            created_at__gte=bound_lo, created_at__lt=bound_hi
        )
        # #109 Part H — optional customer narrowing.
        customer = _resolve_customer(
            request.user,
            _first_param(request.query_params, "customer", "customer_id"),
        )
        if customer is not None:
            qs = qs.filter(customer_id=customer.id)
        # Aggregate by local date so the series buckets line up with the
        # YYYY-MM-DD presentation.
        rows = (
            qs.annotate(day=TruncDate("created_at"))
            .values("day")
            .annotate(c=Count("id"))
            .order_by("day")
        )
        day_counts = {row["day"]: row["c"] for row in rows}

        series = _bucket_series(from_date, to_date, granularity, day_counts)
        total = sum(b["count"] for b in series)
        return Response(
            {
                "from": from_date.isoformat(),
                "to": to_date.isoformat(),
                "granularity": granularity,
                "scope": scope.to_dict(),
                "series": series,
                "total": total,
            }
        )


def _manager_user_ids_in_scope(actor, scope) -> list:
    """
    Returns the ids of users who are 'managers' (BUILDING_MANAGER or
    COMPANY_ADMIN) AND have either a manager assignment or company
    membership inside the resolved scope.
    """
    # Resolve which buildings are visible under the resolved scope. Reuse
    # tickets_for_scope's filter logic indirectly by deriving the building
    # set from scope/actor membership.
    if scope.building is not None:
        building_ids = [scope.building.id]
        company_ids = [scope.building.company_id]
    elif scope.company is not None:
        from buildings.models import Building

        building_ids = list(
            Building.objects.filter(company_id=scope.company.id).values_list(
                "id", flat=True
            )
        )
        company_ids = [scope.company.id]
    else:
        if actor.role == UserRole.SUPER_ADMIN:
            from buildings.models import Building
            from companies.models import Company

            building_ids = list(Building.objects.values_list("id", flat=True))
            company_ids = list(Company.objects.values_list("id", flat=True))
        elif actor.role == UserRole.COMPANY_ADMIN:
            from buildings.models import Building

            company_ids = list(
                CompanyUserMembership.objects.filter(user=actor).values_list(
                    "company_id", flat=True
                )
            )
            building_ids = list(
                Building.objects.filter(company_id__in=company_ids).values_list(
                    "id", flat=True
                )
            )
        elif actor.role == UserRole.BUILDING_MANAGER:
            from buildings.models import Building

            building_ids = list(
                BuildingManagerAssignment.objects.filter(user=actor).values_list(
                    "building_id", flat=True
                )
            )
            company_ids = list(
                Building.objects.filter(id__in=building_ids).values_list(
                    "company_id", flat=True
                )
            )
        else:
            return []

    bm_ids = list(
        BuildingManagerAssignment.objects.filter(
            building_id__in=building_ids
        ).values_list("user_id", flat=True)
    )
    ca_ids = list(
        CompanyUserMembership.objects.filter(
            company_id__in=company_ids
        ).values_list("user_id", flat=True)
    )
    seen = OrderedDict()
    for uid in (*bm_ids, *ca_ids):
        seen[uid] = None
    return list(seen.keys())


class ManagerThroughputView(_ReportView):
    def get(self, request):
        scope = self._resolved_scope(request)
        from_date, to_date = parse_date_range(
            request.query_params.get("from"), request.query_params.get("to")
        )
        bound_lo, bound_hi = date_range_to_aware_bounds(from_date, to_date)

        manager_ids = _manager_user_ids_in_scope(request.user, scope)
        if not manager_ids:
            return Response(
                {
                    "from": from_date.isoformat(),
                    "to": to_date.isoformat(),
                    "scope": scope.to_dict(),
                    "managers": [],
                }
            )

        qs = tickets_for_scope(request.user, scope).filter(
            resolved_at__isnull=False,
            resolved_at__gte=bound_lo,
            resolved_at__lt=bound_hi,
            assigned_to_id__in=manager_ids,
        )
        counts = dict(qs.values_list("assigned_to_id").annotate(c=Count("id")))

        from accounts.models import User

        users = list(
            User.objects.filter(id__in=manager_ids).values(
                "id", "full_name", "email"
            )
        )
        managers = [
            {
                "user_id": u["id"],
                "full_name": u["full_name"],
                "email": u["email"],
                "resolved_count": int(counts.get(u["id"], 0)),
            }
            for u in users
        ]
        managers.sort(key=lambda m: (-m["resolved_count"], m["full_name"]))

        return Response(
            {
                "from": from_date.isoformat(),
                "to": to_date.isoformat(),
                "scope": scope.to_dict(),
                "managers": managers,
            }
        )


def _age_in_days(now, created_at) -> int:
    return (now - created_at).days


# Fixed display-state ordering, mirroring the B2 ticket-list priority. The
# frontend relies on this order; do not reshuffle.
SLA_DISPLAY_BUCKETS = [
    ("ON_TRACK", "On track"),
    ("AT_RISK", "At risk"),
    ("BREACHED", "Breached"),
    ("PAUSED", "Paused"),
    ("COMPLETED", "Completed"),
    ("HISTORICAL", "Historical"),
]


class SLADistributionView(_ReportView):
    def get(self, request):
        scope = self._resolved_scope(request)
        qs = tickets_for_scope(request.user, scope)

        # Each ticket falls into exactly one bucket per the priority rule:
        # HISTORICAL > COMPLETED > PAUSED > BREACHED/AT_RISK/ON_TRACK.
        counts = {
            "HISTORICAL": qs.filter(sla_status="HISTORICAL").count(),
            "COMPLETED": qs.filter(sla_status="COMPLETED").count(),
            "PAUSED": qs.filter(sla_paused_at__isnull=False)
            .exclude(sla_status__in=("HISTORICAL", "COMPLETED"))
            .count(),
            "ON_TRACK": qs.filter(
                sla_status="ON_TRACK", sla_paused_at__isnull=True
            ).count(),
            "AT_RISK": qs.filter(
                sla_status="AT_RISK", sla_paused_at__isnull=True
            ).count(),
            "BREACHED": qs.filter(
                sla_status="BREACHED", sla_paused_at__isnull=True
            ).count(),
        }
        buckets = [
            {"state": state, "label": label, "count": int(counts[state])}
            for state, label in SLA_DISPLAY_BUCKETS
        ]
        return Response(
            {
                "as_of": timezone.now().isoformat(),
                "scope": scope.to_dict(),
                "buckets": buckets,
                "total": sum(b["count"] for b in buckets),
            }
        )


class SLABreachRateOverTimeView(_ReportView):
    def get(self, request):
        scope = self._resolved_scope(request)
        from_date, to_date = parse_date_range(
            request.query_params.get("from"), request.query_params.get("to")
        )
        granularity = _pick_granularity(from_date, to_date)
        bound_lo, bound_hi = date_range_to_aware_bounds(from_date, to_date)

        # Tickets created in range, excluding pre-engine HISTORICAL ones —
        # they don't have a real SLA cycle and shouldn't dilute the rate.
        qs = (
            tickets_for_scope(request.user, scope)
            .filter(created_at__gte=bound_lo, created_at__lt=bound_hi)
            .exclude(sla_status="HISTORICAL")
        )
        breached_qs = qs.filter(sla_first_breached_at__isnull=False)

        rows_total = (
            qs.annotate(day=TruncDate("created_at"))
            .values("day")
            .annotate(c=Count("id"))
            .order_by("day")
        )
        rows_breached = (
            breached_qs.annotate(day=TruncDate("created_at"))
            .values("day")
            .annotate(c=Count("id"))
            .order_by("day")
        )
        day_total = {row["day"]: row["c"] for row in rows_total}
        day_breached = {row["day"]: row["c"] for row in rows_breached}

        series = []
        current = _bucket_start(from_date, granularity)
        end_exclusive = _next_bucket_start(
            _bucket_start(to_date, granularity), granularity
        )
        while current < end_exclusive:
            nxt = _next_bucket_start(current, granularity)
            total = sum(c for d, c in day_total.items() if current <= d < nxt)
            breached = sum(
                c for d, c in day_breached.items() if current <= d < nxt
            )
            rate = round(breached / total, 4) if total > 0 else 0.0
            series.append(
                {
                    "period_start": current.isoformat(),
                    "total": int(total),
                    "breached": int(breached),
                    "breach_rate": rate,
                }
            )
            current = nxt

        return Response(
            {
                "from": from_date.isoformat(),
                "to": to_date.isoformat(),
                "granularity": granularity,
                "scope": scope.to_dict(),
                "buckets": series,
            }
        )


class AgeBucketsView(_ReportView):
    def get(self, request):
        scope = self._resolved_scope(request)
        now = timezone.now()
        qs = tickets_for_scope(request.user, scope).filter(status__in=OPEN_STATUSES)
        ages = [_age_in_days(now, t.created_at) for t in qs.only("created_at")]

        buckets = []
        for spec in AGE_BUCKETS:
            if spec["max_days"] is None:
                count = sum(1 for a in ages if a >= spec["min_days"])
            else:
                count = sum(
                    1 for a in ages if spec["min_days"] <= a <= spec["max_days"]
                )
            buckets.append(
                {
                    "key": spec["key"],
                    "label": spec["label"],
                    "min_days": spec["min_days"],
                    "max_days": spec["max_days"],
                    "count": count,
                }
            )

        return Response(
            {
                "as_of": now.isoformat(),
                "scope": scope.to_dict(),
                "buckets": buckets,
                "total_open": sum(b["count"] for b in buckets),
            }
        )


# ===========================================================================
# Sprint 5: tickets-by-{type, customer, building}
#
# JSON endpoints + paired CSV / PDF export endpoints. The paired exports
# build off the SAME `compute_*` payload as the JSON view, so the three
# response formats cannot drift apart.
# ===========================================================================


def _csv_response(filename: str, body: bytes) -> HttpResponse:
    response = HttpResponse(body, content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response


def _pdf_response(filename: str, body: bytes) -> HttpResponse:
    response = HttpResponse(body, content_type="application/pdf")
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response


class _DimensionView(_ReportView):
    """Common base — collects the parsed-and-validated DimensionFilters."""

    accept_customer = False
    accept_type = False

    def _filters(self, request) -> DimensionFilters:
        return DimensionFilters(
            request.user,
            request.query_params,
            accept_customer=self.accept_customer,
            accept_type=self.accept_type,
        )

    def handle_exception(self, exc):
        # Render the ?origin= validation error as a clean 400 body with a
        # stable plain-string `code` (DRF's ValidationError would wrap dict
        # values in lists, mangling `code`).
        if isinstance(exc, OriginInvalid):
            return Response(
                {"detail": str(exc), "code": exc.code},
                status=http_status.HTTP_400_BAD_REQUEST,
            )
        return super().handle_exception(exc)


# ---- tickets-by-type --------------------------------------------------------


class TicketsByTypeView(_DimensionView):
    accept_customer = True
    accept_type = False

    def get(self, request):
        return Response(compute_tickets_by_type(self._filters(request)))


class TicketsByTypeCSVView(_DimensionView):
    accept_customer = True
    accept_type = False

    def get(self, request):
        payload = compute_tickets_by_type(self._filters(request))
        return _csv_response(
            f"tickets-by-type_{payload['from']}_{payload['to']}.csv",
            build_tickets_by_type_csv(payload),
        )


class TicketsByTypePDFView(_DimensionView):
    accept_customer = True
    accept_type = False

    def get(self, request):
        payload = compute_tickets_by_type(self._filters(request))
        return _pdf_response(
            f"tickets-by-type_{payload['from']}_{payload['to']}.pdf",
            build_tickets_by_type_pdf(payload),
        )


# ---- tickets-by-customer ----------------------------------------------------


class TicketsByCustomerView(_DimensionView):
    accept_customer = False
    accept_type = True

    def get(self, request):
        return Response(compute_tickets_by_customer(self._filters(request)))


class TicketsByCustomerCSVView(_DimensionView):
    accept_customer = False
    accept_type = True

    def get(self, request):
        payload = compute_tickets_by_customer(self._filters(request))
        return _csv_response(
            f"tickets-by-customer_{payload['from']}_{payload['to']}.csv",
            build_tickets_by_customer_csv(payload),
        )


class TicketsByCustomerPDFView(_DimensionView):
    accept_customer = False
    accept_type = True

    def get(self, request):
        payload = compute_tickets_by_customer(self._filters(request))
        return _pdf_response(
            f"tickets-by-customer_{payload['from']}_{payload['to']}.pdf",
            build_tickets_by_customer_pdf(payload),
        )


# ---- tickets-by-building ----------------------------------------------------


class TicketsByBuildingView(_DimensionView):
    accept_customer = True
    accept_type = True

    def get(self, request):
        return Response(compute_tickets_by_building(self._filters(request)))


class TicketsByBuildingCSVView(_DimensionView):
    accept_customer = True
    accept_type = True

    def get(self, request):
        payload = compute_tickets_by_building(self._filters(request))
        return _csv_response(
            f"tickets-by-building_{payload['from']}_{payload['to']}.csv",
            build_tickets_by_building_csv(payload),
        )


class TicketsByBuildingPDFView(_DimensionView):
    accept_customer = True
    accept_type = True

    def get(self, request):
        payload = compute_tickets_by_building(self._filters(request))
        return _pdf_response(
            f"tickets-by-building_{payload['from']}_{payload['to']}.pdf",
            build_tickets_by_building_pdf(payload),
        )


# ===========================================================================
# Sprint 14A — Part A: tickets-by-origin (NORMAL / EXTRA_WORK / CONVERTED /
# PLANNED). JSON + CSV + PDF, sharing the same compute payload.
# ===========================================================================


class TicketsByOriginView(_DimensionView):
    accept_customer = True
    accept_type = True

    def get(self, request):
        return Response(compute_tickets_by_origin(self._filters(request)))


class TicketsByOriginCSVView(_DimensionView):
    accept_customer = True
    accept_type = True

    def get(self, request):
        payload = compute_tickets_by_origin(self._filters(request))
        return _csv_response(
            f"tickets-by-origin_{payload['from']}_{payload['to']}.csv",
            build_tickets_by_origin_csv(payload),
        )


class TicketsByOriginPDFView(_DimensionView):
    accept_customer = True
    accept_type = True

    def get(self, request):
        payload = compute_tickets_by_origin(self._filters(request))
        return _pdf_response(
            f"tickets-by-origin_{payload['from']}_{payload['to']}.pdf",
            build_tickets_by_origin_pdf(payload),
        )


# ===========================================================================
# Sprint 14A — Part B: Extra Work revenue states. JSON + CSV.
#
# PERMISSION: provider-management only (SUPER_ADMIN / COMPANY_ADMIN /
# BUILDING_MANAGER). STAFF + CUSTOMER_USER are DENIED — the report exposes
# commercial amounts (privacy floor). PDF is deferred (multi-column money
# table); JSON + CSV cover the contract.
# ===========================================================================


class ExtraWorkRevenueView(APIView):
    permission_classes = [IsAuthenticated, IsRevenueReportConsumer]

    def get(self, request):
        return Response(
            compute_extra_work_revenue(request.user, request.query_params)
        )


class ExtraWorkRevenueCSVView(APIView):
    permission_classes = [IsAuthenticated, IsRevenueReportConsumer]

    def get(self, request):
        payload = compute_extra_work_revenue(request.user, request.query_params)
        return _csv_response(
            f"extra-work-revenue_{payload['from']}_{payload['to']}.csv",
            build_extra_work_revenue_csv(payload),
        )


class ExtraWorkRevenuePDFView(APIView):
    # Sprint 14D — PDF export of the Extra Work revenue-state report.
    # Reuses the SAME compute path (scope, filters, date range, states,
    # money totals) as the JSON / CSV views; writes nothing.
    permission_classes = [IsAuthenticated, IsRevenueReportConsumer]

    def get(self, request):
        payload = compute_extra_work_revenue(request.user, request.query_params)
        return _pdf_response(
            "extra-work-revenue.pdf",
            build_extra_work_revenue_pdf(payload),
        )


# ===========================================================================
# Sprint 124 — Extra Work revenue grouped by building. Same permission
# floor as the flat revenue report (commercial amounts): SUPER_ADMIN /
# COMPANY_ADMIN / BUILDING_MANAGER only, never STAFF or CUSTOMER_USER.
# ===========================================================================


class ExtraWorkRevenueByBuildingView(APIView):
    permission_classes = [IsAuthenticated, IsRevenueReportConsumer]

    def get(self, request):
        return Response(
            compute_extra_work_revenue_by_building(
                request.user, request.query_params
            )
        )


class ExtraWorkRevenueByBuildingCSVView(APIView):
    permission_classes = [IsAuthenticated, IsRevenueReportConsumer]

    def get(self, request):
        payload = compute_extra_work_revenue_by_building(
            request.user, request.query_params
        )
        return _csv_response(
            f"extra-work-revenue-by-building_{payload['from']}_{payload['to']}.csv",
            build_extra_work_revenue_by_building_csv(payload),
        )


class ExtraWorkRevenueByBuildingPDFView(APIView):
    permission_classes = [IsAuthenticated, IsRevenueReportConsumer]

    def get(self, request):
        payload = compute_extra_work_revenue_by_building(
            request.user, request.query_params
        )
        return _pdf_response(
            f"extra-work-revenue-by-building_{payload['from']}_{payload['to']}.pdf",
            build_extra_work_revenue_by_building_pdf(payload),
        )


# ===========================================================================
# Sprint 131 — Extra Work revenue grouped Building -> Department -> Work
# Type. Same permission floor as the other revenue reports (commercial
# amounts): SUPER_ADMIN / COMPANY_ADMIN / BUILDING_MANAGER only.
# ===========================================================================


class ExtraWorkByDepartmentView(APIView):
    permission_classes = [IsAuthenticated, IsRevenueReportConsumer]

    def get(self, request):
        return Response(
            compute_extra_work_by_department(request.user, request.query_params)
        )


class ExtraWorkByDepartmentCSVView(APIView):
    permission_classes = [IsAuthenticated, IsRevenueReportConsumer]

    def get(self, request):
        payload = compute_extra_work_by_department(
            request.user, request.query_params
        )
        return _csv_response(
            f"extra-work-by-department_{payload['from']}_{payload['to']}.csv",
            build_extra_work_by_department_csv(payload),
        )


class ExtraWorkByDepartmentPDFView(APIView):
    permission_classes = [IsAuthenticated, IsRevenueReportConsumer]

    def get(self, request):
        payload = compute_extra_work_by_department(
            request.user, request.query_params
        )
        return _pdf_response(
            f"extra-work-by-department_{payload['from']}_{payload['to']}.pdf",
            build_extra_work_by_department_pdf(payload),
        )


class HoursComparisonView(APIView):
    """
    Sprint 165 §5 — contracted hours against worked hours, per building.

        GET /api/reports/hours-comparison/?year=&month=&company=

    Read-only. Provider-side only: `IsRevenueReportConsumer` is reused
    rather than a new class, because this report answers the same
    question about who may see it — it puts a company's contracted
    commitments beside its people's hours, which is provider-internal
    on both counts. STAFF and every CUSTOMER_* role are 403'd.

    The computation lives in `reports/hours_comparison.py`; see that
    module for why it is here and not in `contracts` or `timesheets`.
    """

    permission_classes = [IsAuthenticated, IsRevenueReportConsumer]

    def get(self, request):
        from .hours_comparison import build_comparison, month_bounds
        from .scoping import _allowed_company_ids

        today = timezone.localdate()
        try:
            year = int(request.query_params.get("year") or today.year)
            month = int(request.query_params.get("month") or today.month)
        except (TypeError, ValueError):
            return Response(
                {"detail": "year and month must be integers."},
                status=http_status.HTTP_400_BAD_REQUEST,
            )
        if not 1 <= month <= 12:
            return Response(
                {"detail": "month must be between 1 and 12."},
                status=http_status.HTTP_400_BAD_REQUEST,
            )

        # `None` from the scoping helper means SUPER_ADMIN — no company
        # filter. Everyone else gets their own set, and a `?company=`
        # narrows WITHIN it and can never widen it.
        allowed = _allowed_company_ids(request.user)
        if allowed is None:
            from companies.models import Company

            company_ids = list(Company.objects.values_list("id", flat=True))
        else:
            company_ids = list(allowed)

        requested = request.query_params.get("company")
        if requested:
            try:
                requested_id = int(requested)
            except (TypeError, ValueError):
                company_ids = []
            else:
                company_ids = [c for c in company_ids if c == requested_id]

        rows = build_comparison(company_ids, year, month)
        first, last = month_bounds(year, month)
        return Response(
            {
                "year": year,
                "month": month,
                "from": first.isoformat(),
                "to": last.isoformat(),
                "rows": [
                    {
                        "building": row.building_id,
                        "building_name": row.building_name,
                        "contracted_hours": row.contracted_hours,
                        "worked_hours": row.worked_hours,
                        "difference": row.difference,
                        # Worked only. A contract has no employee
                        # dimension — see the module docstring.
                        "employees": row.employees,
                    }
                    for row in rows
                ],
                "totals": {
                    "contracted_hours": sum(
                        (row.contracted_hours for row in rows), Decimal("0.00")
                    ),
                    "worked_hours": sum(
                        (row.worked_hours for row in rows), Decimal("0.00")
                    ),
                    "difference": sum(
                        (row.difference for row in rows), Decimal("0.00")
                    ),
                },
            }
        )


class WorkerHoursReportView(APIView):
    """
    Sprint 171 §4 — the Worker Hour Report.

        GET /api/reports/worker-hours/?year=&week=&weeks=

    One row per (ISO week, worker, building, hour type) with Mon-Sun and
    a total, plus the four tiles the reference shows.

    `IsRevenueReportConsumer` is reused rather than a new class: this is
    a per-PERSON breakdown of hours worked, which is provider-internal
    on the same grounds the comparison is — STAFF must not read the
    whole team's hours, and no customer-side role reads personnel data
    at all. A new class answering the same question differently is how
    two gates drift.

    The computation lives in `reports/worker_hours.py`.
    """

    permission_classes = [IsAuthenticated, IsRevenueReportConsumer]

    def get(self, request):
        from .worker_hours import build_worker_hours

        today = timezone.localdate()
        default_year, default_week, _ = today.isocalendar()
        try:
            iso_year = int(request.query_params.get("year") or default_year)
            first_week = int(request.query_params.get("week") or default_week)
            # Four at a time is the reference's span; capped at 13 so a
            # hand-edited URL cannot ask for a five-year table.
            week_count = min(
                13, max(1, int(request.query_params.get("weeks") or 4))
            )
        except (TypeError, ValueError):
            return Response(
                {"detail": "year, week and weeks must be integers."},
                status=http_status.HTTP_400_BAD_REQUEST,
            )
        if not 1 <= first_week <= 53:
            return Response(
                {"detail": "week must be between 1 and 53."},
                status=http_status.HTTP_400_BAD_REQUEST,
            )

        return Response(
            build_worker_hours(request.user, iso_year, first_week, week_count)
        )


class WorkerHoursExportView(APIView):
    """
    GET /api/reports/worker-hours/export.csv  (Excel opens it directly)
    GET /api/reports/worker-hours/export.pdf

    Same permission and same computation as the report above — the
    export renders the payload the screen shows, so a downloaded file
    can never disagree with the table it came from.

    CSV rather than a real xlsx: `reports/exports.py` already builds
    CSV for every other report here and Excel opens it without a
    prompt, so this adds no dependency. The PDF goes through
    `config/pdf_branding.py`, which the invoicing app already uses.
    """

    permission_classes = [IsAuthenticated, IsRevenueReportConsumer]

    def get(self, request, fmt: str):
        from .exports import (
            build_worker_hours_csv,
            build_worker_hours_pdf,
        )
        from .worker_hours import build_worker_hours

        today = timezone.localdate()
        default_year, default_week, _ = today.isocalendar()
        try:
            iso_year = int(request.query_params.get("year") or default_year)
            first_week = int(request.query_params.get("week") or default_week)
            week_count = min(
                13, max(1, int(request.query_params.get("weeks") or 4))
            )
        except (TypeError, ValueError):
            return Response(
                {"detail": "year, week and weeks must be integers."},
                status=http_status.HTTP_400_BAD_REQUEST,
            )

        payload = build_worker_hours(
            request.user, iso_year, first_week, week_count
        )
        stem = f"worker-hours-{iso_year}-W{first_week}"
        if fmt == "pdf":
            body = build_worker_hours_pdf(payload)
            content_type = "application/pdf"
            name = f"{stem}.pdf"
        else:
            body = build_worker_hours_csv(payload)
            content_type = "text/csv; charset=utf-8"
            name = f"{stem}.csv"
        response = HttpResponse(body, content_type=content_type)
        response["Content-Disposition"] = f'attachment; filename="{name}"'
        return response
