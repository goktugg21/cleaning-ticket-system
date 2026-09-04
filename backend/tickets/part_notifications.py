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
    event = NotificationEventType.TICKET_PART_ASSIGNED

    # P-16 Part D — the words come from the copy catalogue, rendered in
    # the recipient's own language on both channels.
    from notifications import copy as notification_copy

    template_key = "ticket_part_assigned"
    params = {
        "label": label,
        "ticket_title": ticket.title,
        "part_title": part_title,
    }

    # The bell first: it is the channel that works without an address.
    # `assigned_by` is the actor — the recipient's first question is who
    # put them on this.
    emit_ticket_part_assigned_inapp(
        recipient=user,
        actor=slot.assigned_by,
        template_key=template_key,
        params=params,
        ticket=ticket,
    )
    if getattr(user, "email", ""):
        lang = notification_copy.resolve_lang(getattr(user, "language", "nl"))
        subject, body = notification_copy.render_email(template_key, params, lang)
        send_logged_email(
            recipient_email=user.email,
            recipient_user=user,
            subject=subject,
            body=body,
            event_type=event,
            ticket=ticket,
            template_key=template_key,
            params=params,
        )
    return 1
