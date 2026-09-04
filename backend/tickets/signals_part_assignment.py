"""W-N1 §2 — telling somebody they were put on a PART of a ticket.

A SIGNAL, not four calls. `TicketStaffAssignment` rows are created from
four places today — the single assign in `views_staff_assignments`, the
transition modal's bulk add in `serializers.py`, the staff-request
approval in `views_staff_requests`, and the parts modal through the first
of those — and `sub_task` is additionally a manager-writable PATCH field,
so a person can be moved onto a part without any row being created at
all. Five doors, one rule: hanging it off the model is the only shape
where a sixth door cannot open silently.

WHAT COUNTS AS BEING ASSIGNED A PART
------------------------------------
Either the row arrives already carrying a `sub_task`, or an existing row's
`sub_task` CHANGES to one. Moving a slot from part A to part B is being
assigned part B — the person now owes different work, which is the whole
reason to tell them. Moving a slot OFF a part (`sub_task` -> NULL) tells
nobody: nothing new is owed.

SELF-ASSIGNMENT IS SILENT
-------------------------
`assigned_by` is on the row, so "did this person do it to themselves?" is
answerable without threading a request through the signal. A notification
that tells you what you just did is noise, and it is the kind of noise
that teaches people to ignore the channel.
"""
import logging

from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver

logger = logging.getLogger(__name__)

#: Slot pk -> the `sub_task_id` the row had BEFORE this save. Populated in
#: `pre_save` and consumed in `post_save`, because by then the instance
#: already carries the new value and the old one is gone. Keyed by pk and
#: popped on read, so a failed save cannot leave a stale entry that a
#: later save of the same row would misread.
_PREVIOUS_SUB_TASK: dict[int, int | None] = {}


@receiver(pre_save, sender="tickets.TicketStaffAssignment")
def _remember_previous_sub_task(sender, instance, **kwargs):
    if not instance.pk:
        return
    previous = (
        sender.objects.filter(pk=instance.pk)
        .values_list("sub_task_id", flat=True)
        .first()
    )
    _PREVIOUS_SUB_TASK[instance.pk] = previous


@receiver(post_save, sender="tickets.TicketStaffAssignment")
def _notify_part_assignment(sender, instance, created, **kwargs):
    previous = _PREVIOUS_SUB_TASK.pop(instance.pk, None)
    sub_task_id = instance.sub_task_id
    if sub_task_id is None:
        return
    if not created and previous == sub_task_id:
        return  # an edit that did not move them onto a different part

    # Doing it to yourself is not news.
    if instance.assigned_by_id and instance.assigned_by_id == instance.user_id:
        return

    try:
        from .part_notifications import notify_part_assigned

        notify_part_assigned(instance)
    except Exception:  # noqa: BLE001
        # A notification must never take the assignment down with it. The
        # slot is the record; the message is a courtesy on top of it.
        logger.exception(
            "part-assignment notification failed for slot %s", instance.pk
        )
