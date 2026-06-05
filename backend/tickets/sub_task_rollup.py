"""
Sprint 4 — sub-task completion roll-up.

When a ticket opts into `auto_complete_on_subtasks`, completing the final
outstanding staff-assignment slot auto-advances the ticket from IN_PROGRESS
to WAITING_MANAGER_REVIEW. This is a BEST-EFFORT side effect of slot
completion: the slot save is the primary action and must always succeed, so
a failed transition (e.g. a concurrent status change, or a STAFF actor whose
completion routes to customer-approval) is logged and swallowed.

Layered + back-compat: with the flag off, or with no sub-tasks, NOTHING
changes — completion stays a manual manager/staff action exactly as today.
"""
from __future__ import annotations

import logging

from .models import StaffAssignmentSlotStatus, Ticket, TicketStatus
from .state_machine import TransitionError, apply_transition

logger = logging.getLogger(__name__)

_AUTO_COMPLETE_NOTE = "Auto-advanced to manager review: all sub-tasks completed."


def ticket_all_subtasks_done(ticket) -> bool:
    """
    True iff the ticket is ready to auto-advance on sub-task completion.

    Returns False (never auto-complete) when:
      * the ticket has ZERO sub-tasks — avoids the vacuous-truth bug of
        auto-completing a flagged ticket that was never split;
      * ANY sub-task is not `is_done()` (a sub-task with zero assignments
        is itself not done);
      * ANY loose assignment (sub_task IS NULL — the default un-split work)
        is still non-COMPLETED.
    Otherwise True.
    """
    sub_tasks = list(ticket.sub_tasks.all())
    if not sub_tasks:
        return False
    if any(not st.is_done() for st in sub_tasks):
        return False
    loose_incomplete = (
        ticket.staff_assignments.filter(sub_task__isnull=True)
        .exclude(slot_status=StaffAssignmentSlotStatus.COMPLETED)
        .exists()
    )
    if loose_incomplete:
        return False
    return True


def maybe_auto_complete_ticket_on_subtasks(ticket, user) -> bool:
    """
    Best-effort: advance IN_PROGRESS -> WAITING_MANAGER_REVIEW when the
    ticket opted in AND every sub-task (plus all loose work) is COMPLETED.

    Returns True iff the transition was applied. Any `TransitionError`
    (forbidden transition, stale status, staff route mismatch, ...) is
    logged and swallowed — the caller's slot completion must still commit.
    `apply_transition` is itself `@transaction.atomic`, so a failed call
    rolls back its own savepoint and leaves the outer slot-save intact.

    Concurrency: the readiness check runs against a `select_for_update()`
    re-read of the ticket so two staff finishing the final two slots at once
    serialize on the ticket row. Under READ COMMITTED an un-locked readiness
    SELECT would let each transaction miss the other's still-uncommitted slot
    completion (TOCTOU) and skip the transition, stranding a fully-done ticket
    in IN_PROGRESS. The lock makes the second finisher block until the first
    commits, then re-read the now-COMMITTED sibling and fire the transition.
    Safe + deadlock-free: the caller's slot PATCH is `@transaction.atomic`, so
    the just-saved slot is visible (own write) and only the single ticket row
    is contended (slot rows are never cross-locked). `apply_transition` does
    its own `select_for_update` + stale-status guard on the same row (same tx,
    a no-op re-lock).
    """
    if not ticket.auto_complete_on_subtasks:
        return False
    locked = Ticket.objects.select_for_update().get(pk=ticket.pk)
    if str(locked.status) != str(TicketStatus.IN_PROGRESS):
        return False
    if not ticket_all_subtasks_done(locked):
        return False
    try:
        apply_transition(
            locked,
            user,
            TicketStatus.WAITING_MANAGER_REVIEW,
            note=_AUTO_COMPLETE_NOTE,
        )
        return True
    except TransitionError as exc:
        logger.warning(
            "sub-task auto-complete roll-up skipped for ticket #%s: %s (code=%s)",
            getattr(locked, "pk", None),
            exc,
            getattr(exc, "code", None),
        )
        return False
