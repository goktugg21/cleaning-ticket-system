from pathlib import Path as FilePath
from uuid import uuid4

from django.conf import settings
from django.db import models, transaction
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
    extension = FilePath(filename).suffix.lower()
    return f"tickets/{instance.ticket_id}/{uuid4().hex}{extension}"


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

    ticket_no = models.CharField(max_length=32, unique=True, null=True, blank=True)

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

    # Soft-delete (Sprint 12). The TicketViewSet's DESTROY action sets
    # both fields and the row stays in the database; scope_tickets_for
    # / tickets_for_scope filter rows where deleted_at IS NOT NULL out
    # of every list, detail, and report query. The internal
    # ticket-status history, messages, and attachments are preserved
    # so an operator can audit the row even after a soft delete.
    deleted_at = models.DateTimeField(null=True, blank=True, db_index=True)
    deleted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="deleted_tickets",
    )

    first_response_at = models.DateTimeField(null=True, blank=True)
    sent_for_approval_at = models.DateTimeField(null=True, blank=True)
    approved_at = models.DateTimeField(null=True, blank=True)
    rejected_at = models.DateTimeField(null=True, blank=True)
    resolved_at = models.DateTimeField(null=True, blank=True)
    closed_at = models.DateTimeField(null=True, blank=True)

    # Sprint 28 Batch 7 — link back to the ExtraWorkRequestItem this
    # Ticket was spawned from. NULL for tickets created by any other
    # path (legacy creation, direct API submission, etc.). SET_NULL on
    # the EW side's delete so a Ticket survives if the cart line is
    # later removed — the operational job has already been scheduled
    # / executed and dropping it would lose audit history.
    extra_work_request_item = models.ForeignKey(
        "extra_work.ExtraWorkRequestItem",
        on_delete=models.SET_NULL,
        related_name="spawned_tickets",
        null=True,
        blank=True,
        default=None,
    )

    # Sprint 28 Batch 8 — link back to the ProposalLine this Ticket
    # was spawned from. NULL on tickets that came through the instant
    # route (Batch 7), the legacy ticket-create path, or any other
    # surface. SET_NULL so a Ticket survives if the proposal / line
    # is later deleted — the operational job has audit history we
    # don't want to lose.
    proposal_line = models.ForeignKey(
        "extra_work.ProposalLine",
        on_delete=models.SET_NULL,
        related_name="spawned_tickets_for_proposal_line",
        null=True,
        blank=True,
        default=None,
    )

    # SLA tracking. Engine lives in backend/sla/. sla_first_breached_at is a
    # permanent marker that survives reopens; the rest are recomputed by the
    # engine and the periodic reconciliation task.
    sla_due_at = models.DateTimeField(null=True, blank=True, db_index=True)
    sla_started_at = models.DateTimeField(null=True, blank=True)
    sla_completed_at = models.DateTimeField(null=True, blank=True)
    sla_paused_at = models.DateTimeField(null=True, blank=True)
    sla_paused_seconds = models.PositiveIntegerField(default=0)
    sla_first_breached_at = models.DateTimeField(null=True, blank=True)
    sla_status = models.CharField(
        max_length=16,
        choices=[
            ("ON_TRACK", "On track"),
            ("AT_RISK", "At risk"),
            ("BREACHED", "Breached"),
            ("COMPLETED", "Completed"),
            ("HISTORICAL", "Historical"),
        ],
        default="ON_TRACK",
        db_index=True,
    )

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.ticket_no or self.id} - {self.title}"

    def save(self, *args, **kwargs):
        is_new = self.pk is None

        if not is_new:
            super().save(*args, **kwargs)
            return

        with transaction.atomic():
            super().save(*args, **kwargs)
            if not self.ticket_no:
                self.ticket_no = f"TCK-{self.created_at.year}-{self.id:06d}"
                type(self).objects.filter(pk=self.pk).update(ticket_no=self.ticket_no)

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
    # Sprint 27F-B1 — workflow override flag. Mirrors
    # `ExtraWorkStatusHistory.is_override` / `override_reason`. Set
    # when a provider operator drives a customer-decision transition
    # (WAITING_CUSTOMER_APPROVAL -> APPROVED/REJECTED) — the reason
    # is the operator's audit-trail explanation. Distinct from
    # `note` (which is a generic transition note that may be empty
    # on non-override transitions). H-11 invariant: workflow
    # override is separate from permission override.
    is_override = models.BooleanField(default=False)
    override_reason = models.TextField(blank=True, default="")

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]
        verbose_name_plural = "Ticket status history"

    def __str__(self):
        return f"{self.ticket}: {self.old_status} → {self.new_status}"


class TicketStaffAssignment(models.Model):
    """
    Sprint 23A — additive M:N between Ticket and STAFF user.

    The existing single `Ticket.assigned_to` FK stays as the legacy
    "primary assignee" the existing UI and tests read. This new
    through-style table lets a ticket carry multiple assigned
    staff at the same time (per the OSIUS workflow: "a job may have
    multiple staff; any one completing it moves it to manager
    review"). The workflow change is staged for Sprint 23B — in
    23A the rows are informational only and the existing state
    machine is unchanged.

    Validation (enforced at serializer level, not via a DB check):
      - user.role MUST be UserRole.STAFF.
      - The user MUST hold BuildingStaffVisibility for ticket.building
        (or the assignment was created by a manager who can override).
    """

    ticket = models.ForeignKey(
        Ticket,
        on_delete=models.CASCADE,
        related_name="staff_assignments",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="ticket_staff_assignments",
    )
    assigned_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="staff_assignments_made",
    )
    assigned_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [("ticket", "user")]
        indexes = [models.Index(fields=["ticket", "user"])]

    def __str__(self):
        return f"{self.user.email} → {self.ticket}"


class AssignmentRequestStatus(models.TextChoices):
    """Sprint 23A — lifecycle of a staff-initiated assignment request."""

    PENDING = "PENDING", "Pending"
    APPROVED = "APPROVED", "Approved"
    REJECTED = "REJECTED", "Rejected"
    CANCELLED = "CANCELLED", "Cancelled"


class StaffAssignmentRequest(models.Model):
    """
    Sprint 23A — a STAFF user's "I want to do this work / assign me
    to this" request, awaiting BUILDING_MANAGER (or higher) review.

    Internal to the service-provider side. Never serialized for
    CUSTOMER_USER. A BUILDING_MANAGER may approve or reject
    requests for buildings they hold a BuildingManagerAssignment
    in; COMPANY_ADMIN and SUPER_ADMIN can act on any request.
    """

    staff = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="assignment_requests",
    )
    ticket = models.ForeignKey(
        Ticket,
        on_delete=models.CASCADE,
        related_name="assignment_requests",
    )
    status = models.CharField(
        max_length=16,
        choices=AssignmentRequestStatus.choices,
        default=AssignmentRequestStatus.PENDING,
    )

    requested_at = models.DateTimeField(auto_now_add=True)

    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="reviewed_assignment_requests",
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    reviewer_note = models.TextField(blank=True)

    class Meta:
        ordering = ["-requested_at"]
        indexes = [
            models.Index(fields=["status", "ticket"]),
            models.Index(fields=["staff", "status"]),
        ]

    def __str__(self):
        return f"{self.staff.email} → {self.ticket} ({self.status})"
