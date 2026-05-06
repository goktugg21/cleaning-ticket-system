"""
Backfill SLA fields on existing tickets.

Run once after migrating to the SLA engine. Idempotent: re-running produces
the same final state for any given clock value.

Tickets created before settings.SLA_ENGINE_START_DATE are marked HISTORICAL
and get no due date. Tickets created on or after are computed:
  - Active terminal (APPROVED/REJECTED/CLOSED) → COMPLETED, with
    sla_completed_at taken from resolved_at or updated_at.
  - Active non-terminal → full reconciliation against current clock.
"""
import datetime
from datetime import time
from zoneinfo import ZoneInfo

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from tickets.models import Ticket, TicketStatus

from sla import services


_TERMINAL = (TicketStatus.APPROVED, TicketStatus.REJECTED, TicketStatus.CLOSED)


def _engine_cutoff_utc() -> datetime.datetime:
    iso = settings.SLA_ENGINE_START_DATE
    local_date = datetime.date.fromisoformat(iso)
    tz = ZoneInfo(settings.TIME_ZONE)
    local_dt = datetime.datetime.combine(local_date, time(0, 0), tzinfo=tz)
    return local_dt.astimezone(datetime.timezone.utc)


class Command(BaseCommand):
    help = "Backfill SLA fields on existing tickets. Idempotent."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Compute counts without committing changes.",
        )

    def handle(self, *args, **options):
        dry_run = options.get("dry_run", False)
        cutoff = _engine_cutoff_utc()
        now = timezone.now()

        historical_q = Ticket.objects.filter(created_at__lt=cutoff)
        active_q = Ticket.objects.filter(created_at__gte=cutoff)

        if dry_run:
            historical_count = historical_q.count()
            active_count = active_q.count()
        else:
            with transaction.atomic():
                historical_count = historical_q.update(sla_status=services.HISTORICAL)

                active_count = 0
                for ticket in active_q.iterator():
                    services.on_ticket_created(ticket)
                    if ticket.status in _TERMINAL:
                        ticket.sla_status = services.COMPLETED
                        ticket.sla_completed_at = (
                            ticket.resolved_at or ticket.updated_at
                        )
                    else:
                        services.reconcile(ticket, now=now)
                    Ticket.objects.filter(pk=ticket.pk).update(
                        sla_started_at=ticket.sla_started_at,
                        sla_due_at=ticket.sla_due_at,
                        sla_completed_at=ticket.sla_completed_at,
                        sla_paused_at=ticket.sla_paused_at,
                        sla_paused_seconds=ticket.sla_paused_seconds,
                        sla_status=ticket.sla_status,
                        sla_first_breached_at=ticket.sla_first_breached_at,
                    )
                    active_count += 1

        suffix = " (dry run)" if dry_run else ""
        self.stdout.write(
            self.style.SUCCESS(
                f"Backfilled: {historical_count} historical, "
                f"{active_count} active{suffix}."
            )
        )
