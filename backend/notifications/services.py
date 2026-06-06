from django.conf import settings
from django.core.mail import send_mail
from django.db.models import Q
from django.utils import timezone

from accounts.models import User, UserRole
from tickets.models import (
    TicketMessageType,
    TicketMessageVisibility,
    TicketPriority,
    TicketStatus,
    TicketType,
)

from .models import (
    Notification,
    NotificationEventType,
    NotificationLog,
    NotificationPreference,
    NotificationStatus,
    NotificationType,
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
    "send_slot_unable_to_complete_email",
    "send_password_reset_email",
    "send_invitation_email",
    "emit_ticket_message_notifications",
    "ticket_message_audience",
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


def _ticket_assigned_staff_users(ticket):
    """M1 B1 — active STAFF users assigned to this ticket.

    "Assigned STAFF" = the field workers actually placed on the ticket via
    `TicketStaffAssignment` (any slot), deduped. This is intentionally
    NARROWER than "every STAFF who could read the ticket via building
    visibility": message notifications go to the people working the job,
    not to every staff member in the building. The set is a strict subset
    of the read-visible audience, so it can never notify a STAFF user who
    cannot see the message. Slot status is not filtered — this mirrors the
    `_assigned_staff_payload` roster ("who is on this ticket").
    """
    return (
        _active_users()
        .filter(
            role=UserRole.STAFF,
            ticket_staff_assignments__ticket_id=ticket.id,
        )
        .distinct()
        .order_by("email")
    )


def ticket_message_audience(ticket, message_type):
    """M1 B3 — the NORMAL read-visible audience for a `message_type` on a
    ticket: the SAME composition `emit_ticket_message_notifications` uses for
    a NORMAL message (provider-mgmt + assigned-staff + customer-side, branched
    by tier), built from the SAME B1 resolvers. Returned deduped + active;
    NOT yet minus-author and NOT yet role/scope filtered — callers layer those
    on (the message-recipients endpoint intersects with
    message_type_visible_to_user + user_has_scope_for_ticket so its output is
    always a subset of the valid directed_to targets the B1 serializer
    accepts). Kept separate from emit so the B1 emit path is untouched.
    """
    audience = list(_ticket_staff_users(ticket))  # provider management
    if message_type != TicketMessageType.INTERNAL_NOTE:
        audience.extend(_ticket_assigned_staff_users(ticket))
    if message_type in (
        TicketMessageType.PUBLIC_REPLY,
        TicketMessageType.STAFF_COMPLETION,
    ):
        audience.extend(_ticket_customer_users(ticket))
    return _dedupe_users(audience)


def emit_ticket_message_notifications(message, actor=None):
    """M1 B1 — create in-app Notification rows for a newly created
    TicketMessage. IN-APP ONLY (no email; the lifecycle emails are
    unchanged).

    Recipients = the read-visible audience for `message.message_type`,
    branched by `message.visibility_mode`:

        message_type        NORMAL audience
        ------------------  ----------------------------------------------
        PUBLIC_REPLY        provider-mgmt + assigned-staff + customer-side
        STAFF_COMPLETION    provider-mgmt + assigned-staff + customer-side
        STAFF_OPERATIONAL   provider-mgmt + assigned-staff
        INTERNAL_NOTE       provider-mgmt ONLY

        NORMAL     -> the audience above (+ any directed_to, flagged)
        RESTRICTED -> message.directed_to only

    minus the author, deduped, active only. Every directed_to user (minus
    the author) is flagged `is_directed=True`.

    "provider-mgmt" reuses `_ticket_staff_users` (the email-path resolver =
    the ticket's COMPANY_ADMIN + BUILDING_MANAGER). SUPER_ADMIN is
    deliberately not auto-notified, matching the existing email behaviour;
    SA can still read every message directly.

    HARD invariant: an INTERNAL_NOTE never notifies a customer-side user
    and never notifies STAFF; a STAFF_OPERATIONAL never notifies a
    customer. Enforced twice — the per-type audience sets exclude those
    roles, AND a final `message_type_visible_to_user` filter drops any
    recipient (including any directed_to target) who cannot read the type.
    """
    # Lazy import keeps the module-load import graph free of any
    # notifications <-> tickets.permissions cycle risk.
    from tickets.permissions import (
        message_type_visible_to_user,
        user_has_scope_for_ticket,
    )

    ticket = message.ticket
    message_type = message.message_type

    audience = list(_ticket_staff_users(ticket))  # provider management
    if message_type != TicketMessageType.INTERNAL_NOTE:
        audience.extend(_ticket_assigned_staff_users(ticket))
    if message_type in (
        TicketMessageType.PUBLIC_REPLY,
        TicketMessageType.STAFF_COMPLETION,
    ):
        audience.extend(_ticket_customer_users(ticket))

    directed = [
        u
        for u in message.directed_to.all()
        if u and u.is_active and u.deleted_at is None
    ]

    if message.visibility_mode == TicketMessageVisibility.RESTRICTED:
        base = list(directed)
    else:
        base = audience + directed

    recipients = _dedupe_users(_without_actor(base, actor))
    # Two independent gates make the notification audience EXACTLY the
    # read-visible audience:
    #   1. ROLE gate (`message_type_visible_to_user`) — never notify a role
    #      that cannot read this tier (INTERNAL_NOTE never reaches STAFF or
    #      customer; STAFF_OPERATIONAL never reaches customer).
    #   2. SCOPE gate (`user_has_scope_for_ticket`) — never notify a user who
    #      lacks read scope on THIS ticket. This closes the customer-side
    #      gap: `_ticket_customer_users` resolves EVERY member of the
    #      ticket's customer org, but a member whose building access does not
    #      cover the ticket's building cannot open it (scope_tickets_for /
    #      the messages endpoint would 404 them), so they must not be
    #      notified either. The per-recipient check is bounded by the
    #      (small) already-deduped audience. Provider-mgmt + assigned-staff
    #      are scope-correct by construction; the redundant check on them is
    #      cheap and keeps the invariant uniform.
    recipients = [
        u
        for u in recipients
        if message_type_visible_to_user(u, message_type)
        and user_has_scope_for_ticket(u, ticket)
    ]

    directed_ids = {u.id for u in directed}

    author_label = ""
    if actor:
        author_label = (actor.full_name or actor.email or "").strip()
    body = (message.message or "").strip()
    truncated = body[:140] + ("…" if len(body) > 140 else "")
    if author_label:
        summary = f"{author_label}: {truncated}"
    else:
        summary = truncated
    summary = summary[:500]

    rows = [
        Notification(
            recipient=user,
            actor=actor,
            event_type=NotificationType.TICKET_MESSAGE,
            ticket=ticket,
            is_directed=(user.id in directed_ids),
            summary=summary,
            read_at=None,
        )
        for user in recipients
    ]
    if rows:
        Notification.objects.bulk_create(rows)
    return rows


# Dutch status labels for email rendering. The model's TextChoices labels
# remain English (canonical machine label) and stay in sync with frontend
# i18n keys; this lookup table only governs how statuses appear in email
# bodies and subjects, which Sprint B5 standardised on Dutch.
_STATUS_LABEL_NL = {
    TicketStatus.OPEN: "Open",
    TicketStatus.IN_PROGRESS: "In behandeling",
    TicketStatus.WAITING_CUSTOMER_APPROVAL: "Wacht op goedkeuring",
    TicketStatus.WAITING_MANAGER_REVIEW: "Wacht op controle beheerder",
    TicketStatus.REJECTED: "Afgewezen",
    TicketStatus.APPROVED: "Goedgekeurd",
    TicketStatus.CLOSED: "Gesloten",
    TicketStatus.REOPENED_BY_ADMIN: "Heropend",
}


# WAITING_MANAGER_REVIEW is an internal provider/manager-review state (the
# STAFF default-completion route and the unable-to-complete target). Customers
# must never be emailed about it: the unable / manager-review issue notifies
# the provider/manager side, not the customer (Ramazan). Customer-facing
# states (WAITING_CUSTOMER_APPROVAL / APPROVED / REJECTED) are unaffected.
_CUSTOMER_HIDDEN_STATUSES = {str(TicketStatus.WAITING_MANAGER_REVIEW)}


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

    # Provider-internal states never reach the customer side. The manager /
    # assigned-to (provider-side) recipients below stay unchanged.
    if str(new_status) not in _CUSTOMER_HIDDEN_STATUSES:
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


def send_slot_unable_to_complete_email(ticket, assignment, actor=None):
    """Sprint 12 — notify the provider/manager side that a staff member
    reported a dated SLOT as unable to complete, so a manager can
    reschedule / reassign.

    Unlike the ticket-level unable flow (which moves the ticket to
    WAITING_MANAGER_REVIEW and rides the status-change email), completing or
    failing a SLOT does not change ticket status, so this dedicated email is
    the only manager signal. Recipients are the provider/manager side only
    (`_ticket_staff_users` = company admins + the building's managers);
    customers are never notified (provider-internal operational follow-up),
    mirroring the unable / manager-review recipient rule.
    """
    staff_user = assignment.user
    staff_label = (
        (staff_user.full_name or staff_user.email)
        if staff_user
        else "een medewerker"
    )

    window_bits = []
    if assignment.scheduled_start_at:
        window_bits.append(
            timezone.localtime(assignment.scheduled_start_at).strftime(
                "%Y-%m-%d %H:%M"
            )
        )
    if assignment.time_window_label:
        window_bits.append(assignment.time_window_label)
    window = " / ".join(window_bits) if window_bits else "geen specifiek tijdvak"

    reason = assignment.unable_to_complete_reason or "(geen reden opgegeven)"

    subject = f"[{ticket.ticket_no}] Taak niet afgerond door {staff_label}"
    body = "\n".join(
        [
            f"{staff_label} heeft een geplande taak gemarkeerd als "
            "'niet afgerond'.",
            "",
            f"Tijdvak: {window}",
            f"Reden: {reason}",
            "",
            "Plan deze taak opnieuw in of wijs een andere medewerker toe.",
            "",
            _ticket_summary(ticket),
            "",
            "Met vriendelijke groet,",
            "het CleanOps-team",
            "",
            "Deze e-mail is automatisch verzonden. U kunt niet rechtstreeks "
            "reageren op dit bericht.",
        ]
    )

    return _send_to_users(
        ticket=ticket,
        users=list(_ticket_staff_users(ticket)),
        event_type=NotificationEventType.TICKET_SLOT_UNABLE,
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
