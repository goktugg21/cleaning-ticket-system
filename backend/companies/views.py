from django.db import transaction
from django.utils.text import slugify
from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from audit import context as audit_context

from accounts.permissions import (
    IsAuthenticatedAndActive,
    IsSuperAdmin,
    IsSuperAdminOrCompanyAdminForCompany,
)
from accounts.scoping import scope_companies_for

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
    # Sprint 157 §3 — sortable columns, extended ADDITIVELY exactly as
    # Sprint 153 did for customers. `is_active` sorts the Status column;
    # `slug` is the other column the list renders. Nothing is removed, so
    # every existing `?ordering=` caller keeps working.
    ordering_fields = ["name", "slug", "is_active", "created_at"]

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


# ---------------------------------------------------------------------------
# Sprint 157 §3 — bulk deactivate
# ---------------------------------------------------------------------------

ERR_BULK_DEACTIVATE_COMPANY_INVALID = "bulk_deactivate_company_invalid"
_BULK_DEACTIVATE_COMPANY_INVALID_MESSAGE = (
    "One or more of the selected companies could not be resolved. "
    "Nothing was changed."
)


class _CompanyBulkDeactivateInputSerializer(serializers.Serializer):
    companies = serializers.ListField(
        child=serializers.IntegerField(min_value=1),
        allow_empty=False,
    )


class CompanyBulkDeactivateView(APIView):
    """POST /api/companies/bulk-deactivate/  Body: {"companies": [id,...]}

    Mirrors `customers.views.CustomerBulkDeactivateView` exactly, which
    is what §3 asked for — same all-or-nothing resolution, same constant
    rejection body, same real `save()`.

    ALL-OR-NOTHING: every id resolved through the caller's scope BEFORE
    anything is written; one unresolvable id rejects the batch with zero
    writes and the SAME body whether it belongs to another tenant or to
    nobody (H-1).

    SUPER_ADMIN only, unlike the customer version. `Company` IS the
    tenant: letting a COMPANY_ADMIN deactivate companies would let them
    switch off their own tenant, and the single-row lifecycle already
    reserves reactivation for a SUPER_ADMIN. Deactivating is
    `is_active = False` — a company is never hard-deleted, because every
    building, customer and ticket under it references it.

    A real `save()` per row, never a queryset `.update()`: `.update()`
    fires no signals and would write no AuditLog (H-10). `Company` is in
    the audit full-CRUD trio with generic field introspection, so the
    save audits itself with no `audit/signals.py` change.
    """

    permission_classes = [IsSuperAdmin]

    def post(self, request, *args, **kwargs):
        payload = _CompanyBulkDeactivateInputSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        # De-dup, preserving order: a repeated id is one company, not an
        # error.
        requested_ids = list(dict.fromkeys(payload.validated_data["companies"]))

        scoped = {
            company.id: company
            for company in scope_companies_for(request.user).filter(
                id__in=requested_ids
            )
        }
        if len(scoped) != len(requested_ids):
            raise ValidationError(
                {
                    "companies": [
                        serializers.ErrorDetail(
                            _BULK_DEACTIVATE_COMPANY_INVALID_MESSAGE,
                            code=ERR_BULK_DEACTIVATE_COMPANY_INVALID,
                        )
                    ]
                }
            )

        try:
            audit_context.set_current_reason("company_bulk_deactivate")
        except Exception:  # pragma: no cover - defensive
            pass

        deactivated = 0
        with transaction.atomic():
            for company_id in requested_ids:
                company = scoped[company_id]
                if not company.is_active:
                    # Already inactive: no write, no audit row, not
                    # counted.
                    continue
                company.is_active = False
                company.save(update_fields=["is_active"])
                deactivated += 1

        return Response({"deactivated": deactivated}, status=status.HTTP_200_OK)
