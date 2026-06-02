"""Occurrence materialization + operational-ticket spawning
(Sprint 11B Batch 2).

`generate_occurrences` is the daily entry point (Celery task +
management command). It upserts `PlannedOccurrence` rows from each
active `RecurringJob` inside the look-ahead horizon and spawns exactly
one operational ticket per fresh PLANNED occurrence. The
(recurring_job, planned_date) unique constraint is the idempotency
anchor, so re-runs never duplicate.
"""
from __future__ import annotations

import datetime
import logging
from datetime import date, timedelta
from typing import Optional

from django.db import transaction
from django.utils import timezone

from buildings.models import BuildingManagerAssignment, BuildingStaffVisibility
from tickets.models import (
    Ticket,
    TicketManagerAssignment,
    TicketScheduleStatus,
    TicketStaffAssignment,
    TicketStatus,
    TicketStatusHistory,
)

from .constants import DEFAULT_GENERATION_DAYS_AHEAD
from .lifecycle import apply_occurrence_status
from .models import PlannedOccurrence, PlannedOccurrenceStatus, RecurringJob
from .recurrence import iter_occurrence_dates

logger = logging.getLogger("planned_work")


def spawn_ticket_for_occurrence(occurrence: PlannedOccurrence, *, actor=None) -> Ticket:
    """Spawn the operational Ticket for a PLANNED occurrence and flip it
    to TICKET_CREATED. The caller MUST hold an active transaction
    (generate_occurrences wraps each occurrence in `transaction.atomic`).
    """
    job = occurrence.recurring_job
    creator = actor or job.created_by

    # Seed scheduled_start_at from the occurrence's planned_date combined
    # with the OCCURRENCE's snapshotted preferred_start_time (midnight when
    # none), made timezone-aware. The occurrence snapshot is the
    # planned-work calendar source of truth (Sprint 12); it equals the
    # job's value at generation time but honours any per-occurrence
    # override applied before the ticket is spawned. Mirrors
    # instant_tickets.earliest_requested_start.
    start_time = occurrence.preferred_start_time or datetime.time.min
    naive_start = datetime.datetime.combine(occurrence.planned_date, start_time)
    scheduled_start_at = timezone.make_aware(naive_start)

    ticket = Ticket.objects.create(
        company=occurrence.company,
        building=occurrence.building,
        customer=occurrence.customer,
        created_by=creator,
        title=job.title or "Planned job",
        description=job.description or "",
        status=TicketStatus.OPEN,
        planned_occurrence=occurrence,
        scheduled_start_at=scheduled_start_at,
        schedule_status=TicketScheduleStatus.SCHEDULED,
    )

    # SLA EXEMPTION (CRITICAL). A planned / recurring ticket is scheduled
    # work, not ad-hoc response-time work, so it must be EXEMPT from SLA
    # breach counting. The SLA engine anchors `sla_due_at` on
    # `created_at`, so a ticket spawned up to 14 days ahead of its
    # planned date would false-breach the moment the horizon passes the
    # target window. The Ticket post_save SLA signal has already set
    # sla_status=ON_TRACK + sla_due_at during create(); immediately
    # override to the SLA-exempt HISTORICAL state — the reconcile task
    # excludes sla_status="HISTORICAL" and services.reconcile() returns
    # False for it, so the ticket is never reconciled or breach-counted.
    Ticket.objects.filter(pk=ticket.pk).update(
        sla_status="HISTORICAL",
        sla_due_at=None,
        sla_started_at=None,
        sla_completed_at=None,
        sla_paused_at=None,
        sla_paused_seconds=0,
    )
    # Mirror onto the in-memory instance so callers reading `ticket`
    # observe the exempt state (update() does not refresh the instance).
    ticket.sla_status = "HISTORICAL"
    ticket.sla_due_at = None
    ticket.sla_started_at = None
    ticket.sla_completed_at = None
    ticket.sla_paused_at = None
    ticket.sla_paused_seconds = 0

    # Initial OPEN history row, written MANUALLY (the Ticket model does
    # NOT auto-write one — only state_machine.apply_transition does).
    # Mirrors extra_work.instant_tickets.
    TicketStatusHistory.objects.create(
        ticket=ticket,
        old_status="",
        new_status=TicketStatus.OPEN,
        changed_by=creator,
        note="Generated from recurring/planned job #%s (occurrence %s)."
        % (job.id, occurrence.planned_date),
        is_override=False,
        override_reason="",
    )

    # Copy default crew with per-building eligibility checks. An
    # ineligible default (no building assignment / visibility) is skipped
    # with a logger.warning — never crash the spawn.
    first_eligible_manager = None
    for dm in job.default_managers.select_related("user"):
        user = dm.user
        if BuildingManagerAssignment.objects.filter(
            user=user, building=occurrence.building
        ).exists():
            TicketManagerAssignment.objects.create(
                ticket=ticket, user=user, assigned_by=creator
            )
            if first_eligible_manager is None:
                first_eligible_manager = user
        else:
            logger.warning(
                "Skipping default manager %s for occurrence %s: no "
                "BuildingManagerAssignment for building %s.",
                user.pk,
                occurrence.pk,
                occurrence.building_id,
            )

    for ds in job.default_staff.select_related("user"):
        user = ds.user
        if BuildingStaffVisibility.objects.filter(
            user=user, building=occurrence.building
        ).exists():
            TicketStaffAssignment.objects.create(
                ticket=ticket, user=user, assigned_by=creator
            )
        else:
            logger.warning(
                "Skipping default staff %s for occurrence %s: no "
                "BuildingStaffVisibility for building %s.",
                user.pk,
                occurrence.pk,
                occurrence.building_id,
            )

    # Seed the legacy single-pointer assigned_to from the first eligible
    # default manager (only when not already set).
    if first_eligible_manager is not None and ticket.assigned_to_id is None:
        ticket.assigned_to = first_eligible_manager
        ticket.save(update_fields=["assigned_to", "updated_at"])

    # Flip the occurrence to TICKET_CREATED (this stamps generated_at).
    apply_occurrence_status(
        occurrence,
        PlannedOccurrenceStatus.TICKET_CREATED,
        actor=creator,
        note="Operational ticket #%s spawned." % ticket.id,
    )

    return ticket


def generate_occurrences(
    *,
    days_ahead: int = DEFAULT_GENERATION_DAYS_AHEAD,
    today: Optional[date] = None,
    actor=None,
    jobs=None,
) -> dict:
    """Materialize occurrences for every active job inside the horizon
    and spawn their operational tickets. Idempotent. Returns counts.

    `jobs` lets a caller scope generation to a specific iterable /
    queryset of `RecurringJob` rows (e.g. the per-job `generate` action
    passing `RecurringJob.objects.filter(pk=job.pk)`). When None, the
    daily-generator default of "every active, non-archived job" applies.
    """
    today = today or timezone.localdate()
    range_start = today
    range_end = today + timedelta(days=days_ahead)

    created_occurrences = 0
    created_tickets = 0

    if jobs is None:
        jobs = RecurringJob.objects.filter(
            is_active=True, archived_at__isnull=True
        )

    for job in jobs:
        for d in iter_occurrence_dates(
            job.frequency, job.start_date, range_start, range_end, job.end_date
        ):
            with transaction.atomic():
                occ, created = PlannedOccurrence.objects.get_or_create(
                    recurring_job=job,
                    planned_date=d,
                    defaults={
                        "company": job.company,
                        "building": job.building,
                        "customer": job.customer,
                        "status": PlannedOccurrenceStatus.PLANNED,
                        # Sprint 12 — snapshot the job's pricing + schedule
                        # window onto the occurrence at materialization
                        # time. `defaults` only applies on CREATE, so an
                        # existing occurrence keeps its frozen snapshot when
                        # the parent job is later edited; only freshly
                        # generated future occurrences pick up new values.
                        "pricing_mode": job.pricing_mode,
                        "fixed_price": job.fixed_price,
                        "vat_pct": job.vat_pct,
                        "preferred_start_time": job.preferred_start_time,
                        "time_window_label": job.time_window_label,
                    },
                )
                if created:
                    created_occurrences += 1

                # Idempotent spawn: only a PLANNED occurrence with no
                # ticket spawns one. SKIPPED / CANCELLED / etc. are left
                # alone.
                if (
                    occ.status == PlannedOccurrenceStatus.PLANNED
                    and not Ticket.objects.filter(planned_occurrence=occ).exists()
                ):
                    spawn_ticket_for_occurrence(occ, actor=actor)
                    created_tickets += 1

    return {
        "occurrences_created": created_occurrences,
        "tickets_created": created_tickets,
    }
