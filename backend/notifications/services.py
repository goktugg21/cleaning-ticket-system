from django.conf import settings
from django.core.mail import send_mail
from django.db.models import Q

from accounts.models import User, UserRole
from tickets.models import TicketPriority, TicketStatus, TicketType

from .models import (
    NotificationEventType,
    NotificationLog,
    NotificationPreference,
    NotificationStatus,
)

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


# Dutch status labels for email rendering. The model's TextChoices labels
# remain English (canonical machine label) and stay in sync with frontend
# i18n keys; this lookup table only governs how statuses appear in email
# bodies and subjects, which Sprint B5 standardised on Dutch.
_STATUS_LABEL_NL = {
    TicketStatus.OPEN: "Open",
    TicketStatus.IN_PROGRESS: "In behandeling",
    TicketStatus.WAITING_CUSTOMER_APPROVAL: "Wacht op goedkeuring",
    TicketStatus.REJECTED: "Afgewezen",
    TicketStatus.APPROVED: "Goedgekeurd",
    TicketStatus.CLOSED: "Gesloten",
    TicketStatus.REOPENED_BY_ADMIN: "Heropend",
}


_ROLE_LABEL_NL = {
    UserRole.SUPER_ADMIN: "Superbeheerder",
    UserRole.COMPANY_ADMIN: "Bedrijfsbeheerder",
    UserRole.BUILDING_MANAGER: "Beheerder",
    UserRole.CUSTOMER_USER: "Klant",
}


_TYPE_LABEL_NL = {
    TicketType.REPORT: "Melding",
    TicketType.COMPLAINT: "Klacht",
    TicketType.REQUEST: "Verzoek",
    TicketType.SUGGESTION: "Suggestie",
    TicketType.QUOTE_REQUEST: "Offerteaanvraag",
}


_PRIORITY_LABEL_NL = {
    TicketPriority.NORMAL: "Normaal",
    TicketPriority.HIGH: "Hoog",
    TicketPriority.URGENT: "Urgent",
}


def _status_label(value):
    try:
        return _STATUS_LABEL_NL[TicketStatus(value)]
    except (ValueError, KeyError):
        return str(value)


def _role_label(value):
    try:
        return _ROLE_LABEL_NL[UserRole(value)]
    except (ValueError, KeyError):
        return str(value)


def _type_label(value):
    try:
        return _TYPE_LABEL_NL[TicketType(value)]
    except (ValueError, KeyError):
        return str(value)


def _priority_label(value):
    try:
        return _PRIORITY_LABEL_NL[TicketPriority(value)]
    except (ValueError, KeyError):
        return str(value)


def _ticket_summary(ticket):
    lines = [
        f"Ticket: {ticket.ticket_no}",
        f"Onderwerp: {ticket.title}",
        f"Status: {_status_label(ticket.status)}",
        f"Prioriteit: {_priority_label(ticket.priority)}",
        f"Type: {_type_label(ticket.type)}",
        f"Bedrijf: {ticket.company.name}",
        f"Gebouw: {ticket.building.name}",
        f"Klant: {ticket.customer.name}",
    ]

    if ticket.room_label:
        lines.append(f"Ruimte: {ticket.room_label}")

    if ticket.assigned_to_id:
        lines.append(f"Toegewezen aan: {ticket.assigned_to.email}")

    lines.extend(["", "Omschrijving:", ticket.description])

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


def _drop_muted(users, event_type):
    """Drop users who muted this event_type in their notification preferences.

    No-op for transactional event types (PASSWORD_RESET, INVITATION_SENT) —
    those bypass preferences entirely because operators must always receive
    them. The transactional senders also never call this path (they go
    through send_logged_email directly), but we keep the guard so any future
    caller that lands here with a transactional type still sends.
    """
    if event_type not in NotificationPreference.USER_MUTABLE_EVENT_TYPES:
        return users
    if not users:
        return users

    user_ids = [user.id for user in users if user.id]
    muted_ids = set(
        NotificationPreference.objects.filter(
            user_id__in=user_ids,
            event_type=event_type,
            muted=True,
        ).values_list("user_id", flat=True)
    )
    if not muted_ids:
        return users

    return [user for user in users if user.id not in muted_ids]


def _send_to_users(ticket, users, event_type, subject, body, actor=None):
    # Recipient resolution layered as: dedupe → exclude-actor → drop-muted.
    # The mute filter sits at the recipient layer (not the Celery task), so a
    # user with muted=True never gets a NotificationLog row at all — no QUEUED
    # rows that get marked SKIPPED later, just absent from the result set.
    candidates = _drop_muted(
        _dedupe_users(_without_actor(users, actor)),
        event_type,
    )
    logs = []
    for user in candidates:
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
    subject = f"[{ticket.ticket_no}] Nieuwe ticket aangemaakt: {ticket.title}"
    body = "\n".join(
        [
            "Er is een nieuwe ticket aangemaakt.",
            "",
            _ticket_summary(ticket),
            "",
            "Met vriendelijke groet,",
            "het CleanOps-team",
            "",
            "Deze e-mail is automatisch verzonden. U kunt niet rechtstreeks reageren op dit bericht.",
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
    actor_label = getattr(actor, "email", "") or "een beheerder"
    override = (
        is_admin_override
        and str(new_status) in {str(TicketStatus.APPROVED), str(TicketStatus.REJECTED)}
    )

    if override:
        decision_word = (
            "Goedgekeurd"
            if str(new_status) == str(TicketStatus.APPROVED)
            else "Afgewezen"
        )
        subject = (
            f"[{ticket.ticket_no}] {decision_word} namens de klant door {actor_label}"
        )
        body = "\n".join(
            [
                f"Deze ticket is {decision_word.lower()} namens de klant door {actor_label}.",
                "",
                f"Oude status: {_status_label(old_status)}",
                f"Nieuwe status: {_status_label(new_status)}",
                "",
                "Bent u de klant voor deze ticket en bent u het niet eens met deze beslissing? "
                "Reageer dan op de ticket of neem contact op met uw facilitair beheerder.",
                "",
                _ticket_summary(ticket),
                "",
                "Met vriendelijke groet,",
                "het CleanOps-team",
                "",
                "Deze e-mail is automatisch verzonden. U kunt niet rechtstreeks reageren op dit bericht.",
            ]
        )
    else:
        subject = (
            f"[{ticket.ticket_no}] Status gewijzigd: "
            f"{_status_label(old_status)} → {_status_label(new_status)}"
        )
        body = "\n".join(
            [
                "De status van een ticket is gewijzigd.",
                "",
                f"Oude status: {_status_label(old_status)}",
                f"Nieuwe status: {_status_label(new_status)}",
                "",
                _ticket_summary(ticket),
                "",
                "Met vriendelijke groet,",
                "het CleanOps-team",
                "",
                "Deze e-mail is automatisch verzonden. U kunt niet rechtstreeks reageren op dit bericht.",
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

    subject = f"[{ticket.ticket_no}] Ticket aan u toegewezen: {ticket.title}"
    body = "\n".join(
        [
            "Er is een ticket aan u toegewezen.",
            "",
            _ticket_summary(ticket),
            "",
            "Met vriendelijke groet,",
            "het CleanOps-team",
            "",
            "Deze e-mail is automatisch verzonden. U kunt niet rechtstreeks reageren op dit bericht.",
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

    subject = f"[{ticket.ticket_no}] Toewijzing ingetrokken: {ticket.title}"
    body = "\n".join(
        [
            "U bent niet langer toegewezen aan deze ticket.",
            "",
            _ticket_summary(ticket),
            "",
            "Met vriendelijke groet,",
            "het CleanOps-team",
            "",
            "Deze e-mail is automatisch verzonden. U kunt niet rechtstreeks reageren op dit bericht.",
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
    subject = "Wachtwoord opnieuw instellen voor CleanOps"
    body_lines = [
        "Er is een verzoek ingediend om het wachtwoord van uw account opnieuw in te stellen.",
        "",
        f"UID: {uid}",
        f"Token: {token}",
    ]
    if reset_url:
        body_lines.extend(["", f"Herstelkoppeling: {reset_url}"])
    body_lines.extend(
        [
            "",
            "Heeft u dit verzoek niet zelf gedaan? Dan kunt u deze e-mail negeren.",
            "",
            "Met vriendelijke groet,",
            "het CleanOps-team",
            "",
            "Deze e-mail is automatisch verzonden. U kunt niet rechtstreeks reageren op dit bericht.",
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
    role_label = _role_label(invitation.role)

    scope_lines = []
    company_names = list(invitation.companies.values_list("name", flat=True))
    if company_names:
        scope_lines.append("Bedrijven: " + ", ".join(company_names))
    building_names = list(invitation.buildings.values_list("name", flat=True))
    if building_names:
        scope_lines.append("Gebouwen: " + ", ".join(building_names))
    customer_names = list(invitation.customers.values_list("name", flat=True))
    if customer_names:
        scope_lines.append("Klanten: " + ", ".join(customer_names))

    subject = f"Uitnodiging voor CleanOps als {role_label}"
    body_lines = [
        "Hallo,",
        "",
        f"{inviter_label} heeft u uitgenodigd om deel te nemen aan CleanOps als {role_label}.",
    ]
    if scope_lines:
        body_lines.append("")
        body_lines.extend(scope_lines)
    body_lines.extend([
        "",
        f"Accepteer deze uitnodiging via onderstaande link. De link verloopt op "
        f"{invitation.expires_at:%Y-%m-%d %H:%M %Z}.",
        "",
        accept_url or "(beheerder: stel INVITATION_ACCEPT_FRONTEND_URL in)",
        "",
        "Heeft u deze uitnodiging niet verwacht? Dan kunt u deze e-mail negeren.",
        "",
        "Met vriendelijke groet,",
        "het CleanOps-team",
        "",
        "Deze e-mail is automatisch verzonden. U kunt niet rechtstreeks reageren op dit bericht.",
    ])

    return send_logged_email(
        recipient_email=invitation.email,
        subject=subject,
        body="\n".join(body_lines),
        event_type=NotificationEventType.INVITATION_SENT,
        recipient_user=None,
        actor=inviter,
    )
