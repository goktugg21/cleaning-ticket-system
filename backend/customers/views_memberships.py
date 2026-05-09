from django.db import transaction
from django.shortcuts import get_object_or_404
from rest_framework import generics, status
from rest_framework.response import Response

from accounts.models import User, UserRole
from accounts.permissions import IsSuperAdminOrCompanyAdminForCompany
from buildings.models import Building
from config.pagination import UnboundedPagination

from .models import (
    Customer,
    CustomerBuildingMembership,
    CustomerUserBuildingAccess,
    CustomerUserMembership,
)
from .serializers_memberships import (
    CustomerBuildingMembershipSerializer,
    CustomerUserBuildingAccessSerializer,
    CustomerUserMembershipSerializer,
)


class CustomerUserListCreateView(generics.ListCreateAPIView):
    permission_classes = [IsSuperAdminOrCompanyAdminForCompany]
    serializer_class = CustomerUserMembershipSerializer
    pagination_class = UnboundedPagination

    def _get_customer(self):
        customer = get_object_or_404(Customer, pk=self.kwargs["customer_id"])
        self.check_object_permissions(self.request, customer)
        return customer

    def get_queryset(self):
        customer = self._get_customer()
        return (
            CustomerUserMembership.objects.filter(customer=customer)
            .select_related("user")
            .order_by("-created_at")
        )

    def create(self, request, *args, **kwargs):
        customer = self._get_customer()
        user_id = request.data.get("user_id")
        if not user_id:
            return Response(
                {"user_id": "This field is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        user = get_object_or_404(
            User, pk=user_id, is_active=True, deleted_at__isnull=True
        )
        if user.role != UserRole.CUSTOMER_USER:
            return Response(
                {"user_id": "User must have the customer-user role."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        membership, created = CustomerUserMembership.objects.get_or_create(
            customer=customer, user=user
        )
        return Response(
            CustomerUserMembershipSerializer(membership).data,
            status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
        )


class CustomerUserDeleteView(generics.GenericAPIView):
    permission_classes = [IsSuperAdminOrCompanyAdminForCompany]

    def delete(self, request, customer_id, user_id):
        customer = get_object_or_404(Customer, pk=customer_id)
        self.check_object_permissions(request, customer)
        # Sprint 14: deleting the parent membership cascades to all of
        # this user's per-building access rows under this customer
        # (CustomerUserBuildingAccess has on_delete=CASCADE on its
        # membership FK, so the DB does this for us — documented here
        # so reviewers do not look for explicit cleanup).
        deleted, _ = CustomerUserMembership.objects.filter(
            customer=customer, user_id=user_id
        ).delete()
        if deleted == 0:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        return Response(status=status.HTTP_204_NO_CONTENT)


# ===========================================================================
# Sprint 14 — Customer ↔ Buildings (M:N) management
# ===========================================================================


class CustomerBuildingListCreateView(generics.ListCreateAPIView):
    """
    GET  /api/customers/<customer_id>/buildings/      list linked buildings
    POST /api/customers/<customer_id>/buildings/      {building_id} → link
    """

    permission_classes = [IsSuperAdminOrCompanyAdminForCompany]
    serializer_class = CustomerBuildingMembershipSerializer
    pagination_class = UnboundedPagination

    def _get_customer(self):
        customer = get_object_or_404(Customer, pk=self.kwargs["customer_id"])
        self.check_object_permissions(self.request, customer)
        return customer

    def get_queryset(self):
        customer = self._get_customer()
        return (
            CustomerBuildingMembership.objects.filter(customer=customer)
            .select_related("building")
            .order_by("building__name")
        )

    def create(self, request, *args, **kwargs):
        customer = self._get_customer()
        building_id = request.data.get("building_id")
        if not building_id:
            return Response(
                {"building_id": "This field is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        building = get_object_or_404(Building, pk=building_id)

        # Building must belong to the same company as the customer; we
        # do not let an admin link a customer to a building that lives
        # in a different tenant.
        if building.company_id != customer.company_id:
            return Response(
                {"building_id": "Building does not belong to the customer's company."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if not building.is_active:
            return Response(
                {"building_id": "Building is inactive."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        link, created = CustomerBuildingMembership.objects.get_or_create(
            customer=customer, building=building
        )
        return Response(
            CustomerBuildingMembershipSerializer(link).data,
            status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
        )


class CustomerBuildingDeleteView(generics.GenericAPIView):
    """
    DELETE /api/customers/<customer_id>/buildings/<building_id>/

    Sprint 14: removing a customer↔building link also revokes any
    per-user building access rows that pointed at the same
    (customer, building) pair. Without this cascade the access rows
    would be orphaned (still referenced by `building` but no longer
    valid for this customer because the parent link is gone), and
    the scope subquery would still match them.
    """

    permission_classes = [IsSuperAdminOrCompanyAdminForCompany]

    @transaction.atomic
    def delete(self, request, customer_id, building_id):
        customer = get_object_or_404(Customer, pk=customer_id)
        self.check_object_permissions(request, customer)

        link = CustomerBuildingMembership.objects.filter(
            customer=customer, building_id=building_id
        ).first()
        if link is None:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)

        # Cascade-revoke any per-user access for this customer/building.
        CustomerUserBuildingAccess.objects.filter(
            membership__customer=customer, building_id=building_id
        ).delete()

        link.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


# ===========================================================================
# Sprint 14 — per-customer-user building access
# ===========================================================================


class CustomerUserAccessListCreateView(generics.ListCreateAPIView):
    """
    GET  /api/customers/<customer_id>/users/<user_id>/access/
    POST /api/customers/<customer_id>/users/<user_id>/access/  {building_id}
    """

    permission_classes = [IsSuperAdminOrCompanyAdminForCompany]
    serializer_class = CustomerUserBuildingAccessSerializer
    pagination_class = UnboundedPagination

    def _get_membership(self):
        customer = get_object_or_404(Customer, pk=self.kwargs["customer_id"])
        self.check_object_permissions(self.request, customer)
        membership = get_object_or_404(
            CustomerUserMembership,
            customer=customer,
            user_id=self.kwargs["user_id"],
        )
        return membership

    def get_queryset(self):
        membership = self._get_membership()
        return (
            CustomerUserBuildingAccess.objects.filter(membership=membership)
            .select_related("building", "membership__user")
            .order_by("building__name")
        )

    def create(self, request, *args, **kwargs):
        membership = self._get_membership()
        building_id = request.data.get("building_id")
        if not building_id:
            return Response(
                {"building_id": "This field is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        building = get_object_or_404(Building, pk=building_id)

        # Sprint 14 invariant: a customer-user can only be granted
        # access to a building that is currently linked to the parent
        # customer. If the operator wants to add an access for a
        # not-yet-linked building they have to add the customer↔building
        # link first; the admin UI does this in one flow.
        if not CustomerBuildingMembership.objects.filter(
            customer=membership.customer, building=building
        ).exists():
            return Response(
                {"building_id": "Building is not linked to this customer."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if not building.is_active:
            return Response(
                {"building_id": "Building is inactive."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        access, created = CustomerUserBuildingAccess.objects.get_or_create(
            membership=membership, building=building
        )
        return Response(
            CustomerUserBuildingAccessSerializer(access).data,
            status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
        )


class CustomerUserAccessDeleteView(generics.GenericAPIView):
    """
    DELETE /api/customers/<customer_id>/users/<user_id>/access/<building_id>/
    """

    permission_classes = [IsSuperAdminOrCompanyAdminForCompany]

    def delete(self, request, customer_id, user_id, building_id):
        customer = get_object_or_404(Customer, pk=customer_id)
        self.check_object_permissions(request, customer)
        deleted, _ = CustomerUserBuildingAccess.objects.filter(
            membership__customer=customer,
            membership__user_id=user_id,
            building_id=building_id,
        ).delete()
        if deleted == 0:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        return Response(status=status.HTTP_204_NO_CONTENT)
