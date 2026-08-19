"""W2-D — the planning layer: what we said the job would take.

    POST /api/extra-work/<id>/plan/       one work
    POST /api/extra-work/bulk-plan/       many works, one body

Both go through `apply_plan` below, so a field the single form writes and
a field the bulk table writes cannot mean two different things. That is
not a tidiness preference — it is the specific defect this module was
written against.

In the reference system NEITHER completion flag survives a write at all.
The plan modal sends `upload_is_required` and `notes_is_required`, the
config-driven update persists only the fields in its own allow-list, and
neither name is in that list — so both values are silently discarded, and
0 of 78 live records has either flag set to true
(`docs/reference/osius-reference-system/01-extra-work.md` §1.6 and §3.6).
The gap-closing brief describes the same failure from the operator's
side, as "bulk plan writes both to false on every selected work"; the
mechanism differs, the consequence does not. Either way it is a write
path that ACCEPTS a flag and does not carry it, and the operator is told
nothing.

Ours carries both, on both paths, by key presence.

THE FOUR THINGS A PLAN SETS
---------------------------
    budget_hours                 the planned total for the job
    provider_planned_date        the day we commit to starting
    provider_planned_end_date    the day we commit to finishing
    planned hours per person     that total, distributed (ExtraWorkPlannedHours)

plus the two completion requirements (`file_upload_required`,
`completion_notes_required`), and then it STARTS the work — plan and
start are one action, as they are in the reference system, where the
button is labelled "Start Work".

WHAT A PLAN DELIBERATELY DOES NOT TOUCH
---------------------------------------
`preferred_date`, `planned_end_date` and `deadline`. Those are what the
customer asked for and what is owed; the pair above is what the provider
committed to. Holding both is the only way to answer, months later, "did
we do what we promised, or what they asked for?" — and it means a plan
can never quietly move the date the provider is measured against.

KEY PRESENCE, NOT TRUTHINESS
----------------------------
Every field follows the convention `dates.py` established and the bulk
dialog rests on:

    absent from the payload  -> left exactly as it was
    present and null         -> cleared
    present and a value      -> set

`None` and "not sent" collapsing into one thing is precisely how the
reference system wipes a flag nobody touched. Presence is the only
encoding that can express all three states, so it is the one used for
every field here, booleans included.

OVERRUN IS A WARNING. IT IS NEVER A BLOCK.
------------------------------------------
When the distributed hours exceed the budget the response says so and
the save still succeeds. This is a business decision with evidence
behind it: in the reference system a complete hard-cap function,
`validateTotalHours()`, exists and is never called, and the model's boot
carries the epitaph `// Hours validation removed per user request`.
Somebody built the block and the business had it removed. Do not rebuild
it.

BUDGET HOURS NEVER TOUCHES MONEY
--------------------------------
Not one number in this module reaches a price. `rowAmounts()` in
`frontend/src/lib/billing.ts` and its server-side mirror
(`extra_work.final_amounts`) remain the one billing-total rule. Hours
here are a planning and control number; the moment an hours field
reaches a price there are two money rules and they disagree by cents on
the same record, which is exactly what the reference system does six
different ways.

THE AUDIT TRAIL IS THE HISTORY ROW
----------------------------------
A plan writes one `ExtraWorkStatusHistory` annotation row (same status in
and out, the change described in `note`) — the pattern the actual-hours
entry already uses. It is deliberately NOT added to
`audit.signals._EW_TRACKED_FIELDS`: that handler tracks the narrow set of
fields that steer MONEY (billing month, invoice marks, the label FKs,
`billed_to`), and H-11 is explicit that a workflow write's history row IS
its audit trail and must not also be registered as a generic AuditLog.
"""
from __future__ import annotations

from decimal import Decimal

from .dates import apply_extra_work_dates
from .models import (
    ExtraWorkAssignment,
    ExtraWorkPlannedHours,
    ExtraWorkStatus,
    ExtraWorkStatusHistory,
)
from .state_machine import TransitionError, apply_transition


#: Every field a plan may carry, in the order the note renders them.
PLAN_FIELDS = (
    "budget_hours",
    "provider_planned_date",
    "provider_planned_end_date",
    "planned_hours",
    "file_upload_required",
    "completion_notes_required",
)

#: The two dates `apply_extra_work_dates` owns. Routed there rather than
#: written here so the window rule, and the "planning the work moves the
#: work" ticket write behind it (Sprint 184 §1), exist once.
_PLAN_DATE_FIELDS = ("provider_planned_date", "provider_planned_end_date")

ERR_NOTHING_TO_PLAN = "nothing_to_plan"
ERR_PLANNED_HOURS_INVALID = "planned_hours_invalid"
ERR_PLANNED_HOURS_DUPLICATE = "planned_hours_duplicate_user"

#: ONE message for every way a named person can fail to resolve — not
#: assigned to this work, not visible to this caller, or not a real
#: account at all. A distinguishable answer here would let a caller
#: enumerate who works where and which ids exist (H-1, the Sprint 142.1
#: oracle class). The tests compare two response bodies for equality
#: rather than merely checking that both are errors.
PLANNED_HOURS_INVALID_MESSAGE = (
    "One or more of the named people could not be resolved, or are not "
    "assigned to this work. Nothing was changed."
)

#: The one warning this module raises. See the module docstring for why
#: it is a warning and not a refusal.
WARN_HOURS_OVERRUN = "hours_overrun"

#: Why a start did not happen. Reported, never raised — a plan whose
#: start was skipped is still a plan that landed.
START_NOT_REQUESTED = "start_not_requested"
START_ALREADY_IN_PROGRESS = "already_in_progress"


class PlanRejected(Exception):
    """A refusal with a ready-to-return 400 body.

    Mirrors `dates.py`'s error-dict return rather than raising DRF's
    ValidationError, so the same rejection can be produced by the single
    endpoint and by the bulk one without either of them re-deriving the
    wording.
    """

    def __init__(self, body: dict):
        super().__init__(body.get("detail", ""))
        self.body = body


def _reject_hours() -> None:
    raise PlanRejected(
        {
            "detail": PLANNED_HOURS_INVALID_MESSAGE,
            "code": ERR_PLANNED_HOURS_INVALID,
        }
    )


def _q2(value: Decimal) -> Decimal:
    return Decimal(value).quantize(Decimal("0.01"))


def distributed_hours(extra_work) -> Decimal:
    """The sum of every planned-hours row on this work.

    EVERY row, including one belonging to somebody who has since been
    un-assigned. The read surface lists those rows too, flagged
    `is_assigned: false`. In the reference system the grid is built from
    the assignment list and hours are matched onto it, so a removed
    worker's hours vanish from the screen while staying in the total —
    the screen and the total then disagree and nobody can see why.
    """
    total = Decimal("0.00")
    for row in extra_work.planned_hours.all():
        total += row.hours
    return _q2(total)


def hours_overrun(extra_work) -> dict | None:
    """The overrun warning body, or None when there is nothing to warn about.

    No budget means nothing to overrun — an undistributed budget and an
    unbudgeted distribution are both normal mid-planning states, and
    warning about either would train operators to ignore the warning
    that matters.
    """
    budget = extra_work.budget_hours
    if budget is None:
        return None
    distributed = distributed_hours(extra_work)
    if distributed <= budget:
        return None
    return {
        "code": WARN_HOURS_OVERRUN,
        "budget_hours": f"{_q2(budget):.2f}",
        "distributed_hours": f"{distributed:.2f}",
        "over_by": f"{_q2(distributed - budget):.2f}",
    }


def resolve_planned_hours(extra_work, rows) -> list[tuple[int, Decimal]]:
    """Validate a `[{user, hours}, ...]` distribution against ONE work.

    Returns `[(user_id, hours), ...]`. Raises `PlanRejected` — with the
    same body for every failure — when a named person is not currently
    assigned to this work in any role.

    ASSIGNED FIRST, THEN BUDGETED. You distribute a budget across the
    crew you have staffed; if somebody is not on the job yet, put them on
    it (`POST /api/extra-work/bulk-assign/`) and then budget their hours.
    Deriving the crew from this endpoint instead would give it a second,
    unscoped way to attach a person to a job.
    """
    resolved: list[tuple[int, Decimal]] = []
    seen: set[int] = set()
    for row in rows:
        user_id = row["user"]
        if user_id in seen:
            # About the PAYLOAD, not about any id — so it says what is
            # wrong without becoming an existence oracle.
            raise PlanRejected(
                {
                    "detail": (
                        "The same person appears twice in the hours "
                        "distribution."
                    ),
                    "code": ERR_PLANNED_HOURS_DUPLICATE,
                }
            )
        seen.add(user_id)
        resolved.append((user_id, _q2(row["hours"])))

    if not resolved:
        return resolved

    assigned = set(
        ExtraWorkAssignment.objects.filter(
            extra_work_request=extra_work, user_id__in=seen
        ).values_list("user_id", flat=True)
    )
    if assigned != seen:
        _reject_hours()
    return resolved


def _write_planned_hours(extra_work, resolved, *, actor) -> str:
    """Replace this work's distribution with `resolved`. Returns a note fragment.

    REPLACE, not merge: the list submitted IS the distribution, so an
    omitted person's row is deleted and `planned_hours: []` clears the
    lot. The three states stay legible — absent leaves the distribution
    alone, `[]` empties it, a list sets it — and an operator who removes
    a line from the plan modal gets the removal they asked for rather
    than a stale row nobody can see how to delete.

    Instance `.delete()` and `objects.update_or_create()` per row, never
    a queryset `.update()`: the bulk paths in the reference system fire
    no model events at all, which is why a work can move there leaving
    no trace of who moved it.
    """
    wanted = dict(resolved)
    existing = {row.user_id: row for row in extra_work.planned_hours.all()}

    for user_id, row in existing.items():
        if user_id not in wanted:
            row.delete()

    for user_id, hours in resolved:
        row = existing.get(user_id)
        if row is None:
            ExtraWorkPlannedHours.objects.create(
                extra_work_request=extra_work,
                user_id=user_id,
                hours=hours,
                set_by=actor,
            )
        elif row.hours != hours:
            row.hours = hours
            row.set_by = actor
            row.save(update_fields=["hours", "set_by", "set_at"])

    if not resolved:
        return "hours distribution cleared"
    total = sum((hours for _, hours in resolved), Decimal("0.00"))
    people = len(resolved)
    return (
        f"hours for {people} "
        f"{'person' if people == 1 else 'people'} ({total:.2f}h)"
    )


def _start(extra_work, *, actor) -> tuple[bool, str | None, object]:
    """Plan and start are one action. Returns `(started, skipped_code, row)`.

    A start that cannot happen is REPORTED, not raised. Two of the three
    reasons are ordinary operating states rather than mistakes:

      * `operational_status_follows_ticket` — Sprint 181 §1. Once this
        work has a ticket, "has it started?" is answered by the ticket
        and by nothing else. The plan is still written; the status will
        follow the ticket when somebody starts it. Forcing it here is
        how eight rows on crmtest came to read COMPLETED against a
        ticket that was still OPEN.
      * `already_in_progress` — pressing Plan & Start twice.
      * `invalid_transition` — the work is not customer-approved yet, so
        there is nothing to start.

    Raising on any of these would throw away a plan the operator
    correctly entered because of a state they can see on the screen.
    """
    if extra_work.status == ExtraWorkStatus.IN_PROGRESS:
        return False, START_ALREADY_IN_PROGRESS, extra_work
    try:
        row = apply_transition(
            extra_work,
            actor,
            ExtraWorkStatus.IN_PROGRESS,
            note="Started from the plan action (W2-D).",
        )
    except TransitionError as exc:
        return False, exc.code, extra_work
    return True, None, row


def apply_plan(extra_work, data: dict, *, actor) -> dict:
    """Write the plan onto `extra_work`, then start the work.

    `data` is a validated payload (see `ExtraWorkPlanSerializer`) read by
    KEY PRESENCE — see the module docstring. Raises `PlanRejected` with a
    ready 400 body; returns a result block on success:

        {"warnings": [...],            # hours overrun, if any
         "started": bool,
         "start_skipped": <code>|None,
         "tickets_moved": [...],       # Sprint 184 §1, via dates.py
         "tickets_kept_own_date": [...]}

    The caller supplies the transaction. Everything is resolved before
    anything is written, so a refusal leaves the row exactly as it was.
    """
    touched = [field for field in PLAN_FIELDS if field in data]
    if not touched and "start" not in data:
        raise PlanRejected(
            {
                "detail": (
                    "Provide at least one planning field to set, or "
                    "start: true."
                ),
                "code": ERR_NOTHING_TO_PLAN,
            }
        )

    # ---- resolve everything first ------------------------------------
    resolved_hours = None
    if "planned_hours" in data:
        resolved_hours = resolve_planned_hours(
            extra_work, data["planned_hours"] or []
        )

    note_parts: list[str] = []

    # ---- the committed window, through the ONE date writer ------------
    date_fields = {
        key: data[key] for key in _PLAN_DATE_FIELDS if key in data
    }
    if date_fields:
        error = apply_extra_work_dates(extra_work, date_fields)
        if error is not None:
            raise PlanRejected(error)
        note_parts.append(
            "committed window "
            f"{extra_work.provider_planned_date or '-'} -> "
            f"{extra_work.provider_planned_end_date or '-'}"
        )

    # ---- the plain columns -------------------------------------------
    update_fields: list[str] = []
    if "budget_hours" in data:
        value = data["budget_hours"]
        extra_work.budget_hours = None if value is None else _q2(value)
        update_fields.append("budget_hours")
        note_parts.append(
            "budget "
            + (
                "cleared"
                if extra_work.budget_hours is None
                else f"{extra_work.budget_hours:.2f}h"
            )
        )
    for flag in ("file_upload_required", "completion_notes_required"):
        if flag in data:
            setattr(extra_work, flag, bool(data[flag]))
            update_fields.append(flag)
            note_parts.append(f"{flag}={getattr(extra_work, flag)}")
    if update_fields:
        update_fields.append("updated_at")
        extra_work.save(update_fields=update_fields)

    # ---- the distribution --------------------------------------------
    if resolved_hours is not None:
        note_parts.append(
            _write_planned_hours(extra_work, resolved_hours, actor=actor)
        )

    # ---- the warning that never blocks -------------------------------
    warnings = []
    overrun = hours_overrun(extra_work)
    if overrun is not None:
        warnings.append(overrun)

    # ---- one history row describing what a person changed -------------
    if note_parts:
        ExtraWorkStatusHistory.objects.create(
            extra_work=extra_work,
            old_status=extra_work.status,
            new_status=extra_work.status,
            changed_by=actor,
            note=(
                f"Planned by {getattr(actor, 'email', 'system')}: "
                + "; ".join(note_parts)
                + "."
            ),
            is_override=False,
        )

    ticket_result = getattr(extra_work, "planned_date_ticket_result", None) or {}

    # ---- plan and start are one action --------------------------------
    started = False
    start_skipped: str | None = START_NOT_REQUESTED
    # ABSENT MEANS START. Plan and start are one action; `start: false`
    # is how a caller asks for a plan without one. An empty body never
    # reaches here — it is refused above as `nothing_to_plan`.
    if data.get("start", True):
        started, start_skipped, row = _start(extra_work, actor=actor)
        if started:
            # `apply_transition` locks and returns its own instance; the
            # caller renders `extra_work`, which would otherwise still
            # be carrying the pre-transition status.
            extra_work.status = row.status

    return {
        "warnings": warnings,
        "started": started,
        "start_skipped": start_skipped,
        "tickets_moved": ticket_result.get("moved", []),
        "tickets_kept_own_date": ticket_result.get("kept_own_date", []),
    }
