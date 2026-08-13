"""
Sprint 178 §1 — building-type catalog endpoints.

    GET  / POST            /api/buildings/types/
    GET  / PATCH / DELETE  /api/buildings/types/<int:building_type_id>/

Deliberately the `timesheets.views_work_types` shape, because that shape
is settled: reads open to any authenticated provider-side actor (a
picker and a list filter both need the active list), writes restricted to
SUPER_ADMIN / COMPANY_ADMIN and checked against the row's OWNING company
rather than the actor's — the check that stops a two-company admin
writing into the wrong one.

**No standard-set endpoint.** `HourType` and `WorkType` have recognised
standard kinds worth seeding; a building type is bespoke by nature. The
owner's example is a type only one company will ever want, so seeding a
"standard" list would be inventing product content. `CatalogTab` treats
`standardSetUrl` as optional for exactly this case (Sprint 178 §1).

There is no `scope_building_types_for` helper: a building type is owned
by a company and carries no per-building visibility, so scoping is the
company filter below and reusing `scope_buildings_for` would be reading
a building rule onto a catalog row.
"""
from __future__ import annotations

from django.db import IntegrityError
from django.db.models import Count
from rest_framework import generics, status
from rest_framework.response import Response

from accounts.models import UserRole
from accounts.permissions import IsAuthenticatedAndActive
from audit import context as audit_context
from companies.models import CompanyUserMembership
from config.pagination import UnboundedPagination

from .models import BuildingType
from .serializers_building_types import (
    ERR_BUILDING_TYPE_NAME_NOT_UNIQUE,
    BuildingTypeSerializer,
)


def _visible_types(user):
    """Every building type this actor may READ.

    SUPER_ADMIN sees all; anyone else sees the types of the companies
    they belong to. A customer-side actor belongs to no provider company
    and therefore sees none — which is the same answer as "there are
    none", the H-1 equivalence.
    """
    queryset = BuildingType.objects.select_related("company")
    if user.role == UserRole.SUPER_ADMIN:
        return queryset
    company_ids = CompanyUserMembership.objects.filter(user=user).values_list(
        "company_id", flat=True
    )
    return queryset.filter(company_id__in=list(company_ids))


def _may_manage(user, company_id) -> bool:
    """Writes: SUPER_ADMIN anywhere, COMPANY_ADMIN in their OWN company.

    Checked against the row's company, never the actor's "current" one —
    an admin of two companies must not be able to write into the other
    by naming its id.
    """
    if user.role == UserRole.SUPER_ADMIN:
        return True
    if user.role != UserRole.COMPANY_ADMIN:
        return False
    return CompanyUserMembership.objects.filter(
        user=user, company_id=company_id
    ).exists()


def _annotate_usage(queryset):
    """One aggregate for the whole page: how many buildings carry this
    type. The UI needs the number to decide whether to offer Delete, and
    a per-row count would be the N+1 the query-count tests exist to
    catch."""
    return queryset.annotate(annotated_usage_count=Count("buildings"))


class BuildingTypeListCreateView(generics.ListCreateAPIView):
    """GET (any provider-side actor) / POST (SA + CA of that company)."""

    serializer_class = BuildingTypeSerializer
    permission_classes = [IsAuthenticatedAndActive]
    # The catalog is a picker source and a filter source; both want the
    # whole list, and no caller of this endpoint has pagination UI.
    pagination_class = UnboundedPagination

    def get_queryset(self):
        queryset = _annotate_usage(_visible_types(self.request.user))
        company = self.request.query_params.get("company")
        if company:
            queryset = queryset.filter(company_id=company)
        active = self.request.query_params.get("is_active")
        if active in ("true", "false"):
            queryset = queryset.filter(is_active=active == "true")
        return queryset

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        company = serializer.validated_data["company"]
        if not _may_manage(request.user, company.id):
            return Response(
                {
                    "detail": "You may not manage this company's building "
                    "types.",
                    "code": "building_type_forbidden",
                },
                status=status.HTTP_403_FORBIDDEN,
            )
        try:
            audit_context.set_current_reason("building_type_create")
        except Exception:  # pragma: no cover - defensive
            pass
        try:
            serializer.save()
        except IntegrityError:
            # The DB constraint is the authority; the serializer's own
            # check is a friendlier duplicate of it and can lose a race.
            return Response(
                {
                    "detail": "A building type with this name already "
                    "exists for this company.",
                    "code": ERR_BUILDING_TYPE_NAME_NOT_UNIQUE,
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
        return Response(serializer.data, status=status.HTTP_201_CREATED)


class BuildingTypeDetailView(generics.RetrieveUpdateDestroyAPIView):
    """GET / PATCH / DELETE one type."""

    serializer_class = BuildingTypeSerializer
    permission_classes = [IsAuthenticatedAndActive]
    lookup_url_kwarg = "building_type_id"

    def get_queryset(self):
        return _annotate_usage(_visible_types(self.request.user))

    def _guard(self, instance):
        if not _may_manage(self.request.user, instance.company_id):
            return Response(
                {
                    "detail": "You may not manage this company's building "
                    "types.",
                    "code": "building_type_forbidden",
                },
                status=status.HTTP_403_FORBIDDEN,
            )
        return None

    def update(self, request, *args, **kwargs):
        instance = self.get_object()
        denied = self._guard(instance)
        if denied is not None:
            return denied
        serializer = self.get_serializer(
            instance, data=request.data, partial=True
        )
        serializer.is_valid(raise_exception=True)
        try:
            audit_context.set_current_reason("building_type_update")
        except Exception:  # pragma: no cover - defensive
            pass
        try:
            serializer.save()
        except IntegrityError:
            return Response(
                {
                    "detail": "A building type with this name already "
                    "exists for this company.",
                    "code": ERR_BUILDING_TYPE_NAME_NOT_UNIQUE,
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
        return Response(serializer.data)

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        denied = self._guard(instance)
        if denied is not None:
            return denied
        # `Building.building_type` is SET_NULL, so a delete cannot raise
        # ProtectedError the way the hour-type catalog's can — the
        # buildings simply lose their tag. That is a real loss, so a type
        # still in use is refused here and the operator is told to
        # archive instead. Archiving is what "stop offering this" means;
        # deleting is for a row created by mistake.
        in_use = instance.buildings.count()
        if in_use:
            return Response(
                {
                    "detail": (
                        f"{in_use} building(s) still carry this type. "
                        "Archive it instead — archiving stops it being "
                        "offered without untagging anything."
                    ),
                    "code": "building_type_in_use",
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            audit_context.set_current_reason("building_type_delete")
        except Exception:  # pragma: no cover - defensive
            pass
        instance.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)
