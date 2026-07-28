from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.response import Response

from accounts.models import UserRole
from accounts.permissions import (
    IsAuthenticatedAndActive,
    IsSuperAdmin,
    IsSuperAdminOrCompanyAdminForCompany,
)
from accounts.scoping import scope_customers_for
from companies.models import Company, CompanyUserMembership

from .filters import CustomerFilter
from .models import Customer
from .serializers import CustomerSerializer


class CustomerViewSet(viewsets.ModelViewSet):
    serializer_class = CustomerSerializer
    filterset_class = CustomerFilter
    search_fields = ["name", "contact_email", "phone"]
    ordering_fields = ["name", "created_at"]

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
        return (
            scope_customers_for(self.request.user)
            .select_related("company", "building")
            .prefetch_related("building_memberships")
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
