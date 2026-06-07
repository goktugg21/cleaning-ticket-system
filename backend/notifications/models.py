from django.conf import settings
from django.db import models
from django.utils import timezone


class NotificationEventType(models.TextChoices):
    TICKET_CREATED = "TICKET_CREATED", "Ticket created"
    TICKET_STATUS_CHANGED = "TICKET_STATUS_CHANGED", "Ticket status changed"
    TICKET_ASSIGNED = "TICKET_ASSIGNED", "Ticket assigned"
    TICKET_UNASSIGNED = "TICKET_UNASSIGNED", "Ticket unassigned"
    # Sprint 12 — a staff member reported a dated SLOT as unable-to-complete
    # (slot_status=UNABLE_TO_COMPLETE on the slot PATCH). Unlike the
    # ticket-level unable flow this does NOT change ticket status, so the
    # status-change email never fires; the provider managers are notified
    # via a dedicated event so they can reschedule. Deliberately NOT in
    # USER_MUTABLE_EVENT_TYPES — operational follow-up must always reach
    # the managers.
    TICKET_SLOT_UNABLE = "TICKET_SLOT_UNABLE", "Staff slot unable to complete"
    PASSWORD_RESET = "PASSWORD_RESET", "Password reset"
    INVITATION_SENT = "INVITATION_SENT", "Invitation sent"


class NotificationStatus(models.TextChoices):
    QUEUED = "QUEUED", "Queued"
    SENT = "SENT", "Sent"
    FAILED = "FAILED", "Failed"
    SKIPPED = "SKIPPED", "Skipped"


class NotificationLog(models.Model):
    ticket = models.ForeignKey(
        "tickets.Ticket",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="notification_logs",
    )
    recipient_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="received_notification_logs",
    )
    triggered_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="triggered_notification_logs",
    )

    recipient_email = models.EmailField()
    event_type = models.CharField(max_length=64, choices=NotificationEventType.choices)
    subject = models.CharField(max_length=255)
    body = models.TextField()

    status = models.CharField(
        max_length=32,
        choices=NotificationStatus.choices,
        default=NotificationStatus.SENT,
    )
    error_message = models.TextField(blank=True)
    sent_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.event_type} → {self.recipient_email} ({self.status})"

    def mark_sent(self):
        self.status = NotificationStatus.SENT
        self.error_message = ""
        self.sent_at = timezone.now()
        self.save(update_fields=["status", "error_message", "sent_at"])

    def mark_failed(self, message):
        self.status = NotificationStatus.FAILED
        self.error_message = str(message)
        self.sent_at = None
        self.save(update_fields=["status", "error_message", "sent_at"])

    def mark_queued(self):
        self.status = NotificationStatus.QUEUED
        self.save(update_fields=["status"])


class NotificationType(models.TextChoices):
    """In-app (bell / message-center) notification event types.

    Deliberately SEPARATE from the email `NotificationEventType` above:
    in-app notifications are a different surface with a different lifecycle
    (no SMTP, no NotificationLog, read/unread per recipient). Overloading
    the email enum here would conflate the two channels. B1 ships
    TICKET_MESSAGE; B4 adds the Extra Work lifecycle event types below.
    """

    TICKET_MESSAGE = "TICKET_MESSAGE", "Ticket message"

    # M1 B4 — Extra Work lifecycle (in-app only; no email path is added).
    #   EXTRA_WORK_REQUESTED      a new EW request needs provider attention.
    #   EXTRA_WORK_PROPOSAL_SENT  a quote/proposal was sent; customer decides.
    #   EXTRA_WORK_DECISION       the customer approved OR rejected. ONE type:
    #     the approved-vs-rejected distinction is carried in the row `summary`
    #     (and the deep-linked EW status), not in a separate event_type. A
    #     single type keeps the FE bell/page rendering generic and avoids a
    #     migration churn pair where one would do.
    EXTRA_WORK_REQUESTED = "EXTRA_WORK_REQUESTED", "Extra work requested"
    EXTRA_WORK_PROPOSAL_SENT = (
        "EXTRA_WORK_PROPOSAL_SENT",
        "Extra work proposal sent",
    )
    EXTRA_WORK_DECISION = "EXTRA_WORK_DECISION", "Extra work decision"

    # M1 B6 — Extra Work message thread (mirrors TICKET_MESSAGE, in-app only).
    #   EXTRA_WORK_MESSAGE    a new message on an Extra Work request thread.
    #   EXTRA_WORK_PUBLISHED  item-7: a provider direct-published (quote-bypass)
    #     the customer's extra work WITHOUT a separate decision step — the
    #     customer is told it was approved/started.
    EXTRA_WORK_MESSAGE = "EXTRA_WORK_MESSAGE", "Extra work message"
    EXTRA_WORK_PUBLISHED = "EXTRA_WORK_PUBLISHED", "Extra work published"


class Notification(models.Model):
    """In-app notification (M1 — message center, phase B1).

    One row per (recipient, triggering event). Distinct from
    `NotificationLog`, which is the EMAIL audit/delivery log. A
    `Notification` is purely an in-app signal: it is created when a
    ticket message (B1) — and later an Extra Work event (B4) — needs the
    recipient's attention, and it is dismissed by setting `read_at`.

    Source / deep-link reference (FE route derivation): a nullable
    `ticket` FK covers both ticket and *melding* (a melding IS a ticket),
    and a nullable `extra_work` FK is added forward-compatibly for B4
    (unused in B1). The FE derives the route from whichever FK is set:
    `ticket` -> /tickets/<id>, `extra_work` -> /extra-work/<id>. Explicit
    FKs (over a (source_kind, source_id) pair) keep referential integrity
    and allow cheap select_related for the feed.
    """

    recipient = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        db_index=True,
        related_name="notifications",
    )
    # Who triggered the notification (message author / actor). SET_NULL so
    # deleting the actor never destroys the recipient's notification.
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="emitted_notifications",
    )

    event_type = models.CharField(
        max_length=32,
        choices=NotificationType.choices,
    )

    # True when this recipient was personally named in the message's
    # `directed_to` set (FE renders "directed to you"). For a NORMAL
    # message the directed recipients are a flagged subset of the audience;
    # for a RESTRICTED message they ARE the audience.
    is_directed = models.BooleanField(default=False)

    # Deep-link source. Exactly one is set in B1 (ticket). CASCADE: an
    # in-app notification is an ephemeral UX signal, not the audit trail
    # (the AuditLog / *StatusHistory rows are), so if the source row is
    # ever hard-deleted its now-dead deep-links go with it.
    ticket = models.ForeignKey(
        "tickets.Ticket",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="inapp_notifications",
    )
    extra_work = models.ForeignKey(
        "extra_work.ExtraWorkRequest",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="inapp_notifications",
    )

    # Short denormalised display line (author label + truncated body). Only
    # content the recipient is already allowed to see is stored here (the
    # recipient set is the message's visible audience), so this carries no
    # PII the recipient could not already read on the ticket.
    summary = models.CharField(max_length=500, blank=True, default="")

    # NULL = unread. Set to now() when the recipient marks it read.
    read_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["recipient", "read_at"]),
        ]

    def __str__(self):
        state = "read" if self.read_at else "unread"
        return f"{self.event_type} -> {self.recipient_id} ({state})"


class NotificationPreference(models.Model):
    """Per-user mute toggle for a notification event type.

    Absence of a row is the default (unmuted). A row with muted=True silences
    that event for the user. Only the user-mutable event types are stored
    here; transactional types (PASSWORD_RESET, INVITATION_SENT) are never
    read from this table — those mails always go out for security and
    onboarding reasons.
    """

    USER_MUTABLE_EVENT_TYPES = (
        NotificationEventType.TICKET_CREATED,
        NotificationEventType.TICKET_STATUS_CHANGED,
        NotificationEventType.TICKET_ASSIGNED,
        NotificationEventType.TICKET_UNASSIGNED,
    )

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="notification_preferences",
    )
    event_type = models.CharField(
        max_length=64,
        choices=NotificationEventType.choices,
    )
    muted = models.BooleanField(default=False)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ("user", "event_type")
        indexes = [
            models.Index(fields=["user", "event_type"]),
        ]

    def __str__(self):
        state = "muted" if self.muted else "unmuted"
        return f"{self.user_id}/{self.event_type} → {state}"
