"""W2-D — the planning layer: what we said the job would take.

    POST /api/extra-work/<id>/plan/       one work
    POST /api/extra-work/bulk-plan/       many works, one body PER WORK

Both go through `apply_plan` below, so a field the single form writes and
a field the bulk table writes cannot mean two different things. That is
not a tidiness preference — it is the specific defect this module was
written against.

W4-O — ONE CALL, DIFFERENT VALUES PER WORK. `apply_plan` was always
per-work; what changed is what the bulk endpoint hands it. It used to
copy ONE payload onto every selected id, so work A and work B could not
be given four and six hours, and hours per person were unusable in bulk
at all (they validate against the crew of EACH work, so a shared
distribution was only ever valid when the same crew was on every job).
The endpoint now normalises whatever shape it is given into a list of
`(work, payload)` pairs and calls this function once per pair, inside
one transaction. Nothing about the write path changed; the difference is
that the batch stopped being forced to say the same thing twelve times.

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

#: W4-O — the same refusal, said in a way an operator staring at a
#: twelve-row bulk table can act on.
#:
#: A batch has a question a single work does not: WHICH ROW. A constant
#: body is the right answer to "which person" (see above) and the wrong
#: answer to "which of the twelve works I just edited" — an operator who
#: is told only "something was wrong somewhere" re-reads twelve rows, or
#: reads the dialog as broken, which is exactly the failure mode the
#: gap-closing brief names.
#:
#: NAMING THE ROW IS NOT AN ORACLE, AND THE DIFFERENCE IS PRECISE. The
#: only values this body carries beyond the constant text are values the
#: CALLER SENT (`extra_work`, `user`) plus the title of a work the caller
#: has ALREADY resolved through its own scope — every id in the batch is
#: scope-checked before a single row is read. The body is therefore a
#: pure function of the request, so it answers "does this user id exist"
#: and "does that person work here" exactly as the constant body does:
#: not at all. The three causes — not assigned, not visible, not a real
#: account — still produce one identical sentence.
#:
#: The SINGLE-work endpoint keeps the constant body. There is no "which
#: row" question when there is one row, so the ids would buy nothing
#: there, and `test_w2d_planning.py`'s equality test is a floor worth
#: leaving exactly where it is.
PLANNED_HOURS_INVALID_IN_BATCH_MESSAGE = (
    'On "{title}" (#{extra_work}): person #{user} could not be given '
    "hours here — they are not assigned to this work, or could not be "
    "resolved. Nothing was changed, on any of the selected works."
)

PLANNED_HOURS_DUPLICATE_IN_BATCH_MESSAGE = (
    'On "{title}" (#{extra_work}): person #{user} appears twice in the '
    "hours distribution. Nothing was changed, on any of the selected "
    "works."
)

NOTHING_TO_PLAN_IN_BATCH_MESSAGE = (
    'On "{title}" (#{extra_work}): no planning field was given, and no '
    "start was asked for. Nothing was changed, on any of the selected "
    "works."
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


def _reject_hours(extra_work=None, user_id=None) -> None:
    """Refuse a distribution. `extra_work` set => name the row (W4-O).

    `extra_work is None` is the single-work path and produces the
    constant body byte for byte. See the two message constants above for
    why the batch path may say more without becoming an oracle.
    """
    if extra_work is None:
        raise PlanRejected(
            {
                "detail": PLANNED_HOURS_INVALID_MESSAGE,
                "code": ERR_PLANNED_HOURS_INVALID,
            }
        )
    raise PlanRejected(
        {
            "detail": PLANNED_HOURS_INVALID_IN_BATCH_MESSAGE.format(
                title=extra_work.title,
                extra_work=extra_work.id,
                user=user_id,
            ),
            "code": ERR_PLANNED_HOURS_INVALID,
            "extra_work": extra_work.id,
            "extra_work_title": extra_work.title,
            "user": user_id,
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


def resolve_planned_hours(
    extra_work, rows, *, name_the_work: bool = False
) -> list[tuple[int, Decimal]]:
    """Validate a `[{user, hours}, ...]` distribution against ONE work.

    Returns `[(user_id, hours), ...]`. Raises `PlanRejected` — with the
    same body for every failure — when a named person is not currently
    assigned to this work in any role.

    ASSIGNED FIRST, THEN BUDGETED. You distribute a budget across the
    crew you have staffed; if somebody is not on the job yet, put them on
    it (`POST /api/extra-work/bulk-assign/`) and then budget their hours.
    Deriving the crew from this endpoint instead would give it a second,
    unscoped way to attach a person to a job.

    W4-O — EVERY WORK IN A BATCH VALIDATES ITS HOURS AGAINST ITS OWN
    CREW. This function was already per-work; what changed is that the
    bulk endpoint now hands it a DIFFERENT distribution per work instead
    of the same one for all of them, so "the same crew must be on every
    selected job" stopped being a precondition of planning hours in bulk.

    `name_the_work` puts the row and the person into the refusal — see
    `PLANNED_HOURS_INVALID_IN_BATCH_MESSAGE` for why that is not an
    oracle and why the single-work path leaves it off.
    """
    context = extra_work if name_the_work else None
    resolved: list[tuple[int, object, Decimal]] = []
    seen: set[tuple[int, object]] = set()
    seen_users: set[int] = set()
    for row in rows:
        user_id = row["user"]
        # W6-H — the grain is (person, DAY). The same person may appear
        # once per day; twice on the SAME day is still the payload
        # mistake the duplicate check was written for.
        key = (user_id, row.get("date"))
        seen_users.add(user_id)
        if key in seen:
            # About the PAYLOAD, not about any id — so it says what is
            # wrong without becoming an existence oracle.
            body = {
                "detail": (
                    "The same person appears twice in the hours "
                    "distribution."
                ),
                "code": ERR_PLANNED_HOURS_DUPLICATE,
            }
            if context is not None:
                body["detail"] = (
                    PLANNED_HOURS_DUPLICATE_IN_BATCH_MESSAGE.format(
                        title=context.title,
                        extra_work=context.id,
                        user=user_id,
                    )
                )
                body["extra_work"] = context.id
                body["extra_work_title"] = context.title
                body["user"] = user_id
            raise PlanRejected(body)
        seen.add(key)
        resolved.append((user_id, row.get("date"), _q2(row["hours"])))

    if not resolved:
        return resolved

    # ASSIGNED FIRST, THEN BUDGETED — unchanged by W6-H. Adding a day to
    # a row does not create a second way to attach a person to a job.
    assigned = set(
        ExtraWorkAssignment.objects.filter(
            extra_work_request=extra_work, user_id__in=seen_users
        ).values_list("user_id", flat=True)
    )
    if assigned != seen_users:
        # The FIRST unresolved person in PAYLOAD order, so the id named
        # is a function of the request and not of iteration order over a
        # set — two identical requests must produce two identical
        # bodies, or the equality property above is not a property.
        first_bad = next(
            (uid for uid, _, _ in resolved if uid not in assigned), None
        )
        _reject_hours(context, first_bad)
    return resolved


def _write_planned_hours(extra_work, resolved, *, actor) -> str:
    """Replace this work's distribution with `resolved`. Returns a note fragment.

    REPLACE, not merge: the list submitted IS the distribution, so an
    omitted (person, day) row is deleted and `planned_hours: []` clears
    the lot. The three states stay legible — absent leaves the
    distribution alone, `[]` empties it, a list sets it — and an
    operator who clears a cell in the day grid gets the removal they
    asked for rather than a stale row nobody can see how to delete.

    W6-H — THE KEY IS (person, DAY). A person with 8 hours on Monday and
    6 on Tuesday is two rows, and a person with an undated total is one
    row keyed `(person, None)`. That means submitting a dated grid for
    somebody who previously had one undated total REPLACES the total
    with the days, which is the intended reading: the operator has just
    decided the days.

    Instance `.delete()` and `objects.update_or_create()` per row, never
    a queryset `.update()`: the bulk paths in the reference system fire
    no model events at all, which is why a work can move there leaving
    no trace of who moved it.
    """
    wanted = {(user_id, on_date): hours for user_id, on_date, hours in resolved}
    existing = {
        (row.user_id, row.date): row for row in extra_work.planned_hours.all()
    }

    for key, row in existing.items():
        if key not in wanted:
            row.delete()

    for (user_id, on_date), hours in wanted.items():
        row = existing.get((user_id, on_date))
        if row is None:
            ExtraWorkPlannedHours.objects.create(
                extra_work_request=extra_work,
                user_id=user_id,
                date=on_date,
                hours=hours,
                set_by=actor,
            )
        elif row.hours != hours:
            row.hours = hours
            row.set_by = actor
            row.save(update_fields=["hours", "set_by", "set_at"])

    if not resolved:
        return "hours distribution cleared"
    total = sum((hours for _, _, hours in resolved), Decimal("0.00"))
    people = len({user_id for user_id, _, _ in resolved})
    days = {on_date for _, on_date, _ in resolved if on_date is not None}
    fragment = (
        f"hours for {people} "
        f"{'person' if people == 1 else 'people'} ({total:.2f}h)"
    )
    if days:
        fragment += (
            f" across {len(days)} {'day' if len(days) == 1 else 'days'}"
        )
    return fragment


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


def apply_plan(
    extra_work, data: dict, *, actor, name_the_work: bool = False
) -> dict:
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

    W4-O — `name_the_work` makes every refusal say WHICH work it is
    about. The bulk endpoint sets it because a batch has a "which row"
    question a single work does not; the single endpoint leaves it off
    so its bodies stay byte-for-byte what they were.
    """
    touched = [field for field in PLAN_FIELDS if field in data]
    if not touched and "start" not in data:
        body = {
            "detail": (
                "Provide at least one planning field to set, or "
                "start: true."
            ),
            "code": ERR_NOTHING_TO_PLAN,
        }
        if name_the_work:
            body["detail"] = NOTHING_TO_PLAN_IN_BATCH_MESSAGE.format(
                title=extra_work.title, extra_work=extra_work.id
            )
            body["extra_work"] = extra_work.id
            body["extra_work_title"] = extra_work.title
        raise PlanRejected(body)

    # ---- resolve everything first ------------------------------------
    resolved_hours = None
    if "planned_hours" in data:
        resolved_hours = resolve_planned_hours(
            extra_work,
            data["planned_hours"] or [],
            name_the_work=name_the_work,
        )

    note_parts: list[str] = []

    # ---- the committed window, through the ONE date writer ------------
    date_fields = {
        key: data[key] for key in _PLAN_DATE_FIELDS if key in data
    }
    if date_fields:
        error = apply_extra_work_dates(extra_work, date_fields)
        if error is not None:
            if name_the_work:
                # Same reason as every other refusal here: in a batch the
                # operator needs to know which of the rows they just
                # edited has the impossible window. The date module's own
                # wording and code are left untouched and only annotated.
                error = {
                    **error,
                    "extra_work": extra_work.id,
                    "extra_work_title": extra_work.title,
                }
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
