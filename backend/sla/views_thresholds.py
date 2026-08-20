"""Sprint W4-Q §2 — the admin surface for the per-company thresholds.

PROVIDER MANAGEMENT ONLY, AND NARROWER THAN THAT
------------------------------------------------
SUPER_ADMIN and COMPANY_ADMIN. Not BUILDING_MANAGER, even though it is a
provider-management role elsewhere: these numbers govern every ticket in
a whole company, and a building manager's authority is one building. Not
STAFF. And a CUSTOMER_USER must never see them at all — they are the
provider's internal operating rhythm, and telling a customer "your
provider warns itself after 8 hours" is a commercial disclosure nobody
asked us to make. Both non-provider roles get 403, not an empty list:
a filtered-to-nothing list would leak the shape of the endpoint.

A COMPANY_ADMIN reaches exactly the companies they hold a
`CompanyUserMembership` in. `_allowed_company_ids` is the single place
that decides that, and BOTH the list and the detail routes go through
it — a detail route with its own membership check is how the two drift
until one of them forgets.
"""
from django.conf import settings
from django.db import transaction
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.models import UserRole
from accounts.permissions import IsSuperAdminOrCompanyAdmin
from companies.models import Company, CompanyUserMembership

from .models import SlaWarningThreshold
from .serializers_thresholds import (
    SlaWarningThresholdWriteSerializer,
    serialize_company_thresholds,
)
from .thresholds import THRESHOLD_FIELDS, defaults


def _own_company_first(companies):
    """The caller's OWN company first, then the rest by name.

    The screen opens on `results[0]`, so this ordering IS the default
    selection — reported wrong four waves running, and the reason is
    here rather than on the screen.

    A COMPANY_ADMIN only ever receives companies they are a member of,
    so every row is already "own" and name order stands. A SUPER_ADMIN
    receives every company and belongs to none of them
    (`accounts.scoping.company_ids_for` returns the whole table for that
    role and `CompanyUserMembership` is empty), so "the companies you
    belong to" cannot pick one out. The platform's OWN company can:
    `settings.PLATFORM_BRAND_SLUG` is the slug this deployment is run
    by, and `config.pdf_branding` already treats it as "us".
    """
    brand = getattr(settings, "PLATFORM_BRAND_SLUG", "")
    return sorted(
        companies,
        key=lambda company: (0 if brand and company.slug == brand else 1),
    )


def _allowed_company_ids(user):
    """THE tenant gate. SUPER_ADMIN: every active company. COMPANY_ADMIN:
    the companies they are actually a member of. Anything else: nothing —
    though the permission class has already turned those away."""
    if user.role == UserRole.SUPER_ADMIN:
        return set(
            Company.objects.filter(is_active=True).values_list("id", flat=True)
        )
    if user.role == UserRole.COMPANY_ADMIN:
        return set(
            CompanyUserMembership.objects.filter(user=user).values_list(
                "company_id", flat=True
            )
        )
    return set()


def _business_window():
    """The business window the "business hours" unit is measured in, so
    the screen can say "24 business hours (Mon-Fri 09:00-17:00)" instead
    of "24". Read from the SAME settings `sla.business_hours` reads, not
    a second copy — a hardcoded window on the screen would go on saying
    09:00-17:00 the day somebody changes the engine."""
    from django.conf import settings

    start_h, start_m = settings.SLA_BUSINESS_HOURS_START
    end_h, end_m = settings.SLA_BUSINESS_HOURS_END
    return {
        "start": f"{start_h:02d}:{start_m:02d}",
        "end": f"{end_h:02d}:{end_m:02d}",
        # Python weekday numbers (Mon=0), rendered by the frontend
        # through its own weekday labels so the sentence translates.
        "days": sorted(int(d) for d in settings.SLA_BUSINESS_DAYS),
        "hours_per_day": (
            (end_h * 60 + end_m) - (start_h * 60 + start_m)
        ) / 60.0,
    }


class SlaWarningThresholdListView(APIView):
    """GET /api/sla/warning-thresholds/ — every company the caller may
    tune, each with its effective / override / default numbers.

    Deliberately UNPAGINATED and deliberately small: the row set is one
    per provider company, which is tens, and the screen is a picker over
    exactly this list. It is not a server collection that grows with
    tenant data, so the bounded-list rule that governs tickets and
    buildings does not reach it — and loosening a shared list
    endpoint's pagination to serve a picker is the mistake Sprint 134
    made and Sprint 135 reverted. This endpoint has one caller and no
    pagination UI, so it never had a contract to loosen.
    """

    permission_classes = [IsSuperAdminOrCompanyAdmin]

    def get(self, request):
        allowed = _allowed_company_ids(request.user)
        companies = _own_company_first(
            Company.objects.filter(id__in=allowed).order_by("name")
        )
        rows = {
            row.company_id: row
            for row in SlaWarningThreshold.objects.filter(
                company_id__in=allowed
            ).select_related("updated_by")
        }
        return Response(
            {
                "results": [
                    serialize_company_thresholds(
                        company=company, row=rows.get(company.id)
                    )
                    for company in companies
                ],
                "defaults": defaults(),
                "fields": [
                    {"field": name, "unit": unit}
                    for name, _s, unit in THRESHOLD_FIELDS
                ],
                "business_window": _business_window(),
            }
        )


class SlaWarningThresholdDetailView(APIView):
    """GET / PUT / DELETE /api/sla/warning-thresholds/<company_id>/.

    PUT stores overrides; an explicit null on a field clears it back to
    the platform default. DELETE removes the whole override row, which
    is the "reset this company to the defaults" action.

    404 rather than 403 for a company outside the caller's tenancy: a
    COMPANY_ADMIN probing ids should not be able to learn which company
    ids exist from the difference between the two codes.
    """

    permission_classes = [IsSuperAdminOrCompanyAdmin]

    def _company(self, request, company_id):
        if company_id not in _allowed_company_ids(request.user):
            from django.http import Http404

            raise Http404
        return get_object_or_404(Company, pk=company_id)

    def get(self, request, company_id):
        company = self._company(request, company_id)
        row = (
            SlaWarningThreshold.objects.select_related("updated_by")
            .filter(company_id=company.id)
            .first()
        )
        return Response(
            serialize_company_thresholds(company=company, row=row)
        )

    def put(self, request, company_id):
        company = self._company(request, company_id)
        with transaction.atomic():
            row = SlaWarningThreshold.objects.filter(
                company_id=company.id
            ).first()
            serializer = SlaWarningThresholdWriteSerializer(
                instance=row, data=request.data, partial=True
            )
            serializer.is_valid(raise_exception=True)
            if row is None:
                row = SlaWarningThreshold(company=company)
            for name, value in serializer.validated_data.items():
                setattr(row, name, value)
            row.updated_by = request.user
            row.save()
        row = (
            SlaWarningThreshold.objects.select_related("updated_by")
            .filter(company_id=company.id)
            .first()
        )
        return Response(
            serialize_company_thresholds(company=company, row=row)
        )

    def delete(self, request, company_id):
        company = self._company(request, company_id)
        SlaWarningThreshold.objects.filter(company_id=company.id).delete()
        return Response(
            serialize_company_thresholds(company=company, row=None),
            status=status.HTTP_200_OK,
        )
