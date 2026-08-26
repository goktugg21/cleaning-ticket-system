"""W-HOURS5 Task 2 — the ticket's crew and the plan's crew are ONE crew.

Post-spawn there are two stores for "who is on this job": the ticket's
own rows (`TicketStaffAssignment` slots, `TicketManagerAssignment`) that
the People tab edits, and the extra work's `ExtraWorkAssignment` rows
that the plan reads — `extra_work.planning.resolve_planned_hours`
refuses hours for anybody not assigned THERE. Spawn carries the extra
work's crew onto the ticket once (`extra_work.assignment_carryover`)
and nothing ever carried a later change back. So a person added on the
People tab was on the job but could not be planned, and a person
removed there kept a plan row nobody could take away.

This module is the way back. Every user-driven ticket-crew write on a
spawned ticket mirrors to the extra work the ticket came from:

  * a BASE staff slot created      -> WORKER assignment (get_or_create)
  * the person's last base slot
    on the extra work's tickets
    removed                        -> WORKER assignment deleted
  * a manager assigned             -> MANAGER assignment (get_or_create)
  * the person's last manager row
    on the extra work's tickets
    removed                        -> MANAGER assignment deleted

"Last" is judged across EVERY ticket the extra work spawned: a series
job is one plan over several day-tickets, and taking somebody off
Tuesday's ticket does not take them off the job while Wednesday's still
names them.

## Removal and the plan — the ruling

Removing a person clears ONLY their today-and-future planned cells
(dated today or later, or undated — "no day yet" is not history). PAST
planned hours are history and STAY; the comparison marks the person as
no longer assigned. Deleting past plan is possible only by hand: unlock
the past days with a reason, then zero the cells. Nothing here deletes
a row dated before today, and `extra_work.planning._write_planned_hours`
leaves a former crew member's past rows alone on every later save.

Instance `.delete()` on the assignment, never a queryset delete: the
audit rows come from post_delete receivers (H-10). Everything runs
inside the calling view's transaction, so a mirror that cannot be
written rolls the ticket write back with it — one crew, or nothing.
"""
from __future__ import annotations

from django.utils import timezone


def _extra_work_of(ticket):
    """The extra work `ticket` was spawned from, or None."""
    if not getattr(ticket, "extra_work_request_id", None):
        return None
    return ticket.extra_work_request


def _clear_open_plan(extra_work, user_id: int) -> int:
    """Delete this person's planned rows that are NOT history: dated
    today or later, or undated. Returns how many went. Past rows stay."""
    from extra_work.models import ExtraWorkPlannedHours
    from django.db.models import Q

    today = timezone.localdate()
    rows = ExtraWorkPlannedHours.objects.filter(
        extra_work_request=extra_work, user_id=user_id
    ).filter(Q(date__isnull=True) | Q(date__gte=today))
    count = 0
    for row in rows:
        row.delete()
        count += 1
    return count


def worker_added(ticket, user, *, actor=None) -> bool:
    """A base slot was created for `user` on `ticket`. Returns True when
    a WORKER assignment was created on the extra work."""
    extra_work = _extra_work_of(ticket)
    if extra_work is None:
        return False
    from extra_work.models import ExtraWorkAssignment, ExtraWorkAssignmentRole

    _, created = ExtraWorkAssignment.objects.get_or_create(
        extra_work_request=extra_work,
        user=user,
        role=ExtraWorkAssignmentRole.WORKER,
        defaults={"assigned_by": actor},
    )
    return created


def worker_removed(ticket, user_id: int) -> bool:
    """A base slot of `user_id` was deleted on `ticket`. When the person
    holds no base slot on ANY ticket of the extra work any more, their
    WORKER assignment goes and their open plan is cleared. Returns True
    when the assignment was removed."""
    extra_work = _extra_work_of(ticket)
    if extra_work is None:
        return False
    from extra_work.models import ExtraWorkAssignment, ExtraWorkAssignmentRole
    from .models import TicketStaffAssignment

    still_on_job = TicketStaffAssignment.objects.filter(
        ticket__extra_work_request=extra_work,
        user_id=user_id,
        sub_task__isnull=True,
    ).exists()
    if still_on_job:
        return False
    removed = False
    for assignment in ExtraWorkAssignment.objects.filter(
        extra_work_request=extra_work,
        user_id=user_id,
        role=ExtraWorkAssignmentRole.WORKER,
    ):
        assignment.delete()
        removed = True
    if removed:
        _clear_open_plan(extra_work, user_id)
    return removed


def manager_added(ticket, user, *, actor=None) -> bool:
    """`user` became a responsible manager of `ticket`."""
    extra_work = _extra_work_of(ticket)
    if extra_work is None:
        return False
    from extra_work.models import ExtraWorkAssignment, ExtraWorkAssignmentRole

    _, created = ExtraWorkAssignment.objects.get_or_create(
        extra_work_request=extra_work,
        user=user,
        role=ExtraWorkAssignmentRole.MANAGER,
        defaults={"assigned_by": actor},
    )
    return created


def manager_removed(ticket, user_id: int) -> bool:
    """`user_id` stopped being a responsible manager of `ticket`. Same
    "last one across the series" rule as `worker_removed`."""
    extra_work = _extra_work_of(ticket)
    if extra_work is None:
        return False
    from extra_work.models import ExtraWorkAssignment, ExtraWorkAssignmentRole
    from .models import TicketManagerAssignment

    still_on_job = TicketManagerAssignment.objects.filter(
        ticket__extra_work_request=extra_work, user_id=user_id
    ).exists()
    if still_on_job:
        return False
    removed = False
    for assignment in ExtraWorkAssignment.objects.filter(
        extra_work_request=extra_work,
        user_id=user_id,
        role=ExtraWorkAssignmentRole.MANAGER,
    ):
        assignment.delete()
        removed = True
    if removed:
        _clear_open_plan(extra_work, user_id)
    return removed
