"""
Sprint 158 §1 — an extra-work request's MANAGERS follow it onto the
ticket it spawns.

Called from all THREE spawn paths, which is the point of putting it in
one function:

  * `instant_tickets.spawn_tickets_for_request`         — INSTANT route
  * `proposal_tickets.spawn_tickets_for_proposal`       — PROPOSAL route
  * `proposal_tickets.spawn_tickets_for_extra_work_request`
                                                        — legacy pricing

A fourth `Ticket.objects.create` exists in `planned_work/generation.py`.
It is deliberately NOT a caller: planned work does not come from an
extra-work request, so there are no extra-work managers to carry.

**Sprint 161 §5 — workers ARE carried over now, WITH their schedule.**

Sprint 158's objection was sound and is worth keeping in view:
`TicketStaffAssignment` is not a thin link — since Sprint 14E each row is
a dated operational SLOT carrying `scheduled_start_at`,
`time_window_label`, a per-slot status and completion evidence. A worker
copied into an undated slot reads on the agenda as planned work nobody
planned, which is worse than no row at all.

What that objection missed is that the ticket ALREADY knows when the work
is. Sprint 9B seeds `Ticket.scheduled_start_at` from the extra-work
line's requested date on all three spawn paths, and the slot's own
`scheduled_start_at` / `scheduled_end_at` are nullable with
`default=None`. So the slot is seeded FROM THE TICKET'S OWN SCHEDULE:
the slot is dated exactly as the work is dated, the agenda shows it where
it belongs, and nothing is invented.

Where the ticket has no schedule (the line carried no requested date, so
`seed_start` was None), the slot's dates stay None. That is the honest
state — it matches what the ticket says about itself — and it is not
papered over with today's date.

**P-11 A8 — the request's PLAN travels too.** A person who planned the
request (days per person in `ExtraWorkPlannedHours`, the window in
`provider_planned_date`) made a real plan; the spawned ticket is born on
it (`instant_tickets.plan_seed`) and each worker's slot is dated from
their OWN planned days, falling back to the ticket's schedule for a
person planned without days.

An extra-work worker who is no longer ELIGIBLE at the ticket's building
is skipped rather than carried. `buildings.assignment_eligibility` is
the authority, the same one the assign endpoint uses, so the carry-over
can never create a row the assign endpoint would refuse. The skip is
logged: a silently missing worker is exactly the kind of absence nobody
notices.

Idempotent by construction (`get_or_create`): a request whose ticket is
respawned, or a manager already named on the ticket, produces no
duplicate and no error.
"""
from __future__ import annotations

import datetime
import logging

from django.utils import timezone

from .models import (
    ExtraWorkAssignment,
    ExtraWorkAssignmentRole,
    ExtraWorkPlannedHours,
)


logger = logging.getLogger(__name__)


def _at(day: datetime.date, hour: int):
    """A plan DAY as an aware instant — 09:00/17:00, the same clocks
    `planning._sync_slot_windows` writes, so a slot dated at spawn and
    one moved by a later plan edit are indistinguishable."""
    return timezone.make_aware(
        datetime.datetime.combine(day, datetime.time(hour, 0))
    )


def carry_managers_to_ticket(extra_work_request, ticket, *, actor=None) -> int:
    """Copy the request's MANAGER assignments onto `ticket`.

    Returns how many rows were created. Never raises: a spawn that
    succeeded must not be rolled back because the convenience of
    pre-filling its managers failed. The ticket is the thing that
    matters; a missing manager row is visible and fixable on the ticket
    itself, whereas a lost ticket is not.
    """
    from tickets.models import TicketManagerAssignment

    created = 0
    try:
        managers = ExtraWorkAssignment.objects.filter(
            extra_work_request=extra_work_request,
            role=ExtraWorkAssignmentRole.MANAGER,
        ).select_related("user")

        for assignment in managers:
            # `objects.get_or_create` rather than `bulk_create`: the
            # audit rows for TicketManagerAssignment come from post_save
            # receivers, and a bulk insert fires none of them (H-10).
            # P-15 (P-14's S4 attribution finding, slot 101/ticket
            # 328) — the carry stamps the PLANNER (who put this person
            # on the job), never the transition's actor: a customer
            # approving a quote never assigned anybody, and a
            # past-tense fact on the job must be true (the P-13
            # standard). None (the system) when the plan row carries
            # no author either.
            _, was_created = TicketManagerAssignment.objects.get_or_create(
                ticket=ticket,
                user=assignment.user,
                defaults={"assigned_by": assignment.assigned_by},
            )
            if was_created:
                created += 1
    except Exception:  # pragma: no cover - defensive
        logger.exception(
            "extra_work: manager carry-over failed for request #%s -> "
            "ticket #%s",
            getattr(extra_work_request, "pk", None),
            getattr(ticket, "pk", None),
        )
    return created


def carry_workers_to_ticket(extra_work_request, ticket, *, actor=None) -> int:
    """Copy the request's WORKER assignments onto `ticket` as dated
    operational slots.

    Returns how many rows were created. Never raises, for the same
    reason `carry_managers_to_ticket` does not: a spawn that succeeded
    must not be rolled back because pre-filling its crew failed.

    The slot inherits the TICKET's schedule (`scheduled_start_at` /
    `scheduled_end_at`), which is what makes carrying a worker over safe
    — see the module docstring. A worker who is not eligible at the
    ticket's building is skipped and logged.
    """
    from buildings.assignment_eligibility import (
        ROLE_WORKER,
        eligible_users_for_building,
    )
    from tickets.models import TicketStaffAssignment

    created = 0
    try:
        workers = ExtraWorkAssignment.objects.filter(
            extra_work_request=extra_work_request,
            role=ExtraWorkAssignmentRole.WORKER,
        ).select_related("user")
        if not workers:
            return 0

        # Resolved ONCE for the ticket's building, not per worker: the
        # eligibility query is the expensive part and the answer is the
        # same for everyone on this ticket.
        #
        # `actor=None` on purpose — this is the system acting, not a
        # user, so the result is the raw eligibility set rather than
        # "who may this actor administer". Passing the actor would make
        # the carry-over depend on who happened to trigger the spawn.
        eligible_ids = set(
            eligible_users_for_building(
                ticket.building, ROLE_WORKER, actor=None
            ).values_list("id", flat=True)
        )

        # P-11 A8 — the request's plan travels onto the crew's slots.
        # Each person's `ExtraWorkPlannedHours` days become their slot's
        # window (first..last day, 09:00/17:00 — `_sync_slot_windows`'s
        # own reading, so the post-spawn plan edit and the spawn write
        # the same shape); a person planned WITHOUT days keeps the
        # ticket's own schedule, which `plan_seed` has already set from
        # `provider_planned_date` when the request holds a plan. The
        # hours themselves stay in the one plan store the ticket's Plan
        # tab already reads — nothing is copied.
        days_by_user: dict[int, list[datetime.date]] = {}
        for user_id, on_date in ExtraWorkPlannedHours.objects.filter(
            extra_work_request=extra_work_request, date__isnull=False
        ).values_list("user_id", "date"):
            days_by_user.setdefault(user_id, []).append(on_date)

        for assignment in workers:
            if assignment.user_id not in eligible_ids:
                logger.info(
                    "extra_work: worker carry-over skipped user #%s for "
                    "ticket #%s - not eligible at building #%s",
                    assignment.user_id,
                    ticket.pk,
                    ticket.building_id,
                )
                continue
            # P-11 A8 — this person's slot window: their own planned
            # days when the plan names any, else the ticket's schedule.
            days = sorted(days_by_user.get(assignment.user_id, []))
            if days:
                slot_start = _at(days[0], 9)
                slot_end = _at(days[-1], 17) if days[-1] > days[0] else None
            else:
                slot_start = ticket.scheduled_start_at
                slot_end = ticket.scheduled_end_at
            # `get_or_create` rather than `bulk_create`: the audit rows
            # for TicketStaffAssignment come from post_save receivers,
            # and a bulk insert fires none of them (H-10). Keyed on
            # (ticket, user, scheduled_start_at) because a slot is dated
            # — the same person may legitimately hold two slots on one
            # ticket, and Sprint 14E dropped unique_together(ticket,
            # user) for exactly that reason.
            _, was_created = TicketStaffAssignment.objects.get_or_create(
                ticket=ticket,
                user=assignment.user,
                scheduled_start_at=slot_start,
                defaults={
                    # P-15 — the PLANNER, never the transition's actor
                    # (see `carry_managers_to_ticket`).
                    "assigned_by": assignment.assigned_by,
                    "scheduled_end_at": slot_end,
                },
            )
            if was_created:
                created += 1
    except Exception:  # pragma: no cover - defensive
        logger.exception(
            "extra_work: worker carry-over failed for request #%s -> "
            "ticket #%s",
            getattr(extra_work_request, "pk", None),
            getattr(ticket, "pk", None),
        )
    return created


def carry_assignments_to_ticket(extra_work_request, ticket, *, actor=None):
    """Carry BOTH sides over. The single entry point the three spawn
    paths call, so a future change to what "carry over" means lands in
    one place rather than three.
    """
    managers = carry_managers_to_ticket(extra_work_request, ticket, actor=actor)
    workers = carry_workers_to_ticket(extra_work_request, ticket, actor=actor)
    return managers, workers
