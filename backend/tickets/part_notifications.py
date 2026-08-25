"""The message itself, kept out of the signal so it can be called and
tested directly."""


def notify_part_assigned(slot):
    """Tell the person they are on this part, on both channels."""
    from notifications.models import NotificationEventType
    from notifications.services import (
        emit_ticket_part_assigned_inapp,
        send_logged_email,
    )

    user = slot.user
    if user is None or not user.is_active or user.deleted_at is not None:
        return 0

    ticket = slot.ticket
    part = slot.sub_task
    label = ticket.ticket_no or f"#{ticket.pk}"
    part_title = getattr(part, "title", "") or ""
    summary = f"{label} — you are on “{part_title}”" if part_title else label
    event = NotificationEventType.TICKET_PART_ASSIGNED

    # The bell first: it is the channel that works without an address.
    # `assigned_by` is the actor — the recipient's first question is who
    # put them on this.
    emit_ticket_part_assigned_inapp(
        recipient=user,
        actor=slot.assigned_by,
        summary=summary,
        ticket=ticket,
    )
    if getattr(user, "email", ""):
        send_logged_email(
            recipient_email=user.email,
            recipient_user=user,
            subject=f"You were assigned a part of {label}",
            body=f"{label} — {ticket.title}\nPart: {part_title}\n",
            event_type=event,
            ticket=ticket,
        )
    return 1
