"""
Sprint 127 — customer-scoped CRUD for the Extra Work label lists
(`Department` + `WorkType`), mounted under
`/api/customers/<customer_id>/departments/` and `.../work-types/`
(see customers/urls.py). Model + view live here in the customers app
because the label is customer-owned data; the URL anchor being
customer-scoped mirrors the documents / pricing routes.

Permissions
-----------
* WRITE (POST / PATCH / DELETE): provider-side only, the same
  `IsSuperAdminOrCompanyAdminForCompany` rule the customer pricing catalog
  uses for provider-side management — SUPER_ADMIN any customer,
  COMPANY_ADMIN their own company's customers.
* READ (GET list / retrieve): the write audience PLUS customer users with
  active access to the URL customer, so the customer-side Extra Work create
  form can populate its Department / Work Type dropdowns. BUILDING_MANAGER /
  STAFF read the label off the Extra Work payload itself
  (`department_name` / `work_type_name`) and do not need the picker.

Every queryset is filtered to the URL customer, so the picker only ever
returns that customer's own rows and a cross-tenant `label_id` is a 404 at
the row level. Deleting a label still referenced by an ExtraWorkRequest is
refused by the DB `PROTECT` (`ProtectedError`), turned here into a clean
coded 400 that points at the `is_active=False` soft-retire path — never a
500.
"""
from __future__ import annotations

from django.db import IntegrityError, transaction
from django.db.models import ProtectedError
from django.shortcuts import get_object_or_404
from rest_framework import generics, permissions, serializers, status
from rest_framework.exceptions import PermissionDenied
from rest_framework.response import Response

from accounts.models import UserRole
from accounts.permissions import IsAuthenticatedAndActive
from companies.models import CompanyUserMembership
from config.pagination import UnboundedPagination

from .models import (
    Customer,
    CustomerUserBuildingAccess,
    CustomerUserMembership,
    Department,
    WorkType,
)
from .serializers_labels import DepartmentSerializer, WorkTypeSerializer


def _parse_bool_param(value):
    """Parse a `?is_active=true|false` query-string value. Returns True /
    False on a recognised value, None when absent or unparseable (the
    caller then applies no filter). Mirrors the catalog helper."""
    if value is None:
        return None
    lowered = str(value).strip().lower()
    if lowered in ("true", "1", "yes"):
        return True
    if lowered in ("false", "0", "no"):
        return False
    return None


def _customer_user_has_access(user, customer) -> bool:
    """True iff `user` (role=CUSTOMER_USER) may see this customer: a
    company-wide Customer Company Admin (membership `is_company_admin`, which
    needs no per-building row), or any ACTIVE per-building access row under
    the customer. Local twin of the pricing surface's helper, kept in the
    customers app so this module needs no cross-app import."""
    if CustomerUserMembership.objects.filter(
        user=user, customer=customer, is_company_admin=True
    ).exists():
        return True
    return CustomerUserBuildingAccess.objects.filter(
        membership__user=user,
        membership__customer=customer,
        is_active=True,
    ).exists()


class _CustomerLabelPermission(IsAuthenticatedAndActive):
    """Coarse role gate; the per-customer object checks (COMPANY_ADMIN own
    company / CUSTOMER_USER access) run in the view's `_get_customer`, which
    has the resolved Customer."""

    def has_permission(self, request, view):
        if not super().has_permission(request, view):
            return False
        user = request.user
        if user.role in (UserRole.SUPER_ADMIN, UserRole.COMPANY_ADMIN):
            return True
        # Customer users may READ only (to populate the create dropdowns).
        if (
            request.method in permissions.SAFE_METHODS
            and user.role == UserRole.CUSTOMER_USER
        ):
            return True
        return False


class _CustomerLabelViewMixin:
    model = None
    conflict_code = None
    protected_code = None
    permission_classes = [_CustomerLabelPermission]
    pagination_class = UnboundedPagination

    def _get_customer(self) -> Customer:
        """Resolve the URL customer and enforce the per-customer object
        check for the acting role. A missing customer 404s; a foreign
        company (COMPANY_ADMIN) or a no-access customer user 403s."""
        customer = get_object_or_404(Customer, pk=self.kwargs["customer_id"])
        user = self.request.user
        if user.role == UserRole.SUPER_ADMIN:
            return customer
        if user.role == UserRole.COMPANY_ADMIN:
            if not CompanyUserMembership.objects.filter(
                user=user, company_id=customer.company_id
            ).exists():
                raise PermissionDenied("Forbidden.")
            return customer
        # CUSTOMER_USER — reads only (writes already blocked in
        # has_permission); must hold access to this customer.
        if user.role == UserRole.CUSTOMER_USER and _customer_user_has_access(
            user, customer
        ):
            return customer
        raise PermissionDenied("Forbidden.")

    def get_queryset(self):
        customer = self._get_customer()
        qs = self.model.objects.filter(customer=customer)
        flag = _parse_bool_param(self.request.query_params.get("is_active"))
        if flag is not None:
            qs = qs.filter(is_active=flag)
        return qs.order_by("name", "id")

    def get_serializer_context(self):
        ctx = super().get_serializer_context()
        # The uniqueness pre-check needs the (URL-bound) customer, and it
        # only runs on writes. Resolving it here also re-runs the write
        # permission check before the serializer touches the DB.
        if self.request.method not in permissions.SAFE_METHODS:
            ctx["customer"] = self._get_customer()
        return ctx

    def _conflict_error(self):
        return serializers.ValidationError(
            {
                "name": [
                    serializers.ErrorDetail(
                        "A label with this name already exists for this "
                        "customer.",
                        code=self.conflict_code,
                    )
                ]
            }
        )


class _CustomerLabelListCreateView(
    _CustomerLabelViewMixin, generics.ListCreateAPIView
):
    def perform_create(self, serializer):
        customer = self._get_customer()
        try:
            # Inner atomic so a UniqueConstraint IntegrityError leaves the
            # surrounding transaction usable (Postgres refuses further
            # commands in a transaction after an error until rollback).
            with transaction.atomic():
                serializer.save(customer=customer)
        except IntegrityError:
            # Backstop for the race between the serializer pre-check and the
            # DB constraint.
            raise self._conflict_error()


class _CustomerLabelDetailView(
    _CustomerLabelViewMixin, generics.RetrieveUpdateDestroyAPIView
):
    lookup_url_kwarg = "label_id"

    def perform_update(self, serializer):
        try:
            with transaction.atomic():
                serializer.save()
        except IntegrityError:
            raise self._conflict_error()

    def delete(self, request, *args, **kwargs):
        instance = self.get_object()
        try:
            instance.delete()
        except ProtectedError:
            return Response(
                {
                    "detail": (
                        "Cannot delete a label that is still assigned to an "
                        "extra work. Archive it (is_active=false) instead."
                    ),
                    "code": self.protected_code,
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
        return Response(status=status.HTTP_204_NO_CONTENT)


# --- Department -------------------------------------------------------------
class DepartmentListCreateView(_CustomerLabelListCreateView):
    model = Department
    serializer_class = DepartmentSerializer
    conflict_code = "department_name_conflict"


class DepartmentDetailView(_CustomerLabelDetailView):
    model = Department
    serializer_class = DepartmentSerializer
    conflict_code = "department_name_conflict"
    protected_code = "department_protected"


# --- Work Type --------------------------------------------------------------
class WorkTypeListCreateView(_CustomerLabelListCreateView):
    model = WorkType
    serializer_class = WorkTypeSerializer
    conflict_code = "work_type_name_conflict"


class WorkTypeDetailView(_CustomerLabelDetailView):
    model = WorkType
    serializer_class = WorkTypeSerializer
    conflict_code = "work_type_name_conflict"
    protected_code = "work_type_protected"
