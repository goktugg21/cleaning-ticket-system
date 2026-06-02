"""Sprint 14A — unified, read-only ticket audit timeline.

A single GET endpoint that aggregates every audit-relevant fact about one
ticket into a flat, timestamp-sorted list. READ-SIDE ONLY: it performs NO
writes and registers NO new AuditLog rows — surfacing the workflow trail
must never double-write it (matrix H-11).

The timeline merges four sources:

  * status_history            — TicketStatusHistory rows (the H-11 workflow
                                trail: status changes, schedule annotations,
                                unable-to-complete, conversion, overrides).
  * audit_log                 — generic AuditLog rows whose target is this
                                ticket (soft-delete + manager/staff
                                assignment membership events).
  * extra_work_status_history — ExtraWorkStatusHistory rows of a linked EW
                                (spawned-from or converted-source), plus a
                                lightweight link reference per linked EW.
  * planned_occurrence_link   — a reference when the ticket originates from
                                a planned/recurring occurrence.

Privacy floor: this is provider-internal audit. Only SUPER_ADMIN,
COMPANY_ADMIN and BUILDING_MANAGER are admitted (CUSTOMER_USER + STAFF ->
403). Scope is enforced per actor: a ticket outside the actor's scope
returns 404 so existence is not leaked across providers / buildings.
"""
from __future__ import annotations

from django.utils import timezone
from rest_framework.permissions import BasePermission
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.models import UserRole
from accounts.scoping import scope_tickets_for


# Provider-internal audit roles. STAFF and CUSTOMER_USER are denied
# outright (403) — they must never see commercial / provider-internal
# audit detail. Mirrors reports.IsReportsConsumer / planned_work
# IsProviderManager shape.
_PROVIDER_AUDIT_ROLES = frozenset(
    {
        UserRole.SUPER_ADMIN,
        UserRole.COMPANY_ADMIN,
        UserRole.BUILDING_MANAGER,
    }
)


class IsTicketAuditConsumer(BasePermission):
    """Admit only provider-management roles; STAFF + CUSTOMER_USER -> 403."""

    def has_permission(self, request, view) -> bool:
        user = request.user
        if not user or not user.is_authenticated:
            return False
        if not getattr(user, "is_active", False):
            return False
        return getattr(user, "role", None) in _PROVIDER_AUDIT_ROLES


def _iso(value):
    return value.isoformat() if value is not None else None


class TicketAuditTimelineView(APIView):
    """GET /api/audit/tickets/<ticket_id>/timeline/ — unified read-only feed."""

    permission_classes = [IsTicketAuditConsumer]

    def get(self, request, ticket_id: int):
        # Scope-check via the canonical ticket scope helper: a ticket the
        # actor cannot see is reported as 404 (do not leak existence
        # across providers / buildings). SUPER_ADMIN sees all; CA is
        # bounded to their company tickets; BM to their assigned-building
        # tickets — exactly the company / building anchors the brief asks
        # for, with no caller-supplied id trusted.
        ticket = (
            scope_tickets_for(request.user)
            .filter(pk=ticket_id)
            .select_related("extra_work_request", "planned_occurrence")
            .first()
        )
        if ticket is None:
            return Response({"detail": "Not found."}, status=404)

        timeline: list[dict] = []

        # --- status_history (the H-11 workflow trail) ----------------------
        for row in (
            ticket.status_history.select_related("changed_by")
            .all()
            .order_by("created_at", "id")
        ):
            timeline.append(
                {
                    "source": "status_history",
                    "timestamp": _iso(row.created_at),
                    "old_status": row.old_status,
                    "new_status": row.new_status,
                    "note": row.note,
                    "is_override": row.is_override,
                    "override_reason": row.override_reason,
                    "changed_by_email": (
                        row.changed_by.email if row.changed_by_id else None
                    ),
                }
            )

        # --- audit_log (soft-delete + assignment membership events) --------
        # The generic AuditLog labels a row by the MUTATED model, not by
        # its parent ticket. Three target_models can carry ticket-anchored
        # audit facts:
        #
        #   * "tickets.Ticket"                 — target_id == ticket.id.
        #     (Reserved: the Ticket model is not in the generic CRUD trio
        #     today, but a future soft-delete/registration would land here;
        #     querying it now keeps the timeline forward-compatible.)
        #   * "tickets.TicketStaffAssignment"  — target_id == assignment.pk.
        #   * "tickets.TicketManagerAssignment"— target_id == assignment.pk.
        #
        # For the two assignment tables we resolve the live row pks that
        # belong to THIS ticket and match the audit rows whose target_id is
        # one of them. This surfaces every CREATE event (and any UPDATE) on
        # the ticket's assignments. A DELETE event for an assignment that
        # was subsequently removed leaves no FK row to anchor on; surfacing
        # those is out of scope for this bounded read-side aggregation.
        from audit.models import AuditLog
        from django.db.models import Q
        from tickets.models import TicketManagerAssignment, TicketStaffAssignment

        staff_pks = list(
            TicketStaffAssignment.objects.filter(ticket_id=ticket_id).values_list(
                "id", flat=True
            )
        )
        manager_pks = list(
            TicketManagerAssignment.objects.filter(ticket_id=ticket_id).values_list(
                "id", flat=True
            )
        )

        audit_filter = Q(target_model="tickets.Ticket", target_id=ticket_id)
        if staff_pks:
            audit_filter |= Q(
                target_model="tickets.TicketStaffAssignment",
                target_id__in=staff_pks,
            )
        if manager_pks:
            audit_filter |= Q(
                target_model="tickets.TicketManagerAssignment",
                target_id__in=manager_pks,
            )

        for log in (
            AuditLog.objects.filter(audit_filter)
            .select_related("actor")
            .order_by("created_at", "id")
        ):
            timeline.append(
                {
                    "source": "audit_log",
                    "timestamp": _iso(log.created_at),
                    "target_model": log.target_model,
                    "target_id": log.target_id,
                    "action": log.action,
                    "changes": log.changes,
                    "reason": log.reason,
                    "severity": log.severity,
                    "metadata": log.metadata,
                    "actor_email": log.actor.email if log.actor_id else None,
                }
            )

        # --- extra_work links ---------------------------------------------
        # Collect each related EW exactly once (spawned-from-EW via
        # `extra_work_request`, plus any converted-source EWs via the
        # reverse `converted_extra_work_requests`). De-dup by id so a
        # ticket that is both does not double-list.
        linked_ews: dict[int, object] = {}
        if ticket.extra_work_request_id is not None and ticket.extra_work_request:
            linked_ews[ticket.extra_work_request_id] = ticket.extra_work_request
        for ew in ticket.converted_extra_work_requests.all():
            linked_ews.setdefault(ew.id, ew)

        for ew in linked_ews.values():
            # Bounded: one link reference per EW (timestamped at the EW's
            # creation so it merges sensibly), plus the EW's own status
            # history rows tagged with their own source.
            timeline.append(
                {
                    "source": "extra_work_link",
                    "timestamp": _iso(getattr(ew, "created_at", None)),
                    "extra_work_id": ew.id,
                    "extra_work_status": ew.status,
                    "relation": (
                        "spawned_from"
                        if ew.id == ticket.extra_work_request_id
                        else "converted_source"
                    ),
                }
            )
            for ew_row in ew.status_history.select_related("changed_by").order_by(
                "created_at", "id"
            ):
                timeline.append(
                    {
                        "source": "extra_work_status_history",
                        "timestamp": _iso(ew_row.created_at),
                        "extra_work_id": ew.id,
                        "old_status": ew_row.old_status,
                        "new_status": ew_row.new_status,
                        "note": ew_row.note,
                        "is_override": ew_row.is_override,
                        "changed_by_email": (
                            ew_row.changed_by.email
                            if ew_row.changed_by_id
                            else None
                        ),
                    }
                )

        # --- planned_occurrence link --------------------------------------
        occ = ticket.planned_occurrence
        if occ is not None:
            timeline.append(
                {
                    "source": "planned_occurrence_link",
                    "timestamp": _iso(occ.created_at),
                    "occurrence_id": occ.id,
                    "status": occ.status,
                    "planned_date": (
                        occ.planned_date.isoformat()
                        if occ.planned_date is not None
                        else None
                    ),
                }
            )

        # Stable ascending sort by timestamp. None timestamps (defensive —
        # no source above emits one for a persisted row) sort first. Python's
        # sort is stable, so equal timestamps keep source insertion order.
        timeline.sort(
            key=lambda entry: (entry["timestamp"] is not None, entry["timestamp"])
        )

        return Response(
            {
                "ticket_id": ticket.id,
                "ticket_no": ticket.ticket_no,
                "timeline": timeline,
                "generated_at": timezone.now().isoformat(),
            }
        )
