from django.conf import settings
from django.db import models
from django.utils import timezone


class NotificationEventType(models.TextChoices):
    TICKET_CREATED = "TICKET_CREATED", "Ticket created"
    TICKET_STATUS_CHANGED = "TICKET_STATUS_CHANGED", "Ticket status changed"
    TICKET_ASSIGNED = "TICKET_ASSIGNED", "Ticket assigned"
    TICKET_UNASSIGNED = "TICKET_UNASSIGNED", "Ticket unassigned"
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
