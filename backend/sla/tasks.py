"""
Periodic SLA reconciliation. Wired in CELERY_BEAT_SCHEDULE in settings.py to
run every 5 minutes via the dedicated `beat` container in docker-compose.

Sprint W1-B §2.7 adds a SECOND task on the same beat: `sweep_sla_warnings`,
which is the half that talks to people. `reconcile_sla_states` measures and
writes a column; the sweep reads clocks and sends mail. They are kept as two
tasks rather than one because they fail differently — a reconciler that dies
leaves stale statuses, a sweep that dies leaves silence — and because a
future operator will want to disable one without the other.
"""
import logging

from celery import shared_task
from django.utils import timezone

from tickets.models import Ticket, TicketStatus

from . import services

logger = logging.getLogger(__name__)


_NON_TERMINAL_STATUSES = [
    s for s in TicketStatus.values
    # Sprint 7B — CONVERTED_TO_EXTRA_WORK is terminal: SLA reconciliation
    # must treat a converted ticket as done and stop touching its clock.
    if s
    not in (
        TicketStatus.APPROVED,
        TicketStatus.REJECTED,
        TicketStatus.CLOSED,
        TicketStatus.CONVERTED_TO_EXTRA_WORK,
    )
]


@shared_task
def reconcile_sla_states():
    """Update sla_status across all live tickets. Idempotent."""
    now = timezone.now()
    base_qs = Ticket.objects.filter(
        status__in=_NON_TERMINAL_STATUSES,
    ).exclude(sla_status="HISTORICAL")
    checked = base_qs.count()

    fields = [
        "id", "status", "sla_started_at", "sla_due_at", "sla_paused_at",
        "sla_paused_seconds", "sla_first_breached_at", "sla_status",
    ]
    updated = 0
    for ticket in base_qs.only(*fields).iterator():
        if services.reconcile(ticket, now=now):
            Ticket.objects.filter(pk=ticket.pk).update(
                sla_status=ticket.sla_status,
                sla_first_breached_at=ticket.sla_first_breached_at,
            )
            updated += 1
    return {"checked": checked, "updated": updated}


@shared_task
def sweep_sla_warnings(now=None):
    """Emit the three time-driven warnings. See `sla/warnings.py`.

    Never raises: this shares a beat with nothing today, but a periodic
    task that dies on one bad row stops warning about every other row too
    — which is the exact silence this sprint exists to end. Per-subject
    failures are already caught inside the sweep and counted in
    `failed`; this outer guard covers a failure of the sweep itself.

    `now` (an ISO datetime string) exists for tests and for an operator
    re-running a missed window by hand; the beat schedule never passes it.
    """
    from datetime import datetime

    from . import warnings as sla_warnings

    when = datetime.fromisoformat(now) if now else timezone.now()
    try:
        return sla_warnings.sweep(now=when)
    except Exception:  # noqa: BLE001 — never let one tick kill the schedule.
        logger.exception("sla.tasks: warning sweep failed")
        return {
            "approval_cutoff": 0,
            "manager_review": 0,
            "not_started_tickets": 0,
            "not_started_extra_work": 0,
            "failed": 1,
        }
