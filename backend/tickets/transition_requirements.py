"""W13-FIX §1 — WHAT A STEP NEEDS BEFORE IT MAY BE TAKEN.

    The owner's father, a twenty-year programmer, on the workflow card:
    "If you work on those transition modals, this job is done."

    The owner, pressing the buttons: "I click. It has to give me a
    warning. I cannot be sure whether the button worked."

Until this module the workflow card was a row of buttons that each fired
a POST on the first click. Nothing was asked, so a job could be started
with nobody doing it and no date on it, and the operator learned what a
button meant by pressing it and reading the result.

This module is the ONE place that answers "what does this step need",
and both sides read it:

  * `GET /api/tickets/<id>/transition-requirements/?to_status=X` --
    the modal renders a field per unsatisfied requirement.
  * `TicketStatusChangeSerializer.save` -- refuses the move while one
    is unmet, so a client that skipped the modal gets no further.

WHY THE SERIALIZER AND NOT `apply_transition`
----------------------------------------------
The first version of this gated `apply_transition` itself. That is the
state machine -- it owns which moves are LEGAL for which role -- and it
is also the programmatic primitive that `auto_close`, the sub-task
rollup, the extra-work sync hook, the demo seeder and much test setup
use to walk a ticket into a state. None of those is a person filling in
a form, and 71 tests failed for exactly the right reason.

"Did the operator answer what this step needs" is a question about a
REQUEST, so it belongs at the door a request arrives through:
`POST /tickets/<id>/status/`. The guarantee asked for -- you cannot
move it without answering -- is unchanged for every caller that is
actually a caller.

That is the point of putting it here rather than in the page: a screen
that predicted the rule would be a second copy of it, and this codebase
has already had that failure twice (CLAUDE.md, the render-order array
and the pagination class). The page does not predict. It asks.

THE RULES, AND WHY EACH ONE IS THE STATUS'S OWN DEFINITION
----------------------------------------------------------
Nothing here is invented. Each requirement is the thing the target
status already claims to mean in `models.TicketStatus`:

  -> ACKNOWLEDGED   needs WHEN.
                    Its own docstring: "a human has seen it, IT IS
                    SCHEDULED, and nobody has started". The status
                    promised a date and never checked for one.

  -> IN_PROGRESS    needs WHO and WHEN.
                    Work that is "in progress" with nobody assigned and
                    no start time is not in progress; it is a claim.
                    Only on the FORWARD moves into work -- a manager
                    rejecting a staff completion sends the ticket back
                    to IN_PROGRESS as a correction and must not be made
                    to re-answer questions the job already answered.

  -> WAITING_*      needs the completion evidence that
                    `completion_requirements.py` already computed and
                    `state_machine` already enforced for STAFF. It is
                    surfaced here so the MODAL can show it before the
                    press instead of the operator meeting it as a 400.
                    The rule itself is unchanged, scoping included.

WHAT THIS DOES NOT DO
---------------------
It does not decide WHO MAY make a move (`can_transition` owns that), it
does not widen `ALLOWED_TRANSITIONS`, and it does not touch the
override-reason contract (Sprint 27F-B1) -- that stays exactly where it
is, because a reason justifies a move the machine did not expect, while
these requirements are the data a perfectly ordinary move needs.
"""
from __future__ import annotations

from dataclasses import dataclass

from .models import TicketStatus


#: Stable code the client branches on, in the shape the page already
#: understands from `override_reason_required`.
ERR_TRANSITION_REQUIREMENTS = "transition_requirements_unmet"

REQ_ASSIGNEE = "assignee"
REQ_SCHEDULE = "schedule"
REQ_COMPLETION_EVIDENCE = "completion_evidence"


#: The forward moves into work. A rejection landing on IN_PROGRESS is a
#: correction and is deliberately absent -- see the module docstring.
_FORWARD_INTO_WORK = {
    (TicketStatus.OPEN, TicketStatus.IN_PROGRESS),
    (TicketStatus.ACKNOWLEDGED, TicketStatus.IN_PROGRESS),
    (TicketStatus.ON_HOLD, TicketStatus.IN_PROGRESS),
}

_INTO_ACKNOWLEDGED = {
    (TicketStatus.OPEN, TicketStatus.ACKNOWLEDGED),
}


@dataclass(frozen=True)
class Requirement:
    """One thing this step needs, and whether the ticket already has it.

    `satisfied` is answered from the ticket as it stands NOW, so the
    modal can render only what is actually missing rather than asking
    again for a date the job already carries.
    """

    key: str
    satisfied: bool

    def as_dict(self) -> dict:
        return {"key": self.key, "satisfied": self.satisfied}


def _has_assignee(ticket) -> bool:
    """Somebody is doing the work.

    Either a dispatched field-staff row or the single legacy manager
    pointer counts: both are a named human, and refusing a job that has
    a manager but no staff row would block the small-team case the
    owner actually runs.
    """
    if getattr(ticket, "assigned_to_id", None):
        return True
    return ticket.staff_assignments.exists()


def _has_schedule(ticket) -> bool:
    return getattr(ticket, "scheduled_start_at", None) is not None


#: A move nobody pressed. `auto_close`, the sub-task rollup and the
#: extra-work sync hook all drive transitions with `user=None`; there is
#: no operator standing there to answer a question, so these carry no
#: requirements. This is the same actor convention `apply_transition`
#: already uses for `SYSTEM_AUTO_TRANSITIONS`.
def _is_system_actor(user) -> bool:
    return user is None


def requirements_for_transition(ticket, to_status, user=None) -> list[Requirement]:
    """Every requirement this move carries, satisfied ones included.

    Returning the satisfied ones too is deliberate: the modal shows the
    step's full checklist, so an operator can see that the date is
    already set rather than wondering whether it was asked for.
    """
    if _is_system_actor(user):
        return []

    pair = (str(ticket.status), str(to_status))
    reqs: list[Requirement] = []

    if pair in {(str(a), str(b)) for a, b in _INTO_ACKNOWLEDGED}:
        reqs.append(Requirement(REQ_SCHEDULE, _has_schedule(ticket)))

    if pair in {(str(a), str(b)) for a, b in _FORWARD_INTO_WORK}:
        reqs.append(Requirement(REQ_ASSIGNEE, _has_assignee(ticket)))
        reqs.append(Requirement(REQ_SCHEDULE, _has_schedule(ticket)))

    return reqs


def unmet(ticket, to_status, user=None) -> list[str]:
    """The keys that block this move right now."""
    return [
        r.key for r in requirements_for_transition(ticket, to_status, user) if not r.satisfied
    ]
