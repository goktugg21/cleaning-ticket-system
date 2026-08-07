from django.db import transaction
from django.db.models import Count
from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.models import UserRole
from accounts.permissions import (
    IsAuthenticatedAndActive,
    IsSuperAdmin,
    IsSuperAdminOrCompanyAdminForCompany,
)
from accounts.scoping import scope_customers_for
from audit import context as audit_context
from companies.models import Company, CompanyUserMembership

from .filters import CustomerFilter
from .models import Customer
from .serializers import CustomerSerializer


# Sprint 153 §2.3 — one stable code for BOTH bulk-deactivate rejection
# reasons (an id outside the caller's scope, and an id that does not
# exist at all). They MUST be indistinguishable: a distinguishable pair
# is an existence oracle over another tenant's customer ids (H-1, the
# Sprint 142.1 class). That is also why the message below is a
# CONSTANT and never interpolates the offending id.
ERR_BULK_DEACTIVATE_CUSTOMER_INVALID = "bulk_deactivate_customer_invalid"
_BULK_DEACTIVATE_INVALID_MESSAGE = (
    "One or more of the selected customers could not be resolved. "
    "No customers were deactivated."
)


class CustomerViewSet(viewsets.ModelViewSet):
    serializer_class = CustomerSerializer
    filterset_class = CustomerFilter
    search_fields = ["name", "contact_email", "phone"]
    # Sprint 153 §2.1 — the customers list table sorts by header click.
    # `OrderingFilter` is already in DEFAULT_FILTER_BACKENDS, so extending
    # this tuple is the whole change; every entry is a concrete column on
    # Customer (no annotation, no related traversal).
    ordering_fields = ["name", "created_at", "contact_email", "is_active"]

    def get_permissions(self):
        if self.action in ("list", "retrieve"):
            return [IsAuthenticatedAndActive()]
        if self.action == "reactivate":
            return [IsSuperAdmin()]
        return [IsSuperAdminOrCompanyAdminForCompany()]

    def get_queryset(self):
        # Sprint 14 hotfix: prefetch building_memberships so the
        # serializer's linked_building_ids field does not run N
        # extra queries when a list endpoint returns 50+ customers.
        #
        # Sprint 153 §2.2: the three list counts are ANNOTATED here for
        # exactly the same reason. A SerializerMethodField calling
        # `.count()` per row would be 3 extra queries x page_size (75 on
        # a 25-row page) — the N+1 this method already exists to prevent.
        # `distinct=True` is mandatory: three joined Counts in one query
        # multiply each other's row sets otherwise.
        return (
            scope_customers_for(self.request.user)
            .select_related("company", "building")
            .prefetch_related("building_memberships")
            .annotate(
                _linked_building_count=Count("building_memberships", distinct=True),
                _user_count=Count("user_memberships", distinct=True),
                _contact_count=Count("contacts", distinct=True),
            )
        )

    def perform_create(self, serializer):
        company: Company = serializer.validated_data["company"]
        # Sprint 14: legacy `building` is optional now. Existing data
        # still carries it; new consolidated customers can be created
        # with no anchor building and linked to many buildings via the
        # M:N CustomerBuildingMembership endpoint.
        building = serializer.validated_data.get("building")
        actor = self.request.user
        if building is not None and building.company_id != company.id:
            raise ValidationError(
                {"building": "Building does not belong to the selected company."}
            )
        if actor.role == UserRole.COMPANY_ADMIN and not CompanyUserMembership.objects.filter(
            user=actor, company_id=company.id
        ).exists():
            raise PermissionDenied("You can only create customers within your own company.")
        serializer.save()

    def perform_destroy(self, instance):
        instance.is_active = False
        instance.save(update_fields=["is_active"])

    @action(detail=True, methods=["post"], permission_classes=[IsSuperAdmin])
    def reactivate(self, request, pk=None):
        customer = Customer.objects.filter(pk=pk).first()
        if customer is None:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        customer.is_active = True
        customer.save(update_fields=["is_active"])
        return Response(CustomerSerializer(customer).data, status=status.HTTP_200_OK)


class _BulkDeactivateInputSerializer(serializers.Serializer):
    customers = serializers.ListField(
        child=serializers.IntegerField(min_value=1),
        allow_empty=False,
    )


class CustomerBulkDeactivateView(APIView):
    """Sprint 153 §2.3 — deactivate many customers in one request.

    POST /api/customers/bulk-deactivate/
    Body: { "customers": [id, ...] }
    Response: { "deactivated": N }

    Shape mirrors `extra_work.views_pricing.CustomerServicePriceBulkRaise
    View` — the house pattern for a bulk write, and the standing fix for
    N sequential client requests.

    ALL-OR-NOTHING. Every id is resolved through
    `scope_customers_for(request.user)` BEFORE anything is written; one
    unresolvable id rejects the whole batch with zero writes.

    "Deactivate" is `is_active = False`, identical to the single-row
    `perform_destroy`. A Customer is NEVER hard-deleted (invoices and
    extra work PROTECT it).

    Each row goes through a real `save()`, not a queryset `.update()`:
    `.update()` fires no pre_save/post_save, so it writes NO AuditLog row
    (H-10). Customer is in the audit full-CRUD trio with generic field
    introspection, so a real save on `is_active` audits itself with no
    `audit/signals.py` change.
    """

    permission_classes = [IsSuperAdminOrCompanyAdminForCompany]

    def post(self, request, *args, **kwargs):
        payload = _BulkDeactivateInputSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        # De-dup while preserving the caller's order; a repeated id is
        # not an error, it is just one customer.
        requested_ids = list(dict.fromkeys(payload.validated_data["customers"]))

        # Resolve EVERY id through the caller's scope first. This is the
        # only membership test — there is no second, looser path.
        scoped = {
            customer.id: customer
            for customer in scope_customers_for(request.user).filter(
                id__in=requested_ids
            )
        }
        if len(scoped) != len(requested_ids):
            # Same body whether the id belongs to another tenant or to
            # nobody at all. See ERR_BULK_DEACTIVATE_CUSTOMER_INVALID.
            raise ValidationError(
                {
                    "customers": [
                        serializers.ErrorDetail(
                            _BULK_DEACTIVATE_INVALID_MESSAGE,
                            code=ERR_BULK_DEACTIVATE_CUSTOMER_INVALID,
                        )
                    ]
                }
            )

        # Object-level gate, per row. `scope_customers_for` already
        # limits a COMPANY_ADMIN to their own companies; this re-checks
        # through the same class the single-row destroy path uses, so
        # the two cannot drift apart.
        for customer in scoped.values():
            self.check_object_permissions(request, customer)

        try:
            audit_context.set_current_reason("customer_bulk_deactivate")
        except Exception:  # pragma: no cover - defensive
            pass

        deactivated = 0
        with transaction.atomic():
            for customer_id in requested_ids:
                customer = scoped[customer_id]
                if not customer.is_active:
                    # Already inactive: no write, no audit row, not
                    # counted. Reachable only for a SUPER_ADMIN, whose
                    # scope includes inactive customers.
                    continue
                customer.is_active = False
                customer.save(update_fields=["is_active"])
                deactivated += 1

        return Response({"deactivated": deactivated}, status=status.HTTP_200_OK)
