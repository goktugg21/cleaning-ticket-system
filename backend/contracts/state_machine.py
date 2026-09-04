"""P-15 §1.1 — the contract lifecycle gets a guard.

`Contract.lifecycle` was a plain writable ChoiceField: any PATCH could
jump anywhere with a 200 — a CANCELLED contract back to ACTIVE, an
ACTIVE one silently to DRAFT (which stops its invoicing). Every other
money-adjacent machine (ticket, extra work, proposal, invoice) has an
explicit ALLOWED_TRANSITIONS guard; this one had none (P-14's S1
finding).

THIS IS A SAFETY GUARD INSIDE THE FREEZE, NOT A MODEL CHANGE. The
allowed set mirrors exactly the moves the UI's own buttons offer today:

    DRAFT   -> ACTIVE      (the detail page's Activate)
    DRAFT   -> CANCELLED   (the form dialog's lifecycle select)
    ACTIVE  -> CANCELLED   (idem)
    CANCELLED -> nothing   (terminal — nothing out of cancelled)

Nothing goes back to DRAFT: un-drafting an activated contract would
silently stop its invoicing, which is the exact jump the S1 finding
demonstrated. "Ending" is not a lifecycle move at all — it is setting
`end_date`, and EXPIRED stays derived (see `ContractLifecycle`).

THE HISTORY ROW is the generic `AuditLog` diff: `Contract` is
registered for the full CRUD trio in `audit/signals.py` (Sprint 160),
so every lifecycle flip already lands as a before/after diff naming
both states — the same trail `ContractHours` status moves rely on.
There is no `ContractStatusHistory` model and this sprint's
zero-migrations law forbids adding one; the transition endpoint stamps
an audit *reason* instead so the row says it came through the door.

The locking pattern is `invoicing/state_machine.py`'s: one atomic
block, `select_for_update` on the contract row, the precondition
checked on the LOCKED status (which doubles as the concurrency guard).
The refusal shape is the machine standard: HTTP 400 with
`{"detail": <human sentence>, "code": <stable code>}`.
"""
from __future__ import annotations

from django.db import transaction

from audit import context as audit_context

from .models import Contract, ContractKind, ContractLifecycle


#: The authority. Keys are FROM states; values are the states an
#: operator may move them TO. Exactly the UI's own buttons — see the
#: module docstring before widening it.
ALLOWED_TRANSITIONS: dict[str, frozenset[str]] = {
    ContractLifecycle.DRAFT: frozenset(
        {ContractLifecycle.ACTIVE, ContractLifecycle.CANCELLED}
    ),
    ContractLifecycle.ACTIVE: frozenset({ContractLifecycle.CANCELLED}),
    ContractLifecycle.CANCELLED: frozenset(),
}


class ContractTransitionError(Exception):
    """An illegal lifecycle move. Carries the stable code beside the
    human sentence, the shape every other machine's refusal has."""

    def __init__(self, message: str, code: str = "invalid_transition"):
        super().__init__(message)
        self.message = message
        self.code = code


@transaction.atomic
def transition_contract(actor, contract, to_lifecycle: str) -> Contract:
    """Move one contract's lifecycle along ALLOWED_TRANSITIONS.

    The caller has already answered WHO may operate contracts
    (`IsContractManager` + `enforce_contract_management`); this module
    answers only WHETHER the move is legal. Returns the locked, saved
    row. Raises `ContractTransitionError` otherwise — nothing is
    written on a refusal.
    """
    valid = {choice.value for choice in ContractLifecycle}
    if to_lifecycle not in valid:
        raise ContractTransitionError(
            f"Unknown lifecycle '{to_lifecycle}'. A contract can be "
            "draft, active or cancelled; expired is derived from the "
            "end date.",
            code="unknown_lifecycle",
        )

    locked = Contract.objects.select_for_update().get(pk=contract.pk)

    if locked.kind == ContractKind.EXTRA_WORK:
        # A register mirrors work that is billed elsewhere; it is made
        # and retired by the register machinery, never operated by hand
        # (the same refusal shape `ContractPlanningView` gives it).
        raise ContractTransitionError(
            "An extra-work register mirrors billed work; its lifecycle "
            "is not operated by hand.",
            code="register_lifecycle_locked",
        )

    if locked.lifecycle == to_lifecycle:
        raise ContractTransitionError(
            f"The contract is already {to_lifecycle}.",
            code="no_op_transition",
        )

    allowed = ALLOWED_TRANSITIONS.get(locked.lifecycle, frozenset())
    if to_lifecycle not in allowed:
        raise ContractTransitionError(
            f"A {locked.lifecycle} contract cannot move to "
            f"{to_lifecycle}. "
            + (
                "Cancelled is final — make a new contract instead."
                if locked.lifecycle == ContractLifecycle.CANCELLED
                else "Nothing goes back to draft; cancel it instead."
            ),
            code="invalid_transition",
        )

    # The AuditLog post_save diff is the history row (module docstring);
    # the reason marks it as a door move rather than a field edit.
    audit_context.set_current_reason("contract_transition")
    try:
        locked.lifecycle = to_lifecycle
        locked.save(update_fields=["lifecycle", "updated_at"])
    finally:
        audit_context.set_current_reason(None)
    return locked
