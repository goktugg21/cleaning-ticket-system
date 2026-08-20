import logging

from django.db import transaction
from django.db.models import Count, Q
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import generics, mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ErrorDetail, ValidationError
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.response import Response

from accounts.models import UserRole
from accounts.permissions import (
    IsAuthenticatedAndActive,
    is_customer_side,
    is_provider_management_role,
    is_staff_role,
)
from accounts.scoping import scope_tickets_for
from audit.models import AuditAction, AuditLog
from audit import context as audit_context
from notifications.services import (
    emit_ticket_message_notifications,
    send_ticket_assigned_email,
    send_ticket_created_email,
    send_ticket_status_changed_email,
    send_ticket_unassigned_email,
    ticket_message_audience,
)

from .filters import (
    TicketFilter,
    apply_is_extra_work,
    exclude_finished_extra_work,
    parse_is_extra_work,
)
from .models import (
    AttachmentVisibility,
    Ticket,
    TicketAttachment,
    TicketMessage,
    TicketMessageType,
    TicketScheduleStatus,
    TicketStaffAssignment,
    TicketStatus,
    TicketStatusHistory,
    TicketType,
)
from buildings.models import BuildingManagerAssignment
from .permissions import (
    CanPostMessage,
    CanViewTicket,
    filter_messages_visible_to,
    message_type_visible_to_user,
    user_has_scope_for_ticket,
)
from .state_machine import TransitionError, apply_transition
from .serializers import (
    TicketAssignableManagerSerializer,
    TicketAssignSerializer,
    TicketAttachmentPolicySerializer,
    TicketAttachmentSerializer,
    TicketAttachmentVisibilitySerializer,
    TicketAutoCompleteFlagSerializer,
    TicketCategorySerializer,
    TicketConvertToExtraWorkSerializer,
    TicketCreateSerializer,
    TicketDetailSerializer,
    TicketListSerializer,
    TicketMessageSerializer,
    TicketBulkStatusChangeSerializer,
    TicketScheduleInputSerializer,
    TicketStatusChangeSerializer,
)


# Sprint 9B — terminal statuses for the schedule endpoint guard.
# A converted / closed / decided ticket has left every operational
# queue and cannot be scheduled or rescheduled.
_SCHEDULE_TERMINAL_STATUSES = {
    TicketStatus.APPROVED,
    TicketStatus.REJECTED,
    TicketStatus.CLOSED,
    TicketStatus.CONVERTED_TO_EXTRA_WORK,
}

# Sprint 9B — provider-management roles permitted to mutate a ticket's
# schedule. STAFF + customer-side roles can still READ the schedule via
# the list / agenda / detail endpoints; they just cannot set it.
_SCHEDULE_ALLOWED_ROLES = {
    UserRole.SUPER_ADMIN,
    UserRole.COMPANY_ADMIN,
    UserRole.BUILDING_MANAGER,
}


_audit_logger = logging.getLogger(__name__)


def _user_can_soft_delete_ticket(user, ticket) -> bool:
    """
    Sprint 12 — conservative permission rule for ticket soft-delete.

    The caller is already known to be in scope (the queryset gate enforces
    that before this check fires). This function decides who, *within scope*,
    is permitted to soft-delete:

      - SUPER_ADMIN: always allowed.
      - COMPANY_ADMIN: allowed for any in-scope ticket (their company's).
      - BUILDING_MANAGER and CUSTOMER_USER: only the user who created the
        ticket. A manager is not allowed to delete a customer's ticket they
        did not raise themselves; one customer-user is not allowed to delete
        another customer-user's ticket even if both share a customer.

    The narrower "creator-only" rule for non-admin roles matches the brief's
    intent: this feature exists to clean up tickets opened by accident, so
    only the person who opened it (or an admin in scope) can roll it back.
    """
    if user.role == UserRole.SUPER_ADMIN:
        return True
    if user.role == UserRole.COMPANY_ADMIN:
        return True
    return ticket.created_by_id == user.id


class TicketViewSet(
    mixins.CreateModelMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet,
):
    permission_classes = [IsAuthenticatedAndActive, CanViewTicket]
    filterset_class = TicketFilter
    ordering_fields = ["created_at", "updated_at", "priority", "status"]

    @property
    def search_fields(self):
        # Only staff can substring-search across descriptions; for customer
        # users descriptions can carry context that should stay scoped to the
        # one ticket they were typed into. Implemented as a property because
        # DRF's SearchFilter reads view.search_fields directly via getattr.
        if is_staff_role(self.request.user):
            return ["ticket_no", "title", "room_label", "description"]
        return ["ticket_no", "title", "room_label"]

    def get_queryset(self):
        qs = scope_tickets_for(self.request.user).select_related(
            "company", "building", "customer", "created_by", "assigned_to"
        )
        if self.action == "retrieve":
            qs = qs.prefetch_related(
                "status_history",
                "status_history__changed_by",
                # Sprint 4 — the detail serializer's `sub_tasks` field nests
                # each sub-task's staff assignments + a computed is_done;
                # prefetch the chain so the render stays N+1-free.
                "sub_tasks",
                "sub_tasks__staff_assignments",
                "sub_tasks__staff_assignments__user",
            )
        if self.action == "list":
            # Eager-load the Extra Work origin chain the list serializer's
            # `extra_work_origin` field reads (`resolve_extra_work_origin_core`).
            # All three links + their nested reads are forward FKs, so a
            # single multi-join select_related keeps the list query count
            # flat regardless of how many EW-spawned rows the page holds
            # (no N+1):
            #   * extra_work_request          -> canonical parent EW
            #   * extra_work_request_item     -> service + legacy-fallback EW
            #   * proposal_line               -> service + proposal -> EW
            qs = qs.select_related(
                "extra_work_request",
                "extra_work_request_item",
                "extra_work_request_item__service",
                "extra_work_request_item__extra_work_request",
                "proposal_line",
                "proposal_line__service",
                "proposal_line__proposal",
                "proposal_line__proposal__extra_work_request",
            )
            qs = self._apply_sla_filter(qs)
        return qs

    # Mirrors the frontend display-state priority. Paused overrides underlying
    # state (?sla=breached excludes paused tickets); unknown values fall
    # through to "all" rather than raising 400.
    def _apply_sla_filter(self, qs):
        value = (self.request.query_params.get("sla") or "all").lower()
        if value == "paused":
            return qs.filter(sla_paused_at__isnull=False)
        if value == "historical":
            return qs.filter(sla_status="HISTORICAL")
        if value == "completed":
            return qs.filter(sla_status="COMPLETED")
        if value == "breached":
            return qs.filter(sla_paused_at__isnull=True, sla_status="BREACHED")
        if value == "at_risk":
            return qs.filter(sla_paused_at__isnull=True, sla_status="AT_RISK")
        if value == "on_track":
            return qs.filter(sla_paused_at__isnull=True, sla_status="ON_TRACK")
        return qs

    def get_serializer_class(self):
        if self.action == "create":
            return TicketCreateSerializer
        if self.action == "retrieve":
            return TicketDetailSerializer
        return TicketListSerializer

    def get_permissions(self):
        if self.action == "create":
            return [IsAuthenticatedAndActive()]
        return super().get_permissions()

    def perform_create(self, serializer):
        # M7 — a customer-created ticket is always a "melding" (REPORT).
        # Enforced here (not just in the UI) so the invariant holds for a
        # raw API call too, keeping the M6 meldingen split (meldingen =
        # REPORT) intact. Coerce rather than reject: every customer
        # submission becomes a melding.
        if self.request.user.role == UserRole.CUSTOMER_USER:
            ticket = serializer.save(type=TicketType.REPORT)
        else:
            ticket = serializer.save()
        send_ticket_created_email(ticket, actor=self.request.user)

        # Sprint 14E — audit ticket creation as an explicit business
        # event (SoT §9.1 "ticket created"). View-level, not a signal,
        # so only genuine API creates are logged: EW-spawned tickets
        # carry their own EW / proposal audit trail and must not be
        # double-counted as "created" here. This does NOT touch status
        # (TicketStatusHistory owns the lifecycle), so H-11 holds.
        # NB: there is no generic ticket-edit endpoint (the viewset has
        # no UpdateModelMixin), so "field updated" has no surface to
        # audit; if one is added later it should be audited there.
        try:
            _scope = audit_context.get_current_actor_scope() or {}
            if not _scope:
                _scope = (
                    audit_context.snapshot_actor_scope(self.request.user) or {}
                )
            AuditLog.objects.create(
                actor=self.request.user,
                action=AuditAction.CREATE,
                target_model="tickets.Ticket",
                target_id=ticket.id,
                changes={
                    "ticket_no": {"before": None, "after": ticket.ticket_no},
                    "title": {"before": None, "after": ticket.title},
                    "type": {"before": None, "after": ticket.type},
                    "priority": {"before": None, "after": ticket.priority},
                    "building_id": {"before": None, "after": ticket.building_id},
                    "customer_id": {"before": None, "after": ticket.customer_id},
                },
                request_ip=audit_context.get_current_request_ip(),
                request_id=audit_context.get_current_request_id(),
                reason=audit_context.get_current_reason(),
                actor_scope=_scope,
            )
        except Exception:  # pragma: no cover — audit must not block create
            _audit_logger.exception(
                "audit: failed to record ticket create #%s", ticket.id
            )

    def destroy(self, request, *args, **kwargs):
        """
        Sprint 12 — soft-delete an accidentally-opened ticket.

        - The instance is fetched through the scoped queryset (so a 404 is
          returned before we even reach this method when the ticket lives
          outside the caller's scope).
        - `_user_can_soft_delete_ticket` further narrows by role/creator.
        - We set `deleted_at` + `deleted_by` and save those two fields
          only, leaving the rest of the row (status, assigned_to, sla_*)
          intact so the audit trail and the lifecycle history survive.
        - Related TicketMessage / TicketAttachment / TicketStatusHistory
          rows are NOT touched.
        - Exactly one AuditLog row is written with action=DELETE and a
          rich changes payload (ticket_no, title, deleted_by_email)
          so an operator can later see who removed which ticket without
          a cross-lookup. The audit write is best-effort: a failure is
          logged but does not roll back the soft-delete.
        """
        ticket = self.get_object()
        if not _user_can_soft_delete_ticket(request.user, ticket):
            self.permission_denied(
                request,
                message="You are not allowed to delete this ticket.",
            )
        # Sprint 182 §4 — an extra-work-born ticket CANNOT be deleted.
        #
        # This ticket is the operational record of chargeable work, and
        # three separate things read it as such: `billing.is_earned`
        # asks whether it is CLOSED, the unbilled pool is assembled from
        # that answer, and the spawn-idempotency guards treat its
        # existence as "this extra work already has its ticket".
        # Soft-deleting it therefore did two things at once, both
        # silent: the extra work dropped out of the unbilled pool (the
        # money stopped being owed, with nothing on any screen saying
        # so), and the slot stayed occupied by the deleted row, so no
        # replacement could ever be spawned.
        #
        # REFUSED rather than allowed-and-repaired, which was the other
        # option on the table. Freeing the slot would need
        # `deleted_at__isnull=True` added to the two spawn guards in
        # `extra_work/instant_tickets.py` and `proposal_tickets.py`,
        # neither of which this agent owns — and a half-applied version
        # of that fix leaves the slot jammed, which is the worse
        # failure. It is also the weaker shape on merit: even done
        # perfectly it still lets the money leave the pool silently
        # between the delete and a re-spawn nobody may remember to press.
        #
        # There is already a correct action for "this should not have
        # been created", and it lives on the extra work rather than on
        # the ticket: CANCEL it. That is audited, demands a written
        # reason, and leaves the row visible. The error says so rather
        # than leaving the operator to guess.
        if ticket.extra_work_request_id is not None:
            return Response(
                {
                    "detail": (
                        "This ticket is the operational record of "
                        "chargeable work and cannot be deleted, because "
                        "deleting it would remove the work from "
                        "invoicing without a trace. Cancel the extra "
                        "work instead."
                    ),
                    "code": "extra_work_ticket_not_deletable",
                    "extra_work_request_id": ticket.extra_work_request_id,
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        if ticket.deleted_at is not None:
            # Idempotent: already soft-deleted means the queryset gate
            # would have returned 404, but defend in depth.
            return Response(status=status.HTTP_204_NO_CONTENT)

        ticket.deleted_at = timezone.now()
        ticket.deleted_by = request.user
        ticket.save(update_fields=["deleted_at", "deleted_by", "updated_at"])

        try:
            # Sprint 27F-B2 (G-B6): pass `reason` + `actor_scope` explicitly
            # so the audit contract stays visible at every call site. The
            # soft-delete endpoint has no reason capture today (no modal),
            # so `reason` falls through to the empty string. The
            # `actor_scope` falls through to the lazy middleware-seeded
            # snapshot (resolved by `_create_log` in audit/signals.py),
            # but here we resolve it directly off the JWT-authenticated
            # request.user so the snapshot is anchored even when the
            # middleware ran with AnonymousUser.
            _actor = audit_context.get_current_actor()
            _scope = audit_context.get_current_actor_scope() or {}
            if not _scope and _actor is not None:
                _scope = audit_context.snapshot_actor_scope(_actor) or {}
            AuditLog.objects.create(
                actor=_actor,
                action=AuditAction.DELETE,
                target_model="tickets.Ticket",
                target_id=ticket.id,
                changes={
                    "ticket_id": {"before": ticket.id, "after": None},
                    "ticket_no": {"before": ticket.ticket_no, "after": None},
                    "title": {"before": ticket.title, "after": None},
                    "deleted_by_email": {
                        "before": None,
                        "after": getattr(request.user, "email", None),
                    },
                },
                request_ip=audit_context.get_current_request_ip(),
                request_id=audit_context.get_current_request_id(),
                reason=audit_context.get_current_reason(),
                actor_scope=_scope,
            )
        except Exception:  # pragma: no cover — audit must not block delete
            _audit_logger.exception(
                "audit: failed to record soft-delete of tickets.Ticket#%s",
                ticket.id,
            )

        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(detail=True, methods=["post"], url_path="status")
    def change_status(self, request, pk=None):
        ticket = self.get_object()
        old_status = ticket.status
        to_status = request.data.get("to_status")
        if not is_staff_role(request.user) and to_status not in {
            "APPROVED",
            "REJECTED",
        }:
            self.permission_denied(
                request,
                message="Customer users cannot perform staff-only status transitions.",
            )
        serializer = TicketStatusChangeSerializer(
            data=request.data,
            context={"request": request, "ticket": ticket},
        )
        serializer.is_valid(raise_exception=True)
        updated = serializer.save()

        # Sprint 180 §1 — the email describes the transition the ACTOR
        # drove, which is no longer always the ticket's final status.
        #
        # A customer approval now auto-closes (`tickets/auto_close.py`),
        # so `updated.status` can be CLOSED while the thing that
        # happened was "the customer approved". Reading `updated.status`
        # here would have two consequences:
        #   * recipients get "Goedgekeurd -> Gesloten" instead of the
        #     decision they actually care about, and
        #   * `is_admin_override` resolves False on an on-behalf
        #     approval, silently downgrading the "approved on the
        #     customer's behalf by X" mail to a generic status change.
        #
        # This is also the whole answer to "should auto-close fire a
        # second customer notification": it must not, and it does not.
        # The close happens inside `apply_transition`, which sends
        # nothing (notification is a view-layer concern in this app), so
        # the customer who just clicked Approve gets exactly ONE email,
        # about their own decision. The close is visible on the ticket
        # and in its timeline — where a bookkeeping step belongs.
        requested_status = str(serializer.validated_data["to_status"])
        is_admin_override = (
            is_staff_role(request.user)
            and old_status == "WAITING_CUSTOMER_APPROVAL"
            and requested_status in {"APPROVED", "REJECTED"}
        )
        send_ticket_status_changed_email(
            updated,
            old_status=old_status,
            new_status=requested_status,
            actor=request.user,
            is_admin_override=is_admin_override,
        )
        return Response(
            TicketDetailSerializer(updated, context={"request": request}).data,
            status=status.HTTP_200_OK,
        )


    @action(detail=False, methods=["post"], url_path="bulk-status")
    def bulk_status(self, request):
        """
        Sprint 7 — bulk manager-confirm.

        Provider management advances many WAITING_MANAGER_REVIEW tickets
        to WAITING_CUSTOMER_APPROVAL in one call ("the select button").

        PER-ITEM semantics (NOT all-or-nothing): each ticket is
        transitioned in its own `transaction.atomic()` block via the
        existing `apply_transition`, so a ticket the actor is
        out-of-scope for, or one in the wrong state, fails individually
        without aborting the batch. No permission / state-machine logic
        is duplicated here — every per-ticket role / scope / state rule
        is inherited from `apply_transition`. Always returns HTTP 200
        with a per-item breakdown.
        """
        # Endpoint-level gate: only provider-management roles (SUPER_ADMIN
        # / COMPANY_ADMIN / BUILDING_MANAGER) may drive the manager-confirm
        # forward leg. CUSTOMER_USER (and STAFF) are rejected outright —
        # neither appears in the WAITING_MANAGER_REVIEW ->
        # WAITING_CUSTOMER_APPROVAL row of ALLOWED_TRANSITIONS, so there is
        # no point loading the batch for them.
        if not is_provider_management_role(request.user):
            return Response(
                {"detail": "Only provider management can bulk-confirm tickets."},
                status=status.HTTP_403_FORBIDDEN,
            )

        serializer = TicketBulkStatusChangeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        ticket_ids = serializer.validated_data["ticket_ids"]
        to_status = serializer.validated_data["to_status"]
        note = serializer.validated_data.get("note", "")

        # Resolve through the SCOPED queryset (scope_tickets_for) so an
        # out-of-scope id becomes a per-item `not_found`, never a whole-
        # batch 404. Keyed map for O(1) lookup; the caller's id order
        # drives the result ordering.
        scoped = {
            ticket.id: ticket
            for ticket in self.get_queryset().filter(pk__in=ticket_ids)
        }

        results = []
        succeeded = 0
        failed = 0
        for ticket_id in ticket_ids:
            ticket = scoped.get(ticket_id)
            if ticket is None:
                results.append({"id": ticket_id, "ok": False, "error": "not_found"})
                failed += 1
                continue

            # Sprint 7 (Codex P2) — manager-confirm is ONLY the
            # WAITING_MANAGER_REVIEW -> WAITING_CUSTOMER_APPROVAL leg.
            # apply_transition alone is an insufficient guard: a SUPER_ADMIN can
            # transition from ANY source status, and every provider role can drive
            # IN_PROGRESS -> WAITING_CUSTOMER_APPROVAL directly. An explicit
            # source-status check keeps this endpoint to its single documented leg,
            # returning a per-item failure for anything else.
            if str(ticket.status) != str(TicketStatus.WAITING_MANAGER_REVIEW):
                results.append({"id": ticket_id, "ok": False, "error": "not_in_review"})
                failed += 1
                continue

            old_status = ticket.status
            try:
                with transaction.atomic():
                    updated = apply_transition(
                        ticket,
                        request.user,
                        to_status,
                        note=note,
                    )
            except TransitionError as exc:
                results.append(
                    {"id": ticket_id, "ok": False, "error": exc.code}
                )
                failed += 1
                continue

            # Notification parity with the single-status `change_status`
            # action: one status-changed email per successfully
            # transitioned ticket. The manager-confirm leg is never an
            # `is_admin_override` case (that only applies to
            # WAITING_CUSTOMER_APPROVAL -> APPROVED/REJECTED), so the
            # flag stays at its default False.
            send_ticket_status_changed_email(
                updated,
                old_status=old_status,
                new_status=updated.status,
                actor=request.user,
            )
            results.append({"id": ticket_id, "ok": True})
            succeeded += 1

        return Response(
            {"succeeded": succeeded, "failed": failed, "results": results},
            status=status.HTTP_200_OK,
        )


    @action(detail=True, methods=["post"], url_path="convert-to-extra-work")
    def convert_to_extra_work(self, request, pk=None):
        """
        Sprint 7B — convert a normal ticket / melding into a new Extra
        Work request. The source ticket is superseded to the terminal
        status CONVERTED_TO_EXTRA_WORK; a NEW operational ticket is
        spawned by the existing Sprint 6A/6B machinery (immediately on
        the INSTANT route, later via the proposal flow on the PROPOSAL
        route). The original ticket is NOT reused.

        Provider-only (SUPER_ADMIN / COMPANY_ADMIN / BUILDING_MANAGER).
        All three EW intents are allowed on conversion, including
        REQUEST_QUOTE, which the normal provider create path forbids.
        """
        user = request.user

        # Role gate FIRST — before the object lookup — so STAFF and every
        # customer-side role get a stable 403 `conversion_forbidden_for_role`
        # rather than a scope-driven 404 (the convert action is a
        # provider-management capability; the role check does not depend on
        # the specific ticket).
        if user.role not in {
            UserRole.SUPER_ADMIN,
            UserRole.COMPANY_ADMIN,
            UserRole.BUILDING_MANAGER,
        }:
            return Response(
                {
                    "detail": "This role cannot convert tickets to Extra Work.",
                    "code": "conversion_forbidden_for_role",
                },
                status=status.HTTP_403_FORBIDDEN,
            )

        # `get_object()` runs through `scope_tickets_for` — out-of-scope
        # / soft-deleted tickets 404 before the scope/convertibility gates.
        ticket = self.get_object()

        # Scope gate: SUPER_ADMIN is global; COMPANY_ADMIN /
        # BUILDING_MANAGER must hold provider-side building scope.
        if user.role != UserRole.SUPER_ADMIN:
            from accounts.permissions_v2 import user_has_osius_permission

            if not user_has_osius_permission(
                user,
                "osius.ticket.view_building",
                building_id=ticket.building_id,
            ):
                return Response(
                    {
                        "detail": "You do not have provider-side scope to "
                        "convert this ticket.",
                        "code": "conversion_forbidden_scope",
                    },
                    status=status.HTTP_403_FORBIDDEN,
                )

        # EW-origin guard (Codex P2 on PR #72). An EW-origin ticket
        # (itself spawned from an Extra Work request) must NOT be
        # re-converted: nesting a second EW would flip the original EW's
        # single operational ticket to CONVERTED_TO_EXTRA_WORK and break
        # the one-operational-ticket-per-EW model. This is intrinsic to
        # the ticket (not its operational status), so it is checked
        # BEFORE the status/convertibility gates. Resolved via the SAME
        # path as the read-side `extra_work_origin` field (canonical
        # extra_work_request FK + legacy proposal_line /
        # extra_work_request_item fallbacks) so this guard and the UI
        # mirror can never drift. Backend is the authority (SoT §11.4);
        # the dashboard/detail UI also hides the action when
        # `extra_work_origin` is set.
        from .serializers import resolve_extra_work_origin_core

        if resolve_extra_work_origin_core(ticket) is not None:
            return Response(
                {
                    "detail": "This ticket was spawned from an Extra Work "
                    "request and cannot be converted to Extra Work again.",
                    "code": "ticket_already_extra_work_origin",
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Convertibility gate.
        if ticket.status == TicketStatus.CONVERTED_TO_EXTRA_WORK:
            return Response(
                {
                    "detail": "This ticket has already been converted to "
                    "Extra Work.",
                    "code": "ticket_already_converted",
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
        if ticket.status not in {
            TicketStatus.OPEN,
            TicketStatus.IN_PROGRESS,
            TicketStatus.REOPENED_BY_ADMIN,
        }:
            return Response(
                {
                    "detail": "This ticket is not in a convertible status.",
                    "code": "ticket_not_convertible",
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        serializer = TicketConvertToExtraWorkSerializer(
            data=request.data,
            context={"request": request, "ticket": ticket},
        )
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        from extra_work.classification import IntentValidationError
        from extra_work.conversion import convert_ticket_to_extra_work
        from extra_work.serializers import ExtraWorkRequestDetailSerializer

        try:
            ew, spawned = convert_ticket_to_extra_work(
                ticket,
                actor=user,
                request_intent=data["request_intent"],
                line_items_data=data["line_items"],
                customer_visible_note=data.get("customer_visible_note", ""),
                internal_note=data.get("internal_note", ""),
            )
        except IntentValidationError as exc:
            return Response(
                {"request_intent": [exc.message], "code": exc.code},
                status=status.HTTP_400_BAD_REQUEST,
            )

        ticket.refresh_from_db()
        return Response(
            {
                "extra_work_request": ExtraWorkRequestDetailSerializer(
                    ew, context={"request": request}
                ).data,
                "source_ticket": {
                    "id": ticket.id,
                    "ticket_no": ticket.ticket_no,
                    "status": ticket.status,
                },
                "operational_ticket_ids": [t.id for t in spawned],
            },
            status=status.HTTP_201_CREATED,
        )

    def _schedule_history_note(
        self, *, action: str, old_start, new_start, window_label, reason
    ) -> str:
        """Sprint 9B — compose the TicketStatusHistory annotation-row note
        summarizing a schedule set / reschedule / clear."""
        def _fmt(dt):
            return dt.isoformat() if dt is not None else "—"

        if action == "clear":
            return f"Schedule cleared (was {_fmt(old_start)})."
        parts = [f"Schedule {action}: {_fmt(old_start)} -> {_fmt(new_start)}"]
        if window_label:
            parts.append(f"window={window_label}")
        if reason:
            parts.append(f"reason={reason}")
        return "; ".join(parts)

    @action(detail=True, methods=["post", "delete"], url_path="schedule")
    def schedule(self, request, pk=None):
        """
        Sprint 9B — set / reschedule (POST) or clear (DELETE) a ticket's
        operational schedule. Additive: never changes the workflow
        `status` and never disturbs SLA (the save uses an explicit
        `update_fields` set that excludes `status`, so the SLA post_save
        signal sees no status change).

        Provider-management only (SUPER_ADMIN / COMPANY_ADMIN /
        BUILDING_MANAGER). STAFF + customer-side roles can READ the
        schedule via list / agenda / detail but get a stable 403
        `schedule_forbidden_for_role` here.
        """
        user = request.user

        # Role gate FIRST — before the object lookup — mirrors the
        # `convert_to_extra_work` shape so STAFF / customer roles get a
        # stable 403 rather than a scope-driven 404.
        if user.role not in _SCHEDULE_ALLOWED_ROLES:
            return Response(
                {
                    "detail": "This role cannot schedule tickets.",
                    "code": "schedule_forbidden_for_role",
                },
                status=status.HTTP_403_FORBIDDEN,
            )

        # `get_object()` runs through `scope_tickets_for` — out-of-scope
        # / soft-deleted tickets 404 before the scope / terminal gates.
        ticket = self.get_object()

        # Scope gate: SUPER_ADMIN is global; CA / BM must hold
        # provider-side building scope for this ticket's building.
        if user.role != UserRole.SUPER_ADMIN:
            from accounts.permissions_v2 import user_has_osius_permission

            if not user_has_osius_permission(
                user,
                "osius.ticket.view_building",
                building_id=ticket.building_id,
            ):
                return Response(
                    {
                        "detail": "You do not have provider-side scope to "
                        "schedule this ticket.",
                        "code": "schedule_forbidden_scope",
                    },
                    status=status.HTTP_403_FORBIDDEN,
                )

        # Terminal guard — applies to BOTH POST and DELETE.
        if ticket.status in _SCHEDULE_TERMINAL_STATUSES:
            return Response(
                {
                    "detail": "This ticket is in a terminal status and "
                    "cannot be scheduled.",
                    "code": "schedule_not_allowed_terminal",
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        if request.method == "DELETE":
            return self._schedule_clear(request, ticket)
        return self._schedule_set(request, ticket)

    def _schedule_set(self, request, ticket):
        serializer = TicketScheduleInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        old_start = ticket.scheduled_start_at
        is_reschedule = (
            ticket.schedule_status != TicketScheduleStatus.UNSCHEDULED
        )
        reason = (data.get("reschedule_reason") or "").strip()

        if is_reschedule and not reason:
            return Response(
                {
                    "detail": "A reschedule reason is required when "
                    "changing an existing schedule.",
                    "code": "reschedule_reason_required",
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        with transaction.atomic():
            ticket.scheduled_start_at = data["scheduled_start_at"]
            ticket.scheduled_end_at = data.get("scheduled_end_at")
            ticket.time_window_label = data.get("time_window_label", "")
            if is_reschedule:
                ticket.schedule_status = TicketScheduleStatus.RESCHEDULED
                ticket.rescheduled_from = old_start
                ticket.reschedule_reason = reason
                history_action = "rescheduled"
            else:
                ticket.schedule_status = TicketScheduleStatus.SCHEDULED
                # First scheduling leaves rescheduled_from /
                # reschedule_reason empty.
                ticket.rescheduled_from = None
                ticket.reschedule_reason = ""
                history_action = "set"

            # Explicit update_fields EXCLUDES `status` so the SLA
            # post_save signal sees no status change.
            ticket.save(
                update_fields=[
                    "scheduled_start_at",
                    "scheduled_end_at",
                    "time_window_label",
                    "schedule_status",
                    "rescheduled_from",
                    "reschedule_reason",
                    "updated_at",
                ]
            )

            # Sprint 8B annotation-row pattern: old_status == new_status
            # == ticket.status; is_override=False. This IS the audit
            # trail for the schedule change (no generic AuditLog row).
            TicketStatusHistory.objects.create(
                ticket=ticket,
                old_status=ticket.status,
                new_status=ticket.status,
                changed_by=request.user,
                note=self._schedule_history_note(
                    action=history_action,
                    old_start=old_start,
                    new_start=ticket.scheduled_start_at,
                    window_label=ticket.time_window_label,
                    reason=reason,
                ),
                is_override=False,
                override_reason="",
            )

        return Response(
            TicketDetailSerializer(ticket, context={"request": request}).data,
            status=status.HTTP_200_OK,
        )

    def _schedule_clear(self, request, ticket):
        old_start = ticket.scheduled_start_at

        with transaction.atomic():
            ticket.scheduled_start_at = None
            ticket.scheduled_end_at = None
            ticket.time_window_label = ""
            ticket.rescheduled_from = None
            ticket.reschedule_reason = ""
            ticket.schedule_status = TicketScheduleStatus.UNSCHEDULED
            ticket.save(
                update_fields=[
                    "scheduled_start_at",
                    "scheduled_end_at",
                    "time_window_label",
                    "schedule_status",
                    "rescheduled_from",
                    "reschedule_reason",
                    "updated_at",
                ]
            )
            TicketStatusHistory.objects.create(
                ticket=ticket,
                old_status=ticket.status,
                new_status=ticket.status,
                changed_by=request.user,
                note=self._schedule_history_note(
                    action="clear",
                    old_start=old_start,
                    new_start=None,
                    window_label="",
                    reason="",
                ),
                is_override=False,
                override_reason="",
            )

        return Response(
            TicketDetailSerializer(ticket, context={"request": request}).data,
            status=status.HTTP_200_OK,
        )

    @action(detail=True, methods=["patch"], url_path="auto-complete-flag")
    def auto_complete_flag(self, request, pk=None):
        """
        Sprint 4 — set the per-ticket `auto_complete_on_subtasks` opt-in.

        PA / SA only (COMPANY_ADMIN / SUPER_ADMIN). BUILDING_MANAGER, STAFF,
        and customer roles may READ the flag on the detail but get a stable
        403 `auto_complete_flag_forbidden` here. Blocked on a terminal ticket
        (mirrors the schedule guard). COMPANY_ADMIN is implicitly scoped to
        their own company because `get_object()` runs through the scoped
        queryset (a cross-company ticket 404s). On a real change, an explicit
        AuditLog UPDATE row is written (Ticket is not signal-audited).
        """
        # Role gate FIRST — before the object lookup — so a wrong role gets a
        # clean 403 rather than a scope-driven 404 (mirrors the schedule /
        # convert actions).
        if request.user.role not in (
            UserRole.SUPER_ADMIN,
            UserRole.COMPANY_ADMIN,
        ):
            return Response(
                {
                    "detail": "Only a provider admin can change the "
                    "sub-task auto-complete setting.",
                    "code": "auto_complete_flag_forbidden",
                },
                status=status.HTTP_403_FORBIDDEN,
            )

        ticket = self.get_object()

        if ticket.status in _SCHEDULE_TERMINAL_STATUSES:
            return Response(
                {
                    "detail": "This ticket is in a terminal status; the "
                    "auto-complete setting cannot be changed.",
                    "code": "auto_complete_flag_not_allowed_terminal",
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        ser = TicketAutoCompleteFlagSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        new_value = ser.validated_data["auto_complete_on_subtasks"]
        old_value = ticket.auto_complete_on_subtasks

        if new_value != old_value:
            ticket.auto_complete_on_subtasks = new_value
            # Explicit update_fields EXCLUDES `status` so the SLA post_save
            # signal sees no status change (mirrors the schedule endpoint).
            ticket.save(
                update_fields=["auto_complete_on_subtasks", "updated_at"]
            )
            self._audit_auto_complete_flag(
                request, ticket, old_value, new_value
            )

        return Response(
            TicketDetailSerializer(ticket, context={"request": request}).data,
            status=status.HTTP_200_OK,
        )

    @action(
        detail=True,
        methods=["patch"],
        url_path="attachment-visibility-policy",
    )
    def attachment_visibility_policy(self, request, pk=None):
        """
        Sprint 191 §2.5 — set the per-work photo-visibility setting
        (`Ticket.staff_uploads_customer_visible`).

        OFF (the default) is the decision: a staff upload on this work
        lands INTERNAL and waits for a provider to promote it. ON is the
        opt-in for a customer who has asked to see the work as it
        happens — staff uploads on THIS work are customer-visible the
        moment they arrive.

        Flipping it changes only what happens NEXT. It does not
        retro-promote the photos already stored (those still need the
        per-attachment promote action) and it does not retro-hide the
        ones already released, because turning a default off cannot
        un-say what a manager already decided.

        PA / SA only, blocked on a terminal ticket, one explicit AuditLog
        row on a real change — deliberately the same shape as
        `auto_complete_flag` above, which is the closest existing
        per-work switch.
        """
        if request.user.role not in (
            UserRole.SUPER_ADMIN,
            UserRole.COMPANY_ADMIN,
        ):
            return Response(
                {
                    "detail": "Only a provider admin can change the "
                    "attachment visibility setting.",
                    "code": "attachment_visibility_policy_forbidden",
                },
                status=status.HTTP_403_FORBIDDEN,
            )

        ticket = self.get_object()

        if ticket.status in _SCHEDULE_TERMINAL_STATUSES:
            return Response(
                {
                    "detail": "This ticket is in a terminal status; the "
                    "attachment visibility setting cannot be changed.",
                    "code": "attachment_visibility_policy_not_allowed_terminal",
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        ser = TicketAttachmentPolicySerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        new_value = ser.validated_data["staff_uploads_customer_visible"]
        old_value = ticket.staff_uploads_customer_visible

        if new_value != old_value:
            ticket.staff_uploads_customer_visible = new_value
            # Explicit update_fields EXCLUDES `status` so the SLA
            # post_save signal sees no status change (mirrors the
            # auto-complete-flag / schedule endpoints).
            ticket.save(
                update_fields=[
                    "staff_uploads_customer_visible",
                    "updated_at",
                ]
            )
            self._audit_ticket_flag(
                request,
                ticket,
                "staff_uploads_customer_visible",
                old_value,
                new_value,
            )

        return Response(
            TicketDetailSerializer(ticket, context={"request": request}).data,
            status=status.HTTP_200_OK,
        )

    def _audit_auto_complete_flag(self, request, ticket, old_value, new_value):
        """Sprint 4 — explicit AuditLog UPDATE row for the flag flip. Ticket
        is NOT signal-audited (audit/signals.py registers only its
        sub-models), so the flip is recorded here, mirroring the
        perform_create / destroy explicit-audit blocks. Best-effort: a
        failure is logged but never blocks the flip."""
        self._audit_ticket_flag(
            request,
            ticket,
            "auto_complete_on_subtasks",
            old_value,
            new_value,
        )

    def _audit_ticket_flag(self, request, ticket, field, old_value, new_value):
        """Sprint 191 §2.5 — the body of `_audit_auto_complete_flag`, with
        the field name as a parameter so the second per-work switch
        (`staff_uploads_customer_visible`) writes an identically shaped
        row instead of a copy of this block. Ticket is NOT signal-audited,
        so every flag flip on it has to say so here. Best-effort: a
        failure is logged but never blocks the flip."""
        try:
            _scope = audit_context.get_current_actor_scope() or {}
            if not _scope:
                _scope = (
                    audit_context.snapshot_actor_scope(request.user) or {}
                )
            AuditLog.objects.create(
                actor=request.user,
                action=AuditAction.UPDATE,
                target_model="tickets.Ticket",
                target_id=ticket.id,
                changes={
                    field: {
                        "before": old_value,
                        "after": new_value,
                    }
                },
                request_ip=audit_context.get_current_request_ip(),
                request_id=audit_context.get_current_request_id(),
                reason=audit_context.get_current_reason(),
                actor_scope=_scope,
            )
        except Exception:  # pragma: no cover — audit must not block the flip
            _audit_logger.exception(
                "audit: failed to record ticket %s flag flip #%s",
                field,
                ticket.id,
            )

    @action(detail=True, methods=["patch"], url_path="category")
    def category(self, request, pk=None):
        """
        Sprint 185 E §1 — set or clear the melding's WORK CATEGORY.

        A dedicated action rather than a PATCH on the ticket, because
        `TicketViewSet` carries no `UpdateModelMixin`: there is no
        general ticket-edit endpoint in this system, and adding one to
        reach a single field would open every other field with it. Every
        other single-field ticket edit here is an action for the same
        reason (`schedule`, `assign`, `auto-complete-flag`).

        SUPER_ADMIN / COMPANY_ADMIN / BUILDING_MANAGER. Categorising is
        triage, and the building manager is who sees a melding first;
        `get_object()` runs through the scoped queryset, so a BM can only
        ever reach a ticket in a building they manage. STAFF and every
        customer-side role are refused — the category feeds a
        provider-side report, and a customer choosing the trade would be
        the customer classifying the provider's work.

        `null` CLEARS the category and is a real edit, not a no-op: "this
        was tagged wrong" has to be expressible or the first mistake is
        permanent.

        NOT blocked on a terminal ticket, unlike `schedule`. A melding is
        very often categorised while somebody reads back through last
        month — that is precisely when the monthly review happens — and
        refusing to classify closed work would leave the report unable
        to describe the period it exists to describe. Nothing downstream
        of a terminal ticket reads this field.

        `Ticket` is not signal-audited, so the change is recorded with an
        explicit AuditLog UPDATE row, mirroring `auto-complete-flag`.
        """
        # Role gate FIRST — before the object lookup — so a wrong role
        # gets a clean 403 rather than a scope-driven 404.
        if request.user.role not in (
            UserRole.SUPER_ADMIN,
            UserRole.COMPANY_ADMIN,
            UserRole.BUILDING_MANAGER,
        ):
            return Response(
                {
                    "detail": "Only a provider operator can categorise a "
                    "melding.",
                    "code": "ticket_category_forbidden",
                },
                status=status.HTTP_403_FORBIDDEN,
            )

        ticket = self.get_object()

        ser = TicketCategorySerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        new_category = ser.validated_data["category"]

        # A category belongs to ONE provider company. Naming another
        # company's category reads as nonexistent rather than forbidden —
        # the H-1 equivalence, and the same answer the create serializer
        # gives.
        if (
            new_category is not None
            and new_category.company_id != ticket.company_id
        ):
            return Response(
                {"category": ["Unknown work category."]},
                status=status.HTTP_400_BAD_REQUEST,
            )

        old_category = ticket.category
        if (new_category.id if new_category else None) != (
            old_category.id if old_category else None
        ):
            ticket.category = new_category
            # Explicit update_fields EXCLUDES `status`, so the SLA
            # post_save signal sees no status change (the rule every
            # single-field action here follows).
            ticket.save(update_fields=["category", "updated_at"])
            self._audit_category(request, ticket, old_category, new_category)

        return Response(
            TicketDetailSerializer(ticket, context={"request": request}).data,
            status=status.HTTP_200_OK,
        )

    def _audit_category(self, request, ticket, old_category, new_category):
        """Sprint 185 E §1 — explicit AuditLog UPDATE row for a category
        change. `Ticket` is NOT signal-audited (audit/signals.py registers
        only its sub-models), so this mirrors `_audit_auto_complete_flag`.
        Best-effort: a failure is logged and never blocks the edit.

        The NAMES travel with the ids. An audit row that records
        `category: 4 -> 7` is unreadable a year later, and by then the
        catalog row may have been renamed or archived."""
        try:
            _scope = audit_context.get_current_actor_scope() or {}
            if not _scope:
                _scope = (
                    audit_context.snapshot_actor_scope(request.user) or {}
                )
            AuditLog.objects.create(
                actor=request.user,
                action=AuditAction.UPDATE,
                target_model="tickets.Ticket",
                target_id=ticket.id,
                changes={
                    "category": {
                        "before": (
                            {"id": old_category.id, "name": old_category.name}
                            if old_category
                            else None
                        ),
                        "after": (
                            {"id": new_category.id, "name": new_category.name}
                            if new_category
                            else None
                        ),
                    }
                },
                request_ip=audit_context.get_current_request_ip(),
                request_id=audit_context.get_current_request_id(),
                reason=audit_context.get_current_reason(),
                actor_scope=_scope,
            )
        except Exception:  # pragma: no cover — audit must not block the edit
            _audit_logger.exception(
                "audit: failed to record ticket category change #%s",
                ticket.id,
            )

    @action(detail=True, methods=["post"], url_path="assign")
    def assign(self, request, pk=None):
        ticket = self.get_object()
        # Sprint 28 Batch 2: `is_staff_role` returns True for STAFF (Sprint
        # 23A widened it so STAFF inherits internal-note / hidden-attachment
        # visibility), but the BM-assign endpoint is reserved for the
        # provider-admin / building-manager triad. Gate explicitly on the
        # allowed role set. Audit row 26 + master plan Batch 2.
        #
        # Sprint 28 Batch 10: STAFF passes the BM-assign gate only when
        # the actor holds a BuildingStaffVisibility row at level
        # `BUILDING_READ_AND_ASSIGN` for the ticket's building. STAFF
        # without an explicit B3 row stays 403 (preserves the Batch 2
        # block). The multi-staff endpoint at
        # `/api/tickets/<id>/staff-assignments/` stays admin-only via
        # `views_staff_assignments.py::_gate_actor` — Batch 10 only
        # touches the single-target `assigned_to` field on Ticket.
        user = request.user
        if user.role == UserRole.STAFF:
            from buildings.models import BuildingStaffVisibility

            if not BuildingStaffVisibility.objects.filter(
                user=user,
                building_id=ticket.building_id,
                visibility_level=BuildingStaffVisibility.VisibilityLevel.BUILDING_READ_AND_ASSIGN,
            ).exists():
                self.permission_denied(
                    request,
                    message="STAFF without BUILDING_READ_AND_ASSIGN cannot assign tickets.",
                )
        elif user.role not in (
            UserRole.SUPER_ADMIN,
            UserRole.COMPANY_ADMIN,
            UserRole.BUILDING_MANAGER,
        ):
            self.permission_denied(
                request,
                message="This role cannot assign tickets.",
            )
        old_assigned_to = ticket.assigned_to
        serializer = TicketAssignSerializer(
            data=request.data,
            context={"request": request, "ticket": ticket},
        )
        serializer.is_valid(raise_exception=True)
        updated = serializer.save()

        old_assigned_to_id = old_assigned_to.id if old_assigned_to else None
        if old_assigned_to_id != updated.assigned_to_id:
            send_ticket_assigned_email(
                updated,
                old_assigned_to=old_assigned_to,
                actor=request.user,
            )
            if old_assigned_to is not None:
                send_ticket_unassigned_email(
                    updated,
                    recipient_user=old_assigned_to,
                    actor=request.user,
                )

        return Response(
            TicketDetailSerializer(updated, context={"request": request}).data,
            status=status.HTTP_200_OK,
        )

    @action(detail=True, methods=["post"], url_path="unable-to-complete")
    def unable_to_complete(self, request, pk=None):
        """
        Sprint 10B — a STAFF member assigned to the ticket reports they
        could NOT complete the work. This is a thin wrapper over the
        EXISTING state machine: it always drives
        `IN_PROGRESS -> WAITING_MANAGER_REVIEW` with an "[UNABLE TO
        COMPLETE]" note so the responsible manager picks it up and
        reschedules / reassigns via the existing flows.

        It never marks the ticket completed and never sends it to
        customer approval — WAITING_MANAGER_REVIEW is the only target.

        The resulting `TicketStatusHistory` row written by
        `apply_transition` IS the audit/history record (actor =
        changed_by, the unable reason in `note`, old -> new status); we
        do not write a second row.

        Body: {"reason": "...", "evidence_attachment_id": <optional>}.

        Evidence: in Sprint 10B we do NOT build a new upload path. If an
        `evidence_attachment_id` is supplied AND it already references a
        visible `TicketAttachment` on THIS ticket, its filename is woven
        into the note for traceability; otherwise it is ignored. The
        shipped behaviour is reason-only — a photo can be uploaded
        separately through the existing attachment endpoint and referred
        to in the reason text.
        """
        ticket = self.get_object()

        if request.user.role != UserRole.STAFF:
            return Response(
                {
                    "detail": "Only assigned staff can report an inability to complete.",
                    "code": "unable_forbidden",
                },
                status=status.HTTP_403_FORBIDDEN,
            )
        if not TicketStaffAssignment.objects.filter(
            ticket=ticket, user=request.user
        ).exists():
            return Response(
                {
                    "detail": "You are not assigned to this ticket.",
                    "code": "unable_not_assigned",
                },
                status=status.HTTP_403_FORBIDDEN,
            )
        if str(ticket.status) != str(TicketStatus.IN_PROGRESS):
            return Response(
                {
                    "detail": "This ticket is not in progress.",
                    "code": "unable_invalid_state",
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        reason = (request.data.get("reason") or "").strip()
        if not reason:
            return Response(
                {
                    "detail": "A reason is required when reporting an inability to complete.",
                    "code": "unable_reason_required",
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Optional evidence reference (NOT a new upload path). Only an
        # existing, visible attachment already on THIS ticket is woven
        # into the note; anything else is silently ignored so a bad id
        # can't 400 a legitimate unable-to-complete.
        note = f"[UNABLE TO COMPLETE] {reason}"
        evidence_id = request.data.get("evidence_attachment_id")
        if evidence_id is not None:
            attachment = TicketAttachment.objects.filter(
                pk=evidence_id, ticket=ticket, is_hidden=False
            ).first()
            if attachment is not None:
                note = f"{note} (evidence: {attachment.original_filename})"

        old_status = ticket.status
        try:
            # WAITING_MANAGER_REVIEW is the ONLY target. The non-blank
            # `note` satisfies the staff COMPLETION_EVIDENCE_TRANSITIONS
            # gate for the (IN_PROGRESS, WAITING_MANAGER_REVIEW) leg.
            updated = apply_transition(
                ticket=ticket,
                user=request.user,
                to_status=TicketStatus.WAITING_MANAGER_REVIEW,
                note=note,
            )
        except TransitionError as exc:
            return Response(
                {"detail": str(exc), "code": exc.code},
                status=status.HTTP_400_BAD_REQUEST,
            )

        send_ticket_status_changed_email(
            updated,
            old_status=old_status,
            new_status=updated.status,
            actor=request.user,
            is_admin_override=False,
        )
        return Response(
            TicketDetailSerializer(updated, context={"request": request}).data,
            status=status.HTTP_200_OK,
        )

    @action(detail=False, methods=["get"], url_path="stats")
    def stats(self, request):
        scoped = scope_tickets_for(request.user)

        # Sprint 180 §2 — the count chips sit directly above the rows
        # they count, so they have to be counting the same thing. When
        # the caller is hiding finished Extra Work in the list, it
        # passes the same flag here and the counts drop the same rows.
        # Absent / falsy param == the untouched totals every existing
        # caller (the dashboard KPI strip, the status-breakdown panel)
        # already gets.
        if request.query_params.get("hide_finished_extra_work") in {
            "true",
            "True",
            "1",
        }:
            scoped = exclude_finished_extra_work(scoped)

        # Sprint 183 §2 — the SAME work-type parameter the list takes.
        #
        # Sprint 182 gave the Tickets page a work-type control but not
        # this endpoint, so under "Tickets only" every status chip fell
        # back to an em dash: the page had no number to show because it
        # had no way to ask for one. A chip showing a dash is a chip that
        # stopped answering.
        #
        # `apply_is_extra_work` is the LIST's own helper, so the chips
        # and the rows beneath them are counted from one definition, and
        # its two branches are exact complements — which is what makes
        # the two halves sum back to the unfiltered total.
        scoped = apply_is_extra_work(
            scoped,
            parse_is_extra_work(request.query_params.get("is_extra_work")),
        )

        # The chips must count the rows they sit above. A customer's own
        # ticket page pins `?customer=<id>` on the LIST and the chips did
        # not carry it, so every customer's page showed the whole
        # company's totals -- two different customers both reading "25".
        # Same defect as the work-type one directly above, one filter
        # later: the rows narrowed and the counts did not.
        customer_id = request.query_params.get("customer")
        if customer_id:
            try:
                scoped = scoped.filter(customer_id=int(customer_id))
            except (TypeError, ValueError):
                # An unparseable value is no opinion, not an empty page:
                # the same convention `parse_is_extra_work` follows.
                pass

        # Sprint 187 §5 — the work-category narrowing. Third appearance
        # of this exact defect, which is why the block above is copied
        # rather than re-derived: Sprint 185 gave the Tickets page a
        # category dropdown and taught it to the LIST only, so choosing a
        # category narrowed the rows and left the chips above them
        # counting the whole company. Same shape as the work-type dash
        # and the customer's "25", one filter later.
        #
        # `TicketFilter.Meta.fields` already offers `exact` / `in` /
        # `isnull` on this field to the list; the two the page actually
        # sends are mirrored here. Tolerant int parse, exactly as
        # `customer` above — a junk value is no opinion, not a 500.
        category_id = request.query_params.get("category")
        if category_id:
            try:
                scoped = scoped.filter(category_id=int(category_id))
            except (TypeError, ValueError):
                pass

        # "Not yet categorised" is a real state an operator lists and
        # works through (`filters.py` has offered the lookup since
        # Sprint 185), so the chips have to be able to count it too.
        if request.query_params.get("category__isnull") in {
            "true",
            "True",
            "1",
        }:
            scoped = scoped.filter(category__isnull=True)

        status_counts = {row["status"]: row["c"] for row in scoped.values("status").annotate(c=Count("id"))}
        priority_counts = {row["priority"]: row["c"] for row in scoped.values("priority").annotate(c=Count("id"))}

        # Sprint 7B — CONVERTED_TO_EXTRA_WORK is terminal: a converted
        # ticket has left every operational queue and must not count as
        # open / urgent.
        closed_states = {"CLOSED", "APPROVED", "REJECTED", "CONVERTED_TO_EXTRA_WORK"}
        my_open = sum(c for s, c in status_counts.items() if s not in closed_states)
        waiting_customer_approval = status_counts.get("WAITING_CUSTOMER_APPROVAL", 0)
        urgent = scoped.exclude(status__in=closed_states).filter(priority="URGENT").count()
        total = sum(status_counts.values())

        return Response(
            {
                "total": total,
                "by_status": status_counts,
                "by_priority": priority_counts,
                "my_open": my_open,
                "waiting_customer_approval": waiting_customer_approval,
                "urgent": urgent,
            },
            status=status.HTTP_200_OK,
        )

    @action(detail=False, methods=["get"], url_path="stats/by-building")
    def stats_by_building(self, request):
        scoped = scope_tickets_for(request.user)
        # Sprint 7B — CONVERTED_TO_EXTRA_WORK is terminal (see `stats`).
        closed_states = ["CLOSED", "APPROVED", "REJECTED", "CONVERTED_TO_EXTRA_WORK"]

        rows = (
            scoped.values("building_id", "building__name")
            .annotate(
                total=Count("id"),
                open=Count("id", filter=Q(status="OPEN")),
                in_progress=Count("id", filter=Q(status="IN_PROGRESS")),
                waiting_customer_approval=Count(
                    "id", filter=Q(status="WAITING_CUSTOMER_APPROVAL")
                ),
                urgent=Count(
                    "id",
                    filter=Q(priority="URGENT") & ~Q(status__in=closed_states),
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
                    "open": row["open"],
                    "in_progress": row["in_progress"],
                    "waiting_customer_approval": row["waiting_customer_approval"],
                    "urgent": row["urgent"],
                }
                for row in rows
            ],
            status=status.HTTP_200_OK,
        )

    @action(detail=True, methods=["get"], url_path="assignable-managers")
    def assignable_managers(self, request, pk=None):
        ticket = self.get_object()

        if not is_staff_role(request.user):
            self.permission_denied(
                request,
                message="Customer users cannot view assignable managers.",
            )

        managers = [
            assignment.user
            for assignment in BuildingManagerAssignment.objects.filter(
                building_id=ticket.building_id,
                user__is_active=True,
                user__deleted_at__isnull=True,
                user__role=UserRole.BUILDING_MANAGER,
            )
            .select_related("user")
            .order_by("user__email")
        ]

        return Response(
            TicketAssignableManagerSerializer(managers, many=True).data,
            status=status.HTTP_200_OK,
        )

    @action(detail=True, methods=["get"], url_path="staff-completion-route")
    def staff_completion_route(self, request, pk=None):
        """
        Sprint 28 Batch 11 — read-only helper for the frontend completion
        modal. Returns the resolved routing destination for STAFF on this
        ticket: "manager_review" (default) or "customer_approval"
        (configured per BuildingStaffVisibility.staff_completion_routes_to_customer).

        Authorization: STAFF must have a TicketStaffAssignment row for
        the ticket. Provider operators in scope (SUPER_ADMIN,
        COMPANY_ADMIN, BUILDING_MANAGER for the ticket's building) get
        the route a hypothetical STAFF on this ticket would see; pass
        `?staff_id=<id>` to ask about a specific STAFF user (useful for
        on-behalf flows). Without `staff_id` a provider operator gets
        the conservative "manager_review" default. Out-of-scope -> 404
        (not 403, to avoid leaking ticket existence).
        """
        from buildings.models import BuildingStaffVisibility
        from .models import TicketStaffAssignment

        ticket = self.get_object()  # 404 if out of scope per scope_tickets_for
        user = request.user

        if user.role == UserRole.STAFF:
            if not TicketStaffAssignment.objects.filter(
                ticket=ticket, user=user
            ).exists():
                raise Http404
            staff_user = user
        elif user.role in (
            UserRole.SUPER_ADMIN,
            UserRole.COMPANY_ADMIN,
            UserRole.BUILDING_MANAGER,
        ):
            staff_id = request.query_params.get("staff_id")
            if staff_id is None:
                return Response({"route": "manager_review"})
            from accounts.models import User

            try:
                staff_user = User.objects.get(
                    pk=staff_id, role=UserRole.STAFF, is_active=True
                )
            except (User.DoesNotExist, ValueError, TypeError):
                raise Http404
            if not TicketStaffAssignment.objects.filter(
                ticket=ticket, user=staff_user
            ).exists():
                raise Http404
        else:
            raise Http404

        bsv = BuildingStaffVisibility.objects.filter(
            user=staff_user, building_id=ticket.building_id
        ).first()
        routes_to_customer = bool(
            bsv and bsv.staff_completion_routes_to_customer
        )
        return Response(
            {
                "route": (
                    "customer_approval"
                    if routes_to_customer
                    else "manager_review"
                )
            }
        )

    @action(detail=True, methods=["get"], url_path="assignable-staff")
    def assignable_staff(self, request, pk=None):
        """
        Sprint 25A — eligible STAFF users for direct admin/manager
        assignment to this ticket. The matching add/remove endpoints
        live at `/api/tickets/<id>/staff-assignments/[/<assignment_id>/]`
        (see `views_staff_assignments.py`). Eligibility is:
          - role=STAFF
          - active StaffProfile
          - BuildingStaffVisibility on the ticket's building
        """
        from .views_staff_assignments import assignable_staff_view

        ticket = self.get_object()
        return assignable_staff_view(request, ticket)


class TicketMessageListCreateView(generics.ListCreateAPIView):
    serializer_class = TicketMessageSerializer
    permission_classes = [IsAuthenticatedAndActive, CanPostMessage]

    def _get_ticket(self):
        ticket_id = self.kwargs["ticket_id"]
        ticket = get_object_or_404(Ticket, pk=ticket_id)
        if not scope_tickets_for(self.request.user).filter(pk=ticket.pk).exists():
            raise Http404("Ticket not found.")
        self.check_object_permissions(self.request, ticket)
        return ticket

    def get_queryset(self):
        ticket = self._get_ticket()
        qs = (
            TicketMessage.objects.filter(ticket=ticket)
            .select_related("author")
            .prefetch_related("directed_to")
        )
        # M1 B2 — route through the SINGLE visibility chokepoint. It layers
        # the (unchanged) B7 role/is_hidden four-tier filter AND the M1 B2
        # RESTRICTED party filter (visible iff author or directed_to member,
        # for EVERY role including provider management). See
        # tickets.permissions.filter_messages_visible_to.
        qs = filter_messages_visible_to(qs, self.request.user)
        return qs.order_by("created_at")

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context["ticket"] = self._get_ticket()
        return context

    def perform_create(self, serializer):
        ticket = self._get_ticket()
        user = self.request.user

        # M1 B5 — the serializer's validate() / validate_message_type is now
        # the AUTHORITATIVE posting gate (the POSTING table, via
        # `_user_may_post_message_type`), rejecting every disallowed
        # (author, tier) combination with HTTP 400 before we get here. We
        # therefore save the validated tier verbatim — no silent
        # force-normalise, which would mis-save a customer's CUSTOMER_INTERNAL
        # as PUBLIC_REPLY and contradicts the new reject-don't-coerce
        # contract.
        message_type = serializer.validated_data.get(
            "message_type", TicketMessageType.PUBLIC_REPLY
        )

        message = serializer.save(
            ticket=ticket,
            author=user,
            message_type=message_type,
            # B7 — only PROVIDER_INTERNAL (INTERNAL_NOTE) is auto-
            # hidden. STAFF_OPERATIONAL and STAFF_COMPLETION remain
            # visible to their respective audiences via the queryset
            # filter, not via `is_hidden`.
            is_hidden=(message_type == TicketMessageType.INTERNAL_NOTE),
        )

        # First staff response stamps first_response_at on the ticket.
        if is_staff_role(user):
            ticket.mark_first_response_if_needed()

        # M1 B1 — emit in-app notifications for this message. Best-effort:
        # the message is already saved, and a failure to fan out
        # notifications must never fail the message POST. The error is
        # logged (not silently swallowed) so a real bug stays visible.
        try:
            emit_ticket_message_notifications(message, actor=user)
        except Exception:  # noqa: BLE001 — best-effort fan-out, logged below
            _audit_logger.exception(
                "Failed to emit in-app notifications for ticket message %s",
                message.id,
            )

        return message


def _recipient_side(user):
    """Bucket a directed-recipient candidate so the picker can group/label
    them: provider management, field staff, or customer-side."""
    if is_provider_management_role(user):
        return "provider"
    if getattr(user, "role", None) == UserRole.STAFF:
        return "staff"
    return "customer"


class TicketMessageRecipientsView(generics.GenericAPIView):
    """M1 B3 — directed-recipients source for the composer's "notify
    specific people" picker.

    GET /api/tickets/<ticket_id>/message-recipients/?message_type=<tier>

    Returns the users who are VALID directed_to targets for that tier on
    this ticket = the B1 read-visible audience
    (notifications.services.ticket_message_audience, which reuses the B1
    resolvers) INTERSECTED with message_type_visible_to_user AND
    user_has_scope_for_ticket, MINUS the caller. Every returned user
    therefore passes the B1 directed_to validation, so the picker can never
    offer a target the POST would 400 (esp. INTERNAL_NOTE -> no customer;
    STAFF_OPERATIONAL -> no customer; out-of-scope users excluded).

    Scope-gated exactly like the messages endpoint (same permission classes
    + scope_tickets_for guard): a caller without ticket access gets 404.
    """

    permission_classes = [IsAuthenticatedAndActive, CanPostMessage]

    def _get_ticket(self):
        ticket = get_object_or_404(Ticket, pk=self.kwargs["ticket_id"])
        if not scope_tickets_for(self.request.user).filter(pk=ticket.pk).exists():
            raise Http404("Ticket not found.")
        self.check_object_permissions(self.request, ticket)
        return ticket

    def get(self, request, ticket_id):
        ticket = self._get_ticket()
        caller = request.user
        message_type = request.query_params.get(
            "message_type", TicketMessageType.PUBLIC_REPLY
        )
        if message_type not in set(TicketMessageType.values):
            return Response(
                {"detail": "Invalid message_type.", "code": "invalid_message_type"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # M1 B5 — the picker is SIDE-AWARE by the CALLER:
        #   * STAFF caller  -> no picker at all (field staff never direct a
        #     message). Empty list, 200 — the FE renders nothing.
        #   * CUST caller   -> only customer-side candidates (a customer can
        #     never direct a message at a provider user, on any tier).
        #   * MGMT / SA     -> the full tier audience (provider + customer
        #     as applicable), as before.
        if getattr(caller, "role", None) == UserRole.STAFF:
            return Response({"results": []})
        caller_is_customer = is_customer_side(caller)

        results = []
        for user in ticket_message_audience(ticket, message_type):
            if user.id == caller.id:
                continue
            # Belt-and-suspenders: the audience is already type-scoped, but
            # intersect with the exact predicates the serializer validates
            # so the endpoint output can never drift wider than valid.
            if not message_type_visible_to_user(user, message_type):
                continue
            if not user_has_scope_for_ticket(user, ticket):
                continue
            side = _recipient_side(user)
            # A customer composer may only ever direct at customer-side
            # people — drop provider/staff candidates from a customer caller
            # so the picker can never offer a target the POST would 400
            # (directed_to_must_be_customer_side).
            if caller_is_customer and side != "customer":
                continue
            results.append(
                {
                    "id": user.id,
                    "full_name": user.full_name or user.email.split("@")[0],
                    "side": side,
                }
            )
        return Response({"results": results})


class TicketAttachmentListCreateView(generics.ListCreateAPIView):
    serializer_class = TicketAttachmentSerializer
    permission_classes = [IsAuthenticatedAndActive, CanViewTicket]
    parser_classes = [MultiPartParser, FormParser]

    def _get_ticket(self):
        ticket_id = self.kwargs["ticket_id"]
        ticket = get_object_or_404(Ticket, pk=ticket_id)

        if not scope_tickets_for(self.request.user).filter(pk=ticket.pk).exists():
            raise Http404("Ticket not found.")

        self.check_object_permissions(self.request, ticket)
        return ticket

    def get_queryset(self):
        ticket = self._get_ticket()
        qs = TicketAttachment.objects.filter(ticket=ticket).select_related(
            "uploaded_by",
            "message",
        )

        user = self.request.user
        # B7 — mirror the message queryset's four-tier filter. Provider
        # management sees every attachment; STAFF sees PUBLIC_REPLY +
        # STAFF_OPERATIONAL + STAFF_COMPLETION attachments;
        # customer-side sees PUBLIC_REPLY + STAFF_COMPLETION
        # attachments only.
        if not is_provider_management_role(user):
            qs = qs.filter(is_hidden=False)
            qs = qs.exclude(message__is_hidden=True)
            qs = qs.exclude(
                message__message_type=TicketMessageType.INTERNAL_NOTE
            )
            if not is_staff_role(user):
                qs = qs.exclude(
                    message__message_type=TicketMessageType.STAFF_OPERATIONAL
                )
                # Sprint 191 §2.5 — the customer wall. A customer-side
                # caller sees ONLY what has been released to them: their
                # own uploads (created CUSTOMER) plus whatever a provider
                # manager has promoted. `is_staff_role` is the whole
                # provider side (SA / CA / BM / STAFF), so this branch is
                # customer-side only and the worker who took the photo
                # keeps seeing it while it is INTERNAL.
                qs = qs.filter(visibility=AttachmentVisibility.CUSTOMER)

        return qs.order_by("-created_at")

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context["ticket"] = self._get_ticket()
        return context

    def _resolve_evidence_slot(self, ticket, user, slot_id):
        """Sprint 12 — resolve + scope-check an optional completion-evidence
        slot link. CUSTOMER_USER may never link to an internal staff slot;
        the slot must belong to THIS ticket; STAFF may link only their OWN
        slot; provider managers/admins may link any in-scope slot (the
        ticket is already scoped by `_get_ticket`)."""
        if user.role == UserRole.CUSTOMER_USER:
            raise ValidationError(
                {
                    "staff_assignment_id": [
                        ErrorDetail(
                            "Customers cannot link evidence to a staff slot.",
                            code="slot_link_forbidden",
                        )
                    ]
                }
            )
        slot = TicketStaffAssignment.objects.filter(pk=slot_id).first()
        if slot is None or slot.ticket_id != ticket.id:
            raise ValidationError(
                {
                    "staff_assignment_id": [
                        ErrorDetail(
                            "The staff slot does not belong to this ticket.",
                            code="slot_ticket_mismatch",
                        )
                    ]
                }
            )
        # Only the STAFF worker is restricted to their OWN slot; provider
        # managers/admins (is_staff_role would also be True for them) may
        # link any in-scope slot, so check the concrete STAFF role here.
        if user.role == UserRole.STAFF and slot.user_id != user.id:
            raise ValidationError(
                {
                    "staff_assignment_id": [
                        ErrorDetail(
                            "Staff may only attach evidence to their own slot.",
                            code="slot_not_owned",
                        )
                    ]
                }
            )
        return slot

    def _default_visibility(self, ticket, user):
        """Sprint 191 §2.5 — the level an upload lands at when the
        uploader did not choose one. THE one place that default lives.

        Three cases, in order:

          1. A customer-side uploader gets CUSTOMER. Their own file must
             not be hidden from them, and it was never internal in the
             first place.
          2. A provider-side upload on a work whose
             `staff_uploads_customer_visible` is set gets CUSTOMER — the
             per-work opt-in for the customers who asked to see the job
             as it happens.
          3. Everything else gets INTERNAL. That is the decision: nothing
             a worker uploads crosses the wall until a provider promotes
             it.

        Provider management can still override at upload time by sending
        `visibility` (see `TicketAttachmentSerializer.validate_
        visibility`); STAFF and customer-side cannot, and get this.
        """
        if not is_staff_role(user):
            return AttachmentVisibility.CUSTOMER
        if ticket.staff_uploads_customer_visible:
            return AttachmentVisibility.CUSTOMER
        return AttachmentVisibility.INTERNAL

    def perform_create(self, serializer):
        ticket = self._get_ticket()
        user = self.request.user
        uploaded_file = serializer.validated_data["file"]

        is_hidden = serializer.validated_data.get("is_hidden", False)
        visibility = serializer.validated_data.get(
            "visibility"
        ) or self._default_visibility(ticket, user)

        # Sprint 12 — optional per-slot evidence link (pop the write-only
        # input so it is not double-applied via validated_data).
        slot_id = serializer.validated_data.pop("staff_assignment_id", None)
        slot = (
            self._resolve_evidence_slot(ticket, user, slot_id)
            if slot_id is not None
            else None
        )

        serializer.save(
            ticket=ticket,
            uploaded_by=user,
            staff_assignment=slot,
            original_filename=uploaded_file.name,
            mime_type=getattr(uploaded_file, "content_type", "") or "application/octet-stream",
            file_size=getattr(uploaded_file, "size", 0),
            is_hidden=is_hidden,
            visibility=visibility,
        )


class TicketAttachmentVisibilityView(generics.GenericAPIView):
    """
    Sprint 191 §2.5 — promote ONE attachment across the customer wall,
    or pull it back.

    `PATCH /api/tickets/<ticket_id>/attachments/<attachment_id>/visibility/`
    with `{"visibility": "CUSTOMER"}` (or `"INTERNAL"`).

    Provider management only (SUPER_ADMIN / COMPANY_ADMIN /
    BUILDING_MANAGER). The worker who took the photo cannot publish it,
    which is the whole decision: a provider decides what the customer
    sees.

    Tenant scoping is the P0 surface here. The role gate answers 403
    FIRST (a wrong role learns nothing about which tickets exist), and
    the ticket is then resolved through `scope_tickets_for(user)`, so a
    manager of another tenant gets a 404 and cannot promote a photo
    across a tenant boundary. The attachment is looked up with
    `ticket=ticket`, so an id from another ticket 404s too.

    The audit row is automatic: `TicketAttachment` is registered in the
    generic CRUD trio in `audit/signals.py`, whose UPDATE handler diffs
    only the fields that actually changed — so a promote lands as one
    AuditLog row reading visibility INTERNAL -> CUSTOMER, with the actor
    on it (Addendum A §A.3.3: visibility changes are audited).

    It does NOT touch `is_hidden` and it does NOT touch `phase`: this
    endpoint moves the customer wall and nothing else. Completion
    evidence is unaffected — the gates count `is_hidden=False` rows.
    """

    permission_classes = [IsAuthenticatedAndActive]

    def patch(self, request, ticket_id, attachment_id):
        # Role gate FIRST, before any object lookup, so a wrong role gets
        # a stable 403 rather than a scope-driven 404 (the shape the
        # auto-complete-flag / schedule actions already use).
        if not is_provider_management_role(request.user):
            return Response(
                {
                    "detail": "Only provider management can change an "
                    "attachment's visibility.",
                    "code": "attachment_visibility_forbidden",
                },
                status=status.HTTP_403_FORBIDDEN,
            )

        ticket = get_object_or_404(Ticket, pk=ticket_id)
        if not scope_tickets_for(request.user).filter(pk=ticket.pk).exists():
            raise Http404("Ticket not found.")

        attachment = get_object_or_404(
            TicketAttachment,
            pk=attachment_id,
            ticket=ticket,
        )

        ser = TicketAttachmentVisibilitySerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        new_visibility = ser.validated_data["visibility"]

        # Releasing a row the OTHER filters would still hide would
        # produce a lie in the UI: the pill would read "customer
        # visible" while `is_hidden` / the parent note's tier keeps the
        # customer from ever seeing it. Refuse instead, and say which
        # flag is in the way. The two axes stay independent — this is a
        # consistency check, not one axis deciding the other.
        if new_visibility == AttachmentVisibility.CUSTOMER:
            blocked_by_hidden = attachment.is_hidden
            blocked_by_message = bool(
                attachment.message_id
                and (
                    attachment.message.is_hidden
                    or attachment.message.message_type
                    in (
                        TicketMessageType.INTERNAL_NOTE,
                        TicketMessageType.STAFF_OPERATIONAL,
                    )
                )
            )
            if blocked_by_hidden or blocked_by_message:
                return Response(
                    {
                        "detail": (
                            "This attachment is hidden (moderation flag) "
                            "and cannot be made customer-visible."
                            if blocked_by_hidden
                            else "This attachment belongs to an internal "
                            "note and cannot be made customer-visible."
                        ),
                        "code": "attachment_visibility_conflict",
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )

        if attachment.visibility != new_visibility:
            attachment.visibility = new_visibility
            attachment.save(update_fields=["visibility"])

        return Response(
            TicketAttachmentSerializer(
                attachment, context={"request": request, "ticket": ticket}
            ).data,
            status=status.HTTP_200_OK,
        )


class TicketAttachmentDownloadView(generics.GenericAPIView):
    permission_classes = [IsAuthenticatedAndActive]

    def get(self, request, ticket_id, attachment_id):
        ticket = get_object_or_404(Ticket, pk=ticket_id)

        if not scope_tickets_for(request.user).filter(pk=ticket.pk).exists():
            raise Http404("Ticket not found.")

        attachment = get_object_or_404(
            TicketAttachment,
            pk=attachment_id,
            ticket=ticket,
        )

        # B7 — derive the attachment's visibility tier from the parent
        # message and apply the four-tier rule:
        #
        #   * INTERNAL_NOTE (PROVIDER_INTERNAL) — provider management only.
        #   * STAFF_OPERATIONAL — provider management + STAFF only.
        #   * Hidden flag — moderation; provider management only.
        #   * Other (PUBLIC_REPLY / STAFF_COMPLETION / no parent message)
        #     — everyone in scope; existing handler applies.
        message_internal = (
            attachment.message_id
            and attachment.message.message_type
            == TicketMessageType.INTERNAL_NOTE
        )
        message_hidden = (
            attachment.message_id and attachment.message.is_hidden
        )
        message_staff_operational = (
            attachment.message_id
            and attachment.message.message_type
            == TicketMessageType.STAFF_OPERATIONAL
        )
        provider_management_only = (
            attachment.is_hidden or message_internal or message_hidden
        )
        if provider_management_only and not is_provider_management_role(
            request.user
        ):
            self.permission_denied(
                request, message="Attachment not found in your scope."
            )
        if message_staff_operational and not is_staff_role(request.user):
            self.permission_denied(
                request, message="Attachment not found in your scope."
            )
        # Sprint 191 §2.5 — the customer wall, mirroring the list
        # queryset. An INTERNAL row is provider-side only; the download
        # URL is the second way to reach a file and must refuse the same
        # rows the list hides, or the wall is decorative.
        if (
            attachment.visibility != AttachmentVisibility.CUSTOMER
            and not is_staff_role(request.user)
        ):
            self.permission_denied(
                request, message="Attachment not found in your scope."
            )

        if not attachment.file:
            raise Http404("File not found.")

        return FileResponse(
            attachment.file.open("rb"),
            as_attachment=True,
            filename=attachment.original_filename,
        )
