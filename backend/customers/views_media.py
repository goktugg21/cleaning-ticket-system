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
from audit import context as audit_context

from .media_urls import customer_logo_url
from .models import Customer, CustomerUserMembership


def _may_manage_customer_logo(actor, customer: Customer) -> bool:
    if actor.role == UserRole.SUPER_ADMIN:
        return True
    if actor.role == UserRole.CUSTOMER_USER:
        return CustomerUserMembership.objects.filter(
            user=actor, customer=customer, is_company_admin=True
        ).exists()
    return False


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
