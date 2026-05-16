"""
Sprint 28 Batch 5 — provider catalog CRUD endpoints
(`ServiceCategory`, `Service`).

Routes (registered in `extra_work/urls.py`, mounted under
`/api/services/`):

  GET / POST    /api/services/categories/
  GET / PATCH / DELETE  /api/services/categories/<int:category_id>/
  GET / POST    /api/services/
  GET / PATCH / DELETE  /api/services/<int:service_id>/

Permission gate: `IsSuperAdminOrCompanyAdmin`. The catalog is
provider-wide (it is NOT scoped per-company-membership) — every
COMPANY_ADMIN sees the same global catalog. BUILDING_MANAGER /
STAFF / CUSTOMER_USER never reach the view.

Deletion of a `ServiceCategory` that still has `Service` rows
pointing at it is blocked by `on_delete=PROTECT`. The view catches
`ProtectedError` and surfaces a clean 400 with a structured payload
instead of the default 500.
"""
from __future__ import annotations

from django.db.models import ProtectedError
from rest_framework import generics, status
from rest_framework.response import Response

from accounts.permissions import IsSuperAdminOrCompanyAdmin
from config.pagination import UnboundedPagination

from .models import Service, ServiceCategory
from .serializers_catalog import ServiceCategorySerializer, ServiceSerializer


def _parse_bool_param(value):
    """Parse a `?is_active=true|false` query-string value.

    Returns True / False on a recognised value, None when the param
    is absent or unparseable (the caller falls back to "no filter").
    """
    if value is None:
        return None
    lowered = value.strip().lower()
    if lowered in {"true", "1", "yes", "y"}:
        return True
    if lowered in {"false", "0", "no", "n"}:
        return False
    return None


class ServiceCategoryListCreateView(generics.ListCreateAPIView):
    """GET (list) + POST (create) at /api/services/categories/."""

    permission_classes = [IsSuperAdminOrCompanyAdmin]
    serializer_class = ServiceCategorySerializer
    pagination_class = UnboundedPagination

    def get_queryset(self):
        qs = ServiceCategory.objects.all()
        flag = _parse_bool_param(self.request.query_params.get("is_active"))
        if flag is not None:
            qs = qs.filter(is_active=flag)
        return qs.order_by("name", "id")


class ServiceCategoryDetailView(generics.RetrieveUpdateDestroyAPIView):
    """GET / PATCH / DELETE at /api/services/categories/<id>/."""

    permission_classes = [IsSuperAdminOrCompanyAdmin]
    serializer_class = ServiceCategorySerializer
    lookup_url_kwarg = "category_id"
    queryset = ServiceCategory.objects.all()

    def delete(self, request, *args, **kwargs):
        instance = self.get_object()
        try:
            instance.delete()
        except ProtectedError:
            return Response(
                {
                    "detail": (
                        "Cannot delete a category that still has services "
                        "attached. Deactivate it (is_active=false) or "
                        "delete the services first."
                    ),
                    "code": "category_protected",
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
        return Response(status=status.HTTP_204_NO_CONTENT)


class ServiceListCreateView(generics.ListCreateAPIView):
    """GET (list) + POST (create) at /api/services/."""

    permission_classes = [IsSuperAdminOrCompanyAdmin]
    serializer_class = ServiceSerializer
    pagination_class = UnboundedPagination

    def get_queryset(self):
        qs = Service.objects.select_related("category").all()
        category = self.request.query_params.get("category")
        if category:
            try:
                qs = qs.filter(category_id=int(category))
            except (TypeError, ValueError):
                # Bad input -> empty result rather than 500.
                qs = qs.none()
        flag = _parse_bool_param(self.request.query_params.get("is_active"))
        if flag is not None:
            qs = qs.filter(is_active=flag)
        return qs.order_by("category__name", "name", "id")


class ServiceDetailView(generics.RetrieveUpdateDestroyAPIView):
    """GET / PATCH / DELETE at /api/services/<id>/."""

    permission_classes = [IsSuperAdminOrCompanyAdmin]
    serializer_class = ServiceSerializer
    lookup_url_kwarg = "service_id"
    queryset = Service.objects.select_related("category").all()

    def delete(self, request, *args, **kwargs):
        instance = self.get_object()
        try:
            instance.delete()
        except ProtectedError:
            return Response(
                {
                    "detail": (
                        "Cannot delete a service that still has customer "
                        "contract prices. Deactivate it (is_active=false) "
                        "or delete the contract prices first."
                    ),
                    "code": "service_protected",
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
        return Response(status=status.HTTP_204_NO_CONTENT)
