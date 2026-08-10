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

**Workers are NOT carried over, deliberately.**
`TicketStaffAssignment` is not a thin link — since Sprint 14E each row is
a dated operational SLOT carrying `scheduled_start_at`,
`time_window_label`, a per-slot status and completion evidence. Copying
an extra-work worker into one would create a slot with no schedule and no
window that reads, on the agenda, as planned work nobody planned. The
manager side has no such shape: `TicketManagerAssignment` is a plain
responsibility link, so carrying it over is a clean one-to-one with no
invented data. Assigning the workers is a scheduling decision and stays a
deliberate act.

Idempotent by construction (`get_or_create`): a request whose ticket is
respawned, or a manager already named on the ticket, produces no
duplicate and no error.
"""
from __future__ import annotations

import logging

from .models import ExtraWorkAssignment, ExtraWorkAssignmentRole


logger = logging.getLogger(__name__)


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
            _, was_created = TicketManagerAssignment.objects.get_or_create(
                ticket=ticket,
                user=assignment.user,
                defaults={"assigned_by": actor},
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
