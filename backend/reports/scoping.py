from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Optional

from django.conf import settings
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied, ValidationError

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover
    from backports.zoneinfo import ZoneInfo  # type: ignore

from accounts.models import UserRole
from buildings.models import Building, BuildingManagerAssignment
from companies.models import Company, CompanyUserMembership
from tickets.models import Ticket


@dataclass(frozen=True)
class ResolvedScope:
    company: Optional[Company]
    building: Optional[Building]

    def to_dict(self) -> dict:
        return {
            "company_id": self.company.id if self.company else None,
            "company_name": self.company.name if self.company else None,
            "building_id": self.building.id if self.building else None,
            "building_name": self.building.name if self.building else None,
        }


def _parse_id(raw, field_name):
    if raw is None or raw == "":
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        raise ValidationError({field_name: f"Must be an integer."})


def _allowed_company_ids(actor) -> Optional[set]:
    """None means unrestricted (super admin); otherwise a set of allowed ids."""
    if actor.role == UserRole.SUPER_ADMIN:
        return None
    if actor.role == UserRole.COMPANY_ADMIN:
        return set(
            CompanyUserMembership.objects.filter(user=actor).values_list(
                "company_id", flat=True
            )
        )
    if actor.role == UserRole.BUILDING_MANAGER:
        return set(
            BuildingManagerAssignment.objects.filter(user=actor).values_list(
                "building__company_id", flat=True
            )
        )
    return set()


def _allowed_building_ids(actor) -> Optional[set]:
    """None means unrestricted (super admin); otherwise a set of allowed ids."""
    if actor.role == UserRole.SUPER_ADMIN:
        return None
    if actor.role == UserRole.COMPANY_ADMIN:
        company_ids = list(
            CompanyUserMembership.objects.filter(user=actor).values_list(
                "company_id", flat=True
            )
        )
        return set(
            Building.objects.filter(company_id__in=company_ids).values_list(
                "id", flat=True
            )
        )
    if actor.role == UserRole.BUILDING_MANAGER:
        return set(
            BuildingManagerAssignment.objects.filter(user=actor).values_list(
                "building_id", flat=True
            )
        )
    return set()


def resolve_scope(actor, raw_company, raw_building) -> ResolvedScope:
    """
    Parse and validate ?company= and ?building= query params against the
    actor's allowed set. Returns the resolved Company / Building model
    instances (or None for either). Raises:
      - ValidationError (400) for malformed ids or building/company mismatch.
      - PermissionDenied (403) when the actor does not have access to the
        requested company or building.
    """
    company_id = _parse_id(raw_company, "company")
    building_id = _parse_id(raw_building, "building")

    allowed_companies = _allowed_company_ids(actor)
    allowed_buildings = _allowed_building_ids(actor)

    company: Optional[Company] = None
    building: Optional[Building] = None

    if company_id is not None:
        if allowed_companies is not None and company_id not in allowed_companies:
            raise PermissionDenied("Forbidden.")
        company = Company.objects.filter(id=company_id).first()
        if company is None:
            raise PermissionDenied("Forbidden.")

    if building_id is not None:
        if allowed_buildings is not None and building_id not in allowed_buildings:
            raise PermissionDenied("Forbidden.")
        building = Building.objects.filter(id=building_id).first()
        if building is None:
            raise PermissionDenied("Forbidden.")

    if company is not None and building is not None:
        if building.company_id != company.id:
            raise ValidationError(
                {"detail": "Building does not belong to the given company."}
            )

    return ResolvedScope(company=company, building=building)


def tickets_for_scope(actor, scope: ResolvedScope):
    """
    Returns a Ticket queryset filtered to the resolved scope, falling back to
    the actor's full allowed scope if neither company nor building is
    specified.

    Sprint 12: every branch filters deleted_at__isnull=True so soft-deleted
    tickets do not appear in any report, export, or chart.
    """
    base = Ticket.objects.filter(deleted_at__isnull=True)

    if scope.building is not None:
        return base.filter(building_id=scope.building.id)

    if scope.company is not None:
        return base.filter(company_id=scope.company.id)

    if actor.role == UserRole.SUPER_ADMIN:
        return base
    if actor.role == UserRole.COMPANY_ADMIN:
        company_ids = list(
            CompanyUserMembership.objects.filter(user=actor).values_list(
                "company_id", flat=True
            )
        )
        return base.filter(company_id__in=company_ids)
    if actor.role == UserRole.BUILDING_MANAGER:
        building_ids = list(
            BuildingManagerAssignment.objects.filter(user=actor).values_list(
                "building_id", flat=True
            )
        )
        return base.filter(building_id__in=building_ids)
    return Ticket.objects.none()


def _parse_date(raw, field_name) -> date:
    try:
        return datetime.strptime(raw, "%Y-%m-%d").date()
    except (TypeError, ValueError):
        raise ValidationError(
            {"detail": f"Invalid date format for '{field_name}'. Expected YYYY-MM-DD."}
        )


def parse_date_range(raw_from, raw_to, default_window_days: int = 30):
    """
    Parse ?from= and ?to= into (from_date, to_date) date objects with the
    last `default_window_days` (inclusive of today) as the default. Raises
    ValidationError on malformed dates or reversed range.
    """
    today = timezone.localdate()
    if raw_to is None or raw_to == "":
        to_date = today
    else:
        to_date = _parse_date(raw_to, "to")
    if raw_from is None or raw_from == "":
        from_date = to_date - timedelta(days=default_window_days - 1)
    else:
        from_date = _parse_date(raw_from, "from")

    if from_date > to_date:
        raise ValidationError(
            {"detail": "Invalid date range: 'from' must not be after 'to'."}
        )
    return from_date, to_date


def date_range_to_aware_bounds(from_date: date, to_date: date):
    """
    Convert (from_date, to_date) into aware datetime bounds in the project
    timezone such that a timestamp `ts` belongs in the range when
    `bound_lo <= ts < bound_hi`.
    """
    tz = ZoneInfo(settings.TIME_ZONE)
    bound_lo = datetime.combine(from_date, time.min, tzinfo=tz)
    bound_hi = datetime.combine(to_date + timedelta(days=1), time.min, tzinfo=tz)
    return bound_lo, bound_hi

