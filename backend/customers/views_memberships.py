from django.shortcuts import get_object_or_404
from rest_framework import generics, status
from rest_framework.response import Response

from accounts.models import User, UserRole
from accounts.permissions import IsSuperAdminOrCompanyAdminForCompany
from config.pagination import UnboundedPagination

from .models import Customer, CustomerUserMembership
from .serializers_memberships import CustomerUserMembershipSerializer


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
                {"user_id": "User must have role CUSTOMER_USER."},
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
        deleted, _ = CustomerUserMembership.objects.filter(
            customer=customer, user_id=user_id
        ).delete()
        if deleted == 0:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        return Response(status=status.HTTP_204_NO_CONTENT)
