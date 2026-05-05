from django.conf import settings
from django.core.mail import send_mail
from django.db.models import Q

from accounts.models import User, UserRole
from tickets.models import TicketStatus

from .models import NotificationEventType, NotificationLog, NotificationStatus

# `send_mail` is re-exported here so that test code patching
# notifications.services.send_mail can intercept the actual SMTP call. The
# Celery worker task in notifications/tasks.py looks send_mail up via this
# module at call time, not via a captured local binding, so a patch applied
# to notifications.services.send_mail flows through into the task body.
__all__ = (
    "send_mail",
    "send_logged_email",
    "send_ticket_created_email",
    "send_ticket_status_changed_email",
    "send_ticket_assigned_email",
    "send_ticket_unassigned_email",
    "send_password_reset_email",
    "send_invitation_email",
)


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
    # Local import keeps Django from importing notifications.tasks during the
    # initial app-loading pass, which would in turn import this module again.
    from .tasks import send_email_task

    log = NotificationLog.objects.create(
        ticket=ticket,
        recipient_user=recipient_user,
        triggered_by=actor,
        recipient_email=recipient_email,
        event_type=event_type,
        subject=subject,
        body=body,
        status=NotificationStatus.QUEUED,
    )

    send_email_task.delay(
        log_id=log.id,
        recipient_email=recipient_email,
        subject=subject,
        body=body,
    )

    # Reflect any state transitions the task already performed (eager mode in
    # tests will have flipped this row to SENT or FAILED before we return).
    # In production the task runs out-of-process, so this re-read just
    # confirms the QUEUED state at the moment the producer returns.
    log.refresh_from_db()
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


def send_ticket_unassigned_email(ticket, recipient_user, actor=None):
    if recipient_user is None:
        return []

    subject = f"[{ticket.ticket_no}] Removed from your assigned tickets: {ticket.title}"
    body = "\n".join(
        [
            "You are no longer assigned to this ticket.",
            "",
            _ticket_summary(ticket),
        ]
    )

    # Reuse _send_to_users so the same actor-exclusion (self-unassign) and
    # dedupe rules apply as the rest of the email pipeline.
    return _send_to_users(
        ticket=ticket,
        users=[recipient_user],
        event_type=NotificationEventType.TICKET_UNASSIGNED,
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


def send_invitation_email(invitation, raw_token, accept_url):
    """
    Sends the invitation email to the invitee. Goes through the async Celery
    task path; the request thread returns immediately after enqueue.

    `raw_token` is the only place outside the email itself where the raw
    token exists; the caller must not persist it.
    """
    inviter = invitation.created_by
    inviter_label = inviter.full_name or inviter.email
    role_label = dict(UserRole.choices).get(invitation.role, invitation.role)

    scope_lines = []
    company_names = list(invitation.companies.values_list("name", flat=True))
    if company_names:
        scope_lines.append("Companies: " + ", ".join(company_names))
    building_names = list(invitation.buildings.values_list("name", flat=True))
    if building_names:
        scope_lines.append("Buildings: " + ", ".join(building_names))
    customer_names = list(invitation.customers.values_list("name", flat=True))
    if customer_names:
        scope_lines.append("Customers: " + ", ".join(customer_names))

    subject = f"You have been invited as {role_label}"
    body_lines = [
        "Hello,",
        "",
        f"{inviter_label} has invited you to join as {role_label}.",
    ]
    if scope_lines:
        body_lines.append("")
        body_lines.extend(scope_lines)
    body_lines.extend([
        "",
        f"Accept this invitation by following the link below. The link expires on "
        f"{invitation.expires_at:%Y-%m-%d %H:%M %Z}.",
        "",
        accept_url or "(operator: set INVITATION_ACCEPT_FRONTEND_URL)",
        "",
        "If you did not expect this invitation, you can ignore this email.",
    ])

    return send_logged_email(
        recipient_email=invitation.email,
        subject=subject,
        body="\n".join(body_lines),
        event_type=NotificationEventType.INVITATION_SENT,
        recipient_user=None,
        actor=inviter,
    )
