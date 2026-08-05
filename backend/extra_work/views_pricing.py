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
from decimal import Decimal, ROUND_HALF_UP

from django.db import IntegrityError, transaction
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404
from rest_framework import generics, serializers, status
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import BasePermission, SAFE_METHODS
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.models import UserRole
from accounts.permissions import (
    IsAuthenticatedAndActive,
    IsSuperAdminOrCompanyAdmin,
    IsSuperAdminOrCompanyAdminForCompany,
)
from audit import context as audit_context
from companies.models import CompanyUserMembership
from config.pagination import UnboundedPagination
from customers.models import (
    Customer,
    CustomerUserBuildingAccess,
    CustomerUserMembership,
)

from .models import (
    CustomerCustomPrice,
    CustomerPriceFolder,
    CustomerServicePrice,
    Service,
)
from .serializers_catalog import (
    CustomerCustomPriceSerializer,
    CustomerPriceFolderSerializer,
    CustomerServicePriceSerializer,
)
# Sprint 123 — reuse the Service-side cross-company guard verbatim
# rather than re-implementing it (same rule: a managed_unit must
# belong to the row's own company).
from .views_catalog import _enforce_same_company_managed_unit


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
ERR_BULK_RAISE_AMOUNT_INVALID = "bulk_raise_amount_invalid"
ERR_BULK_RAISE_PRICE_INVALID = "bulk_raise_price_invalid"
# #108 Part C — a lower that would push any selected price to zero or
# below rejects the WHOLE batch (all-or-nothing, zero writes).
ERR_BULK_RAISE_RESULT_INVALID = "bulk_raise_result_invalid"
# Sprint 143 §3 — customer price folders.
ERR_FOLDER_CUSTOMER_MISMATCH = "price_folder_customer_mismatch"
ERR_FOLDER_NAME_NOT_UNIQUE = "price_folder_name_not_unique"


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
    customer admits the user to the customer-side pricing read.

    SoT Addendum A.1 — a company-wide Customer Company Admin (the
    membership `is_company_admin` flag) has customer-wide access with NO
    per-building access row, so the flag alone admits them (otherwise a
    migrated CCA with zero CUBA rows would be 403'd on the pricing read
    that a strictly-lower Customer User is allowed)."""
    if CustomerUserMembership.objects.filter(
        user=user, customer=customer, is_company_admin=True
    ).exists():
        return True
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


def _enforce_same_customer_folder(folder, customer):
    """Sprint 143 §3 — a price row's `folder` must belong to the SAME
    customer as the row.

    Exactly the shape `_enforce_same_company_managed_unit` uses, and for
    the same reason: `folder` is a writable PK on both price
    serializers, so without this an operator could file THIS customer's
    price row under ANOTHER customer's folder — where its own customer's
    page would never show it and the other customer's "delete with
    contents" would archive it.

    HTTP 400, not 403: the actor is allowed to write here, the value is
    just not a legal one.
    """
    if folder is None or customer is None:
        return
    if folder.customer_id != customer.id:
        raise serializers.ValidationError(
            {
                "folder": [
                    serializers.ErrorDetail(
                        "This folder belongs to a different customer.",
                        code=ERR_FOLDER_CUSTOMER_MISMATCH,
                    )
                ]
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


def _include_archived(request) -> bool:
    """Sprint 137 item 2 — `?include_archived=true` opt-in.

    DELETE on both pricing endpoints soft-archives (`is_active=False`)
    rather than hard-deleting, because `ExtraWorkRequestItem.
    snapshot_customer_service_price` still points at contract rows
    (SET_NULL) and archiving keeps that operational-history link intact.
    The list endpoints used to return archived rows unconditionally, so
    a "deleted" price reappeared greyed-out on the next page load and
    the operator's delete looked like it had silently failed.

    Archived rows are now hidden unless the caller opts in (the
    frontend's "Show archived" toggle). Anything other than a truthy
    string means "hide", so a malformed value fails safe.
    """
    raw = request.query_params.get("include_archived")
    if raw is None:
        return False
    return raw.strip().lower() in {"true", "1", "yes", "y"}


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
            elif not _include_archived(self.request):
                # Sprint 137 item 2 — archived rows are HIDDEN by default.
                # DELETE soft-archives (see `delete` below), and this list
                # used to return the archived row again on the next load,
                # so a "deleted" price reappeared greyed-out and the
                # operator's delete looked like it had silently failed.
                # `?include_archived=true` opts back in (the "Show
                # archived" toggle); an explicit `?is_active=` still wins
                # so existing callers are byte-identical.
                qs = qs.filter(is_active=True)

        return qs.order_by("-valid_from", "-id")

    def perform_create(self, serializer):
        customer = self._get_customer()
        _enforce_customer_price_policy(self.request.user, customer)
        _enforce_same_customer_folder(
            serializer.validated_data.get("folder"), customer
        )
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
        # Sprint 143 §3 — moving a row into or out of a folder is a PATCH
        # of this field, so the same-customer guard runs here too.
        if "folder" in serializer.validated_data:
            _enforce_same_customer_folder(
                serializer.validated_data["folder"],
                serializer.instance.customer,
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
    # Sprint 143 §3 — copy INTO a folder. Either an existing folder id,
    # or a name to create one with (the "copy a company category, with
    # its services" flow, whose default name is the category's). Both in
    # the SAME request so a failed copy cannot strand an empty folder
    # the operator never asked for.
    folder = serializers.IntegerField(
        required=False, allow_null=True, default=None, min_value=1
    )
    folder_name = serializers.CharField(
        required=False, allow_blank=True, default=""
    )

    def validate(self, attrs):
        valid_from = attrs.get("valid_from")
        valid_to = attrs.get("valid_to")
        if attrs.get("folder") and (attrs.get("folder_name") or "").strip():
            raise serializers.ValidationError(
                {
                    "folder": (
                        "Supply either an existing folder or a name for a "
                        "new one, not both."
                    )
                }
            )
        if valid_from is not None and valid_to is not None:
            if valid_to < valid_from:
                raise serializers.ValidationError(
                    {"valid_to": "valid_to must be on or after valid_from."}
                )
        return attrs


class _BulkRaiseInputSerializer(serializers.Serializer):
    """M5 C / #108 Part C — input for POST
    /api/customers/<cid>/pricing/bulk-raise/. Adjusts (raises OR
    lowers) a set of the customer's active CustomerServicePrice rows
    by a percentage or fixed amount, writing NEW validity-window rows
    (history preserved). `prices` = CSP ids to adjust; `mode` =
    percent|fixed; `amount` > 0 always; `direction` = raise|lower
    (defaults to raise so pre-#108 clients stay valid); `valid_from` =
    effective date. A percent LOWER must stay below 100 — a 100%+ cut
    can only zero or negate a price.
    """

    prices = serializers.ListField(
        child=serializers.IntegerField(min_value=1),
        allow_empty=False,
        error_messages={
            "empty": "At least one price id is required.",
            "required": "Prices list is required.",
        },
    )
    mode = serializers.ChoiceField(choices=["percent", "fixed"])
    amount = serializers.DecimalField(max_digits=12, decimal_places=2)
    direction = serializers.ChoiceField(
        choices=["raise", "lower"], default="raise"
    )
    valid_from = serializers.DateField(
        error_messages={"required": "valid_from is required."}
    )

    def validate_amount(self, value):
        if value is None or value <= Decimal("0"):
            raise serializers.ValidationError(
                serializers.ErrorDetail(
                    "amount must be greater than zero.",
                    code=ERR_BULK_RAISE_AMOUNT_INVALID,
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
                            code=ERR_BULK_RAISE_AMOUNT_INVALID,
                        )
                    ]
                }
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
        folder_id = payload.validated_data.get("folder")
        folder_name = (payload.validated_data.get("folder_name") or "").strip()

        # All-or-nothing validation pass.
        resolved_services = self._classify_services(
            services_data, customer
        )

        # Sprint 143 §3 — resolve the folder BEFORE the write loop so an
        # invalid one is a clean 400 with zero rows written, same
        # all-or-nothing discipline as the service pass above.
        folder = None
        if folder_id:
            folder = CustomerPriceFolder.objects.filter(
                pk=folder_id
            ).first()
            if folder is None:
                raise serializers.ValidationError(
                    {"folder": "Unknown folder."}
                )
            _enforce_same_customer_folder(folder, customer)

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
            # Created inside the same transaction as the rows: if the
            # copy fails, the folder goes with it rather than being left
            # behind empty.
            if folder is None and folder_name:
                clash = any(
                    f.name.strip().lower() == folder_name.lower()
                    for f in CustomerPriceFolder.objects.filter(
                        customer=customer
                    )
                )
                if clash:
                    raise serializers.ValidationError(
                        {
                            "folder_name": [
                                serializers.ErrorDetail(
                                    f"A folder named {folder_name!r} "
                                    "already exists for this customer.",
                                    code=ERR_FOLDER_NAME_NOT_UNIQUE,
                                )
                            ]
                        }
                    )
                folder = CustomerPriceFolder.objects.create(
                    customer=customer,
                    name=folder_name,
                    created_by=request.user,
                )
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
                    folder=folder,
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
                # Sprint 143 §3 — so the UI can drill straight into the
                # folder it just created.
                "folder": (
                    CustomerPriceFolderSerializer(folder).data
                    if folder is not None
                    else None
                ),
                "results": results,
            },
            status=status.HTTP_200_OK,
        )


class CustomerPriceFolderListCreateView(generics.ListCreateAPIView):
    """Sprint 143 §3 — GET (list) + POST (create) at
    /api/customers/<customer_id>/price-folders/.

    Provider-operator-only, same gate as the custom-pricing endpoints:
    a folder is a provider-side arrangement of the prices agreed with a
    customer, and the customer does not manage it.

    POST creates an EMPTY folder from a name the operator typed. The
    other creation route — copy a company category WITH its services —
    is `copy-from-default`'s `folder_name`, which creates the folder and
    its price rows in one transaction so a failed copy cannot strand an
    empty folder.
    """

    # Sprint 145 — READ is open to a CUSTOMER_USER with active access to
    # this customer; writes stay provider-only. `IsCustomerPriceReader`
    # already draws exactly that line for `/pricing/`, so reuse it rather
    # than inventing a second rule.
    #
    # This was `IsSuperAdminOrCompanyAdmin`, i.e. provider-only on GET
    # too — so a customer user composing an Extra Work request got a 403,
    # the form degraded to an empty list, and it told them "this customer
    # has no categories yet" while the customer had two. The screen was
    # stating a fact about the data that was really a fact about
    # permissions.
    permission_classes = [IsCustomerPriceReader]
    serializer_class = CustomerPriceFolderSerializer
    pagination_class = UnboundedPagination

    def _get_customer(self):
        customer = get_object_or_404(Customer, pk=self.kwargs["customer_id"])
        # Provider-side actors keep the COMPANY_ADMIN "own company only"
        # object check; a CUSTOMER_USER has already been checked against
        # their own access rows by `IsCustomerPriceReader`. Same shape as
        # `CustomerServicePriceListCreateView._get_customer`.
        if self.request.user.role in (
            UserRole.SUPER_ADMIN,
            UserRole.COMPANY_ADMIN,
        ):
            inner = IsSuperAdminOrCompanyAdminForCompany()
            if not inner.has_object_permission(self.request, self, customer):
                raise PermissionDenied(detail="Forbidden.")
        return customer

    def get_serializer_context(self):
        ctx = super().get_serializer_context()
        # The uniqueness pre-check needs the URL-bound customer. Resolving
        # it here also re-runs the permission check before the serializer
        # touches the DB — and it is what keeps that pre-check scoped, so
        # it can never become the cross-tenant name oracle Sprint 142.1
        # fixed in the catalog serializers.
        if self.request.method not in SAFE_METHODS:
            ctx["customer"] = self._get_customer()
        return ctx

    def get_queryset(self):
        customer = self._get_customer()
        qs = CustomerPriceFolder.objects.filter(
            customer=customer
        ).annotate(
            # ONE aggregate per column for the whole page, no per-row
            # query. `distinct=True` because the two joins multiply.
            annotated_price_count=Count("prices", distinct=True)
            + Count("custom_prices", distinct=True)
        )
        flag = self.request.query_params.get("is_active")
        if flag is not None:
            lowered = flag.strip().lower()
            if lowered in {"true", "1", "yes", "y"}:
                qs = qs.filter(is_active=True)
            elif lowered in {"false", "0", "no", "n"}:
                qs = qs.filter(is_active=False)
        return qs.order_by("name", "id")

    def perform_create(self, serializer):
        customer = self._get_customer()
        _enforce_customer_price_policy(self.request.user, customer)
        try:
            # Savepoint boundary: without it Postgres refuses every
            # further command in the surrounding transaction after the
            # IntegrityError, even though Python catches it. Same
            # rationale as ManagedUnitListCreateView.perform_create.
            with transaction.atomic():
                serializer.save(
                    customer=customer, created_by=self.request.user
                )
        except IntegrityError:
            raise serializers.ValidationError(
                {
                    "name": [
                        serializers.ErrorDetail(
                            "A folder with this name already exists for "
                            "this customer.",
                            code=ERR_FOLDER_NAME_NOT_UNIQUE,
                        )
                    ]
                }
            )


class CustomerPriceFolderDetailView(generics.RetrieveUpdateDestroyAPIView):
    """Sprint 143 §3 — GET / PATCH / DELETE at
    /api/customers/<customer_id>/price-folders/<int:folder_id>/.

    PATCH renames (or archives via `is_active`). The folder is the
    CUSTOMER's own label: renaming one copied from a company category
    never touches that category, because the copy seeded price rows and
    kept no link back.

    DELETE takes `?with_contents=true|false` — TWO honest actions, both
    offered explicitly in the UI rather than one ambiguous "delete":

      * `false` (default) — FOLDER ONLY. The rows survive and become
        folderless, which `on_delete=SET_NULL` does for us. They stay
        visible on the pricing page under its folderless bucket; that is
        the whole reason a folderless row is legal.
      * `true` — WITH CONTENTS. The rows are ARCHIVED
        (`is_active=False`), never hard-deleted, and then the folder
        goes. Archiving is permanent policy for prices (`## NEXT` item
        16): `ExtraWorkRequestItem.snapshot_customer_service_price` is a
        live FK from shipped Extra Work, so destroying a price row would
        break history.

    Per-row `save()` inside one `transaction.atomic()` rather than a
    queryset `.update()`: both price models are registered for generic
    audit and `.update()` fires no `post_save`, so it would silently
    write nothing to `AuditLog` (RBAC H-10).
    """

    permission_classes = [IsSuperAdminOrCompanyAdmin]
    serializer_class = CustomerPriceFolderSerializer
    lookup_url_kwarg = "folder_id"

    def _get_customer(self):
        customer = get_object_or_404(Customer, pk=self.kwargs["customer_id"])
        inner = IsSuperAdminOrCompanyAdminForCompany()
        if not inner.has_object_permission(self.request, self, customer):
            raise PermissionDenied(detail="Forbidden.")
        return customer

    def get_serializer_context(self):
        ctx = super().get_serializer_context()
        if self.request.method not in SAFE_METHODS:
            ctx["customer"] = self._get_customer()
        return ctx

    def get_queryset(self):
        # Scoped BY the URL-bound customer, so another customer's folder
        # id is a clean 404 rather than a silent cross-customer write.
        return CustomerPriceFolder.objects.filter(
            customer=self._get_customer()
        )

    def perform_update(self, serializer):
        _enforce_customer_price_policy(
            self.request.user, serializer.instance.customer
        )
        try:
            with transaction.atomic():
                serializer.save()
        except IntegrityError:
            raise serializers.ValidationError(
                {
                    "name": [
                        serializers.ErrorDetail(
                            "A folder with this name already exists for "
                            "this customer.",
                            code=ERR_FOLDER_NAME_NOT_UNIQUE,
                        )
                    ]
                }
            )

    def delete(self, request, *args, **kwargs):
        folder = self.get_object()
        _enforce_customer_price_policy(request.user, folder.customer)

        raw = (request.query_params.get("with_contents") or "").strip().lower()
        with_contents = raw in {"true", "1", "yes", "y"}

        archived = 0
        with transaction.atomic():
            if with_contents:
                try:
                    audit_context.set_current_reason(
                        "price_folder_delete_with_contents"
                    )
                except Exception:  # pragma: no cover - defensive
                    pass
                for row in list(folder.prices.filter(is_active=True)) + list(
                    folder.custom_prices.filter(is_active=True)
                ):
                    row.is_active = False
                    row.save(update_fields=["is_active", "updated_at"])
                    archived += 1
            folder.delete()

        return Response(
            {
                # Named for what actually happened. A folder-only delete
                # archives nothing and says so.
                "archived_price_count": archived,
                "with_contents": with_contents,
            },
            status=status.HTTP_200_OK,
        )


class CustomerServicePriceBulkRaiseView(APIView):
    """M5 C / #108 Part C — bulk-ADJUST (raise or lower) a customer's
    CustomerServicePrice rows by a percentage or fixed amount, writing
    NEW validity-window rows so pricing history is preserved (the
    resolver picks the latest valid_from from the effective date
    onward).

    POST /api/customers/<customer_id>/pricing/bulk-raise/
    Body: { "prices": [id,...], "mode": "percent"|"fixed",
            "amount": "10.00", "direction": "raise"|"lower",
            "valid_from": "YYYY-MM-DD" }
    (`direction` defaults to "raise" — the pre-#108 wire shape is
    unchanged; the URL keeps its historical name.)

    All-or-nothing: every price id must be an ACTIVE CSP row owned by
    this customer, else 400 (bulk_raise_price_invalid) with zero
    writes. For each, a new row is created with the same service +
    vat_pct, unit_price = old*(1±amount/100) [percent] or old±amount
    [fixed] rounded HALF_UP to 2dp, valid_from = the effective date,
    valid_to = null, is_active = True. Existing rows are NOT modified.
    A lower that would take ANY selected price to zero or below
    rejects the whole batch (400 bulk_raise_result_invalid, zero
    writes); a percent lower >= 100 is rejected at input validation.

    Permission: SA always; CA of the customer's company iff the
    customer-price toggle is on; BM/STAFF/CUSTOMER_USER 403.
    """

    permission_classes = [IsSuperAdminOrCompanyAdminForCompany]

    def _get_customer(self):
        customer = get_object_or_404(Customer, pk=self.kwargs["customer_id"])
        self.check_object_permissions(self.request, customer)
        return customer

    def _resolve_prices(self, price_ids, customer):
        rows_by_id = {
            r.id: r
            for r in CustomerServicePrice.objects.filter(
                id__in=price_ids, customer=customer
            ).select_related("service")
        }
        # Validate every id first (active + owned) — all-or-nothing.
        validated = []
        for pid in price_ids:
            row = rows_by_id.get(pid)
            if row is None or not row.is_active:
                raise serializers.ValidationError(
                    {
                        "prices": [
                            serializers.ErrorDetail(
                                f"Price id={pid} is not an active price "
                                "for this customer.",
                                code=ERR_BULK_RAISE_PRICE_INVALID,
                            )
                        ]
                    }
                )
            validated.append(row)
        # Collapse to ONE row per service — the latest-effective row
        # (max valid_from, then max id), matching resolve_price's
        # ordering. A service can have several active rows (each raise
        # keeps the source open) and the select-all UI sends them all;
        # raising every selected row would create multiple new rows
        # sharing valid_from, where resolve_price's id tie-break could
        # let the row derived from an older source win (a lower, non-
        # compounded price). Raising only the latest source per service
        # yields one deterministic new row per service.
        latest_by_service = {}
        for row in validated:
            current = latest_by_service.get(row.service_id)
            if current is None or (row.valid_from, row.id) > (
                current.valid_from,
                current.id,
            ):
                latest_by_service[row.service_id] = row
        return [latest_by_service[sid] for sid in sorted(latest_by_service)]

    @staticmethod
    def _adjusted(old_price, mode, amount, direction):
        signed = amount if direction == "raise" else -amount
        if mode == "percent":
            new = old_price * (Decimal("1") + signed / Decimal("100"))
        else:  # fixed
            new = old_price + signed
        return new.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    def post(self, request, *args, **kwargs):
        customer = self._get_customer()
        _enforce_customer_price_policy(request.user, customer)

        payload = _BulkRaiseInputSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        price_ids = payload.validated_data["prices"]
        mode = payload.validated_data["mode"]
        amount = payload.validated_data["amount"]
        direction = payload.validated_data["direction"]
        valid_from = payload.validated_data["valid_from"]

        resolved = self._resolve_prices(price_ids, customer)

        # #108 Part C — zero-floor guard, all-or-nothing: compute every
        # new price BEFORE writing anything; one non-positive result
        # rejects the whole batch.
        adjusted = [
            (src, self._adjusted(src.unit_price, mode, amount, direction))
            for src in resolved
        ]
        for src, new_price in adjusted:
            if new_price <= Decimal("0"):
                raise serializers.ValidationError(
                    {
                        "amount": [
                            serializers.ErrorDetail(
                                f"Lowering price id={src.id} "
                                f"({src.unit_price}) by this amount "
                                "would result in a non-positive unit "
                                "price; the batch was rejected.",
                                code=ERR_BULK_RAISE_RESULT_INVALID,
                            )
                        ]
                    }
                )

        try:
            audit_context.set_current_reason("customer_price_bulk_raise")
        except Exception:  # pragma: no cover - defensive
            pass

        results = []
        with transaction.atomic():
            for src, new_price in adjusted:
                row = CustomerServicePrice.objects.create(
                    service=src.service,
                    customer=customer,
                    unit_price=new_price,
                    vat_pct=src.vat_pct,
                    valid_from=valid_from,
                    valid_to=None,
                    is_active=True,
                )
                results.append(
                    {
                        "source_price": src.id,
                        "service": src.service_id,
                        "old_unit_price": str(src.unit_price),
                        "new_unit_price": str(new_price),
                        "customer_service_price": row.id,
                    }
                )

        return Response(
            {
                "created_count": len(results),
                "valid_from": str(valid_from),
                "results": results,
            },
            status=status.HTTP_201_CREATED,
        )


class CustomerCustomPriceListCreateView(generics.ListCreateAPIView):
    """M5 A — GET/POST at /api/customers/<customer_id>/custom-pricing/.
    PROVIDER-ONLY (no CUSTOMER_USER / STAFF): SA always; CA for own
    company with the customer-price toggle (via
    _enforce_customer_price_policy on writes)."""

    permission_classes = [IsSuperAdminOrCompanyAdmin]
    serializer_class = CustomerCustomPriceSerializer
    pagination_class = UnboundedPagination

    def _get_customer(self):
        customer = get_object_or_404(Customer, pk=self.kwargs["customer_id"])
        inner = IsSuperAdminOrCompanyAdminForCompany()
        if not inner.has_object_permission(self.request, self, customer):
            raise PermissionDenied(detail="Forbidden.")
        return customer

    def get_queryset(self):
        customer = self._get_customer()
        qs = CustomerCustomPrice.objects.filter(
            customer=customer
        ).select_related("customer")
        flag = self.request.query_params.get("is_active")
        if flag is not None:
            lowered = flag.strip().lower()
            if lowered in {"true", "1", "yes", "y"}:
                qs = qs.filter(is_active=True)
            elif lowered in {"false", "0", "no", "n"}:
                qs = qs.filter(is_active=False)
        elif not _include_archived(self.request):
            # Sprint 137 item 2 — archived rows hidden by default, same
            # rule as the contract-price list above. These two lists are
            # merged into ONE table on the pricing page, so "delete" has
            # to mean the same thing on both: a mixed selection that
            # half-vanished and half-stayed would be worse than either.
            qs = qs.filter(is_active=True)
        return qs.order_by("-valid_from", "-id")

    def perform_create(self, serializer):
        customer = self._get_customer()
        _enforce_customer_price_policy(self.request.user, customer)
        # Sprint 123 — a managed_unit (if any) must belong to the SAME
        # provider company as this customer (there is no direct
        # company FK on CustomerCustomPrice; company is customer.company).
        _enforce_same_company_managed_unit(
            serializer.validated_data.get("managed_unit"), customer.company
        )
        _enforce_same_customer_folder(
            serializer.validated_data.get("folder"), customer
        )
        serializer.save(customer=customer)


class CustomerCustomPriceDetailView(generics.RetrieveUpdateDestroyAPIView):
    """M5 A — GET/PATCH/DELETE at
    /api/customers/<customer_id>/custom-pricing/<custom_price_id>/.
    PROVIDER-ONLY. DELETE soft-archives (is_active=False, 204)."""

    permission_classes = [IsSuperAdminOrCompanyAdmin]
    serializer_class = CustomerCustomPriceSerializer

    def _get_customer(self):
        customer = get_object_or_404(Customer, pk=self.kwargs["customer_id"])
        inner = IsSuperAdminOrCompanyAdminForCompany()
        if not inner.has_object_permission(self.request, self, customer):
            raise PermissionDenied(detail="Forbidden.")
        return customer

    def get_object(self):
        customer = self._get_customer()
        return get_object_or_404(
            CustomerCustomPrice,
            pk=self.kwargs["custom_price_id"],
            customer=customer,
        )

    def perform_update(self, serializer):
        _enforce_customer_price_policy(
            self.request.user, serializer.instance.customer
        )
        if "managed_unit" in serializer.validated_data:
            _enforce_same_company_managed_unit(
                serializer.validated_data["managed_unit"],
                serializer.instance.customer.company,
            )
        if "folder" in serializer.validated_data:
            _enforce_same_customer_folder(
                serializer.validated_data["folder"],
                serializer.instance.customer,
            )
        serializer.save()

    def delete(self, request, *args, **kwargs):
        price = self.get_object()
        _enforce_customer_price_policy(request.user, price.customer)
        if price.is_active:
            try:
                audit_context.set_current_reason(
                    "customer_custom_price_soft_archive"
                )
            except Exception:  # pragma: no cover - defensive
                pass
            price.is_active = False
            price.save(update_fields=["is_active", "updated_at"])
        return Response(status=status.HTTP_204_NO_CONTENT)
