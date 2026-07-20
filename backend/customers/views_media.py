"""RF-1 — customer logo upload / delete / serve.

  GET    /api/customers/<customer_id>/logo/   serve the logo (any active user)
  POST   /api/customers/<customer_id>/logo/   upload  (that customer's CCA OR SA)
  DELETE /api/customers/<customer_id>/logo/   remove  (that customer's CCA OR SA)

Hardcoded write rule: a customer's logo may be set only by that
customer's CUSTOMER_COMPANY_ADMIN (the `is_company_admin` membership
flag) or by SUPER_ADMIN. Serving is open to any active user (the logo is
the customer's inbox avatar, shown broadly). Write gate failure = 403;
missing file on GET = 404 (no existence leak).
"""
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.image_uploads import ImageUploadSerializer
from accounts.models import UserRole
from accounts.permissions import IsAuthenticatedAndActive
from accounts.scoping import scope_customers_for
from audit import context as audit_context
from companies.models import CompanyUserMembership

from .media_urls import customer_contract_pdf_url, customer_logo_url
from .models import Customer, CustomerUserMembership
from .pdf_uploads import PdfUploadSerializer

# Provider-side roles that may VIEW the informational contract PDF (customer
# read is Phase 5). The WRITE gate is narrower — OSIUS admins only.
_PROVIDER_ROLES = (
    UserRole.SUPER_ADMIN,
    UserRole.COMPANY_ADMIN,
    UserRole.BUILDING_MANAGER,
)


def _may_manage_customer_logo(actor, customer: Customer) -> bool:
    if actor.role == UserRole.SUPER_ADMIN:
        return True
    if actor.role == UserRole.CUSTOMER_USER:
        return CustomerUserMembership.objects.filter(
            user=actor, customer=customer, is_company_admin=True
        ).exists()
    return False


def _may_manage_contract_pdf(actor, customer: Customer) -> bool:
    """The contract PDF is a PROVIDER-side billing document: only an OSIUS
    admin may set it — SUPER_ADMIN, or a COMPANY_ADMIN in the customer's own
    provider company. (Mirrors the CustomerViewSet write gate
    `IsSuperAdminOrCompanyAdminForCompany`; NOT the customer's CCA, unlike the
    logo.) Customer users -> 403."""
    if actor.role == UserRole.SUPER_ADMIN:
        return True
    if actor.role == UserRole.COMPANY_ADMIN:
        return CompanyUserMembership.objects.filter(
            user=actor, company_id=customer.company_id
        ).exists()
    return False


def _may_view_contract_pdf(actor, customer: Customer) -> bool:
    """Provider-side view only (customer read is Phase 5): a provider operator
    whose scope contains this customer. Bound to the tenant via
    scope_customers_for so a cross-tenant fetch cannot see it."""
    if actor.role not in _PROVIDER_ROLES:
        return False
    return scope_customers_for(actor).filter(pk=customer.pk).exists()


class CustomerLogoView(APIView):
    permission_classes = [IsAuthenticatedAndActive]
    parser_classes = [MultiPartParser, FormParser]

    def _target(self, customer_id) -> Customer:
        return get_object_or_404(Customer, pk=customer_id)

    def get(self, request, customer_id):
        customer = self._target(customer_id)
        if not customer.logo:
            raise Http404("No logo.")
        return FileResponse(customer.logo.open("rb"))

    def post(self, request, customer_id):
        customer = self._target(customer_id)
        if not _may_manage_customer_logo(request.user, customer):
            return Response(
                {"detail": "You may not change this logo."},
                status=status.HTTP_403_FORBIDDEN,
            )
        serializer = ImageUploadSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        audit_context.set_current_reason("customer_logo_upload")
        if customer.logo:
            customer.logo.delete(save=False)
        customer.logo = serializer.validated_data["file"]
        customer.save(update_fields=["logo"])
        return Response(
            {"logo_url": customer_logo_url(customer, request)},
            status=status.HTTP_200_OK,
        )

    def delete(self, request, customer_id):
        customer = self._target(customer_id)
        if not _may_manage_customer_logo(request.user, customer):
            return Response(
                {"detail": "You may not change this logo."},
                status=status.HTTP_403_FORBIDDEN,
            )
        if customer.logo:
            audit_context.set_current_reason("customer_logo_remove")
            customer.logo.delete(save=False)
            customer.logo = None
            customer.save(update_fields=["logo"])
        return Response(status=status.HTTP_204_NO_CONTENT)


class CustomerContractPdfView(APIView):
    """Invoicing Phase 4a — informational contract PDF (ZERO behavioural
    effect; drives nothing).

      GET    /api/customers/<id>/contract-pdf/  serve   (provider operator in scope)
      POST   /api/customers/<id>/contract-pdf/  upload  (OSIUS admin only)
      DELETE /api/customers/<id>/contract-pdf/  remove  (OSIUS admin only)

    One active PDF, replace-on-reupload (the Phase-1 `contract_pdf` field
    already carries a uuid path per upload, so no version history). Mirrors
    `CustomerLogoView`; the write gate is narrower (OSIUS admins, not the
    customer's CCA) and the serve is provider-only (customer read is Phase 5).
    A missing file / out-of-scope customer both 404 (no existence leak)."""

    permission_classes = [IsAuthenticatedAndActive]
    parser_classes = [MultiPartParser, FormParser]

    def _target(self, customer_id) -> Customer:
        return get_object_or_404(Customer, pk=customer_id)

    def get(self, request, customer_id):
        customer = self._target(customer_id)
        if not _may_view_contract_pdf(request.user, customer):
            raise Http404("No contract PDF.")
        if not customer.contract_pdf:
            raise Http404("No contract PDF.")
        return FileResponse(
            customer.contract_pdf.open("rb"), content_type="application/pdf"
        )

    def post(self, request, customer_id):
        customer = self._target(customer_id)
        if not _may_manage_contract_pdf(request.user, customer):
            return Response(
                {"detail": "You may not change this contract PDF."},
                status=status.HTTP_403_FORBIDDEN,
            )
        serializer = PdfUploadSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        audit_context.set_current_reason("customer_contract_pdf_upload")
        if customer.contract_pdf:
            customer.contract_pdf.delete(save=False)
        customer.contract_pdf = serializer.validated_data["file"]
        customer.save(update_fields=["contract_pdf"])
        return Response(
            {"contract_pdf_url": customer_contract_pdf_url(customer, request)},
            status=status.HTTP_200_OK,
        )

    def delete(self, request, customer_id):
        customer = self._target(customer_id)
        if not _may_manage_contract_pdf(request.user, customer):
            return Response(
                {"detail": "You may not change this contract PDF."},
                status=status.HTTP_403_FORBIDDEN,
            )
        if customer.contract_pdf:
            audit_context.set_current_reason("customer_contract_pdf_remove")
            customer.contract_pdf.delete(save=False)
            customer.contract_pdf = None
            customer.save(update_fields=["contract_pdf"])
        return Response(status=status.HTTP_204_NO_CONTENT)
