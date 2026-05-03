from django.conf import settings
from django.db import models
from django.utils import timezone


class TicketType(models.TextChoices):
    REPORT = "REPORT", "Melding / Report"
    COMPLAINT = "COMPLAINT", "Klacht / Complaint"
    REQUEST = "REQUEST", "Verzoek / Request"
    SUGGESTION = "SUGGESTION", "Suggestie / Suggestion"
    QUOTE_REQUEST = "QUOTE_REQUEST", "Offerteaanvraag / Quote Request"


class TicketPriority(models.TextChoices):
    NORMAL = "NORMAL", "Normal"
    HIGH = "HIGH", "High"
    URGENT = "URGENT", "Urgent"


class TicketStatus(models.TextChoices):
    OPEN = "OPEN", "Open"
    IN_PROGRESS = "IN_PROGRESS", "In Progress"
    WAITING_CUSTOMER_APPROVAL = "WAITING_CUSTOMER_APPROVAL", "Waiting Customer Approval"
    REJECTED = "REJECTED", "Rejected"
    APPROVED = "APPROVED", "Approved"
    CLOSED = "CLOSED", "Closed"
    REOPENED_BY_ADMIN = "REOPENED_BY_ADMIN", "Reopened by Admin"


class TicketMessageType(models.TextChoices):
    PUBLIC_REPLY = "PUBLIC_REPLY", "Public Reply"
    INTERNAL_NOTE = "INTERNAL_NOTE", "Internal Note"


def ticket_attachment_upload_path(instance, filename):
    return f"tickets/{instance.ticket_id}/{filename}"


class Ticket(models.Model):
    company = models.ForeignKey(
        "companies.Company",
        on_delete=models.CASCADE,
        related_name="tickets",
    )
    building = models.ForeignKey(
        "buildings.Building",
        on_delete=models.PROTECT,
        related_name="tickets",
    )
    customer = models.ForeignKey(
        "customers.Customer",
        on_delete=models.PROTECT,
        related_name="tickets",
    )

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="created_tickets",
    )
    assigned_to = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="assigned_tickets",
    )

    ticket_no = models.CharField(max_length=32, unique=True, blank=True)

    title = models.CharField(max_length=255)
    description = models.TextField()
    room_label = models.CharField(max_length=255, blank=True)

    type = models.CharField(
        max_length=32,
        choices=TicketType.choices,
        default=TicketType.REPORT,
    )
    priority = models.CharField(
        max_length=32,
        choices=TicketPriority.choices,
        default=TicketPriority.NORMAL,
    )
    status = models.CharField(
        max_length=64,
        choices=TicketStatus.choices,
        default=TicketStatus.OPEN,
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    first_response_at = models.DateTimeField(null=True, blank=True)
    sent_for_approval_at = models.DateTimeField(null=True, blank=True)
    approved_at = models.DateTimeField(null=True, blank=True)
    rejected_at = models.DateTimeField(null=True, blank=True)
    resolved_at = models.DateTimeField(null=True, blank=True)
    closed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.ticket_no or self.id} - {self.title}"

    def save(self, *args, **kwargs):
        is_new = self.pk is None
        super().save(*args, **kwargs)

        if is_new and not self.ticket_no:
            self.ticket_no = f"TCK-{self.created_at.year}-{self.id:06d}"
            super().save(update_fields=["ticket_no"])

    def mark_first_response_if_needed(self):
        if not self.first_response_at:
            self.first_response_at = timezone.now()
            self.save(update_fields=["first_response_at"])


class TicketMessage(models.Model):
    ticket = models.ForeignKey(
        Ticket,
        on_delete=models.CASCADE,
        related_name="messages",
    )
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="ticket_messages",
    )

    message = models.TextField()
    message_type = models.CharField(
        max_length=32,
        choices=TicketMessageType.choices,
        default=TicketMessageType.PUBLIC_REPLY,
    )

    is_hidden = models.BooleanField(default=False)
    hidden_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="hidden_ticket_messages",
    )
    hidden_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]

    def __str__(self):
        return f"{self.ticket} - {self.author}"


class TicketAttachment(models.Model):
    ticket = models.ForeignKey(
        Ticket,
        on_delete=models.CASCADE,
        related_name="attachments",
    )
    message = models.ForeignKey(
        TicketMessage,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="attachments",
    )
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="ticket_attachments",
    )

    file = models.FileField(upload_to=ticket_attachment_upload_path)
    original_filename = models.CharField(max_length=255)
    mime_type = models.CharField(max_length=120)
    file_size = models.PositiveIntegerField()
    is_hidden = models.BooleanField(default=False)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return self.original_filename


class TicketStatusHistory(models.Model):
    ticket = models.ForeignKey(
        Ticket,
        on_delete=models.CASCADE,
        related_name="status_history",
    )

    old_status = models.CharField(max_length=64, blank=True)
    new_status = models.CharField(max_length=64)
    changed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="ticket_status_changes",
    )
    note = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]
        verbose_name_plural = "Ticket status history"

    def __str__(self):
        return f"{self.ticket}: {self.old_status} → {self.new_status}"
