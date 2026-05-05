from django.conf import settings
from django.core.mail import send_mail
from django.db.models import Q

from accounts.models import User, UserRole
from tickets.models import TicketStatus

from .models import NotificationEventType, NotificationLog


def _active_users():
    return User.objects.filter(
        is_active=True,
        deleted_at__isnull=True,
    ).exclude(email="")


def _dedupe_users(users):
    seen = set()
    result = []

    for user in users:
        if not user or not user.id or not user.email:
            continue
        if user.id in seen:
            continue
        seen.add(user.id)
        result.append(user)

    return result


def _without_actor(users, actor):
    if not actor:
        return list(users)
    return [user for user in users if user.id != actor.id]


def _ticket_staff_users(ticket):
    return _active_users().filter(
        Q(
            role=UserRole.COMPANY_ADMIN,
            company_memberships__company_id=ticket.company_id,
        )
        | Q(
            role=UserRole.BUILDING_MANAGER,
            building_assignments__building_id=ticket.building_id,
        )
    ).distinct().order_by("email")


def _ticket_customer_users(ticket):
    users = list(
        _active_users()
        .filter(
            role=UserRole.CUSTOMER_USER,
            customer_memberships__customer_id=ticket.customer_id,
        )
        .distinct()
        .order_by("email")
    )

    if (
        ticket.created_by_id
        and ticket.created_by.role == UserRole.CUSTOMER_USER
        and ticket.created_by.is_active
        and ticket.created_by.deleted_at is None
    ):
        users.append(ticket.created_by)

    return _dedupe_users(users)


def _status_label(value):
    try:
        return TicketStatus(value).label
    except ValueError:
        return str(value)


def _ticket_summary(ticket):
    lines = [
        f"Ticket: {ticket.ticket_no}",
        f"Title: {ticket.title}",
        f"Status: {_status_label(ticket.status)}",
        f"Priority: {ticket.priority}",
        f"Type: {ticket.type}",
        f"Company: {ticket.company.name}",
        f"Building: {ticket.building.name}",
        f"Customer: {ticket.customer.name}",
    ]

    if ticket.room_label:
        lines.append(f"Room: {ticket.room_label}")

    if ticket.assigned_to_id:
        lines.append(f"Assigned to: {ticket.assigned_to.email}")

    lines.extend(["", "Description:", ticket.description])

    return "\n".join(lines)


def send_logged_email(
    *,
    recipient_email,
    subject,
    body,
    event_type,
    ticket=None,
    recipient_user=None,
    actor=None,
):
    log = NotificationLog.objects.create(
        ticket=ticket,
        recipient_user=recipient_user,
        triggered_by=actor,
        recipient_email=recipient_email,
        event_type=event_type,
        subject=subject,
        body=body,
    )

    try:
        sent_count = send_mail(
            subject=subject,
            message=body,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[recipient_email],
            fail_silently=False,
        )

        if sent_count:
            log.mark_sent()
        else:
            log.mark_failed("Email backend returned 0 sent messages.")
    except Exception as exc:
        log.mark_failed(exc)

    return log


def _send_to_user(ticket, recipient_user, event_type, subject, body, actor=None):
    return send_logged_email(
        ticket=ticket,
        recipient_user=recipient_user,
        actor=actor,
        recipient_email=recipient_user.email,
        event_type=event_type,
        subject=subject,
        body=body,
    )


def _send_to_users(ticket, users, event_type, subject, body, actor=None):
    logs = []
    for user in _dedupe_users(_without_actor(users, actor)):
        logs.append(
            _send_to_user(
                ticket=ticket,
                recipient_user=user,
                event_type=event_type,
                subject=subject,
                body=body,
                actor=actor,
            )
        )
    return logs


def send_ticket_created_email(ticket, actor=None):
    subject = f"[{ticket.ticket_no}] New ticket: {ticket.title}"
    body = "\n".join(
        [
            "A new ticket was created.",
            "",
            _ticket_summary(ticket),
        ]
    )

    return _send_to_users(
        ticket=ticket,
        users=list(_ticket_staff_users(ticket)),
        event_type=NotificationEventType.TICKET_CREATED,
        subject=subject,
        body=body,
        actor=actor,
    )


def send_ticket_status_changed_email(
    ticket,
    old_status,
    new_status,
    actor=None,
    is_admin_override=False,
):
    actor_label = getattr(actor, "email", "") or "an administrator"
    override = (
        is_admin_override
        and str(new_status) in {str(TicketStatus.APPROVED), str(TicketStatus.REJECTED)}
    )

    if override:
        decision_word = "Approved" if str(new_status) == str(TicketStatus.APPROVED) else "Rejected"
        subject = (
            f"[{ticket.ticket_no}] {decision_word} on behalf of customer by {actor_label}"
        )
        body = "\n".join(
            [
                f"This ticket was {decision_word.lower()} on behalf of the customer "
                f"by {actor_label}.",
                "",
                f"Old status: {_status_label(old_status)}",
                f"New status: {_status_label(new_status)}",
                "",
                "If you are the customer for this ticket and disagree with this decision, "
                "reply to the ticket or contact your facility manager.",
                "",
                _ticket_summary(ticket),
            ]
        )
    else:
        subject = (
            f"[{ticket.ticket_no}] Status changed: "
            f"{_status_label(old_status)} → {_status_label(new_status)}"
        )
        body = "\n".join(
            [
                "A ticket status was changed.",
                "",
                f"Old status: {_status_label(old_status)}",
                f"New status: {_status_label(new_status)}",
                "",
                _ticket_summary(ticket),
            ]
        )

    users = []
    users.extend(list(_ticket_staff_users(ticket)))
    users.extend(_ticket_customer_users(ticket))

    if ticket.assigned_to_id:
        users.append(ticket.assigned_to)

    return _send_to_users(
        ticket=ticket,
        users=users,
        event_type=NotificationEventType.TICKET_STATUS_CHANGED,
        subject=subject,
        body=body,
        actor=actor,
    )


def send_ticket_assigned_email(ticket, old_assigned_to=None, actor=None):
    if not ticket.assigned_to_id:
        return []

    subject = f"[{ticket.ticket_no}] Ticket assigned to you: {ticket.title}"
    body = "\n".join(
        [
            "A ticket was assigned to you.",
            "",
            _ticket_summary(ticket),
        ]
    )

    return _send_to_users(
        ticket=ticket,
        users=[ticket.assigned_to],
        event_type=NotificationEventType.TICKET_ASSIGNED,
        subject=subject,
        body=body,
        actor=actor,
    )


def send_password_reset_email(user, uid, token, reset_url=None):
    subject = "Reset your Cleaning Ticket System password"
    body_lines = [
        "A password reset was requested for your account.",
        "",
        f"UID: {uid}",
        f"Token: {token}",
    ]
    if reset_url:
        body_lines.extend(["", f"Reset link: {reset_url}"])
    body_lines.extend(
        [
            "",
            "If you did not request this reset, you can ignore this email.",
        ]
    )

    return send_logged_email(
        recipient_user=user,
        recipient_email=user.email,
        event_type=NotificationEventType.PASSWORD_RESET,
        subject=subject,
        body="\n".join(body_lines),
    )
