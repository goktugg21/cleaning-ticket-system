"""
Sprint 14B — Permission Matrix endpoint.

GET /api/permissions/matrix/?target_type=<...>&target_id=<int>

A read-only, additive endpoint that returns a tri-state permission
matrix for a single grant row — either a `CustomerUserBuildingAccess`
(target_type=customer_building_access) or a `BuildingManagerAssignment`
(target_type=building_manager_assignment).

This endpoint writes NOTHING — no AuditLog, no mutation. It is a pure
read over the live resolvers via `accounts.permission_matrix`.

Object scope is enforced as 404 (never 403) on out-of-scope targets so
the endpoint never leaks the existence of rows the caller may not see.
"""
from __future__ import annotations

from typing import Optional

from django.utils import timezone
from rest_framework import status
from rest_framework.permissions import BasePermission
from rest_framework.response import Response
from rest_framework.views import APIView

from buildings.models import BuildingManagerAssignment
from companies.models import CompanyUserMembership
from customers.models import CustomerUserBuildingAccess

from .models import UserRole
from .permission_matrix import (
    build_bm_matrix_rows,
    build_customer_matrix_rows,
)


_CONSUMER_ROLES = frozenset(
    {
        UserRole.SUPER_ADMIN,
        UserRole.COMPANY_ADMIN,
        UserRole.BUILDING_MANAGER,
    }
)

TARGET_CUSTOMER = "customer_building_access"
TARGET_BM = "building_manager_assignment"
_VALID_TARGET_TYPES = frozenset({TARGET_CUSTOMER, TARGET_BM})


class IsPermissionMatrixConsumer(BasePermission):
    """Authenticated + active + role in {SA, CA, BM}. STAFF and
    CUSTOMER_USER are refused at the class gate (403)."""

    def has_permission(self, request, view) -> bool:
        user = request.user
        if user is None or not user.is_authenticated:
            return False
        if not user.is_active:
            return False
        return user.role in _CONSUMER_ROLES


class PermissionMatrixView(APIView):
    permission_classes = [IsPermissionMatrixConsumer]
    http_method_names = ["get", "head", "options"]

    def get(self, request, *args, **kwargs):
        target_type = request.query_params.get("target_type")
        if not target_type:
            return Response(
                {
                    "detail": "target_type is required.",
                    "code": "target_type_required",
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
        if target_type not in _VALID_TARGET_TYPES:
            return Response(
                {
                    "detail": "target_type is invalid.",
                    "code": "target_type_invalid",
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        target_id_raw = request.query_params.get("target_id")
        try:
            target_id = int(target_id_raw)
        except (TypeError, ValueError):
            return Response(
                {
                    "detail": "target_id must be an integer.",
                    "code": "target_id_invalid",
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        if target_type == TARGET_CUSTOMER:
            return self._customer_matrix(request, target_id)
        return self._bm_matrix(request, target_id)

    # ------------------------------------------------------------------
    # customer_building_access
    # ------------------------------------------------------------------
    def _customer_matrix(self, request, target_id: int):
        access = (
            CustomerUserBuildingAccess.objects.select_related(
                "membership__customer__company",
                "building",
                "membership__user",
            )
            .filter(pk=target_id)
            .first()
        )
        if access is None:
            return self._not_found()

        customer = access.membership.customer
        company = customer.company
        if not self._actor_in_customer_scope(request.user, access, company):
            return self._not_found()

        rows = build_customer_matrix_rows(access, request.user)
        target_user = access.membership.user
        building = access.building
        return self._build_response(
            request,
            target_type=TARGET_CUSTOMER,
            target_id=access.id,
            target_user=target_user,
            building=building,
            customer=customer,
            company=company,
            rows=rows,
        )

    def _actor_in_customer_scope(self, actor, access, company) -> bool:
        if actor.role == UserRole.SUPER_ADMIN:
            return True
        if actor.role == UserRole.COMPANY_ADMIN:
            return CompanyUserMembership.objects.filter(
                user=actor, company_id=company.id
            ).exists()
        # BUILDING_MANAGER: must hold an assignment on the access building.
        return BuildingManagerAssignment.objects.filter(
            user=actor, building_id=access.building_id
        ).exists()

    # ------------------------------------------------------------------
    # building_manager_assignment
    # ------------------------------------------------------------------
    def _bm_matrix(self, request, target_id: int):
        assignment = (
            BuildingManagerAssignment.objects.select_related(
                "building__company",
                "user",
            )
            .filter(pk=target_id)
            .first()
        )
        if assignment is None:
            return self._not_found()

        company = assignment.building.company
        if not self._actor_in_bm_scope(request.user, assignment, company):
            return self._not_found()

        rows = build_bm_matrix_rows(assignment, request.user)
        return self._build_response(
            request,
            target_type=TARGET_BM,
            target_id=assignment.id,
            target_user=assignment.user,
            building=assignment.building,
            customer=None,
            company=company,
            rows=rows,
        )

    def _actor_in_bm_scope(self, actor, assignment, company) -> bool:
        if actor.role == UserRole.SUPER_ADMIN:
            return True
        if actor.role == UserRole.COMPANY_ADMIN:
            return CompanyUserMembership.objects.filter(
                user=actor, company_id=company.id
            ).exists()
        # BUILDING_MANAGER: must hold an assignment on the same building.
        return BuildingManagerAssignment.objects.filter(
            user=actor, building_id=assignment.building_id
        ).exists()

    # ------------------------------------------------------------------
    # shared response shaping
    # ------------------------------------------------------------------
    def _build_response(
        self,
        request,
        *,
        target_type: str,
        target_id: int,
        target_user,
        building,
        customer,
        company,
        rows: list[dict],
    ):
        grantable_keys = [r["key"] for r in rows if r["grantable"]]
        read_only_keys = [r["key"] for r in rows if r["read_only"]]
        policy_denied_keys = [r["key"] for r in rows if r["policy_denied"]]

        payload = {
            "target": {
                "type": target_type,
                "id": target_id,
                "user": {
                    "id": target_user.id,
                    "email": target_user.email,
                    "full_name": target_user.full_name,
                    "role": target_user.role,
                },
                "building": {
                    "id": building.id,
                    "name": building.name,
                },
                "customer": (
                    {"id": customer.id, "name": customer.name}
                    if customer is not None
                    else None
                ),
                "company": (
                    {"id": company.id, "name": company.name}
                    if company is not None
                    else None
                ),
            },
            "actor": {
                "id": request.user.id,
                "role": request.user.role,
            },
            "permissions": rows,
            "grantable_keys": grantable_keys,
            "read_only_keys": read_only_keys,
            "policy_denied_keys": policy_denied_keys,
            "generated_at": timezone.now().isoformat(),
        }
        return Response(payload, status=status.HTTP_200_OK)

    def _not_found(self):
        return Response(
            {"detail": "Not found.", "code": "target_not_found"},
            status=status.HTTP_404_NOT_FOUND,
        )
