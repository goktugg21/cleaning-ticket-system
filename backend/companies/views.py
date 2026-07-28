from django.utils.text import slugify
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from accounts.permissions import (
    IsAuthenticatedAndActive,
    IsSuperAdmin,
    IsSuperAdminOrCompanyAdminForCompany,
)
from accounts.scoping import scope_companies_for
from config.pagination import UnboundedPagination

from .filters import CompanyFilter
from .models import Company
from .serializers import CompanySerializer


def _unique_slug_from_name(name: str) -> str:
    base = slugify(name) or "company"
    candidate = base
    suffix = 2
    while Company.objects.filter(slug=candidate).exists():
        candidate = f"{base}-{suffix}"
        suffix += 1
    return candidate


class CompanyViewSet(viewsets.ModelViewSet):
    serializer_class = CompanySerializer
    filterset_class = CompanyFilter
    search_fields = ["name", "slug"]
    ordering_fields = ["name", "created_at"]
    # Sprint 134 — the admin company/customer/building pickers pass
    # `page_size: 200`, silently clamped to 200 by the DRF default
    # (`config.pagination.StandardResultsSetPagination`), for any tenant
    # exceeding it. Same fix shape Sprint 120 used for narrow, tenant-
    # bounded lists (customer contacts, company/customer memberships,
    # staff roster) — this list is bounded by domain reality (how many
    # companies/customers/buildings actually exist) the same way those are.
    pagination_class = UnboundedPagination

    def get_permissions(self):
        if self.action in ("list", "retrieve"):
            return [IsAuthenticatedAndActive()]
        if self.action == "create":
            return [IsSuperAdmin()]
        if self.action == "reactivate":
            return [IsSuperAdmin()]
        # update, partial_update, destroy
        return [IsSuperAdminOrCompanyAdminForCompany()]

    def get_queryset(self):
        return scope_companies_for(self.request.user)

    def perform_create(self, serializer):
        slug = serializer.validated_data.get("slug")
        if not slug:
            slug = _unique_slug_from_name(serializer.validated_data["name"])
        serializer.save(slug=slug)

    def perform_destroy(self, instance):
        # Soft-delete: keep the row so historical tickets stay attached.
        instance.is_active = False
        instance.save(update_fields=["is_active"])

    @action(detail=True, methods=["post"], permission_classes=[IsSuperAdmin])
    def reactivate(self, request, pk=None):
        # Bypass scope_companies_for so super admins can also reactivate rows
        # that the read filter would have hidden.
        company = Company.objects.filter(pk=pk).first()
        if company is None:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        company.is_active = True
        company.save(update_fields=["is_active"])
        return Response(CompanySerializer(company).data, status=status.HTTP_200_OK)
