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

from django.db import IntegrityError, transaction
from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from rest_framework import serializers as drf_serializers
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
from .proposal_pdf import render_proposal_pdf
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
    `osius.ticket.view_building`. CUSTOMER_USER / STAFF get 403.

    B6 — for BUILDING_MANAGER this guard additionally checks
    `osius.building_manager.prepare_extra_work_proposal`. The proposal
    create / line CRUD endpoints below all call this helper before
    mutating the proposal row, so a BM whose
    `BuildingManagerAssignment.permission_overrides` revokes the
    proposal-preparation default is blocked at every write surface
    that does not already flow through the proposal state machine
    (the state machine has its own B6 gate for transitions).
    SA / COMPANY_ADMIN bypass the prep key (it defaults True for them).
    """
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
    if request.user.role == UserRole.BUILDING_MANAGER:
        if not user_has_osius_permission(
            request.user,
            "osius.building_manager.prepare_extra_work_proposal",
            building_id=extra_work.building_id,
        ):
            return Response(
                {
                    "detail": (
                        "Building Manager's extra-work proposal "
                        "preparation has been disabled for this "
                        "building."
                    ),
                    "code": "bm_proposal_preparation_disabled",
                },
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
        # B1 — pass request context so the serializer's customer-side
        # note + override_reason redaction (see
        # ProposalStatusHistorySerializer.get_note / .get_override_reason)
        # can fire. Without context the serializer cannot tell the
        # caller's role and would surface every field unfiltered.
        return Response(
            ProposalStatusHistorySerializer(
                rows, many=True, context={"request": request}
            ).data
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


# ---------------------------------------------------------------------------
# Proposal PDF export (Sprint 28 Batch 14)
# ---------------------------------------------------------------------------
class ProposalPdfView(views.APIView):
    """
    GET /api/extra-work/<ew_id>/proposals/<pid>/pdf/

    Render an already-visible proposal as a PDF. Scope + DRAFT
    visibility inherited from `_resolve_proposal_or_404`. This is a
    read-only rendering — no `CUSTOMER_VIEWED` timeline event is
    emitted (unlike `ProposalDetailView`).
    """

    permission_classes = [IsAuthenticatedAndActive]

    def get(self, request, ew_id: int, pid: int):
        _, proposal = _resolve_proposal_or_404(request, ew_id, pid)
        viewer_is_customer = _is_customer(request.user)
        pdf_bytes = render_proposal_pdf(
            proposal, viewer_is_customer=viewer_is_customer
        )
        response = HttpResponse(pdf_bytes, content_type="application/pdf")
        response["Content-Disposition"] = (
            f'inline; filename="proposal-{proposal.pk}.pdf"'
        )
        return response


# ---------------------------------------------------------------------------
# Proposal direct-publish (provider override of customer approval step)
# ---------------------------------------------------------------------------
class ProposalDirectPublishSerializer(drf_serializers.Serializer):
    """Payload for the direct-publish endpoint.

    `override_reason` is documented as optional on the wire (matches
    the brief's payload shape) but the endpoint REQUIRES a non-empty
    reason on the SENT->CUSTOMER_APPROVED leg. We do not silently
    default — the override-reason convention across the codebase
    (Sprint 27F-B1 tickets, `apply_proposal_transition`, EW state
    machine) is "operator MUST type a reason" with stable code
    `override_reason_required`. A blank or whitespace-only string
    therefore produces an HTTP 400. The `note` field is plumbed
    through to the DRAFT->SENT status history note (the customer
    never sees the SENT row because the same atomic block advances
    the proposal to CUSTOMER_APPROVED before any read happens).
    """

    note = drf_serializers.CharField(required=False, allow_blank=True, default="")
    override_reason = drf_serializers.CharField(
        required=False, allow_blank=True, default=""
    )


class ProposalDirectPublishView(views.APIView):
    """
    POST /api/extra-work/<ew_id>/proposals/<pid>/direct-publish/

    Single-shot atomic "skip the customer step" path for provider
    operators. Drives the proposal from DRAFT straight through
    SENT -> CUSTOMER_APPROVED in one HTTP call, recording the
    override metadata on the SENT->CUSTOMER_APPROVED status-history
    row (`is_override=True`, `override_reason=<payload>`). The
    parent EW + spawn-tickets side effects fire from the existing
    approval path inside `apply_proposal_transition`.

    Permission gate:
      * Provider operator in scope on the parent EW's customer /
        building (SA / CA via `osius.ticket.view_building` / BM in
        assigned building).
      * BUILDING_MANAGER additionally must hold BOTH
        `osius.building_manager.prepare_extra_work_proposal` AND
        `osius.building_manager.override_customer_decision` at the
        EW's building. Either revoked -> 403.
      * CUSTOMER_USER / STAFF -> 403.

    Other preconditions:
      * Proposal MUST be in DRAFT -> 400 with code
        `direct_publish_requires_draft` otherwise.
      * `override_reason` MUST be non-blank in the payload -> 400
        with code `override_reason_required` otherwise. The endpoint
        does NOT silently default the reason: the codebase
        convention (Sprint 27F-B1 + `apply_proposal_transition`) is
        that any provider-driven customer-decision transition
        requires an operator-typed reason.
      * SEND-time validations (at least one line, cart-coverage,
        contract-price floor, non-contract priced) inherited from
        `apply_proposal_transition(... to_status=SENT)`. Any
        failure surfaces the same stable code the normal SEND path
        does, with the whole atomic block rolled back.

    Atomicity:
      Both legs (DRAFT->SENT then SENT->CUSTOMER_APPROVED) run
      inside a single `transaction.atomic()` block. If the second
      transition raises, the first is rolled back. The
      `apply_proposal_transition` call itself is already
      `@transaction.atomic`-wrapped — Django nested atomics use
      savepoints, so this stacking is correct.
    """

    permission_classes = [IsAuthenticatedAndActive]

    def post(self, request, ew_id: int, pid: int):
        extra_work, proposal = _resolve_proposal_or_404(
            request, ew_id, pid
        )

        # Role / scope gate. We reuse the existing
        # `_require_provider_in_scope` helper which already enforces:
        #   * Provider operator role,
        #   * `osius.ticket.view_building` for CA / BM,
        #   * `osius.building_manager.prepare_extra_work_proposal` for BM.
        guard = _require_provider_in_scope(request, extra_work)
        if guard is not None:
            return guard

        # BM additional gate: the direct-publish path crosses the
        # SENT->CUSTOMER_APPROVED leg too, which the proposal state
        # machine treats as a customer-decision override. BM must
        # therefore also hold `osius.building_manager.override_customer_decision`.
        # SA / COMPANY_ADMIN bypass (the resolver returns True for them).
        if request.user.role == UserRole.BUILDING_MANAGER:
            if not user_has_osius_permission(
                request.user,
                "osius.building_manager.override_customer_decision",
                building_id=extra_work.building_id,
            ):
                return Response(
                    {
                        "detail": (
                            "Building Manager's customer-decision "
                            "override has been disabled for this "
                            "building."
                        ),
                        "code": "bm_override_disabled",
                    },
                    status=status.HTTP_403_FORBIDDEN,
                )

        # DRAFT-only precondition. Catching it explicitly here lets
        # the frontend distinguish "not DRAFT" from a generic
        # `forbidden_transition` raised inside the state machine.
        if proposal.status != ProposalStatus.DRAFT:
            return Response(
                {
                    "detail": (
                        "Direct-publish requires the proposal to be in "
                        "DRAFT."
                    ),
                    "code": "direct_publish_requires_draft",
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        payload = ProposalDirectPublishSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        data = payload.validated_data
        note = data.get("note", "")
        override_reason = (data.get("override_reason", "") or "").strip()

        # Pre-flight reason gate. The proposal state machine would
        # raise the same stable code on the SENT->CUSTOMER_APPROVED
        # leg, but checking up front avoids the half-transition
        # (DRAFT->SENT executes, then SENT->CUSTOMER_APPROVED fails
        # for a reason every caller could have known up front).
        # The outer atomic block would roll it back, but doing the
        # cheap pre-check is the cleaner contract.
        if not override_reason:
            return Response(
                {
                    "detail": (
                        "Override reason is required when a provider "
                        "operator directly publishes a proposal without "
                        "customer approval."
                    ),
                    "code": "override_reason_required",
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Atomic two-step: DRAFT -> SENT, then SENT -> CUSTOMER_APPROVED.
        # `apply_proposal_transition` is itself @transaction.atomic-wrapped;
        # Django nested atomics use savepoints so this outer block
        # encompasses both legs correctly. If the second leg raises,
        # the first leg's status mutation + ProposalStatusHistory row +
        # parent-EW advance + timeline event all roll back together.
        try:
            with transaction.atomic():
                apply_proposal_transition(
                    proposal,
                    request.user,
                    ProposalStatus.SENT,
                    note=note,
                )
                # Re-fetch so the in-memory `status` reflects the SENT
                # mutation; `apply_proposal_transition` does a
                # `select_for_update` + `save(update_fields=...)`
                # internally on its own locked clone, so our `proposal`
                # variable's `status` is stale. Refresh from DB.
                proposal.refresh_from_db()

                # Sprint 6B — if the parent EW carries
                # AUTO_START_AFTER_PRICING, the SEND leg above already
                # auto-approved the proposal and spawned the operational
                # ticket (system pre-authorisation, is_override=False).
                # There is no customer decision to override, so skip the
                # SENT->CUSTOMER_APPROVED override leg (it would be a
                # no-op transition) and return the already-approved
                # proposal as-is.
                if proposal.status == ProposalStatus.CUSTOMER_APPROVED:
                    updated = proposal
                else:
                    updated = apply_proposal_transition(
                        proposal,
                        request.user,
                        ProposalStatus.CUSTOMER_APPROVED,
                        note=note,
                        is_override=True,
                        override_reason=override_reason,
                    )
        except TransitionError as exc:
            return Response(
                {"detail": str(exc), "code": exc.code},
                status=status.HTTP_400_BAD_REQUEST,
            )

        return Response(
            ProposalDetailSerializer(
                updated, context={"request": request}
            ).data,
            status=status.HTTP_200_OK,
        )
