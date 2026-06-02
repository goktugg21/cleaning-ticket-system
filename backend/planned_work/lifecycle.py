"""Planned-occurrence lifecycle transitions (Sprint 11B Batch 2).

Every status mutation writes a `PlannedOccurrenceStatusHistory` row in
the SAME `transaction.atomic()` block (mirrors the ticket / extra-work
convention). That history row IS the H-11 workflow audit trail for
planned work; it is intentionally NOT registered in the generic
AuditLog `_*_TRACKED_FIELDS`.

`reconcile_occurrence_from_ticket` is the Ticket->occurrence sync entry
point invoked from the post_save signal — it MUST NOT raise (a planned
occurrence problem must never break an unrelated ticket save).
"""
from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Optional

from django.db import transaction
from django.utils import timezone

from tickets.models import Ticket, TicketScheduleStatus, TicketStatus

from .constants import DEFAULT_MISSED_GRACE_DAYS
from .errors import PlannedWorkError
from .models import (
    PlannedOccurrence,
    PlannedOccurrenceStatus,
    PlannedOccurrenceStatusHistory,
)

logger = logging.getLogger("planned_work")

# Sentinel so `actual_date=None` (an explicit clear) is distinguishable
# from "caller did not pass actual_date".
_UNSET = object()

# Status -> the timestamp column stamped when the occurrence enters it.
# RESCHEDULED / PLANNED intentionally stamp nothing.
_STATUS_TIMESTAMP_FIELD = {
    PlannedOccurrenceStatus.TICKET_CREATED: "generated_at",
    PlannedOccurrenceStatus.COMPLETED: "completed_at",
    PlannedOccurrenceStatus.MISSED: "missed_at",
    PlannedOccurrenceStatus.CANCELLED: "cancelled_at",
    PlannedOccurrenceStatus.SKIPPED: "skipped_at",
}


@transaction.atomic
def apply_occurrence_status(
    occurrence: PlannedOccurrence,
    new_status: str,
    *,
    actor=None,
    note: str = "",
    reason: str = "",
    actual_date=_UNSET,
    when=None,
) -> PlannedOccurrence:
    """Transition `occurrence` to `new_status`, stamping the matching
    timestamp column and writing one history row, atomically."""
    when = when or timezone.now()
    old = occurrence.status
    occurrence.status = new_status

    update_fields = ["status", "updated_at"]

    timestamp_field = _STATUS_TIMESTAMP_FIELD.get(new_status)
    if timestamp_field is not None:
        setattr(occurrence, timestamp_field, when)
        update_fields.append(timestamp_field)

    if actual_date is not _UNSET:
        occurrence.actual_date = actual_date
        update_fields.append("actual_date")

    occurrence.save(update_fields=update_fields)

    PlannedOccurrenceStatusHistory.objects.create(
        occurrence=occurrence,
        old_status=old,
        new_status=new_status,
        changed_by=actor,
        note=note or "",
        reason=reason or "",
    )
    return occurrence


def reconcile_occurrence_from_ticket(ticket: Ticket) -> None:
    """Sync a planned occurrence from its linked ticket. NEVER raises.

    Catches both completion (ticket -> APPROVED/CLOSED -> occurrence
    COMPLETED) and reschedule (ticket schedule_status -> RESCHEDULED ->
    occurrence RESCHEDULED, actual_date moved). The occurrence's
    `planned_date` stays immutable; only `actual_date` moves.
    """
    try:
        occ_id = getattr(ticket, "planned_occurrence_id", None)
        if not occ_id:
            return
        occ = PlannedOccurrence.objects.filter(pk=occ_id).first()
        if occ is None:
            return

        # A late completion may still override MISSED, so MISSED is NOT
        # in the terminal set here.
        done = {
            PlannedOccurrenceStatus.COMPLETED,
            PlannedOccurrenceStatus.SKIPPED,
            PlannedOccurrenceStatus.CANCELLED,
        }
        if occ.status in done:
            return

        now = timezone.now()

        if str(ticket.status) in {
            str(TicketStatus.APPROVED),
            str(TicketStatus.CLOSED),
        }:
            if occ.status != PlannedOccurrenceStatus.COMPLETED:
                # Use the LOCAL calendar date: scheduled_start_at is stored
                # in UTC, so a bare .date() on a local-midnight schedule
                # yields the previous UTC day (off-by-one for the
                # planned-vs-actual reporting field). timezone.localtime
                # re-anchors to settings.TIME_ZONE before taking the date.
                actual = (
                    timezone.localtime(ticket.scheduled_start_at).date()
                    if ticket.scheduled_start_at
                    else timezone.localdate()
                )
                apply_occurrence_status(
                    occ,
                    PlannedOccurrenceStatus.COMPLETED,
                    note="Auto-completed: linked ticket reached %s."
                    % ticket.status,
                    actual_date=actual,
                    when=now,
                )
            return

        if str(ticket.schedule_status) == str(
            TicketScheduleStatus.RESCHEDULED
        ):
            # Local calendar date (see the completion branch above) so a
            # late-evening local reschedule that crosses UTC midnight does
            # not record actual_date on the wrong day.
            new_date = (
                timezone.localtime(ticket.scheduled_start_at).date()
                if ticket.scheduled_start_at
                else None
            )
            if (
                occ.status != PlannedOccurrenceStatus.RESCHEDULED
                or occ.actual_date != new_date
            ):
                apply_occurrence_status(
                    occ,
                    PlannedOccurrenceStatus.RESCHEDULED,
                    note="Auto-rescheduled: linked ticket moved.",
                    actual_date=new_date,
                    when=now,
                )
            return
    except Exception:  # noqa: BLE001 - must never break a ticket save
        logger.exception(
            "reconcile_occurrence_from_ticket failed for ticket %s",
            getattr(ticket, "pk", None),
        )


def mark_missed_occurrences(
    *,
    today: Optional[date] = None,
    grace_days: int = DEFAULT_MISSED_GRACE_DAYS,
    actor=None,
) -> int:
    """Flip PLANNED / TICKET_CREATED occurrences whose planned date is
    past the grace window to MISSED. Returns the count flipped."""
    today = today or timezone.localdate()
    cutoff = today - timedelta(days=grace_days)
    qs = PlannedOccurrence.objects.filter(
        status__in=[
            PlannedOccurrenceStatus.PLANNED,
            PlannedOccurrenceStatus.TICKET_CREATED,
        ],
        planned_date__lt=cutoff,
    )
    count = 0
    for occ in qs:
        ticket = Ticket.objects.filter(planned_occurrence=occ).first()
        if ticket is not None and str(ticket.status) in {
            str(TicketStatus.APPROVED),
            str(TicketStatus.CLOSED),
        }:
            # Defensive: a done ticket should already have driven the
            # occurrence to COMPLETED via the sync signal.
            continue
        apply_occurrence_status(
            occ,
            PlannedOccurrenceStatus.MISSED,
            actor=actor,
            note="Marked missed: planned date passed without completion.",
            when=timezone.now(),
        )
        count += 1
    return count


def skip_occurrence(occurrence: PlannedOccurrence, *, actor, reason: str) -> PlannedOccurrence:
    """Skip a not-yet-generated occurrence. Only valid while the
    occurrence is PLANNED and has no spawned ticket."""
    if occurrence.status != PlannedOccurrenceStatus.PLANNED or Ticket.objects.filter(
        planned_occurrence=occurrence
    ).exists():
        raise PlannedWorkError(
            "Only a not-yet-generated (PLANNED) occurrence can be skipped.",
            code="skip_not_allowed",
        )
    if not (reason or "").strip():
        raise PlannedWorkError(
            "A reason is required to skip an occurrence.",
            code="reason_required",
        )
    return apply_occurrence_status(
        occurrence,
        PlannedOccurrenceStatus.SKIPPED,
        actor=actor,
        reason=reason,
    )


@transaction.atomic
def cancel_occurrence(occurrence: PlannedOccurrence, *, actor, reason: str) -> PlannedOccurrence:
    """Cancel an occurrence (and soft-delete its linked ticket, if any).
    Valid from PLANNED / TICKET_CREATED / RESCHEDULED.

    The CANCELLED transition (history row) and the linked ticket's
    soft-delete are wrapped in one atomic block so they commit / roll
    back together.
    """
    if occurrence.status not in {
        PlannedOccurrenceStatus.PLANNED,
        PlannedOccurrenceStatus.TICKET_CREATED,
        PlannedOccurrenceStatus.RESCHEDULED,
    }:
        raise PlannedWorkError(
            "This occurrence can no longer be cancelled.",
            code="cancel_not_allowed",
        )
    if not (reason or "").strip():
        raise PlannedWorkError(
            "A reason is required to cancel an occurrence.",
            code="reason_required",
        )

    ticket = Ticket.objects.filter(
        planned_occurrence=occurrence, deleted_at__isnull=True
    ).first()

    apply_occurrence_status(
        occurrence,
        PlannedOccurrenceStatus.CANCELLED,
        actor=actor,
        reason=reason,
    )

    # Soft-delete the linked operational ticket (Sprint 12 convention):
    # the row stays in the database with deleted_at / deleted_by set.
    if ticket is not None:
        ticket.deleted_at = timezone.now()
        ticket.deleted_by = actor
        ticket.save(update_fields=["deleted_at", "deleted_by", "updated_at"])

    return occurrence
