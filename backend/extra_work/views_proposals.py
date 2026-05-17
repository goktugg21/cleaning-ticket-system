"""
Sprint 28 Batch 8 — proposal HTTP layer.

Endpoints (all under `/api/extra-work/<ew_id>/proposals/`):

  GET    /                              list proposals (scope-aware)
  POST   /                              create DRAFT proposal (provider only)
  GET    /<pid>/                        retrieve detail (customer 404 on DRAFT)
  POST   /<pid>/transition/             drive state transition
  GET    /<pid>/status-history/         read-only audit rows
  GET    /<pid>/timeline/               read-only timeline events (customer-filtered)
  GET    /<pid>/lines/                  list lines (customer omits internal_note)
  POST   /<pid>/lines/                  create line (provider only; DRAFT only)
  PATCH  /<pid>/lines/<lid>/            update line (provider only; DRAFT only)
  DELETE /<pid>/lines/<lid>/            delete line (provider only; DRAFT only)

Customer users CAN list / retrieve / view status-history /timeline /
lines for proposals on EWs in their scope (DRAFT proposals are
hidden — they are operator-internal until SENT). They CAN POST a
transition to approve / reject a SENT proposal. They CANNOT touch
line CRUD endpoints.
"""
from __future__ import annotations

from django.db import IntegrityError
from django.shortcuts import get_object_or_404
from rest_framework import status, views
from rest_framework.response import Response

from accounts.models import UserRole
from accounts.permissions import IsAuthenticatedAndActive
from accounts.permissions_v2 import user_has_osius_permission

from .models import (
    Proposal,
    ProposalLine,
    ProposalStatus,
    ProposalStatusHistory,
    ProposalTimelineEvent,
    ProposalTimelineEventType,
)
from .proposal_state_machine import (
    TransitionError,
    apply_proposal_transition,
    emit_proposal_event,
)
from .scoping import scope_extra_work_for
from .serializers import (
    ProposalCreateSerializer,
    ProposalDetailSerializer,
    ProposalLineAdminSerializer,
    ProposalLineCustomerSerializer,
    ProposalListSerializer,
    ProposalStatusHistorySerializer,
    ProposalTimelineEventAdminSerializer,
    ProposalTimelineEventCustomerSerializer,
    ProposalTransitionSerializer,
)


PROVIDER_ROLES = {
    UserRole.SUPER_ADMIN,
    UserRole.COMPANY_ADMIN,
    UserRole.BUILDING_MANAGER,
}


def _is_provider_operator(user) -> bool:
    return user.role in PROVIDER_ROLES


def _is_customer(user) -> bool:
    return user.role == UserRole.CUSTOMER_USER


def _resolve_extra_work_or_404(request, ew_id: int):
    """Scope-aware EW resolution. Raises 404 if the requester cannot
    see the parent request."""
    qs = scope_extra_work_for(request.user)
    return get_object_or_404(qs, pk=ew_id)


def _resolve_proposal_or_404(request, ew_id: int, pid: int):
    """Resolve a proposal that belongs to the in-scope parent EW.
    For customer users, DRAFT proposals are invisible (404)."""
    extra_work = _resolve_extra_work_or_404(request, ew_id)
    proposal = get_object_or_404(
        Proposal,
        pk=pid,
        extra_work_request=extra_work,
    )
    if _is_customer(request.user) and proposal.status == ProposalStatus.DRAFT:
        # DRAFT is operator-internal — customers must not see it.
        from django.http import Http404

        raise Http404("Proposal not visible.")
    return extra_work, proposal


def _require_provider_in_scope(request, extra_work):
    """Provider-side scope guard for write actions. SUPER_ADMIN
    bypasses; COMPANY_ADMIN / BUILDING_MANAGER must resolve
    `osius.ticket.view_building`. CUSTOMER_USER / STAFF get 403."""
    if not _is_provider_operator(request.user):
        return Response(
            {"detail": "Provider-side action only."},
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


# ---------------------------------------------------------------------------
# Proposal list + create
# ---------------------------------------------------------------------------
class ProposalListCreateView(views.APIView):
    """
    GET  -> list proposals for an EW; customer-side filter excludes
            DRAFT rows.
    POST -> provider-only create. Body: `{ "lines": [ ... ] }`.
    """

    permission_classes = [IsAuthenticatedAndActive]

    def get(self, request, ew_id: int):
        extra_work = _resolve_extra_work_or_404(request, ew_id)
        proposals = Proposal.objects.filter(extra_work_request=extra_work)
        if _is_customer(request.user):
            proposals = proposals.exclude(status=ProposalStatus.DRAFT)
        proposals = proposals.order_by("-created_at")
        data = ProposalListSerializer(proposals, many=True).data
        return Response(data)

    def post(self, request, ew_id: int):
        extra_work = _resolve_extra_work_or_404(request, ew_id)
        guard = _require_provider_in_scope(request, extra_work)
        if guard is not None:
            return guard
        serializer = ProposalCreateSerializer(
            data=request.data,
            context={"request": request, "extra_work_request": extra_work},
        )
        serializer.is_valid(raise_exception=True)
        try:
            proposal = serializer.save()
        except IntegrityError:
            # Defence-in-depth: the partial UniqueConstraint
            # blocks a race in which two parallel POSTs both pass
            # the pre-check. Catch the resulting IntegrityError and
            # surface it as a clean 400.
            return Response(
                {
                    "detail": (
                        "An open proposal already exists for this "
                        "Extra Work request."
                    ),
                    "code": "proposal_open_already_exists",
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
        return Response(
            ProposalDetailSerializer(
                proposal, context={"request": request}
            ).data,
            status=status.HTTP_201_CREATED,
        )


# ---------------------------------------------------------------------------
# Proposal detail
# ---------------------------------------------------------------------------
class ProposalDetailView(views.APIView):
    permission_classes = [IsAuthenticatedAndActive]

    def get(self, request, ew_id: int, pid: int):
        _, proposal = _resolve_proposal_or_404(request, ew_id, pid)
        if _is_customer(request.user) and proposal.status == ProposalStatus.SENT:
            # Emit CUSTOMER_VIEWED on first customer read of a SENT
            # proposal. Idempotent enough for our purposes — multiple
            # rows are fine since the timeline is append-only.
            emit_proposal_event(
                proposal,
                event_type=ProposalTimelineEventType.CUSTOMER_VIEWED,
                actor=request.user,
                customer_visible=True,
            )
        return Response(
            ProposalDetailSerializer(
                proposal, context={"request": request}
            ).data
        )


# ---------------------------------------------------------------------------
# Proposal transition
# ---------------------------------------------------------------------------
class ProposalTransitionView(views.APIView):
    permission_classes = [IsAuthenticatedAndActive]

    def post(self, request, ew_id: int, pid: int):
        _, proposal = _resolve_proposal_or_404(request, ew_id, pid)
        payload = ProposalTransitionSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        data = payload.validated_data
        try:
            updated = apply_proposal_transition(
                proposal,
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
            ProposalDetailSerializer(
                updated, context={"request": request}
            ).data
        )


# ---------------------------------------------------------------------------
# Read-only history + timeline
# ---------------------------------------------------------------------------
class ProposalStatusHistoryView(views.APIView):
    permission_classes = [IsAuthenticatedAndActive]

    def get(self, request, ew_id: int, pid: int):
        _, proposal = _resolve_proposal_or_404(request, ew_id, pid)
        rows = ProposalStatusHistory.objects.filter(proposal=proposal)
        return Response(
            ProposalStatusHistorySerializer(rows, many=True).data
        )


class ProposalTimelineView(views.APIView):
    permission_classes = [IsAuthenticatedAndActive]

    def get(self, request, ew_id: int, pid: int):
        _, proposal = _resolve_proposal_or_404(request, ew_id, pid)
        events = ProposalTimelineEvent.objects.filter(proposal=proposal)
        if _is_customer(request.user):
            events = events.filter(customer_visible=True)
            data = ProposalTimelineEventCustomerSerializer(
                events, many=True
            ).data
        else:
            data = ProposalTimelineEventAdminSerializer(
                events, many=True
            ).data
        return Response(data)


# ---------------------------------------------------------------------------
# Proposal lines (provider-only CRUD; only when proposal is in DRAFT)
# ---------------------------------------------------------------------------
class ProposalLineListCreateView(views.APIView):
    permission_classes = [IsAuthenticatedAndActive]

    def get(self, request, ew_id: int, pid: int):
        _, proposal = _resolve_proposal_or_404(request, ew_id, pid)
        lines = proposal.lines.all().select_related("service")
        if _is_customer(request.user):
            data = ProposalLineCustomerSerializer(lines, many=True).data
        else:
            data = ProposalLineAdminSerializer(lines, many=True).data
        return Response(data)

    def post(self, request, ew_id: int, pid: int):
        extra_work, proposal = _resolve_proposal_or_404(
            request, ew_id, pid
        )
        guard = _require_provider_in_scope(request, extra_work)
        if guard is not None:
            return guard
        if proposal.status != ProposalStatus.DRAFT:
            return Response(
                {
                    "detail": (
                        "Lines can only be edited while the proposal "
                        "is in DRAFT."
                    ),
                    "code": "proposal_not_draft",
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
        serializer = ProposalLineAdminSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        line = serializer.save(proposal=proposal)
        proposal.recompute_totals()
        return Response(
            ProposalLineAdminSerializer(line).data,
            status=status.HTTP_201_CREATED,
        )


class ProposalLineDetailView(views.APIView):
    permission_classes = [IsAuthenticatedAndActive]

    def _resolve(self, request, ew_id: int, pid: int, lid: int):
        extra_work, proposal = _resolve_proposal_or_404(
            request, ew_id, pid
        )
        line = get_object_or_404(ProposalLine, pk=lid, proposal=proposal)
        return extra_work, proposal, line

    def patch(self, request, ew_id: int, pid: int, lid: int):
        extra_work, proposal, line = self._resolve(
            request, ew_id, pid, lid
        )
        guard = _require_provider_in_scope(request, extra_work)
        if guard is not None:
            return guard
        if proposal.status != ProposalStatus.DRAFT:
            return Response(
                {
                    "detail": (
                        "Lines can only be edited while the proposal "
                        "is in DRAFT."
                    ),
                    "code": "proposal_not_draft",
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
        serializer = ProposalLineAdminSerializer(
            line, data=request.data, partial=True
        )
        serializer.is_valid(raise_exception=True)
        line = serializer.save()
        proposal.recompute_totals()
        return Response(ProposalLineAdminSerializer(line).data)

    def delete(self, request, ew_id: int, pid: int, lid: int):
        extra_work, proposal, line = self._resolve(
            request, ew_id, pid, lid
        )
        guard = _require_provider_in_scope(request, extra_work)
        if guard is not None:
            return guard
        if proposal.status != ProposalStatus.DRAFT:
            return Response(
                {
                    "detail": (
                        "Lines can only be edited while the proposal "
                        "is in DRAFT."
                    ),
                    "code": "proposal_not_draft",
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
        line.delete()
        proposal.recompute_totals()
        return Response(status=status.HTTP_204_NO_CONTENT)
