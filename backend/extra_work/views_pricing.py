"""
Sprint 28 Batch 5 — per-customer pricing CRUD endpoints
(`CustomerServicePrice`).

Routes (registered in `customers/urls.py`, mounted under
`/api/customers/<customer_id>/pricing/`):

  GET / POST                      /api/customers/<customer_id>/pricing/
  GET / PATCH / DELETE            /api/customers/<customer_id>/pricing/<int:price_id>/
  POST                            /api/customers/<customer_id>/pricing/copy-from-default/

Permission gates:
  * Provider write (`IsSuperAdminOrCompanyAdminForCompany`): the
    object check resolves on the Customer model — SUPER_ADMIN
    passes for any customer; COMPANY_ADMIN passes only for
    customers inside their own provider company; BM / STAFF /
    CUSTOMER_USER never reach the view.
  * Customer-side read (Sprint 4B): GET (list + detail) admits
    CUSTOMER_USER who holds at least one active
    `CustomerUserBuildingAccess` row for the URL-bound customer.
    All three customer access roles (CUSTOMER_USER /
    CUSTOMER_LOCATION_MANAGER / CUSTOMER_COMPANY_ADMIN) read the
    same list — Sprint 4B keeps CSP customer-wide, not per-
    building. Customer-side reads are filtered to active /
    currently-valid rows by default and never expose provider
    default prices.
  * Copy-from-default (Sprint 4B): same write gate as POST/PATCH
    plus an all-or-nothing validation pass over the services
    before any DB writes.

ID-smuggling defence: the detail view re-scopes the lookup BY the
URL-bound customer (`customer=customer`). A SUPER_ADMIN asking for
price-B under customer-A's URL therefore 404s instead of silently
acting on the other customer's row.

Sprint 4B — DELETE now SOFT-ARCHIVES.
  * `DELETE /api/customers/<cid>/pricing/<pid>/` flips `is_active`
    to False and saves the row instead of issuing a SQL DELETE.
    Returns 204 to preserve the existing client contract.
  * Idempotent: re-deleting an already-inactive row also returns
    204 (no audit row in that case because nothing changed).
  * Hard delete is no longer exposed through the public API —
    the persistent CSP row is what the Sprint 2A snapshot FK
    points at via `SET_NULL`; archiving keeps the original row
    discoverable for reporting.
"""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from django.db import transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404
from rest_framework import generics, serializers, status
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import BasePermission
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.models import UserRole
from accounts.permissions import (
    IsAuthenticatedAndActive,
    IsSuperAdminOrCompanyAdminForCompany,
)
from audit import context as audit_context
from companies.models import CompanyUserMembership
from config.pagination import UnboundedPagination
from customers.models import Customer, CustomerUserBuildingAccess

from .models import CustomerServicePrice, Service
from .serializers_catalog import CustomerServicePriceSerializer


# Sprint 3B / Sprint 4B — stable error codes surfaced from this module.
ERR_CUSTOMER_PRICE_POLICY_DISABLED = (
    "provider_admin_customer_price_management_disabled"
)
ERR_CUSTOMER_PRICE_READ_FORBIDDEN = "customer_price_read_forbidden"
ERR_INVALID_VALID_ON = "invalid_valid_on"
ERR_COPY_SERVICES_REQUIRED = "copy_from_default_services_required"
ERR_COPY_VALID_FROM_REQUIRED = "copy_from_default_valid_from_required"
ERR_COPY_SERVICE_INVALID = "copy_from_default_service_invalid"
ERR_COPY_FORBIDDEN = "copy_from_default_forbidden"
ERR_SERVICE_COMPANY_MISMATCH = "service_customer_company_mismatch"


def _enforce_customer_price_policy(user, customer):
    """Sprint 3B — gate WRITE methods on the CSP endpoint against
    `Company.provider_admin_may_manage_customer_prices`.

    SUPER_ADMIN bypasses. COMPANY_ADMIN passes only when their
    target company's toggle is True. The cross-company branch is
    already handled by `IsSuperAdminOrCompanyAdminForCompany` at
    the object level (403 there); this helper only fires the
    policy-disabled branch.
    """
    if user.role == UserRole.SUPER_ADMIN:
        return
    if user.role != UserRole.COMPANY_ADMIN:
        # Defensive — the upstream permission rejected other roles
        # at the permission layer.
        raise PermissionDenied(detail="Forbidden.")
    company = customer.company
    if not company.provider_admin_may_manage_customer_prices:
        raise PermissionDenied(
            detail={
                "detail": (
                    "Provider Admin customer-price management is "
                    "disabled for this provider company. Ask Super "
                    "Admin to enable it."
                ),
                "code": ERR_CUSTOMER_PRICE_POLICY_DISABLED,
            }
        )


def _customer_user_has_access(user, customer) -> bool:
    """Sprint 4B — return True iff `user` (role=CUSTOMER_USER) holds at
    least one ACTIVE `CustomerUserBuildingAccess` row for `customer`.
    Sprint 4B keeps CSP customer-wide, so any active access under the
    customer admits the user to the customer-side pricing read."""
    return CustomerUserBuildingAccess.objects.filter(
        membership__user=user,
        membership__customer=customer,
        is_active=True,
    ).exists()


def _company_admin_in_company(user, company) -> bool:
    return CompanyUserMembership.objects.filter(
        user=user, company=company
    ).exists()


class IsCustomerPriceReader(IsAuthenticatedAndActive):
    """Sprint 4B — per-method permission for the CSP list/detail view.

    GET is admitted for:
      * SUPER_ADMIN.
      * COMPANY_ADMIN of the URL-bound customer's company.
      * CUSTOMER_USER who holds an active
        `CustomerUserBuildingAccess` row for the URL-bound customer
        (any of the three customer access roles is enough — Sprint
        4B keeps CSP customer-wide).
      * BUILDING_MANAGER / STAFF / CUSTOMER_USER without access →
        HTTP 403, code `customer_price_read_forbidden`.

    POST / PATCH / DELETE fall back to the existing
    `IsSuperAdminOrCompanyAdminForCompany` rules (BM/STAFF/CUSTOMER
    all blocked at this layer, then policy toggle enforced in the
    view's `perform_*` / `delete` handlers).

    The view computes `request.method` and chooses the right rules.
    Object-level checks are skipped here — the views run their own
    `Customer` lookups + ID-smuggling guards.
    """

    def _customer_id(self, view):
        return view.kwargs.get("customer_id")

    def has_permission(self, request, view):
        if not super().has_permission(request, view):
            return False
        method = request.method.upper()
        user = request.user
        # Provider-side roles handled by the inner permission.
        if user.role in (UserRole.SUPER_ADMIN, UserRole.COMPANY_ADMIN):
            # Defer the per-customer object check to the view's
            # `_get_customer`. SUPER_ADMIN passes any customer;
            # COMPANY_ADMIN must be a member of the company — the
            # existing `IsSuperAdminOrCompanyAdminForCompany`
            # object check will run when `_get_customer` calls
            # `self.check_object_permissions(...)`.
            return True

        if method in ("GET", "HEAD", "OPTIONS"):
            if user.role != UserRole.CUSTOMER_USER:
                # BM / STAFF: read forbidden on this endpoint.
                raise PermissionDenied(
                    detail={
                        "detail": (
                            "You may not read customer-specific "
                            "pricing on this endpoint."
                        ),
                        "code": ERR_CUSTOMER_PRICE_READ_FORBIDDEN,
                    }
                )
            customer_id = self._customer_id(view)
            try:
                customer = Customer.objects.get(pk=customer_id)
            except Customer.DoesNotExist:
                return False
            if not _customer_user_has_access(user, customer):
                raise PermissionDenied(
                    detail={
                        "detail": (
                            "You do not have access to read this "
                            "customer's agreed prices."
                        ),
                        "code": ERR_CUSTOMER_PRICE_READ_FORBIDDEN,
                    }
                )
            return True

        # Non-safe methods: block everyone not provider-side.
        raise PermissionDenied(
            detail={
                "detail": "Only Super Admin or Provider Admin may write.",
                "code": ERR_CUSTOMER_PRICE_READ_FORBIDDEN,
            }
        )


def _parse_valid_on(raw_value):
    """Sprint 4B — parse the `?valid_on=YYYY-MM-DD` filter.

    Returns the parsed `date` on success, or raises a DRF
    ValidationError with stable code `invalid_valid_on` (HTTP 400)
    on a malformed value. An empty / missing string returns None
    so the caller can fall back to `date.today()`.
    """
    if raw_value in (None, ""):
        return None
    try:
        return datetime.strptime(raw_value, "%Y-%m-%d").date()
    except (TypeError, ValueError):
        raise serializers.ValidationError(
            {
                "valid_on": [
                    serializers.ErrorDetail(
                        "Expected YYYY-MM-DD.",
                        code=ERR_INVALID_VALID_ON,
                    )
                ]
            }
        )


class CustomerServicePriceListCreateView(generics.ListCreateAPIView):
    """GET (list) + POST (create) at
    /api/customers/<customer_id>/pricing/.

    Sprint 4B:
      * GET admits CUSTOMER_USER with active access (see
        `IsCustomerPriceReader`); the queryset narrows to
        `is_active=True` + currently-valid rows by default for
        customer-side actors and adds the
        `service__company=customer.company` defensive filter so a
        stray foreign-provider row cannot leak.
      * `?valid_on=YYYY-MM-DD` filter swaps the default "today" for
        the supplied date. Customers may use it to preview past /
        future windows.
      * POST / PATCH / DELETE unchanged on the permission side
        (provider operators with the toggle).
    """

    permission_classes = [IsCustomerPriceReader]
    serializer_class = CustomerServicePriceSerializer
    pagination_class = UnboundedPagination

    def _get_customer(self):
        customer = get_object_or_404(
            Customer, pk=self.kwargs["customer_id"]
        )
        # Provider-side actors run the existing object check via
        # the underlying permission; this preserves the COMPANY_ADMIN
        # "own company only" branch.
        if self.request.user.role in (
            UserRole.SUPER_ADMIN,
            UserRole.COMPANY_ADMIN,
        ):
            inner = IsSuperAdminOrCompanyAdminForCompany()
            if not inner.has_object_permission(
                self.request, self, customer
            ):
                raise PermissionDenied(detail="Forbidden.")
        return customer

    def get_queryset(self):
        customer = self._get_customer()
        qs = CustomerServicePrice.objects.filter(
            customer=customer
        ).select_related("service", "service__category", "customer")

        # Sprint 4B — defensive cross-company filter. Belt-and-braces
        # for the case where any rogue CSP row exists with a service
        # outside the customer's company (the create serializer
        # rejects this, but ORM-direct writes could bypass).
        qs = qs.filter(service__company_id=customer.company_id)

        # Optional `?service=<id>` filter, plus defensive same-company
        # check on the filter argument itself.
        service_param = self.request.query_params.get("service")
        if service_param:
            try:
                service_pk = int(service_param)
            except (TypeError, ValueError):
                return CustomerServicePrice.objects.none()
            qs = qs.filter(service_id=service_pk)

        # Sprint 4B — `?valid_on=` filter + customer-side narrowing.
        raw_valid_on = self.request.query_params.get("valid_on")
        valid_on = _parse_valid_on(raw_valid_on)

        user = self.request.user
        if user.role == UserRole.CUSTOMER_USER:
            # Customer-side reads see ONLY active currently-valid
            # rows. Override `valid_on=` semantics still hold —
            # customer may preview a date — but inactive rows stay
            # hidden.
            target_date = valid_on or date.today()
            qs = qs.filter(
                is_active=True,
                valid_from__lte=target_date,
            ).filter(
                Q(valid_to__isnull=True) | Q(valid_to__gte=target_date)
            )
        else:
            # Provider-side reads: optional `valid_on` narrowing.
            if valid_on is not None:
                qs = qs.filter(
                    valid_from__lte=valid_on,
                ).filter(
                    Q(valid_to__isnull=True) | Q(valid_to__gte=valid_on)
                )
            # `?is_active=true|false` for provider-side actors only.
            flag = self.request.query_params.get("is_active")
            if flag is not None:
                lowered = flag.strip().lower()
                if lowered in {"true", "1", "yes", "y"}:
                    qs = qs.filter(is_active=True)
                elif lowered in {"false", "0", "no", "n"}:
                    qs = qs.filter(is_active=False)

        return qs.order_by("-valid_from", "-id")

    def perform_create(self, serializer):
        customer = self._get_customer()
        _enforce_customer_price_policy(self.request.user, customer)
        serializer.save(customer=customer)


class CustomerServicePriceDetailView(generics.RetrieveUpdateDestroyAPIView):
    """GET / PATCH / DELETE at
    /api/customers/<customer_id>/pricing/<int:price_id>/.

    Sprint 4B:
      * GET admits CUSTOMER_USER with active access via
        `IsCustomerPriceReader`. Customer-side actors only see
        active currently-valid rows (cross-checked against today's
        date when no `valid_on` is supplied).
      * DELETE soft-archives — flips `is_active=False` and returns
        204. Hard delete is no longer reachable from the API.
    """

    permission_classes = [IsCustomerPriceReader]
    serializer_class = CustomerServicePriceSerializer

    def _get_customer(self):
        customer = get_object_or_404(
            Customer, pk=self.kwargs["customer_id"]
        )
        if self.request.user.role in (
            UserRole.SUPER_ADMIN,
            UserRole.COMPANY_ADMIN,
        ):
            inner = IsSuperAdminOrCompanyAdminForCompany()
            if not inner.has_object_permission(
                self.request, self, customer
            ):
                raise PermissionDenied(detail="Forbidden.")
        return customer

    def get_object(self):
        customer = self._get_customer()
        # Defence-in-depth: scope the price lookup BY the URL-bound
        # customer so a price belonging to another customer is a
        # clean 404, never a silent cross-customer operation.
        price = get_object_or_404(
            CustomerServicePrice,
            pk=self.kwargs["price_id"],
            customer=customer,
        )

        # Sprint 4B — customer-side reads must see only active /
        # currently-valid rows. ID-smuggling defence: surface a
        # clean 404 (do not leak the existence of an expired or
        # archived row to the customer).
        if self.request.user.role == UserRole.CUSTOMER_USER:
            today = date.today()
            if (
                not price.is_active
                or price.valid_from > today
                or (price.valid_to is not None and price.valid_to < today)
                or price.service.company_id != customer.company_id
            ):
                from django.http import Http404

                raise Http404
        return price

    def perform_update(self, serializer):
        _enforce_customer_price_policy(
            self.request.user, serializer.instance.customer
        )
        serializer.save()

    def delete(self, request, *args, **kwargs):
        price = self.get_object()
        _enforce_customer_price_policy(request.user, price.customer)

        # Sprint 4B — soft-archive. If already inactive, idempotent
        # no-op (no audit row written because no field changed).
        if price.is_active:
            try:
                audit_context.set_current_reason(
                    "customer_price_soft_archive"
                )
            except Exception:  # pragma: no cover - defensive
                # The audit helper should never raise, but guard
                # against an unexpected runtime so the archive call
                # still succeeds.
                pass
            price.is_active = False
            price.save(update_fields=["is_active", "updated_at"])

        return Response(status=status.HTTP_204_NO_CONTENT)


# ---------------------------------------------------------------------------
# Sprint 4B — copy-from-default action
# ---------------------------------------------------------------------------
class _CopyFromDefaultInputSerializer(serializers.Serializer):
    """Sprint 4B — input shape for
    `POST /api/customers/<cid>/pricing/copy-from-default/`.

    Validates per-field shape (services list non-empty, valid_from
    required); cross-company / per-service rules are validated in
    the view so they can return targeted per-line errors with
    stable codes.
    """

    services = serializers.ListField(
        child=serializers.IntegerField(min_value=1),
        allow_empty=False,
        error_messages={
            "empty": (
                "At least one service id is required."
            ),
            "required": "Services list is required.",
        },
    )
    valid_from = serializers.DateField(
        error_messages={"required": "valid_from is required."}
    )
    valid_to = serializers.DateField(
        required=False, allow_null=True, default=None
    )

    def validate(self, attrs):
        valid_from = attrs.get("valid_from")
        valid_to = attrs.get("valid_to")
        if valid_from is not None and valid_to is not None:
            if valid_to < valid_from:
                raise serializers.ValidationError(
                    {"valid_to": "valid_to must be on or after valid_from."}
                )
        return attrs


class CustomerServicePriceCopyFromDefaultView(APIView):
    """Sprint 4B — bulk seed CSP rows from Service.default_unit_price
    + Service.default_vat_pct.

    POST /api/customers/<customer_id>/pricing/copy-from-default/

    Body:
      {
        "services": [<service_id>, ...],
        "valid_from": "YYYY-MM-DD",
        "valid_to": null | "YYYY-MM-DD"
      }

    Behaviour:
      * All-or-nothing validation pass first. Any invalid service id
        (not found, inactive, or cross-company) returns 400 with a
        stable code (`copy_from_default_service_invalid` or
        `service_customer_company_mismatch`) and writes zero rows.
      * Then per-service idempotency: skip services that already
        have an active CSP row whose `[valid_from, valid_to]`
        overlaps the requested window. The skip path does not write
        a row.
      * Writes happen inside `transaction.atomic`. The existing CSP
        post_save signal stamps an AuditLog CREATE row for each
        new row; the action sets the audit reason to
        `copy_from_provider_default` so the marker rides along.
      * Response shape:
          {
            "created_count": N,
            "skipped_count": M,
            "results": [
              {"service": id, "status": "created",
               "customer_service_price": new_id},
              {"service": id, "status": "skipped_existing"},
              ...
            ]
          }

    Permission:
      * SUPER_ADMIN always.
      * COMPANY_ADMIN of the customer's company iff
        `Company.provider_admin_may_manage_customer_prices=True`.
      * Everyone else 403 (BM/STAFF blocked at DRF permission
        gate; CUSTOMER_USER additionally blocked because they are
        not allowed to seed customer pricing for themselves).
    """

    permission_classes = [IsSuperAdminOrCompanyAdminForCompany]

    def _get_customer(self):
        customer = get_object_or_404(
            Customer, pk=self.kwargs["customer_id"]
        )
        self.check_object_permissions(self.request, customer)
        return customer

    def _classify_services(self, services_data, customer):
        """All-or-nothing validation pass. Returns a list of Service
        objects in the same order as `services_data`, or raises a
        DRF ValidationError with the first invalid service id
        identified.

        Rules:
          * Each id must exist in the Service catalog.
          * Each row's `company_id` must match `customer.company_id`
            (cross-company guard) → code
            `service_customer_company_mismatch`.
          * Each row's `is_active` must be True → code
            `copy_from_default_service_invalid`.
          * Duplicate ids in the request are tolerated; the per-row
            idempotency check downstream skips the second occurrence
            because the first will have produced an overlapping
            active CSP row by then.
        """
        services_by_id = {
            s.id: s
            for s in Service.objects.filter(
                id__in=services_data
            ).select_related("company")
        }
        resolved = []
        for sid in services_data:
            svc = services_by_id.get(sid)
            if svc is None or not svc.is_active:
                raise serializers.ValidationError(
                    {
                        "services": [
                            serializers.ErrorDetail(
                                f"Service id={sid} is not a valid, "
                                "active catalog row.",
                                code=ERR_COPY_SERVICE_INVALID,
                            )
                        ]
                    }
                )
            if svc.company_id != customer.company_id:
                raise serializers.ValidationError(
                    {
                        "services": [
                            serializers.ErrorDetail(
                                f"Service id={sid} belongs to a "
                                "different provider company than "
                                "the customer.",
                                code=ERR_SERVICE_COMPANY_MISMATCH,
                            )
                        ]
                    }
                )
            resolved.append(svc)
        return resolved

    def _has_overlapping_active(
        self, customer, service, valid_from, valid_to
    ):
        """Sprint 4B — idempotency check. True iff there is already
        an ACTIVE `CustomerServicePrice` row for (customer, service)
        whose validity window overlaps the requested one.

        Two-window overlap: `[a_from, a_to] overlaps [b_from, b_to]`
        iff `a_from <= b_to AND b_from <= a_to` (treating NULL `to`
        as +infinity).
        """
        candidates = CustomerServicePrice.objects.filter(
            customer=customer,
            service=service,
            is_active=True,
        )
        for row in candidates:
            row_from = row.valid_from
            row_to = row.valid_to  # may be None = open-ended
            new_to = valid_to  # may be None = open-ended

            # row_from <= new_to (or new_to is None ⇒ True)
            cond_a = (new_to is None) or (row_from <= new_to)
            # valid_from <= row_to (or row_to is None ⇒ True)
            cond_b = (row_to is None) or (valid_from <= row_to)
            if cond_a and cond_b:
                return True
        return False

    def post(self, request, *args, **kwargs):
        customer = self._get_customer()
        _enforce_customer_price_policy(request.user, customer)

        payload = _CopyFromDefaultInputSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        services_data = payload.validated_data["services"]
        valid_from = payload.validated_data["valid_from"]
        valid_to = payload.validated_data.get("valid_to")

        # All-or-nothing validation pass.
        resolved_services = self._classify_services(
            services_data, customer
        )

        # Provenance marker for downstream AuditLog rows.
        try:
            audit_context.set_current_reason(
                "copy_from_provider_default"
            )
        except Exception:  # pragma: no cover
            pass

        results = []
        created_count = 0
        skipped_count = 0
        with transaction.atomic():
            for svc in resolved_services:
                if self._has_overlapping_active(
                    customer, svc, valid_from, valid_to
                ):
                    skipped_count += 1
                    results.append(
                        {
                            "service": svc.id,
                            "status": "skipped_existing",
                        }
                    )
                    continue
                row = CustomerServicePrice.objects.create(
                    service=svc,
                    customer=customer,
                    unit_price=svc.default_unit_price,
                    vat_pct=svc.default_vat_pct,
                    valid_from=valid_from,
                    valid_to=valid_to,
                    is_active=True,
                )
                created_count += 1
                results.append(
                    {
                        "service": svc.id,
                        "status": "created",
                        "customer_service_price": row.id,
                    }
                )

        return Response(
            {
                "created_count": created_count,
                "skipped_count": skipped_count,
                "results": results,
            },
            status=status.HTTP_200_OK,
        )
