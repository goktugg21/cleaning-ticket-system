"""
Sprint 185 E §1 — work-category catalog endpoints.

    GET  / POST            /api/tickets/categories/
    GET  / PATCH / DELETE  /api/tickets/categories/<int:category_id>/

Deliberately the `buildings.views_building_types` shape, which is itself
the `timesheets.views_work_types` shape, because that shape is settled:
reads open to any authenticated provider-side actor (a picker and a list
filter both need the active list), writes restricted to SUPER_ADMIN /
COMPANY_ADMIN and checked against the ROW'S owning company rather than
the actor's — the check that stops a two-company admin writing into the
wrong one.

**No standard-set endpoint.** The kinds of work a cleaning company
distinguishes are its own vocabulary; seeding a "standard" list would be
inventing product content nobody asked for. `CatalogTab` treats
`standardSetUrl` as optional for exactly this case (Sprint 178 §1).

**Adding a category must never need a deployment.** That is the test of
whether this worked, and it is why the catalog is data behind these four
verbs rather than an enum: a company types a name, one melding carries
it, and it appears in the meldingen filter and the category report from
that moment.

There is no `scope_work_categories_for` helper: a category is owned by a
company and carries no per-building visibility, so scoping is the company
filter below. Reusing `scope_tickets_for` would be reading a ticket rule
onto a catalog row.
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

from .models import WorkCategory
from .serializers_work_categories import (
    ERR_WORK_CATEGORY_NAME_NOT_UNIQUE,
    WorkCategorySerializer,
)


def _visible_categories(user):
    """Every work category this actor may READ.

    SUPER_ADMIN sees all; anyone else sees the categories of the
    companies they belong to. A customer-side actor belongs to no
    provider company and therefore sees none — the same answer as "there
    are none", which is the H-1 equivalence.
    """
    queryset = WorkCategory.objects.select_related("company")
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
    """One aggregate for the whole page: how many meldingen carry this
    category. The UI needs the number to decide whether to offer Delete,
    and a per-row count would be the N+1 the query-count tests exist to
    catch."""
    return queryset.annotate(annotated_usage_count=Count("tickets"))


class WorkCategoryListCreateView(generics.ListCreateAPIView):
    """GET (any provider-side actor) / POST (SA + CA of that company)."""

    serializer_class = WorkCategorySerializer
    permission_classes = [IsAuthenticatedAndActive]
    # The catalog is a picker source and a filter source; both want the
    # whole list, and no caller of this endpoint has pagination UI.
    pagination_class = UnboundedPagination

    def get_queryset(self):
        queryset = _annotate_usage(_visible_categories(self.request.user))
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
                    "detail": "You may not manage this company's work "
                    "categories.",
                    "code": "work_category_forbidden",
                },
                status=status.HTTP_403_FORBIDDEN,
            )
        try:
            audit_context.set_current_reason("work_category_create")
        except Exception:  # pragma: no cover - defensive
            pass
        try:
            serializer.save()
        except IntegrityError:
            # The DB constraint is the authority; the serializer's own
            # check is a friendlier duplicate of it and can lose a race.
            return Response(
                {
                    "detail": "A work category with this name already "
                    "exists for this company.",
                    "code": ERR_WORK_CATEGORY_NAME_NOT_UNIQUE,
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
        return Response(serializer.data, status=status.HTTP_201_CREATED)


class WorkCategoryDetailView(generics.RetrieveUpdateDestroyAPIView):
    """GET / PATCH / DELETE one category."""

    serializer_class = WorkCategorySerializer
    permission_classes = [IsAuthenticatedAndActive]
    lookup_url_kwarg = "category_id"

    def get_queryset(self):
        return _annotate_usage(_visible_categories(self.request.user))

    def _guard(self, instance):
        if not _may_manage(self.request.user, instance.company_id):
            return Response(
                {
                    "detail": "You may not manage this company's work "
                    "categories.",
                    "code": "work_category_forbidden",
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
            audit_context.set_current_reason("work_category_update")
        except Exception:  # pragma: no cover - defensive
            pass
        try:
            serializer.save()
        except IntegrityError:
            return Response(
                {
                    "detail": "A work category with this name already "
                    "exists for this company.",
                    "code": ERR_WORK_CATEGORY_NAME_NOT_UNIQUE,
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
        return Response(serializer.data)

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        denied = self._guard(instance)
        if denied is not None:
            return denied
        # `Ticket.category` is SET_NULL, so a delete cannot raise
        # ProtectedError the way the hour-type catalog's can — the
        # meldingen simply lose their tag, and the category report loses
        # the history it was built to show. That is a real loss, so a
        # category still in use is refused here and the operator is told
        # to archive instead. Archiving is what "stop offering this"
        # means; deleting is for a row created by mistake.
        in_use = instance.tickets.count()
        if in_use:
            return Response(
                {
                    "detail": (
                        f"{in_use} melding(en) still carry this category. "
                        "Archive it instead — archiving stops it being "
                        "offered without untagging anything."
                    ),
                    "code": "work_category_in_use",
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            audit_context.set_current_reason("work_category_delete")
        except Exception:  # pragma: no cover - defensive
            pass
        instance.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)
