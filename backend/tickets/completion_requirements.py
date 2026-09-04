"""W3-G (`docs/planning/ew-gap-closing-plan.md` §2.3) — what a job must
carry before it may be reported done.

Until this sprint the answer was hardcoded in two places and was the
same sentence in both: a note OR a photo, for every job in the system.
W2-D stored the real answer on the work itself —
`ExtraWorkRequest.file_upload_required` and
`.completion_notes_required`, both set at plan time, both defaulting
False — and deliberately left enforcement to this sprint, in ONE place.
This module is that place.

THE RULE
--------
    the ticket came from an extra work    read the two flags, and each
                                          is INDEPENDENT of the other:

        file  notes   what completing it requires
        ----  -----   ---------------------------
        yes   no      a file
        no    yes     a note
        yes   yes     both
        no    no      nothing

    the ticket came from nowhere          a note OR a photo, exactly as
    (no extra work at all)                before this sprint.

The second line is the owner's call and it is deliberate. A plain
ticket has no extra work, so it has no flags, so there is nothing to
read; inventing a default would either drop a requirement that live
work has always been held to, or invent one nobody asked for. Keeping
the rule those tickets have always had is the only option that changes
nothing for them. `source` on the result records which of the two
branches answered, so a caller (or a test) can tell "this job requires
nothing" from "we could not find out".

WHAT THIS DOES **NOT** DECIDE
-----------------------------
WHO the rule applies to, and WHICH pile of evidence counts. Both stay
with the caller, because the two callers legitimately differ:

  * `tickets.views_staff_assignments` — the per-slot gate. Evidence is
    what is linked to THAT SLOT, and the actor is whoever may write the
    slot.
  * `tickets.state_machine` — the ticket-level completion transition.
    Evidence is any customer-visible attachment on the ticket, and the
    rule fires for STAFF actors only (B1,
    `system-business-logic-and-workflows.md` §4.4 — a manager closing
    out a job on behalf of an absent worker bypasses it). W3-G did not
    touch that scoping; it only made the CONTENT of the rule
    configurable.

A FILE IS A FILE
----------------
`file_upload_required` is satisfied by any non-hidden attachment,
photo or not, because that is what the field is named and what W2-D
documented ("a file must be attached"). The legacy note-OR-photo
branch keeps its stricter reading, where only a genuine image counts
(`is_photo_attachment`; a PDF mislabelled as image/jpeg does not) —
that strictness exists to stop historical bad data satisfying a gate
nobody consciously configured, which is a different question from an
operator ticking "a file is required" on purpose. If the owner wants
the configured branch to mean a PHOTO specifically, it is the
`has_file` argument at the two call sites, not a change here.
"""
from __future__ import annotations

from dataclasses import dataclass


#: Raised under this code by both gates. UNCHANGED from Sprint 12 /
#: Sprint 25C on purpose: the code is what existing clients and tests
#: branch on, and the thing that had to become specific is the MESSAGE,
#: not the identifier.
ERR_COMPLETION_EVIDENCE = "completion_evidence_required"

SOURCE_EXTRA_WORK = "extra_work"
SOURCE_DEFAULT = "default"


#: W13 — WHO ASKED. A cleaner treats "the customer wants a photo of
#: this" differently from "your manager wants a note", so the gate
#: reports the origin of each requirement rather than only its
#: existence. Both may be true of the same requirement.
ASKED_BY_CUSTOMER = "customer"
ASKED_BY_PROVIDER = "provider"


@dataclass(frozen=True)
class CompletionRequirements:
    """What one job needs before it may be reported done.

    `note_required` / `file_required` are the two configured
    requirements and are independent. `either_required` is the legacy
    rule and is mutually exclusive with them: when it is True the other
    two are False, and vice versa.

    W13 — `note_asked_by` / `file_asked_by` say WHO asked for each one,
    as a tuple that may hold both origins. They are reporting only: the
    gate refuses on `note_required` / `file_required`, which are already
    the union, so a caller that ignores the origins enforces exactly the
    same rule.
    """

    note_required: bool
    file_required: bool
    either_required: bool
    source: str
    note_asked_by: tuple[str, ...] = ()
    file_asked_by: tuple[str, ...] = ()

    @property
    def anything_required(self) -> bool:
        return self.note_required or self.file_required or self.either_required

    def as_dict(self) -> dict:
        return {
            "note_required": self.note_required,
            "file_required": self.file_required,
            "either_required": self.either_required,
            "source": self.source,
            "note_asked_by": list(self.note_asked_by),
            "file_asked_by": list(self.file_asked_by),
        }


LEGACY_NOTE_OR_PHOTO = CompletionRequirements(
    note_required=False,
    file_required=False,
    either_required=True,
    source=SOURCE_DEFAULT,
)


def requirements_for_ticket(ticket) -> CompletionRequirements:
    """The two flags off `ticket`'s extra work, or the legacy rule.

    Reads `extra_work_request` through the canonical FK — the same one
    `extra_work.billing.build_ticket_map` and `reports.dimensions` use
    to decide what is earned — so "which work is this ticket" has one
    answer across the system. A ticket with no extra work, or whose
    extra work row has gone, gets `LEGACY_NOTE_OR_PHOTO`.
    """
    extra_work = getattr(ticket, "extra_work_request", None) if ticket else None
    if extra_work is None:
        return LEGACY_NOTE_OR_PHOTO

    # W13 — THE UNION OF THE TWO ORIGINS.
    #
    # The provider sets its pair when planning; the customer sets theirs
    # when raising the request. If either asked, it is required; if both
    # asked, both origins are reported and the single requirement still
    # only has to be satisfied once. A photo does not have to be
    # uploaded twice because two people wanted it.
    #
    # This is the whole enforcement change. It is here, in the one place
    # that already decides completion, so both existing gates — the
    # per-slot one and the ticket-level transition — pick it up without
    # a second check being written anywhere.
    provider_note = bool(extra_work.completion_notes_required)
    provider_file = bool(extra_work.file_upload_required)
    customer_note = bool(getattr(extra_work, "customer_requires_note", False))
    customer_file = bool(getattr(extra_work, "customer_requires_photo", False))

    def _asked(by_customer: bool, by_provider: bool) -> tuple[str, ...]:
        out = []
        if by_customer:
            out.append(ASKED_BY_CUSTOMER)
        if by_provider:
            out.append(ASKED_BY_PROVIDER)
        return tuple(out)

    return CompletionRequirements(
        note_required=provider_note or customer_note,
        file_required=provider_file or customer_file,
        either_required=False,
        source=SOURCE_EXTRA_WORK,
        note_asked_by=_asked(customer_note, provider_note),
        file_asked_by=_asked(customer_file, provider_file),
    )


def missing_evidence(
    requirements: CompletionRequirements, *, has_note: bool, has_file: bool
) -> tuple[str, ...]:
    """Which requirements are unmet, in reading order. Empty means the
    job may be reported done."""
    missing: list[str] = []
    if requirements.note_required and not has_note:
        missing.append("note")
    if requirements.file_required and not has_file:
        missing.append("file")
    if requirements.either_required and not (has_note or has_file):
        missing.append("either")
    return tuple(missing)


#: One sentence per outcome, naming WHAT IS MISSING rather than
#: restating a rule that is no longer the same for every job. "Completing
#: a slot requires a note or a photo" was true of every job in the system
#: until this sprint and is now true of some of them, which makes it the
#: worst kind of error message: correct often enough to be believed.
_MESSAGES = {
    ("note",): (
        "This job requires a completion note before it can be reported done."
    ),
    ("file",): (
        "This job requires a file to be attached before it can be reported "
        "done."
    ),
    ("note", "file"): (
        "This job requires both a completion note and an attached file "
        "before it can be reported done."
    ),
    ("either",): (
        "Completing this requires a completion note or a photo."
    ),
}


def message_for(missing: tuple[str, ...]) -> str:
    """The sentence for an unmet set. Never called with an empty set by
    either gate, but answers safely if it is."""
    if not missing:
        return ""
    return _MESSAGES.get(
        missing,
        "This job is missing the evidence it requires before it can be "
        "reported done.",
    )
