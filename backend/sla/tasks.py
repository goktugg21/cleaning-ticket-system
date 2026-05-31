"""
Periodic SLA reconciliation. Wired in CELERY_BEAT_SCHEDULE in settings.py to
run every 5 minutes via the dedicated `beat` container in docker-compose.
"""
from celery import shared_task
from django.utils import timezone

from tickets.models import Ticket, TicketStatus

from . import services


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
