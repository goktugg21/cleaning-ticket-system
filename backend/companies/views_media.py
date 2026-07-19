"""RF-1 — provider company logo upload / delete / serve.

  GET    /api/companies/<company_id>/logo/   serve the logo (any active user)
  POST   /api/companies/<company_id>/logo/   upload  (that company's CA OR SA)
  DELETE /api/companies/<company_id>/logo/   remove  (that company's CA OR SA)

Hardcoded write rule: the provider company logo may be set only by a
COMPANY_ADMIN of that company (a CompanyUserMembership row) or by
SUPER_ADMIN. Serving is open to any active user. Write gate failure =
403; missing file on GET = 404.
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

from .media_urls import company_logo_url
from .models import Company, CompanyUserMembership


def _may_manage_company_logo(actor, company: Company) -> bool:
    if actor.role == UserRole.SUPER_ADMIN:
        return True
    if actor.role == UserRole.COMPANY_ADMIN:
        return CompanyUserMembership.objects.filter(
            user=actor, company=company
        ).exists()
    return False


class CompanyLogoView(APIView):
    permission_classes = [IsAuthenticatedAndActive]
    parser_classes = [MultiPartParser, FormParser]

    def _target(self, company_id) -> Company:
        return get_object_or_404(Company, pk=company_id)

    def get(self, request, company_id):
        company = self._target(company_id)
        if not company.logo:
            raise Http404("No logo.")
        return FileResponse(company.logo.open("rb"))

    def post(self, request, company_id):
        company = self._target(company_id)
        if not _may_manage_company_logo(request.user, company):
            return Response(
                {"detail": "You may not change this logo."},
                status=status.HTTP_403_FORBIDDEN,
            )
        serializer = ImageUploadSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        audit_context.set_current_reason("company_logo_upload")
        if company.logo:
            company.logo.delete(save=False)
        company.logo = serializer.validated_data["file"]
        company.save(update_fields=["logo"])
        return Response(
            {"logo_url": company_logo_url(company, request)},
            status=status.HTTP_200_OK,
        )

    def delete(self, request, company_id):
        company = self._target(company_id)
        if not _may_manage_company_logo(request.user, company):
            return Response(
                {"detail": "You may not change this logo."},
                status=status.HTTP_403_FORBIDDEN,
            )
        if company.logo:
            audit_context.set_current_reason("company_logo_remove")
            company.logo.delete(save=False)
            company.logo = None
            company.save(update_fields=["logo"])
        return Response(status=status.HTTP_204_NO_CONTENT)
