"""W-H — the ticket schedule's annotation row: how it is written, and
how it is read back.

Sprint 9B put the schedule's audit trail on `TicketStatusHistory` as an
annotation row (old_status == new_status, `changed_by` = the operator),
and that row is the ONLY record of who planned a job and when they did
it. Nothing on the Ticket carries it, deliberately: the current schedule
is `scheduled_start_at` / `scheduled_end_at` / `schedule_status`, and
adding a `planned_by` column beside them would be a second place holding
a fact the history row already owns.

What was missing was a way to READ that row back. The note was composed
inline in the viewset, so the only way to recognise a schedule row was to
match its prose from somewhere else — the failure mode this codebase
already ruled out for error handling ("match the stable `code`, never the
message"). The prefix is now a constant that the writer and the reader
share, so it cannot drift between them.
"""

# The marker. Every schedule note starts with it and no other
# `TicketStatusHistory` note does; `latest_schedule_change` is the only
# reader and `compose_schedule_note` is the only writer.
SCHEDULE_NOTE_PREFIX = "Schedule "


def compose_schedule_note(
    *, action: str, old_start, new_start, window_label: str, reason: str
) -> str:
    """The annotation-row note for a schedule set / reschedule / clear.

    Moved here from `TicketViewSet._schedule_history_note` unchanged, so
    the wording and the prefix that identifies it live together.
    """

    def _fmt(dt):
        return dt.isoformat() if dt is not None else "—"

    if action == "clear":
        return f"{SCHEDULE_NOTE_PREFIX}cleared (was {_fmt(old_start)})."
    parts = [
        f"{SCHEDULE_NOTE_PREFIX}{action}: {_fmt(old_start)} -> {_fmt(new_start)}"
    ]
    if window_label:
        parts.append(f"window={window_label}")
    if reason:
        parts.append(f"reason={reason}")
    return "; ".join(parts)


def latest_schedule_change(ticket):
    """The newest schedule annotation row on this ticket, or None.

    Iterates `ticket.status_history.all()` rather than filtering in SQL:
    the detail view already prefetches that relation (and its
    `changed_by`), so reading it in Python costs no query at all, while a
    `.filter()` here would issue a fresh one per ticket.

    Ordering is taken from `created_at` rather than from the queryset's
    order, which is not contracted.
    """
    newest = None
    for row in ticket.status_history.all():
        if not (row.note or "").startswith(SCHEDULE_NOTE_PREFIX):
            continue
        if newest is None or row.created_at > newest.created_at:
            newest = row
    return newest
