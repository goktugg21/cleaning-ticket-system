"""Sprint 176 §3 — the ONE writer of an Extra Work's dates after creation.

Two callers need to move `deadline` / `planned_end_date` on a saved row:
the per-request `PATCH /api/extra-work/<id>/dates/` action and the bulk
`POST /api/extra-work/bulk-dates/`. They live in different modules, and the
rule about what makes a window valid must not exist twice — that is exactly
how the list and the detail page end up disagreeing about which rows are
late.

So the write itself is here, once, and both views call it.

The "leave unchanged" convention that both callers depend on is key
PRESENCE, not truthiness:

    absent from the payload  -> field untouched
    present and null         -> field cleared
    present and a date       -> field set

That distinction is what lets the bulk dialog default every field to "leave
unchanged" and still support clearing one deliberately. Truthiness cannot
express it — `None` and "not sent" would collapse into the same thing, and
a bulk edit of ten rows would silently wipe a date nobody touched on the
other nine.
"""

from __future__ import annotations

ERR_PLANNED_END_BEFORE_START = "planned_end_before_start"


def apply_extra_work_dates(extra_work, data: dict) -> dict | None:
    """Apply a validated `{deadline?, planned_end_date?}` to `extra_work`.

    Returns `None` on success (the row is saved), or an error body dict
    ready to hand to a 400 `Response` — so both callers report the same
    code for the same mistake.

    Saves with `update_fields` so the write touches only what changed, and
    includes `updated_at` so the audit handler sees a real modification.
    """
    update_fields: list[str] = []

    if "deadline" in data:
        extra_work.deadline = data["deadline"]
        update_fields.append("deadline")
    if "planned_end_date" in data:
        extra_work.planned_end_date = data["planned_end_date"]
        update_fields.append("planned_end_date")

    if not update_fields:
        return None

    # The window must not close before it opens. Checked against the
    # RESOLVED values (what the row will hold after this write), not
    # against the payload — moving only the end date still has to be
    # judged against the start already stored, or a two-step edit could
    # reach a state a one-step edit is refused.
    #
    # `preferred_date` is the window's start: the customer's wish is also
    # the day the job is planned for, and `planned_end_date` extends that
    # single day into a span (see the model's help_text).
    start = extra_work.preferred_date
    end = extra_work.planned_end_date
    if start is not None and end is not None and end < start:
        return {
            "detail": (
                "The planned end date cannot be before the planned start "
                "date."
            ),
            "code": ERR_PLANNED_END_BEFORE_START,
        }

    # No deadline-vs-window check on purpose. A job planned for next week
    # and due at the end of the month is normal, and so is a deadline
    # BEFORE the planned window — that is a job that is going to be late,
    # which is a fact worth recording rather than an input to refuse. The
    # `is_overdue` property is what surfaces it.

    update_fields.append("updated_at")
    extra_work.save(update_fields=update_fields)
    return None
