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
#: W14 §4 — the justification an OVERRIDE carries. Not data the ticket
#: can already have (see `transition_needs_override_reason`), so it is
#: reported unmet whenever it applies.
REQ_OVERRIDE_REASON = "override_reason"
#: P-5 S0 — the hours an HOURLY meerwerk line bills by. The machine has
#: refused `-> WAITING_CUSTOMER_APPROVAL` on an EW ticket with an
#: hourly line whose `actual_hours` is still empty since Sprint 8B
#: (`actual_hours_required`), and this module never reported it, so the
#: modal never asked and the operator met the refusal as a 400 the page
#: could only call "not accepted". Measured on crmtest TCK-2026-000385:
#: EW 89, line 105 (Extra werk regie uren, HOURS, actual_hours null),
#: `transition-requirements` answered `unmet: []`, the POST answered
#: `actual_hours_required`, the screen said nothing usable.
REQ_ACTUAL_HOURS = "actual_hours"

#: P-5 S0 — THE ERROR-BODY LAW: a refusal names its reason in words.
#: One phrase per requirement key, used by the serializer's refusal
#: sentence. The FRONTEND maps the keys to its own i18n; this text is
#: for the console, the tests and any client without a bundle.
REQUIREMENT_PHRASES = {
    REQ_ASSIGNEE: "somebody doing the work",
    REQ_SCHEDULE: "a start date",
    REQ_COMPLETION_EVIDENCE: "proof the work is done (a note or a photo)",
    REQ_OVERRIDE_REASON: "a reason for the override",
    REQ_ACTUAL_HOURS: "the actual hours on every hourly line",
}


def phrase_for(key: str) -> str:
    return REQUIREMENT_PHRASES.get(key, key.replace("_", " "))


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

#: The completion moves, as strings. Read from `state_machine` rather
#: than re-listed, so the two gates can never disagree about WHICH moves
#: are completions -- only about who they bind.
def _completion_pairs() -> set[tuple[str, str]]:
    from .state_machine import COMPLETION_EVIDENCE_TRANSITIONS

    return {(str(a), str(b)) for (a, b) in COMPLETION_EVIDENCE_TRANSITIONS}


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


def _is_staff(user) -> bool:
    from accounts.models import UserRole

    return getattr(user, "role", None) == UserRole.STAFF


def _has_completion_evidence(ticket, note: str = "") -> bool:
    """Does this ticket already carry what its completion rule wants?

    The RULE is not restated here. `completion_requirements` owns which
    evidence a ticket needs (W2-D's `file_upload_required` /
    `completion_notes_required` off its extra work, falling back to
    Sprint 25C's note-OR-attachment), and `state_machine` owns the same
    two readers for the pool. Both are imported rather than mirrored,
    because a second copy of this rule is how the modal starts asking
    for a photo the server does not want, or staying silent about one it
    does.

    The note pool is the ticket's stored completion note OR the note
    travelling with THIS press. Both count, and the second is the one
    that matters: the modal collects a note and posts it with the move,
    so a gate that read only the stored column would refuse the very
    answer the operator just gave it. (Measured: it did — the first run
    of `test_a_provider_passes_with_proof` got
    `transition_requirements_unmet` while sending a perfectly good
    note.)
    """
    from .completion_requirements import missing_evidence, requirements_for_ticket
    from .state_machine import _ticket_has_visible_attachment

    return not missing_evidence(
        requirements_for_ticket(ticket),
        has_note=bool(
            (getattr(ticket, "completion_note", "") or "").strip()
            or (note or "").strip()
        ),
        has_file=_ticket_has_visible_attachment(ticket),
    )


#: A move nobody pressed. `auto_close`, the sub-task rollup and the
#: extra-work sync hook all drive transitions with `user=None`; there is
#: no operator standing there to answer a question, so these carry no
#: requirements. This is the same actor convention `apply_transition`
#: already uses for `SYSTEM_AUTO_TRANSITIONS`.
def _is_system_actor(user) -> bool:
    return user is None


def _has_actual_hours(ticket) -> bool:
    """Every hourly line on the ticket's meerwerk has its actual hours.

    The RULE is `extra_work.final_amounts.ew_has_unfinalized_hourly_lines`,
    the same reader `state_machine.apply_transition` refuses on, so the
    modal and the gate cannot disagree about which lines count. A
    ticket with no meerwerk has no hourly lines and is trivially
    satisfied; the caller only asks for EW tickets anyway.
    """
    ew_id = getattr(ticket, "extra_work_request_id", None)
    if ew_id is None:
        return True
    from extra_work.final_amounts import ew_has_unfinalized_hourly_lines
    from extra_work.models import ExtraWorkRequest

    ew = ExtraWorkRequest.objects.filter(pk=ew_id).first()
    if ew is None:
        return True
    return not ew_has_unfinalized_hourly_lines(ew)


def requirements_for_transition(
    ticket, to_status, user=None, *, is_override: bool = False, note: str = ""
) -> list[Requirement]:
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

    # W-UX1 §4 — THE PROOF GATE LOSES ITS VIPs.
    #
    # RECON, because the brief named the wrong file and the difference
    # decides the design. `REQ_COMPLETION_EVIDENCE` has been DEFINED in
    # this module since W13-FIX and never once appended: the docstring
    # above promises "-> WAITING_* needs the completion evidence ...
    # surfaced here so the MODAL can show it", and the code never
    # surfaced it. The live rule is `state_machine.py:653`, which fires
    # `if getattr(user, "role", None) == UserRole.STAFF and ...`, with a
    # comment stating the scoping is deliberate and that "a manager can
    # still complete a job that requires a photo without one".
    #
    # The owner has now ruled the other way. Rather than widen the
    # state-machine gate -- which is also the primitive `auto_close`,
    # the sub-task rollup and a great deal of test setup use to WALK
    # tickets into states -- the requirement is added HERE, where the
    # module docstring always said it belonged and where the layering
    # argument in `TicketStatusChangeSerializer.save` puts form
    # completeness: at the door a person came through.
    #
    # That one placement buys both halves the reference model asks for:
    # `requirements_for_transition` feeds the MODAL (R3 -- the warning
    # renders inline before the press) and `unmet` feeds the SERIALIZER
    # (R4 -- the 400 is law, and a client that skips the modal still
    # cannot get past it).
    #
    # NOT FOR STAFF, and that is not an exemption -- it is the opposite.
    # STAFF already meet the older, narrower gate one layer down, which
    # raises the established `completion_evidence` code that the page
    # branches on and several tests assert. Reporting it here too would
    # replace that precise refusal with a generic one for the only role
    # that was never exempt. So: STAFF keep their gate, everyone else
    # gains one, and the union is "every role".
    # THE ONLY BYPASS IS THE EXPLICIT OVERRIDE. Not a role, not a
    # setting: the operator has to press twice and say why, and
    # `apply_transition` writes that reason onto the
    # `TicketStatusHistory` row, which IS the audit trail (H-11). An
    # override with no reason never reaches here -- `apply_transition`
    # refuses it with `override_reason_required` -- so bypassing the
    # proof gate always costs a recorded sentence.
    if pair in _completion_pairs() and not _is_staff(user) and not is_override:
        reqs.append(
            Requirement(
                REQ_COMPLETION_EVIDENCE, _has_completion_evidence(ticket, note)
            )
        )

    # W14 §4 — AND THE REASON, WHEN THE MOVE IS AN OVERRIDE.
    #
    # The module docstring above used to end "it does not touch the
    # override-reason contract (Sprint 27F-B1) -- that stays exactly
    # where it is". Keeping the CONTRACT where it is was right; keeping
    # the QUESTION out of the modal was not. The modal renders a field
    # per unmet requirement and nothing else, so a requirement this
    # endpoint does not report is a field the operator is never offered
    # and a 400 they meet instead. Measured: ACKNOWLEDGED -> OPEN
    # reported `unmet: []` and was then refused with
    # `override_reason_required`.
    #
    # The rule itself is NOT restated here. `state_machine
    # .transition_needs_override_reason` is the one definition, and it
    # is the same pair of predicates `apply_transition` coerces on, so
    # the modal cannot ask for a reason on a move that would not need
    # one, or stay silent on one that would.
    #
    # Imported inside the function: `state_machine` imports nothing from
    # here, and a module-level import in the other direction would make
    # the pair circular the moment it did.
    # P-5 S0 — THE HOURS, before it goes to the customer.
    #
    # Reported for every actor (the machine's gate binds every role)
    # and for the move INTO WAITING_CUSTOMER_APPROVAL from anywhere,
    # which is exactly the set `apply_transition` refuses on. Like the
    # override reason it is reported here and NOT enforced by `unmet`:
    # `apply_transition` already refuses it under its own stable code
    # `actual_hours_required`, which the page branches on and Sprint 8B
    # tests assert, and a second gate here would replace that precise
    # refusal with the generic one.
    if (
        str(to_status) == str(TicketStatus.WAITING_CUSTOMER_APPROVAL)
        and getattr(ticket, "extra_work_request_id", None) is not None
    ):
        reqs.append(Requirement(REQ_ACTUAL_HOURS, _has_actual_hours(ticket)))

    from .state_machine import transition_needs_override_reason

    if transition_needs_override_reason(ticket, to_status, user):
        # Never pre-satisfied: a reason is written FOR the move, so
        # there is nothing on the ticket that could already answer it.
        reqs.append(Requirement(REQ_OVERRIDE_REASON, False))

    return reqs


def unmet(
    ticket, to_status, user=None, *, is_override: bool = False, note: str = ""
) -> list[str]:
    """The keys that block this move right now, FOR THE GATE.

    W14 §4 — `REQ_OVERRIDE_REASON` is deliberately excluded here, and
    only here.

    This function is the ENFORCEMENT half:
    `TicketStatusChangeSerializer.save` calls it and refuses with
    `transition_requirements_unmet`. The override reason already has its
    own gate one layer down, in `apply_transition`, with its own stable
    code `override_reason_required` — the code the page branches on and
    several tests assert. Letting a missing reason ALSO trip this gate
    would replace a precise refusal ("you need to say why") with a
    generic one, and change an established contract for no gain.

    The ASKING half is `requirements_for_transition`, which the
    `transition-requirements` endpoint calls directly and which does
    report it. That asymmetry is the point: the modal must ask for the
    reason, and `apply_transition` must remain the one thing that
    refuses without it.
    """
    return [
        r.key
        for r in requirements_for_transition(
            ticket, to_status, user, is_override=is_override, note=note
        )
        if not r.satisfied and r.key not in (REQ_OVERRIDE_REASON, REQ_ACTUAL_HOURS)
    ]
