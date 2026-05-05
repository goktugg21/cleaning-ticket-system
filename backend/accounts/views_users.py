from django.db.models import Q
from django.shortcuts import get_object_or_404
from rest_framework import filters, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from buildings.models import BuildingManagerAssignment
from companies.models import CompanyUserMembership
from customers.models import CustomerUserMembership

from .models import User, UserRole
from .permissions import CanManageUser, IsSuperAdmin
from .serializers_users import (
    UserDetailSerializer,
    UserListSerializer,
    UserUpdateSerializer,
)


class UserViewSet(viewsets.ModelViewSet):
    permission_classes = [CanManageUser]
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ["email", "full_name"]
    ordering_fields = ["email", "full_name", "role", "is_active"]
    ordering = ["email"]
    http_method_names = ["get", "patch", "delete", "post", "head", "options"]
    # POST is rejected with 405 except for the `reactivate` detail action;
    # users come into the system through the invitation flow only.

    def get_queryset(self):
        actor = self.request.user
        is_active_param = self.request.query_params.get("is_active")
        if is_active_param is not None and is_active_param.lower() == "false":
            qs = User.objects.filter(is_active=False)
        else:
            qs = User.objects.filter(is_active=True, deleted_at__isnull=True)

        if actor.role == UserRole.SUPER_ADMIN:
            base = qs
        elif actor.role == UserRole.COMPANY_ADMIN:
            actor_company_ids = list(
                CompanyUserMembership.objects.filter(user=actor).values_list(
                    "company_id", flat=True
                )
            )
            if not actor_company_ids:
                return User.objects.none()
            in_scope_user_ids = (
                CompanyUserMembership.objects.filter(
                    company_id__in=actor_company_ids
                ).values_list("user_id", flat=True)
            )
            in_scope_user_ids = set(in_scope_user_ids).union(
                BuildingManagerAssignment.objects.filter(
                    building__company_id__in=actor_company_ids
                ).values_list("user_id", flat=True)
            )
            in_scope_user_ids = in_scope_user_ids.union(
                CustomerUserMembership.objects.filter(
                    customer__company_id__in=actor_company_ids
                ).values_list("user_id", flat=True)
            )
            base = qs.filter(id__in=in_scope_user_ids)
        else:
            return User.objects.none()

        role_filter = self.request.query_params.get("role")
        if role_filter:
            roles = [r.strip() for r in role_filter.split(",") if r.strip()]
            base = base.filter(role__in=roles)
        return base.order_by(*self.ordering)

    def get_serializer_class(self):
        if self.action == "list":
            return UserListSerializer
        if self.action == "retrieve":
            return UserDetailSerializer
        return UserUpdateSerializer

    def create(self, request, *args, **kwargs):
        return Response(
            {"detail": "Create users via the invitation flow at /api/auth/invitations/."},
            status=status.HTTP_405_METHOD_NOT_ALLOWED,
        )

    def perform_destroy(self, instance):
        instance.soft_delete(deleted_by=self.request.user)

    @action(detail=True, methods=["post"], permission_classes=[IsSuperAdmin])
    def reactivate(self, request, pk=None):
        user = get_object_or_404(User, pk=pk)
        user.is_active = True
        user.deleted_at = None
        user.deleted_by = None
        user.save(update_fields=["is_active", "deleted_at", "deleted_by"])
        return Response(UserDetailSerializer(user).data, status=status.HTTP_200_OK)
