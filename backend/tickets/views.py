import logging

from django.db.models import Count, Q
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import generics, mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.response import Response

from accounts.models import UserRole
from accounts.permissions import (
    IsAuthenticatedAndActive,
    is_provider_management_role,
    is_staff_role,
)
from accounts.scoping import scope_tickets_for
from audit.models import AuditAction, AuditLog
from audit import context as audit_context
from notifications.services import (
    send_ticket_assigned_email,
    send_ticket_created_email,
    send_ticket_status_changed_email,
    send_ticket_unassigned_email,
)

from .filters import TicketFilter
from .models import (
    Ticket,
    TicketAttachment,
    TicketMessage,
    TicketMessageType,
    TicketStatus,
)
from buildings.models import BuildingManagerAssignment
from .permissions import CanPostMessage, CanViewTicket, user_has_scope_for_ticket
from .serializers import (
    TicketAssignableManagerSerializer,
    TicketAssignSerializer,
    TicketAttachmentSerializer,
    TicketConvertToExtraWorkSerializer,
    TicketCreateSerializer,
    TicketDetailSerializer,
    TicketListSerializer,
    TicketMessageSerializer,
    TicketStatusChangeSerializer,
)


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
            qs = qs.prefetch_related("status_history", "status_history__changed_by")
        if self.action == "list":
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
        ticket = serializer.save()
        send_ticket_created_email(ticket, actor=self.request.user)

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
        is_admin_override = (
            is_staff_role(request.user)
            and old_status == "WAITING_CUSTOMER_APPROVAL"
            and updated.status in {"APPROVED", "REJECTED"}
        )
        send_ticket_status_changed_email(
            updated,
            old_status=old_status,
            new_status=updated.status,
            actor=request.user,
            is_admin_override=is_admin_override,
        )
        return Response(
            TicketDetailSerializer(updated, context={"request": request}).data,
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


    @action(detail=False, methods=["get"], url_path="stats")
    def stats(self, request):
        scoped = scope_tickets_for(request.user)

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
        live at `/api/tickets/<id>/staff-assignments/[/<user_id>/]`
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
        qs = TicketMessage.objects.filter(ticket=ticket).select_related("author")
        user = self.request.user
        # B7 — four-tier note visibility. The three tiers below each
        # exclude a specific subset of `message_type` values:
        #
        #   * Provider management (SA/COMPANY_ADMIN/BM): sees every
        #     tier including INTERNAL_NOTE (PROVIDER_INTERNAL).
        #   * STAFF: sees PUBLIC_REPLY + STAFF_OPERATIONAL +
        #     STAFF_COMPLETION. Hidden from INTERNAL_NOTE
        #     (PROVIDER_INTERNAL) — STAFF must never see commercial /
        #     management notes per §9.2 of the canonical doc.
        #   * Customer-side: sees PUBLIC_REPLY + STAFF_COMPLETION.
        #     Hidden from INTERNAL_NOTE and STAFF_OPERATIONAL.
        #
        # `is_hidden=True` is a moderation flag; only provider
        # management retains visibility on hidden rows.
        if not is_provider_management_role(user):
            qs = qs.filter(is_hidden=False)
            qs = qs.exclude(message_type=TicketMessageType.INTERNAL_NOTE)
            if not is_staff_role(user):
                # Customer-side: also exclude STAFF_OPERATIONAL.
                qs = qs.exclude(
                    message_type=TicketMessageType.STAFF_OPERATIONAL
                )
        return qs.order_by("created_at")

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context["ticket"] = self._get_ticket()
        return context

    def perform_create(self, serializer):
        ticket = self._get_ticket()
        user = self.request.user

        message_type = serializer.validated_data.get(
            "message_type", TicketMessageType.PUBLIC_REPLY
        )
        # CUSTOMER_USER and any non-provider-side actor is force-
        # normalised to PUBLIC_REPLY (defence in depth — the
        # serializer's `validate_message_type` already rejects
        # PROVIDER_INTERNAL / STAFF_OPERATIONAL / STAFF_COMPLETION
        # from non-provider-side actors). Provider-side actors
        # (provider management + STAFF) keep the validated value
        # so STAFF can author STAFF_OPERATIONAL / STAFF_COMPLETION
        # and provider management can author INTERNAL_NOTE.
        if not is_staff_role(user):
            message_type = TicketMessageType.PUBLIC_REPLY

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

        return message



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

        return qs.order_by("-created_at")

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context["ticket"] = self._get_ticket()
        return context

    def perform_create(self, serializer):
        ticket = self._get_ticket()
        user = self.request.user
        uploaded_file = serializer.validated_data["file"]

        is_hidden = serializer.validated_data.get("is_hidden", False)

        serializer.save(
            ticket=ticket,
            uploaded_by=user,
            original_filename=uploaded_file.name,
            mime_type=getattr(uploaded_file, "content_type", "") or "application/octet-stream",
            file_size=getattr(uploaded_file, "size", 0),
            is_hidden=is_hidden,
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

        if not attachment.file:
            raise Http404("File not found.")

        return FileResponse(
            attachment.file.open("rb"),
            as_attachment=True,
            filename=attachment.original_filename,
        )
