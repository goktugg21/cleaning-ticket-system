"""Occurrence materialization + operational-ticket spawning
(Sprint 11B Batch 2; recurring day-model extension).

`generate_occurrences` is the daily entry point (Celery task +
management command). It upserts `PlannedOccurrence` rows from each
active `RecurringJob` inside the look-ahead horizon and spawns exactly
one operational ticket per fresh PLANNED occurrence. A job runs on a SET
of weekdays and in 1..N time windows, so the generator materializes one
occurrence per (date x window). The
(recurring_job, planned_date, source_window) unique constraint is the
idempotency anchor, so re-runs never duplicate.
"""
from __future__ import annotations

import datetime
import logging
from datetime import date, timedelta
from decimal import Decimal
from typing import Optional

from django.db import IntegrityError, transaction
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
from .models import (
    PlannedOccurrence,
    PlannedOccurrenceStatus,
    RecurringJob,
    RecurringJobWindow,
)
from .recurrence import iter_occurrence_dates

logger = logging.getLogger("planned_work")

_DEFAULT_VAT_PCT = Decimal("21.00")


def ensure_job_windows(job: RecurringJob) -> list:
    """Return the job's active windows (ordered), lazily creating ONE
    default window from the job's legacy `preferred_start_time` /
    `time_window_label` if the job has no windows at all.

    This is the backward-compatibility safety net: a RecurringJob created
    before the day-model (the data migration backfills those) — or via any
    path that bypassed the window-aware serializer — still generates
    exactly one occurrence per date with the same schedule snapshot it had
    before. A job whose windows were ALL soft-archived intentionally
    generates nothing (we never resurrect a deliberately emptied job).
    """
    active = list(
        job.windows.filter(is_active=True).order_by("ordering", "id")
    )
    if active:
        return active
    if job.windows.exists():
        # Has windows but every one is archived — respect that.
        return []
    # No windows at all. Serialize lazy creation with a row lock on the job
    # (re-checking inside the atomic block) so two overlapping generator
    # runs — e.g. the daily Celery task overlapping a manual `generate`
    # action — can never both create a default window for the same job (a
    # duplicate default window would explode one-occurrence-per-date into
    # two).
    with transaction.atomic():
        RecurringJob.objects.select_for_update().filter(pk=job.pk).first()
        active = list(
            job.windows.filter(is_active=True).order_by("ordering", "id")
        )
        if active:
            return active
        if job.windows.exists():
            return []
        logger.warning(
            "Recurring job #%s has no windows; creating a default window "
            "from its legacy schedule fields.",
            job.id,
        )
        window = RecurringJobWindow.objects.create(
            recurring_job=job,
            label=job.time_window_label or "",
            start_time=job.preferred_start_time,
            ordering=0,
        )
        return [window]


def _occurrence_pricing_snapshot(job: RecurringJob, window: RecurringJobWindow):
    """(pricing_mode, fixed_price, vat_pct) to freeze onto a new occurrence.

    A window may carry an OPTIONAL pricing override: when its
    `pricing_mode` is set the occurrence snapshots the window's pricing
    (e.g. evening cleans priced higher than morning); otherwise it falls
    back to the job's pricing — which preserves the legacy single-window
    behaviour exactly (the migration's default window leaves pricing
    null)."""
    if window.pricing_mode:
        vat = window.vat_pct if window.vat_pct is not None else _DEFAULT_VAT_PCT
        return window.pricing_mode, window.fixed_price, vat
    return job.pricing_mode, job.fixed_price, job.vat_pct


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

    # Disambiguate the ticket title by window ONLY when the job has more
    # than one active window — a single-window (legacy-style) job keeps
    # its exact title for backward compatibility. With multiple windows
    # (Morning / Evening) the label is appended so the two same-date
    # tickets are distinguishable.
    base_title = job.title or "Planned job"
    window_label = (occurrence.time_window_label or "").strip()
    if window_label and job.windows.filter(is_active=True).count() > 1:
        ticket_title = f"{base_title} — {window_label}"
    else:
        ticket_title = base_title

    ticket = Ticket.objects.create(
        company=occurrence.company,
        building=occurrence.building,
        customer=occurrence.customer,
        created_by=creator,
        title=ticket_title,
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
        windows = ensure_job_windows(job)
        if not windows:
            continue
        for d in iter_occurrence_dates(
            job.frequency,
            job.start_date,
            range_start,
            range_end,
            job.end_date,
            weekdays=job.weekdays,
        ):
            for window in windows:
                # Each (date x window) upsert + spawn is one atomic unit.
                # The (recurring_job, planned_date, source_window) unique
                # constraint makes the occurrence idempotent; the
                # Ticket.planned_occurrence OneToOne makes the spawn
                # idempotent. Under concurrent runs (daily task overlapping
                # a manual generate) the loser's INSERT trips one of those
                # constraints — we catch IntegrityError, roll that unit
                # back, and skip it rather than 500 the whole run.
                created = False
                spawned = False
                try:
                    with transaction.atomic():
                        pricing_mode, fixed_price, vat_pct = (
                            _occurrence_pricing_snapshot(job, window)
                        )
                        occ, created = PlannedOccurrence.objects.get_or_create(
                            recurring_job=job,
                            planned_date=d,
                            source_window=window,
                            defaults={
                                "company": job.company,
                                "building": job.building,
                                "customer": job.customer,
                                "status": PlannedOccurrenceStatus.PLANNED,
                                # Snapshot the schedule + pricing from the
                                # WINDOW (falling back to the job's pricing)
                                # at materialization time, then FREEZE it.
                                # `defaults` only applies on CREATE, so an
                                # existing occurrence keeps its frozen
                                # snapshot when the template / window is
                                # later edited.
                                "pricing_mode": pricing_mode,
                                "fixed_price": fixed_price,
                                "vat_pct": vat_pct,
                                "preferred_start_time": window.start_time,
                                "time_window_label": window.label,
                            },
                        )

                        # Idempotent spawn: only a PLANNED occurrence with no
                        # ticket spawns one. SKIPPED / CANCELLED / etc. are
                        # left alone.
                        if (
                            occ.status == PlannedOccurrenceStatus.PLANNED
                            and not Ticket.objects.filter(
                                planned_occurrence=occ
                            ).exists()
                        ):
                            spawn_ticket_for_occurrence(occ, actor=actor)
                            spawned = True
                except IntegrityError:
                    # A concurrent run already materialized this occurrence
                    # / spawned its ticket. The constraints guarantee one
                    # each, so this unit is simply skipped (its counters are
                    # not incremented).
                    logger.warning(
                        "Concurrent generation race for job #%s on %s "
                        "(window #%s); skipping.",
                        job.id,
                        d,
                        window.id,
                    )
                    continue

                if created:
                    created_occurrences += 1
                if spawned:
                    created_tickets += 1

        # Sprint 6 — also spawn AD-HOC occurrences (hand-added OFF the rule via
        # the calendar add-date action) that fall due within the horizon. The
        # rule-date loop above never visits them (they are not rule dates), so
        # without this pass an ad-hoc PLANNED occurrence would never spawn its
        # ticket. Rule dates are unaffected: this scans only is_ad_hoc PLANNED
        # rows, and the `not Ticket.exists()` guard keeps it idempotent (an
        # ad-hoc row that happens to fall on a rule date was already spawned +
        # flipped to TICKET_CREATED above, so it is excluded here).
        # Defense-in-depth: cap the due window at the job's end_date so an
        # ad-hoc occurrence somehow persisted past end_date never spawns a
        # ticket (add-date already rejects out-of-window dates).
        adhoc_due_end = range_end
        if job.end_date is not None and job.end_date < adhoc_due_end:
            adhoc_due_end = job.end_date
        adhoc_due = PlannedOccurrence.objects.filter(
            recurring_job=job,
            is_ad_hoc=True,
            status=PlannedOccurrenceStatus.PLANNED,
            planned_date__gte=range_start,
            planned_date__lte=adhoc_due_end,
        )
        for occ in adhoc_due:
            try:
                with transaction.atomic():
                    if (
                        occ.status == PlannedOccurrenceStatus.PLANNED
                        and not Ticket.objects.filter(
                            planned_occurrence=occ
                        ).exists()
                    ):
                        spawn_ticket_for_occurrence(occ, actor=actor)
                        created_tickets += 1
            except IntegrityError:
                logger.warning(
                    "Concurrent ad-hoc spawn race for job #%s occurrence #%s; "
                    "skipping.",
                    job.id,
                    occ.id,
                )
                continue

    return {
        "occurrences_created": created_occurrences,
        "tickets_created": created_tickets,
    }
