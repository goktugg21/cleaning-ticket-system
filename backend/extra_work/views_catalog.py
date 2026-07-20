"""
Sprint 28 Batch 5 — provider catalog CRUD endpoints
(`ServiceCategory`, `Service`).

Routes (registered in `extra_work/urls.py`, mounted under
`/api/services/`):

  GET / POST    /api/services/categories/
  GET / PATCH / DELETE  /api/services/categories/<int:category_id>/
  GET / POST    /api/services/
  GET / PATCH / DELETE  /api/services/<int:service_id>/

Permission gate (Sprint 29 Batch 29.8.5 split):
  * GET (list + retrieve) is open to any authenticated user. The
    catalog is provider-wide reference data; CUSTOMER_USER needs to
    read it to populate the Extra Work cart create form (otherwise
    the create form's mount-time fetch returns 403 and the page
    surfaces a misleading "no permission" banner).
  * Writes (POST / PATCH / PUT / DELETE) stay locked to
    `IsSuperAdminOrCompanyAdmin`.

Deletion of a `ServiceCategory` that still has `Service` rows
pointing at it is blocked by `on_delete=PROTECT`. The view catches
`ProtectedError` and surfaces a clean 400 with a structured payload
instead of the default 500.

Sprint 3B additions:
  * GET queryset is now SCOPED to the actor's provider companies
    via `catalog_scope.filter_services_for` /
    `filter_categories_for`. SUPER_ADMIN sees all; everyone else
    only sees rows owned by companies they belong to (CA / BM /
    STAFF) or have customer access for (CUSTOMER_USER).
  * Service CREATE requires `company` on the payload; the view
    validates the actor may write to that company AND that the
    company allows Provider Admin catalog management
    (`Company.provider_admin_may_manage_catalog`). Rejected with
    HTTP 403 + stable code `provider_admin_catalog_management_disabled`
    when the toggle is False; HTTP 403 + stable code
    `catalog_cross_company_forbidden` when CA targets a foreign
    company.
  * Service / Category UPDATE + DELETE run the same policy gate
    against the existing row's owning company.
"""
from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP

from django.db import transaction
from django.db.models import ProtectedError
from rest_framework import generics, serializers, status
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.models import UserRole
from accounts.permissions import IsSuperAdminOrCompanyAdmin
from audit import context as audit_context
from companies.models import Company, CompanyUserMembership
from config.pagination import UnboundedPagination

from .catalog_scope import (
    can_manage_catalog,
    filter_categories_for,
    filter_services_for,
)
from .models import Service, ServiceCategory
from .serializers_catalog import ServiceCategorySerializer, ServiceSerializer


# Stable error codes raised from this module.
ERR_CATALOG_POLICY_DISABLED = "provider_admin_catalog_management_disabled"
ERR_CATALOG_CROSS_COMPANY = "catalog_cross_company_forbidden"
ERR_SERVICE_COMPANY_REQUIRED = "service_company_required"
ERR_CATEGORY_SA_ONLY = "global_category_management_super_admin_only"
ERR_SERVICE_BULK_RAISE_AMOUNT_INVALID = "service_bulk_raise_amount_invalid"
ERR_SERVICE_BULK_RAISE_INVALID = "service_bulk_raise_invalid"
# #108 Part C — a lower that would push any selected default price to
# zero or below rejects the WHOLE batch (all-or-nothing, zero writes).
ERR_SERVICE_BULK_RAISE_RESULT_INVALID = "service_bulk_raise_result_invalid"


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


def _enforce_catalog_management(user, company):
    """Raise a PermissionDenied with a stable code if `user` may not
    manage catalog rows owned by `company`. Returns silently when
    the action is allowed.

    Two distinct codes:
      * `provider_admin_catalog_management_disabled` — actor is the
        right COMPANY_ADMIN but the company has the policy toggle
        off. Surfaced as HTTP 403.
      * `catalog_cross_company_forbidden` — actor is COMPANY_ADMIN
        of a different company. Surfaced as HTTP 403.
    """
    if user.role == UserRole.SUPER_ADMIN:
        return
    if user.role != UserRole.COMPANY_ADMIN:
        # The DRF `IsSuperAdminOrCompanyAdmin` permission already
        # blocks anyone else with 403; this branch is defensive.
        raise PermissionDenied(detail="Forbidden.")
    is_member = CompanyUserMembership.objects.filter(
        user=user, company=company
    ).exists()
    if not is_member:
        raise PermissionDenied(
            detail={
                "detail": (
                    "You may only manage the catalog of your own "
                    "provider company."
                ),
                "code": ERR_CATALOG_CROSS_COMPANY,
            }
        )
    if not company.provider_admin_may_manage_catalog:
        raise PermissionDenied(
            detail={
                "detail": (
                    "Provider Admin catalog management is disabled "
                    "for this provider company. Ask Super Admin to "
                    "enable it."
                ),
                "code": ERR_CATALOG_POLICY_DISABLED,
            }
        )


def _enforce_category_super_admin_only(user):
    """Sprint 3B — categories are global, so non-Super-Admin must
    not mutate them (one Provider Admin changing a category would
    bleed across every provider company on the platform).

    SUPER_ADMIN passes; anyone else gets HTTP 403 with stable code
    `global_category_management_super_admin_only`. Read access is
    governed at the DRF permission layer; this helper guards
    write paths only.
    """
    if user.role == UserRole.SUPER_ADMIN:
        return
    raise PermissionDenied(
        detail={
            "detail": (
                "Service categories are global; only Super Admin "
                "may create, update, or delete them."
            ),
            "code": ERR_CATEGORY_SA_ONLY,
        }
    )


class ServiceCategoryListCreateView(generics.ListCreateAPIView):
    """GET (list) + POST (create) at /api/services/categories/.

    Sprint 29 Batch 29.8.5 — GET opened to any authenticated user so
    CUSTOMER_USER can populate the Extra Work create-form category
    dropdown.

    Sprint 3B — categories remain GLOBAL, so write methods are
    locked to SUPER_ADMIN only via `IsSuperAdmin`. COMPANY_ADMIN
    used to have CRUD access pre-Sprint-3B; that surface bled
    across every provider catalog, so it has been narrowed.
    Stable error code on the 403 path: `global_category_
    management_super_admin_only`.
    """

    serializer_class = ServiceCategorySerializer
    pagination_class = UnboundedPagination

    def get_permissions(self):
        if self.request.method == "GET":
            return [IsAuthenticated()]
        # Use IsSuperAdminOrCompanyAdmin so the DRF gate lets the
        # COMPANY_ADMIN through and the handler can surface the
        # stable `global_category_management_super_admin_only`
        # code. BM / STAFF / CUSTOMER_USER fail the gate with a
        # generic 403, which the tests accept as-is.
        return [IsSuperAdminOrCompanyAdmin()]

    def get_queryset(self):
        qs = ServiceCategory.objects.all()
        flag = _parse_bool_param(self.request.query_params.get("is_active"))
        if flag is not None:
            qs = qs.filter(is_active=flag)
        qs = filter_categories_for(self.request.user, qs)
        return qs.order_by("name", "id")

    def perform_create(self, serializer):
        _enforce_category_super_admin_only(self.request.user)
        serializer.save()


class ServiceCategoryDetailView(generics.RetrieveUpdateDestroyAPIView):
    """GET / PATCH / DELETE at /api/services/categories/<id>/.

    Sprint 29 Batch 29.8.5 — GET opened to any authenticated user.

    Sprint 3B — write methods (PATCH / PUT / DELETE) restricted to
    SUPER_ADMIN. See `ServiceCategoryListCreateView` docstring for
    the rationale.
    """

    serializer_class = ServiceCategorySerializer
    lookup_url_kwarg = "category_id"

    def get_permissions(self):
        if self.request.method == "GET":
            return [IsAuthenticated()]
        # See `ServiceCategoryListCreateView` for the rationale —
        # CA passes the gate; the handler returns the stable code.
        return [IsSuperAdminOrCompanyAdmin()]

    def get_queryset(self):
        return filter_categories_for(
            self.request.user, ServiceCategory.objects.all()
        )

    def perform_update(self, serializer):
        _enforce_category_super_admin_only(self.request.user)
        serializer.save()

    def delete(self, request, *args, **kwargs):
        instance = self.get_object()
        _enforce_category_super_admin_only(request.user)
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


def _resolve_service_create_company(user, supplied_company):
    """Sprint 3B — pick the `company` for a new Service.

    Rules:
      * COMPANY_ADMIN omitted `company` → default to the actor's
        own provider company (the single membership row; if the
        actor is in zero companies, 403 — they shouldn't reach
        here in practice). The catalog-management policy gate
        still runs on that resolved company.
      * COMPANY_ADMIN supplied `company` matching their own → OK.
      * COMPANY_ADMIN supplied `company` for a different provider
        → 403, stable code `catalog_cross_company_forbidden`.
      * SUPER_ADMIN supplied `company` → use it.
      * SUPER_ADMIN omitted `company`:
          - exactly one Company in the DB → default to it (the
            single-tenant pilot path).
          - multiple Companies → 400, stable code
            `service_company_required` (SA must disambiguate).
      * Other roles never reach this branch — DRF's
        IsSuperAdminOrCompanyAdmin permission rejects them at the
        endpoint level with a generic 403.

    Returns the resolved Company instance.
    """
    role = getattr(user, "role", None)

    if role == UserRole.SUPER_ADMIN:
        if supplied_company is not None:
            return supplied_company
        candidates = list(Company.objects.all()[:2])
        if len(candidates) == 1:
            return candidates[0]
        raise serializers.ValidationError(
            {
                "company": [
                    serializers.ErrorDetail(
                        "`company` is required when more than one "
                        "provider Company exists.",
                        code=ERR_SERVICE_COMPANY_REQUIRED,
                    )
                ]
            }
        )

    if role == UserRole.COMPANY_ADMIN:
        own_company_ids = list(
            CompanyUserMembership.objects.filter(user=user).values_list(
                "company_id", flat=True
            )
        )
        if not own_company_ids:
            # Defensive: a COMPANY_ADMIN with zero memberships
            # shouldn't reach the catalog endpoints at all.
            raise PermissionDenied(detail="Forbidden.")
        if supplied_company is not None:
            if supplied_company.id not in own_company_ids:
                raise PermissionDenied(
                    detail={
                        "detail": (
                            "You may only manage the catalog of your "
                            "own provider company."
                        ),
                        "code": ERR_CATALOG_CROSS_COMPANY,
                    }
                )
            return supplied_company
        # Omitted: default to the actor's company. If the CA happens
        # to be a member of multiple companies (unusual in practice),
        # default to the lowest-id membership; the operator can
        # always send `company` explicitly to disambiguate.
        return Company.objects.get(id=own_company_ids[0])

    # Other roles: the permission layer should have rejected them
    # before this helper runs.
    raise PermissionDenied(detail="Forbidden.")


class _ServiceBulkRaiseInputSerializer(serializers.Serializer):
    """M5 C / #108 Part C — input for POST /api/services/bulk-raise/.
    Adjusts (raises OR lowers) the catalog default_unit_price of a set
    of Services by percentage or fixed amount, in place. `services` =
    ids; `mode` = percent|fixed; `amount` > 0 always; `direction` =
    raise|lower (defaults to raise so pre-#108 clients stay valid). A
    percent LOWER must stay below 100.
    """

    services = serializers.ListField(
        child=serializers.IntegerField(min_value=1),
        allow_empty=False,
        error_messages={
            "empty": "At least one service id is required.",
            "required": "Services list is required.",
        },
    )
    mode = serializers.ChoiceField(choices=["percent", "fixed"])
    amount = serializers.DecimalField(max_digits=12, decimal_places=2)
    direction = serializers.ChoiceField(
        choices=["raise", "lower"], default="raise"
    )

    def validate_amount(self, value):
        if value is None or value <= Decimal("0"):
            raise serializers.ValidationError(
                serializers.ErrorDetail(
                    "amount must be greater than zero.",
                    code=ERR_SERVICE_BULK_RAISE_AMOUNT_INVALID,
                )
            )
        return value

    def validate(self, attrs):
        if (
            attrs.get("direction") == "lower"
            and attrs.get("mode") == "percent"
            and attrs.get("amount") is not None
            and attrs["amount"] >= Decimal("100")
        ):
            raise serializers.ValidationError(
                {
                    "amount": [
                        serializers.ErrorDetail(
                            "A percentage lower must be below 100.",
                            code=ERR_SERVICE_BULK_RAISE_AMOUNT_INVALID,
                        )
                    ]
                }
            )
        return attrs


class ServiceListCreateView(generics.ListCreateAPIView):
    """GET (list) + POST (create) at /api/services/.

    Sprint 29 Batch 29.8.5 — GET opened to any authenticated user so
    CUSTOMER_USER can populate the Extra Work create-form services
    dropdown. POST stays admin-only.

    Sprint 3B — list scoped via `filter_services_for`; CREATE
    defaults `company` from the actor when omitted (matches the
    Provider Admin frontend that doesn't send the field), then
    runs the catalog-management policy gate against the resolved
    company.
    """

    serializer_class = ServiceSerializer
    pagination_class = UnboundedPagination

    def get_permissions(self):
        if self.request.method == "GET":
            return [IsAuthenticated()]
        return [IsSuperAdminOrCompanyAdmin()]

    def get_queryset(self):
        qs = Service.objects.select_related("category", "company").all()
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
        qs = filter_services_for(self.request.user, qs)
        return qs.order_by("category__name", "name", "id")

    def perform_create(self, serializer):
        # Resolve company (defaults for CA, multi-Company guard
        # for SA), then run the catalog-management policy gate.
        target_company = _resolve_service_create_company(
            self.request.user,
            serializer.validated_data.get("company"),
        )
        _enforce_catalog_management(self.request.user, target_company)
        # Persist with the resolved company so an omitted field on
        # the wire still lands non-null on the DB row.
        serializer.save(company=target_company)


class ServiceDetailView(generics.RetrieveUpdateDestroyAPIView):
    """GET / PATCH / DELETE at /api/services/<id>/.

    Sprint 29 Batch 29.8.5 — GET opened to any authenticated user;
    PATCH / PUT / DELETE stay admin-only.

    Sprint 3B — GET scoped via `filter_services_for` (404 for
    out-of-scope reads). Write paths run the policy gate against
    the row's existing `company`.
    """

    serializer_class = ServiceSerializer
    lookup_url_kwarg = "service_id"

    def get_permissions(self):
        if self.request.method == "GET":
            return [IsAuthenticated()]
        return [IsSuperAdminOrCompanyAdmin()]

    def get_queryset(self):
        qs = Service.objects.select_related("category", "company").all()
        return filter_services_for(self.request.user, qs)

    def perform_update(self, serializer):
        # company is read-only on UPDATE — the row's existing
        # company governs the policy check.
        _enforce_catalog_management(
            self.request.user, serializer.instance.company
        )
        serializer.save()

    def delete(self, request, *args, **kwargs):
        instance = self.get_object()
        _enforce_catalog_management(request.user, instance.company)
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


class ServiceBulkRaiseView(APIView):
    """M5 C / #108 Part C — bulk-ADJUST (raise or lower) the catalog
    default_unit_price of a set of Services by a percentage or fixed
    amount, IN PLACE. Catalog defaults are quoting-reference numbers
    (no validity window); this updates the baseline only and does NOT
    touch any CustomerServicePrice (what customers are billed).

    POST /api/services/bulk-raise/
    Body: { "services": [id,...], "mode": "percent"|"fixed",
            "amount": "10.00", "direction": "raise"|"lower" }
    (`direction` defaults to "raise" — the pre-#108 wire shape is
    unchanged; the URL keeps its historical name.)

    All-or-nothing: every id must be an active, in-scope catalog row,
    else 400 (service_bulk_raise_invalid) with zero writes. A lower
    that would take ANY selected default price to zero or below
    rejects the whole batch (400 service_bulk_raise_result_invalid,
    zero writes); a percent lower >= 100 is rejected at input
    validation. Provider-only — SA for any in-scope company, CA for
    own company via the catalog-management gate; BM/STAFF/
    CUSTOMER_USER 403.
    """

    permission_classes = [IsSuperAdminOrCompanyAdmin]

    def _resolve_services(self, service_ids, user):
        in_scope = {
            s.id: s
            for s in filter_services_for(
                user,
                Service.objects.filter(
                    id__in=service_ids
                ).select_related("company"),
            )
        }
        resolved = []
        for sid in service_ids:
            svc = in_scope.get(sid)
            if svc is None or not svc.is_active:
                raise serializers.ValidationError(
                    {
                        "services": [
                            serializers.ErrorDetail(
                                f"Service id={sid} is not a valid, "
                                "active catalog row in scope.",
                                code=ERR_SERVICE_BULK_RAISE_INVALID,
                            )
                        ]
                    }
                )
            _enforce_catalog_management(user, svc.company)
            resolved.append(svc)
        return resolved

    @staticmethod
    def _adjusted(old_price, mode, amount, direction):
        signed = amount if direction == "raise" else -amount
        if mode == "percent":
            new = old_price * (Decimal("1") + signed / Decimal("100"))
        else:  # fixed
            new = old_price + signed
        return new.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    def post(self, request, *args, **kwargs):
        payload = _ServiceBulkRaiseInputSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        service_ids = payload.validated_data["services"]
        mode = payload.validated_data["mode"]
        amount = payload.validated_data["amount"]
        direction = payload.validated_data["direction"]

        resolved = self._resolve_services(service_ids, request.user)

        # #108 Part C — zero-floor guard, all-or-nothing: compute every
        # new price BEFORE writing anything; one non-positive result
        # rejects the whole batch.
        adjusted = [
            (
                svc,
                self._adjusted(
                    svc.default_unit_price, mode, amount, direction
                ),
            )
            for svc in resolved
        ]
        for svc, new_price in adjusted:
            if new_price <= Decimal("0"):
                raise serializers.ValidationError(
                    {
                        "amount": [
                            serializers.ErrorDetail(
                                f"Lowering service id={svc.id} "
                                f"({svc.default_unit_price}) by this "
                                "amount would result in a non-positive "
                                "default price; the batch was rejected.",
                                code=ERR_SERVICE_BULK_RAISE_RESULT_INVALID,
                            )
                        ]
                    }
                )

        try:
            audit_context.set_current_reason("service_default_bulk_raise")
        except Exception:  # pragma: no cover - defensive
            pass

        results = []
        with transaction.atomic():
            for svc, new_price in adjusted:
                old_price = svc.default_unit_price
                svc.default_unit_price = new_price
                svc.save(update_fields=["default_unit_price", "updated_at"])
                results.append(
                    {
                        "service": svc.id,
                        "old_default_unit_price": str(old_price),
                        "new_default_unit_price": str(new_price),
                    }
                )

        return Response(
            {"updated_count": len(results), "results": results},
            status=status.HTTP_200_OK,
        )
