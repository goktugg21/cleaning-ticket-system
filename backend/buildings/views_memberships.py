from django.shortcuts import get_object_or_404
from rest_framework import generics, status
from rest_framework.response import Response

from accounts.models import User, UserRole
from accounts.permissions import IsSuperAdminOrCompanyAdminForCompany
from config.pagination import UnboundedPagination

from .models import Building, BuildingManagerAssignment
from .serializers_memberships import BuildingManagerAssignmentSerializer


class BuildingManagerListCreateView(generics.ListCreateAPIView):
    permission_classes = [IsSuperAdminOrCompanyAdminForCompany]
    serializer_class = BuildingManagerAssignmentSerializer
    pagination_class = UnboundedPagination

    def _get_building(self):
        building = get_object_or_404(Building, pk=self.kwargs["building_id"])
        self.check_object_permissions(self.request, building)
        return building

    def get_queryset(self):
        building = self._get_building()
        return BuildingManagerAssignment.objects.filter(building=building).select_related("user")

    def create(self, request, *args, **kwargs):
        building = self._get_building()
        user_id = request.data.get("user_id")
        if not user_id:
            return Response(
                {"user_id": "This field is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        user = get_object_or_404(
            User, pk=user_id, is_active=True, deleted_at__isnull=True
        )
        if user.role != UserRole.BUILDING_MANAGER:
            return Response(
                {"user_id": "User must have role BUILDING_MANAGER."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        membership, created = BuildingManagerAssignment.objects.get_or_create(
            building=building, user=user
        )
        return Response(
            BuildingManagerAssignmentSerializer(membership).data,
            status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
        )


class BuildingManagerDeleteView(generics.GenericAPIView):
    permission_classes = [IsSuperAdminOrCompanyAdminForCompany]

    def delete(self, request, building_id, user_id):
        building = get_object_or_404(Building, pk=building_id)
        self.check_object_permissions(request, building)
        deleted, _ = BuildingManagerAssignment.objects.filter(
            building=building, user_id=user_id
        ).delete()
        if deleted == 0:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        return Response(status=status.HTTP_204_NO_CONTENT)
