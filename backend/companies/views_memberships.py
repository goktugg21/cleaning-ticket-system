from django.shortcuts import get_object_or_404
from rest_framework import generics, status
from rest_framework.response import Response

from accounts.models import User, UserRole
from accounts.permissions import IsSuperAdminOrCompanyAdminForCompany

from .models import Company, CompanyUserMembership
from .serializers_memberships import CompanyAdminMembershipSerializer


class CompanyAdminListCreateView(generics.ListCreateAPIView):
    permission_classes = [IsSuperAdminOrCompanyAdminForCompany]
    serializer_class = CompanyAdminMembershipSerializer

    def _get_company(self):
        company = get_object_or_404(Company, pk=self.kwargs["company_id"])
        # Run object permission so a COMPANY_ADMIN of another company gets 403
        # before the row is touched.
        self.check_object_permissions(self.request, company)
        return company

    def get_queryset(self):
        company = self._get_company()
        return CompanyUserMembership.objects.filter(company=company).select_related("user")

    def create(self, request, *args, **kwargs):
        company = self._get_company()
        user_id = request.data.get("user_id")
        if not user_id:
            return Response(
                {"user_id": "This field is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        user = get_object_or_404(
            User, pk=user_id, is_active=True, deleted_at__isnull=True
        )
        if user.role != UserRole.COMPANY_ADMIN:
            return Response(
                {"user_id": "User must have role COMPANY_ADMIN."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        membership, created = CompanyUserMembership.objects.get_or_create(
            company=company, user=user
        )
        return Response(
            CompanyAdminMembershipSerializer(membership).data,
            status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
        )


class CompanyAdminDeleteView(generics.GenericAPIView):
    permission_classes = [IsSuperAdminOrCompanyAdminForCompany]

    def delete(self, request, company_id, user_id):
        company = get_object_or_404(Company, pk=company_id)
        self.check_object_permissions(request, company)
        deleted, _ = CompanyUserMembership.objects.filter(
            company=company, user_id=user_id
        ).delete()
        if deleted == 0:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        return Response(status=status.HTTP_204_NO_CONTENT)
