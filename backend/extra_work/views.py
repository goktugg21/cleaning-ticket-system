"""
Sprint 26B — Extra Work HTTP layer.

Endpoints (all under `/api/extra-work/`):

  GET    /api/extra-work/                              list (scoped)
  POST   /api/extra-work/                              create -> REQUESTED
  GET    /api/extra-work/<id>/                         retrieve (scoped, role-aware)
  POST   /api/extra-work/<id>/transition/              drive status transition
  GET    /api/extra-work/<id>/status-history/          read-only audit log
  GET    /api/extra-work/<id>/pricing-items/           list line items
  POST   /api/extra-work/<id>/pricing-items/           create line item (provider)
  PATCH  /api/extra-work/<id>/pricing-items/<lid>/     update line item (provider)
  DELETE /api/extra-work/<id>/pricing-items/<lid>/     delete line item (provider)

Customer users CAN reach list / detail / status-history for rows
in their scope and POST a transition (approve/reject pricing).
Provider users CAN additionally manage pricing line items.
"""
from __future__ import annotations

from django.db.models import Count, Q
from django.shortcuts import get_object_or_404
from rest_framework import generics, mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from accounts.models import UserRole
from accounts.permissions import IsAuthenticatedAndActive
from accounts.permissions_v2 import user_has_osius_permission

from .models import (
    ExtraWorkPricingLineItem,
    ExtraWorkRequest,
    ExtraWorkStatus,
    ExtraWorkStatusHistory,
)
from .scoping import scope_extra_work_for
from .serializers import (
    ExtraWorkPricingLineItemCustomerSerializer,
    ExtraWorkPricingLineItemSerializer,
    ExtraWorkRequestCreateSerializer,
    ExtraWorkRequestDetailSerializer,
    ExtraWorkRequestListSerializer,
    ExtraWorkStatusHistorySerializer,
    ExtraWorkTransitionSerializer,
)
from .state_machine import TransitionError, apply_transition


PROVIDER_ROLES = {
    UserRole.SUPER_ADMIN,
    UserRole.COMPANY_ADMIN,
    UserRole.BUILDING_MANAGER,
}


# Sprint 28 Batch 9 — bucket definitions for the Extra Work stats
# endpoints. Kept as module-level constants so the `stats` /
# `stats/by-building` actions share a single source of truth.
#
# String literals (not `ExtraWorkStatus.X.value`) match the style of
# `tickets.views.stats` and keep the Q-filter call sites readable.
EXTRA_WORK_TERMINAL_STATUSES = (
    "CUSTOMER_APPROVED",
    "CUSTOMER_REJECTED",
    "CANCELLED",
)
EXTRA_WORK_AWAITING_PRICING_STATUSES = ("REQUESTED", "UNDER_REVIEW")


def _is_provider_operator(user) -> bool:
    return user.role in PROVIDER_ROLES


class ExtraWorkRequestViewSet(
    mixins.CreateModelMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet,
):
    permission_classes = [IsAuthenticatedAndActive]

    def get_queryset(self):
        return scope_extra_work_for(self.request.user).select_related(
            "company", "building", "customer", "created_by"
        )

    def get_serializer_class(self):
        if self.action == "list":
            return ExtraWorkRequestListSerializer
        if self.action == "create":
            return ExtraWorkRequestCreateSerializer
        return ExtraWorkRequestDetailSerializer

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        instance = serializer.save()
        # Read it back through the detail serializer so the
        # response shape matches what the GET /<id>/ endpoint
        # returns. The actor's role decides whether provider-
        # internal fields appear.
        detail = ExtraWorkRequestDetailSerializer(
            instance, context={"request": request}
        )
        return Response(detail.data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["post"], url_path="transition")
    def transition(self, request, pk=None):
        extra_work = self.get_object()  # 404 if out-of-scope
        payload = ExtraWorkTransitionSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        data = payload.validated_data
        try:
            updated = apply_transition(
                extra_work,
                request.user,
                data["to_status"],
                note=data.get("note", ""),
                is_override=data.get("is_override", False),
                override_reason=data.get("override_reason", ""),
            )
        except TransitionError as exc:
            return Response(
                {"detail": str(exc), "code": exc.code},
                status=status.HTTP_400_BAD_REQUEST,
            )
        return Response(
            ExtraWorkRequestDetailSerializer(
                updated, context={"request": request}
            ).data
        )

    @action(detail=True, methods=["get"], url_path="status-history")
    def status_history(self, request, pk=None):
        extra_work = self.get_object()  # 404 if out-of-scope
        rows = ExtraWorkStatusHistory.objects.filter(extra_work=extra_work)
        return Response(
            ExtraWorkStatusHistorySerializer(rows, many=True).data
        )

    @action(detail=False, methods=["get"], url_path="stats")
    def stats(self, request):
        """
        Sprint 28 Batch 9 — aggregate Extra Work stats scoped per role.

        Shape:
          {
            "total": int,
            "by_status": {status: count, ...},
            "by_routing": {"INSTANT": int, "PROPOSAL": int},
            "by_urgency": {"NORMAL": int, "HIGH": int, "URGENT": int},
            "active": int,                      # NOT in terminal set
            "awaiting_pricing": int,            # routing=PROPOSAL + REQUESTED/UNDER_REVIEW
            "awaiting_customer_approval": int,  # status == PRICING_PROPOSED
            "urgent": int,                      # URGENT urgency, not in terminal set
          }

        STAFF naturally gets all-zeros because `scope_extra_work_for`
        returns `.none()` for STAFF (MVP — no staff-execution surface
        on Extra Work yet).
        """
        scoped = scope_extra_work_for(request.user)

        status_counts = {
            row["status"]: row["c"]
            for row in scoped.values("status").annotate(c=Count("id"))
        }
        routing_counts = {
            row["routing_decision"]: row["c"]
            for row in scoped.values("routing_decision").annotate(c=Count("id"))
        }
        urgency_counts = {
            row["urgency"]: row["c"]
            for row in scoped.values("urgency").annotate(c=Count("id"))
        }

        terminal_states = set(EXTRA_WORK_TERMINAL_STATUSES)
        active = sum(
            c for s, c in status_counts.items() if s not in terminal_states
        )
        awaiting_pricing = scoped.filter(
            routing_decision="PROPOSAL",
            status__in=list(EXTRA_WORK_AWAITING_PRICING_STATUSES),
        ).count()
        awaiting_customer_approval = status_counts.get("PRICING_PROPOSED", 0)
        urgent = (
            scoped.filter(urgency="URGENT")
            .exclude(status__in=list(EXTRA_WORK_TERMINAL_STATUSES))
            .count()
        )
        total = sum(status_counts.values())

        return Response(
            {
                "total": total,
                "by_status": status_counts,
                "by_routing": routing_counts,
                "by_urgency": urgency_counts,
                "active": active,
                "awaiting_pricing": awaiting_pricing,
                "awaiting_customer_approval": awaiting_customer_approval,
                "urgent": urgent,
            },
            status=status.HTTP_200_OK,
        )

    @action(detail=False, methods=["get"], url_path="stats/by-building")
    def stats_by_building(self, request):
        """
        Sprint 28 Batch 9 — per-building Extra Work breakdown scoped
        per role.

        Returns a list ordered by building name. Buildings with no
        Extra Work rows in scope are skipped naturally by the GROUP BY
        (no padding rows). STAFF gets `[]` for the same reason `stats`
        zeroes out for them.
        """
        scoped = scope_extra_work_for(request.user)
        terminal = list(EXTRA_WORK_TERMINAL_STATUSES)
        awaiting_pricing_statuses = list(EXTRA_WORK_AWAITING_PRICING_STATUSES)

        rows = (
            scoped.values("building_id", "building__name")
            .annotate(
                total=Count("id"),
                active=Count("id", filter=~Q(status__in=terminal)),
                awaiting_pricing=Count(
                    "id",
                    filter=Q(routing_decision="PROPOSAL")
                    & Q(status__in=awaiting_pricing_statuses),
                ),
                awaiting_customer_approval=Count(
                    "id", filter=Q(status="PRICING_PROPOSED")
                ),
                urgent=Count(
                    "id",
                    filter=Q(urgency="URGENT") & ~Q(status__in=terminal),
                ),
            )
            .order_by("building__name")
        )

        return Response(
            [
                {
                    "building_id": row["building_id"],
                    "building_name": row["building__name"],
                    "total": row["total"],
                    "active": row["active"],
                    "awaiting_pricing": row["awaiting_pricing"],
                    "awaiting_customer_approval": row[
                        "awaiting_customer_approval"
                    ],
                    "urgent": row["urgent"],
                }
                for row in rows
            ],
            status=status.HTTP_200_OK,
        )


def _resolve_extra_work_or_404(request, ew_id: int) -> ExtraWorkRequest:
    qs = scope_extra_work_for(request.user)
    return get_object_or_404(qs, pk=ew_id)


def _require_provider_pricing_permission(request, extra_work):
    """Pricing line items can only be mutated by SUPER_ADMIN /
    COMPANY_ADMIN inside the company / BUILDING_MANAGER assigned
    to the building. Customer users get 403 (the scoping already
    let them GET the row, so we explicitly refuse mutation here)."""
    if not _is_provider_operator(request.user):
        return Response(
            {"detail": "Customer users cannot edit pricing line items."},
            status=status.HTTP_403_FORBIDDEN,
        )
    if request.user.role == UserRole.SUPER_ADMIN:
        return None
    if not user_has_osius_permission(
        request.user,
        "osius.ticket.view_building",
        building_id=extra_work.building_id,
    ):
        return Response(
            {"detail": "Not in scope for this building."},
            status=status.HTTP_403_FORBIDDEN,
        )
    return None


class ExtraWorkPricingLineItemListCreateView(generics.GenericAPIView):
    """
    GET  -> list (any user in scope, customer serializer strips
            internal_cost_note)
    POST -> provider-only create + recompute aggregate totals
    """

    permission_classes = [IsAuthenticated]

    def get(self, request, ew_id: int):
        extra_work = _resolve_extra_work_or_404(request, ew_id)
        rows = extra_work.pricing_line_items.all()
        if request.user.role == UserRole.CUSTOMER_USER:
            data = ExtraWorkPricingLineItemCustomerSerializer(
                rows, many=True
            ).data
        else:
            data = ExtraWorkPricingLineItemSerializer(rows, many=True).data
        return Response(data)

    def post(self, request, ew_id: int):
        extra_work = _resolve_extra_work_or_404(request, ew_id)
        guard = _require_provider_pricing_permission(request, extra_work)
        if guard is not None:
            return guard
        serializer = ExtraWorkPricingLineItemSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        item = serializer.save(extra_work=extra_work)
        extra_work.recompute_totals()
        return Response(
            ExtraWorkPricingLineItemSerializer(item).data,
            status=status.HTTP_201_CREATED,
        )


class ExtraWorkPricingLineItemDetailView(generics.GenericAPIView):
    """
    PATCH/DELETE for an individual pricing line item. Provider-only.
    Aggregates on the parent row are recomputed after every change.
    """

    permission_classes = [IsAuthenticated]

    def _resolve(self, request, ew_id: int, lid: int):
        extra_work = _resolve_extra_work_or_404(request, ew_id)
        item = get_object_or_404(
            ExtraWorkPricingLineItem, pk=lid, extra_work=extra_work
        )
        return extra_work, item

    def patch(self, request, ew_id: int, lid: int):
        extra_work, item = self._resolve(request, ew_id, lid)
        guard = _require_provider_pricing_permission(request, extra_work)
        if guard is not None:
            return guard
        serializer = ExtraWorkPricingLineItemSerializer(
            item, data=request.data, partial=True
        )
        serializer.is_valid(raise_exception=True)
        item = serializer.save()
        extra_work.recompute_totals()
        return Response(ExtraWorkPricingLineItemSerializer(item).data)

    def delete(self, request, ew_id: int, lid: int):
        extra_work, item = self._resolve(request, ew_id, lid)
        guard = _require_provider_pricing_permission(request, extra_work)
        if guard is not None:
            return guard
        item.delete()
        extra_work.recompute_totals()
        return Response(status=status.HTTP_204_NO_CONTENT)
