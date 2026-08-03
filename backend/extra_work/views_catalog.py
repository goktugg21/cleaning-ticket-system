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

from django.db import IntegrityError, transaction
from django.db.models import Count, Exists, OuterRef, ProtectedError, Q
from rest_framework import generics, serializers, status
from rest_framework.exceptions import NotFound, PermissionDenied
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
    filter_managed_units_for,
    filter_services_for,
    scope_company_ids_for_catalog,
)
from .models import (
    CustomerServicePrice,
    ManagedUnit,
    Service,
    ServiceCategory,
)
from .serializers_catalog import (
    ManagedUnitSerializer,
    ServiceCategorySerializer,
    ServiceSerializer,
)


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
# Sprint 123 — managed-unit catalog.
ERR_MANAGED_UNIT_LABEL_NOT_UNIQUE = "managed_unit_label_not_unique"
ERR_MANAGED_UNIT_COMPANY_MISMATCH = "managed_unit_company_mismatch"


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


def _enforce_same_company_managed_unit(managed_unit, company):
    """Sprint 123 — a `Service` / `CustomerCustomPrice` row's
    `managed_unit` (when set) must belong to the SAME provider company
    as the row itself. Checked here (in the view, after `company` is
    resolved) rather than in the serializer's `validate()`, because a
    COMPANY_ADMIN's Service create may omit `company` entirely and have
    it defaulted by `_resolve_catalog_create_company` AFTER validate()
    already ran — the serializer cannot know the target company yet at
    that point. Raises HTTP 400 (not 403 — this is a data-integrity
    rule, not a permission boundary) with a stable code so a UI can
    show something more specific than a generic error.
    """
    if managed_unit is None or company is None:
        return
    if managed_unit.company_id != company.id:
        raise serializers.ValidationError(
            {
                "managed_unit": [
                    serializers.ErrorDetail(
                        "This managed unit belongs to a different "
                        "provider company.",
                        code=ERR_MANAGED_UNIT_COMPANY_MISMATCH,
                    )
                ]
            }
        )


def _annotate_category_service_counts(queryset, user):
    """Sprint 138 §2 — annotate each category with how many services it
    holds, so the UI can decide which actions to OFFER instead of
    offering all of them and letting the operator find out which ones
    400 (`Service.category` is PROTECT: a non-empty category can never
    be deleted).

    ONE aggregate per column for the whole page — no per-row query.

    The counts are SCOPED to the catalog the actor can actually see
    (`scope_company_ids_for_catalog`): categories are global but
    services are company-scoped, so an unscoped count would tell a
    COMPANY_ADMIN a category holds services they cannot see and cannot
    act on. SUPER_ADMIN — the only role permitted to archive or delete
    a category at all — has scope `None` and therefore always sees the
    COMPLETE count, which is the number the PROTECT rule actually
    depends on.
    """
    scope = scope_company_ids_for_catalog(user)
    service_filter = Q()
    active_filter = Q(services__is_active=True)
    if scope is not None:
        scoped = Q(services__company_id__in=scope)
        service_filter &= scoped
        active_filter &= scoped
    return queryset.annotate(
        annotated_service_count=Count(
            "services",
            filter=service_filter if scope is not None else None,
            distinct=True,
        ),
        annotated_active_service_count=Count(
            "services", filter=active_filter, distinct=True
        ),
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
        qs = _annotate_category_service_counts(
            ServiceCategory.objects.all(), self.request.user
        )
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
            self.request.user,
            _annotate_category_service_counts(
                ServiceCategory.objects.all(), self.request.user
            ),
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
                    # Sprint 138 §2c — BACKSTOP only: the UI offers
                    # Delete on a category exactly when its
                    # `service_count` is 0, and offers Archive /
                    # Move-services-out otherwise.
                    "detail": (
                        "Cannot delete a category that still has "
                        "services attached. Move its services to "
                        "another category first (they cannot be left "
                        "without one), or archive the category — which "
                        "also deactivates the services inside it."
                    ),
                    "code": "category_protected",
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
        return Response(status=status.HTTP_204_NO_CONTENT)


class ServiceCategoryArchiveView(APIView):
    """Sprint 138 §2a — archive a category TOGETHER WITH its services,
    or unarchive the category alone.

        POST /api/services/categories/<id>/archive/
        POST /api/services/categories/<id>/unarchive/

    Why the archive cascades: `Service.category` is NOT nullable, so a
    service cannot exist outside a category. Archiving a category while
    leaving its services active would strand active, orderable services
    inside a category the operator has declared retired — visible
    nowhere in the category UI, still live in every picker. Cascading is
    the honest reading of "archive this category".

    Why the UNarchive does NOT cascade: reactivating a service is a
    deliberate act with its own consequences (it becomes orderable
    again, and it reappears in every cart picker). Restoring a category
    is not a statement about which of its services should come back, so
    the services stay archived and are reactivated one at a time via the
    Service PATCH surface (§1's Activeren). The response returns the
    count that stayed archived so the UI can say so rather than let the
    operator assume everything came back.

    SUPER_ADMIN only, same rule as every other category write
    (`_enforce_category_super_admin_only`): categories are GLOBAL, so
    one provider admin archiving a category would deactivate services
    belonging to every other provider company on the platform. That
    cross-company reach is exactly why this stays SA-only, and why the
    response reports how many companies were touched.

    Per-row `save()` inside one `transaction.atomic()` rather than a
    bulk `.update()`: `Service` and `ServiceCategory` are both
    registered for full-CRUD generic audit, and a queryset `.update()`
    fires no `post_save`, so it would silently write nothing to
    `AuditLog` (RBAC H-10). Mirrors `ServiceBulkRaiseView`.
    """

    permission_classes = [IsSuperAdminOrCompanyAdmin]

    def _get_category(self, category_id, user):
        try:
            return filter_categories_for(
                user, ServiceCategory.objects.all()
            ).get(pk=category_id)
        except ServiceCategory.DoesNotExist:
            raise NotFound(detail="Service category not found.")

    def post(self, request, category_id, *args, **kwargs):
        category = self._get_category(category_id, request.user)
        _enforce_category_super_admin_only(request.user)

        archiving = self.archive

        with transaction.atomic():
            audit_context.set_current_reason(
                "service_category_archive_cascade"
                if archiving
                else "service_category_unarchive"
            )
            touched_services = 0
            affected_company_ids = set()
            if archiving:
                # Only the services that are still ACTIVE need writing;
                # re-saving an already-archived row would add a no-op
                # audit entry for a change that did not happen.
                for service in category.services.filter(
                    is_active=True
                ).select_related("company"):
                    service.is_active = False
                    service.save(update_fields=["is_active", "updated_at"])
                    touched_services += 1
                    affected_company_ids.add(service.company_id)
            if category.is_active == archiving:
                category.is_active = not archiving
                category.save(update_fields=["is_active", "updated_at"])

        payload = ServiceCategorySerializer(
            _annotate_category_service_counts(
                ServiceCategory.objects.filter(pk=category.pk), request.user
            ).first()
        ).data
        return Response(
            {
                "category": payload,
                # Named for what actually happened, not for what was
                # requested: an unarchive deactivates nothing.
                "deactivated_service_count": touched_services,
                "affected_company_count": len(affected_company_ids),
                # On unarchive: how many services stayed archived, so
                # the UI can say "the category is back, its services are
                # not" instead of implying a full restore.
                "still_archived_service_count": (
                    0
                    if archiving
                    else category.services.filter(is_active=False).count()
                ),
            },
            status=status.HTTP_200_OK,
        )


class ServiceCategoryArchiveActionView(ServiceCategoryArchiveView):
    archive = True


class ServiceCategoryUnarchiveActionView(ServiceCategoryArchiveView):
    archive = False


def _resolve_catalog_create_company(user, supplied_company):
    """Sprint 3B — pick the `company` for a new catalog row (a Service;
    Sprint 123 reuses this verbatim for a new ManagedUnit — the
    resolution rule is generic to "a provider-company-scoped catalog
    row", not specific to Service).

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
        qs = (
            Service.objects.select_related("category", "company")
            # Sprint 138 §1 — one EXISTS subquery for the whole page,
            # NOT a per-row query. Deliberately unfiltered on
            # `is_active`: an ARCHIVED CustomerServicePrice still
            # PROTECTs its Service, so a service priced only by
            # archived rows must still report True or the UI would
            # offer a Delete that always 400s.
            .annotate(
                annotated_has_price_rows=Exists(
                    CustomerServicePrice.objects.filter(
                        service=OuterRef("pk")
                    )
                )
            )
            .all()
        )
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
        target_company = _resolve_catalog_create_company(
            self.request.user,
            serializer.validated_data.get("company"),
        )
        _enforce_catalog_management(self.request.user, target_company)
        # Sprint 123 — a managed_unit (if any) must belong to this same
        # company; checked here because `target_company` is only known
        # AFTER resolution, which the serializer's validate() cannot see.
        _enforce_same_company_managed_unit(
            serializer.validated_data.get("managed_unit"), target_company
        )
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
        qs = (
            Service.objects.select_related("category", "company")
            # Sprint 138 §1 — same annotation as the list view so a
            # single-service GET/PATCH response carries the same
            # `has_price_rows` the list does.
            .annotate(
                annotated_has_price_rows=Exists(
                    CustomerServicePrice.objects.filter(
                        service=OuterRef("pk")
                    )
                )
            )
            .all()
        )
        return filter_services_for(self.request.user, qs)

    def perform_update(self, serializer):
        # company is read-only on UPDATE — the row's existing
        # company governs the policy check.
        _enforce_catalog_management(
            self.request.user, serializer.instance.company
        )
        # Sprint 123 — managed_unit (if changing) must stay within the
        # row's own (immutable-on-update) company.
        if "managed_unit" in serializer.validated_data:
            _enforce_same_company_managed_unit(
                serializer.validated_data["managed_unit"],
                serializer.instance.company,
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
                    # Sprint 138 §1 — server-side BACKSTOP only: the UI
                    # no longer offers Delete on a referenced service
                    # (`has_price_rows`), so reaching this is a
                    # direct-API call or a stale page.
                    #
                    # The old wording sent the operator to "delete the
                    # contract prices first", which is a dead end:
                    # deleting a price ARCHIVES it (Sprint 137 item 2 —
                    # `ExtraWorkRequestItem.snapshot_customer_service_
                    # price` is a live FK), and an archived price still
                    # PROTECTs its service. Following that advice
                    # produced exactly the loop the operator hit.
                    "detail": (
                        "Cannot delete a service that has customer "
                        "contract prices. ARCHIVED prices also block "
                        "deletion — deleting a price archives it rather "
                        "than destroying it, because shipped Extra Work "
                        "lines still reference it. Deactivate the "
                        "service instead (is_active=false); it then "
                        "stops appearing in pickers while its history "
                        "stays intact."
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


class ManagedUnitListCreateView(generics.ListCreateAPIView):
    """Sprint 123 — GET (list) + POST (create) at
    /api/services/units/.

    Unlike Service / ServiceCategory, this endpoint is
    PROVIDER-OPERATOR-ONLY on GET too — a managed unit has no
    customer-facing consumer (it backs the OTHER-unit picker on the
    Service and CustomerCustomPrice admin forms only; ProposalLine
    stays plain free text). `IsSuperAdminOrCompanyAdmin` gates both
    methods; `filter_managed_units_for` + `_enforce_catalog_management`
    reuse the exact Service scoping/policy rules (same permission key,
    per the sprint brief — no new one invented).

    `?is_active=true|false` filters the list (the frontend picker
    requests `is_active=true`; the admin management surface requests
    the unfiltered list so archived rows stay visible/reactivatable).
    `?company=<id>` lets a SUPER_ADMIN narrow to one company's units
    (mirrors Service's `?category=` filter shape).
    """

    serializer_class = ManagedUnitSerializer
    permission_classes = [IsSuperAdminOrCompanyAdmin]
    pagination_class = UnboundedPagination

    def get_queryset(self):
        qs = ManagedUnit.objects.select_related("company").all()
        company_param = self.request.query_params.get("company")
        if company_param:
            try:
                qs = qs.filter(company_id=int(company_param))
            except (TypeError, ValueError):
                qs = qs.none()
        flag = _parse_bool_param(self.request.query_params.get("is_active"))
        if flag is not None:
            qs = qs.filter(is_active=flag)
        qs = filter_managed_units_for(self.request.user, qs)
        return qs.order_by("company__name", "label", "id")

    def perform_create(self, serializer):
        target_company = _resolve_catalog_create_company(
            self.request.user,
            serializer.validated_data.get("company"),
        )
        _enforce_catalog_management(self.request.user, target_company)
        try:
            # The inner atomic() is required, not decorative: without a
            # savepoint boundary here, an IntegrityError leaves the
            # surrounding transaction (the test's, or a real request's)
            # unusable at the DB level even though Python catches the
            # exception -- Postgres refuses any further command in a
            # transaction after an error until a ROLLBACK happens.
            with transaction.atomic():
                serializer.save(company=target_company)
        except IntegrityError:
            # Backstop for a race between the serializer's own
            # (non-atomic) pre-check and the DB's UniqueConstraint.
            raise serializers.ValidationError(
                {
                    "label": [
                        serializers.ErrorDetail(
                            "A unit with this name already exists for "
                            "this company.",
                            code=ERR_MANAGED_UNIT_LABEL_NOT_UNIQUE,
                        )
                    ]
                }
            )


class ManagedUnitDetailView(generics.RetrieveUpdateDestroyAPIView):
    """Sprint 123 — GET / PATCH / DELETE at
    /api/services/units/<int:unit_id>/. Provider-operator-only on
    every method (see `ManagedUnitListCreateView`).

    DELETE is a real hard delete, same shape as `ServiceDetailView`'s:
    a unit still referenced by any Service / CustomerCustomPrice row is
    PROTECTed at the DB layer, which raises `ProtectedError`, caught
    below and turned into a clean 400 telling the operator to archive
    (`is_active=false`) instead — archiving never fails, since it does
    not touch the FK.
    """

    serializer_class = ManagedUnitSerializer
    permission_classes = [IsSuperAdminOrCompanyAdmin]
    lookup_url_kwarg = "unit_id"

    def get_queryset(self):
        qs = ManagedUnit.objects.select_related("company").all()
        return filter_managed_units_for(self.request.user, qs)

    def perform_update(self, serializer):
        _enforce_catalog_management(
            self.request.user, serializer.instance.company
        )
        try:
            # See ManagedUnitListCreateView.perform_create for why this
            # inner atomic() is load-bearing, not decorative.
            with transaction.atomic():
                serializer.save()
        except IntegrityError:
            raise serializers.ValidationError(
                {
                    "label": [
                        serializers.ErrorDetail(
                            "A unit with this name already exists for "
                            "this company.",
                            code=ERR_MANAGED_UNIT_LABEL_NOT_UNIQUE,
                        )
                    ]
                }
            )

    def delete(self, request, *args, **kwargs):
        instance = self.get_object()
        _enforce_catalog_management(request.user, instance.company)
        try:
            instance.delete()
        except ProtectedError:
            return Response(
                {
                    "detail": (
                        "Cannot delete a unit that is still in use. "
                        "Archive it (is_active=false) instead."
                    ),
                    "code": "managed_unit_protected",
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
        return Response(status=status.HTTP_204_NO_CONTENT)
