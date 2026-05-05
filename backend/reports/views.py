from collections import OrderedDict
from datetime import date, timedelta

from django.db.models import Count
from django.db.models.functions import TruncDate
from django.utils import timezone
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.models import UserRole
from buildings.models import BuildingManagerAssignment
from companies.models import CompanyUserMembership
from tickets.models import TicketStatus

from .permissions import IsReportsConsumer
from .scoping import (
    date_range_to_aware_bounds,
    parse_date_range,
    resolve_scope,
    tickets_for_scope,
)


OPEN_STATUSES = [
    s for s in TicketStatus.values if s not in (TicketStatus.APPROVED, TicketStatus.REJECTED)
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
