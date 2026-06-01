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


class TicketScheduleStatus(models.TextChoices):
    """
    Sprint 9B — operational scheduling lifecycle on a Ticket.

    Additive to the existing `TicketStatus` workflow: scheduling is an
    orthogonal axis (when is the work planned) that never changes the
    workflow status and never disturbs SLA (SLA stays anchored on
    `created_at`). A ticket is UNSCHEDULED until a provider operator
    sets a `scheduled_start_at`; rescheduling an already-scheduled
    ticket records the prior start + a mandatory reason and lands the
    row in RESCHEDULED. Clearing the schedule returns it to UNSCHEDULED.
    """

    UNSCHEDULED = "UNSCHEDULED", "Unscheduled"
    SCHEDULED = "SCHEDULED", "Scheduled"
    RESCHEDULED = "RESCHEDULED", "Rescheduled"


class TicketStatus(models.TextChoices):
    OPEN = "OPEN", "Open"
    IN_PROGRESS = "IN_PROGRESS", "In Progress"
    # Sprint 28 Batch 11 — STAFF default completion route. When a STAFF
    # user marks their work done, the ticket lands here for BM review.
    # BM accepts -> WAITING_CUSTOMER_APPROVAL, or rejects -> IN_PROGRESS.
    # The per-(staff, building) `BuildingStaffVisibility
    # .staff_completion_routes_to_customer` flag can opt a staff out of
    # this default and route directly to WAITING_CUSTOMER_APPROVAL.
    WAITING_MANAGER_REVIEW = "WAITING_MANAGER_REVIEW", "Waiting Manager Review"
    WAITING_CUSTOMER_APPROVAL = "WAITING_CUSTOMER_APPROVAL", "Waiting Customer Approval"
    REJECTED = "REJECTED", "Rejected"
    APPROVED = "APPROVED", "Approved"
    CLOSED = "CLOSED", "Closed"
    REOPENED_BY_ADMIN = "REOPENED_BY_ADMIN", "Reopened by Admin"
    # Sprint 7B — terminal status for a normal ticket that a provider
    # converted into an Extra Work request. The original ticket is
    # SUPERSEDED (it leaves every operational queue); a NEW operational
    # ticket is spawned later by the Sprint 6A/6B machinery anchored to
    # the new ExtraWorkRequest — the original is NOT reused. This status
    # is intentionally absent from `ALLOWED_TRANSITIONS` in
    # `state_machine.py`, keeping it terminal: no transition leaves it.
    CONVERTED_TO_EXTRA_WORK = "CONVERTED_TO_EXTRA_WORK", "Converted to Extra Work"


class TicketMessageType(models.TextChoices):
    """
    B7 — four-tier note taxonomy (`docs/product/system-business-logic-
    and-workflows.md` §9). Each `TicketMessage` carries one value; the
    enum value IS the canonical visibility classification.

      * `PUBLIC_REPLY` — CUSTOMER_VISIBLE. Visible to customer-side
        users in scope and to every provider-side role.
      * `INTERNAL_NOTE` — PROVIDER_INTERNAL. Visible only to provider
        management roles in scope (Super Admin, Company Admin,
        Building Manager). NOT visible to STAFF or any customer-side
        role. The literal `"INTERNAL_NOTE"` is preserved so legacy
        rows keep their semantic without a data migration; the value
        itself is the PROVIDER_INTERNAL tier.
      * `STAFF_OPERATIONAL` — STAFF_OPERATIONAL. Visible to every
        provider-side role including STAFF in scope. NOT visible to
        customer. Used for operational instructions field staff need
        to do the job (e.g. "bring a ladder", "use the back entrance").
      * `STAFF_COMPLETION` — STAFF_COMPLETION / evidence. Written by
        STAFF as completion evidence; visible to provider-side users
        in scope; customer-visible per the existing staff-completion
        evidence rule (P0/B1).
    """

    PUBLIC_REPLY = "PUBLIC_REPLY", "Public Reply"
    INTERNAL_NOTE = "INTERNAL_NOTE", "Internal Note (provider-internal)"
    STAFF_OPERATIONAL = "STAFF_OPERATIONAL", "Staff Operational Note"
    STAFF_COMPLETION = "STAFF_COMPLETION", "Staff Completion Note"


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
    # Sprint 28 Batch 11 — stamped when the ticket enters
    # WAITING_MANAGER_REVIEW (the STAFF default completion route).
    # Loop semantics mirror the rest of the timestamp cluster: a BM
    # rejection back to IN_PROGRESS followed by another STAFF completion
    # overwrites the value.
    manager_review_at = models.DateTimeField(null=True, blank=True)
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
    #
    # Sprint 6A — retained for back-compat of the origin payload's
    # `extra_work_request_item_id` / `service_name` keys. NOT the
    # canonical EW link anymore: a request now spawns exactly ONE
    # ticket and the canonical parent is `extra_work_request` below.
    # The instant / legacy helpers set `extra_work_request_item` to the
    # FIRST cart line; the proposal helper sets `proposal_line` to the
    # FIRST is_approved_for_spawn line — purely so the origin payload
    # can surface a representative service name.
    proposal_line = models.ForeignKey(
        "extra_work.ProposalLine",
        on_delete=models.SET_NULL,
        related_name="spawned_tickets_for_proposal_line",
        null=True,
        blank=True,
        default=None,
    )

    # Sprint 6A — CANONICAL parent Extra Work request. One
    # ExtraWorkRequest spawns exactly ONE operational Ticket; this FK
    # is that link. SET_NULL so the operational job survives if the
    # parent EW is later soft/hard-deleted. No DB unique constraint:
    # historical data carries multiple tickets per request, so a
    # unique index would fail the backfill. Idempotency
    # (one-ticket-per-request) is enforced in the spawn helpers + tests.
    extra_work_request = models.ForeignKey(
        "extra_work.ExtraWorkRequest",
        on_delete=models.SET_NULL,
        related_name="operational_tickets",
        null=True,
        blank=True,
        default=None,
    )

    # Sprint 11B origin link — the operational Ticket spawned from a
    # recurring / planned occurrence. OneToOne so one occurrence has at
    # most one ticket (idempotency, DB-enforced) and `occurrence.ticket`
    # resolves the reverse. SET_NULL so the ticket survives if the
    # occurrence is hard-deleted. This is the THIRD origin axis next to
    # `extra_work_request` for report separation (planned vs ad-hoc vs
    # Extra Work).
    planned_occurrence = models.OneToOneField(
        "planned_work.PlannedOccurrence",
        on_delete=models.SET_NULL,
        related_name="ticket",
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

    # Sprint 9B — operational scheduling (additive; orthogonal to the
    # workflow `status` field and to SLA). `scheduled_start_at` is the
    # planned start of the on-site work; `scheduled_end_at` is the
    # optional planned end; `time_window_label` is a free-text window
    # hint ("morning", "08:00-10:00"). `schedule_status` tracks the
    # UNSCHEDULED / SCHEDULED / RESCHEDULED lifecycle. On a reschedule,
    # `rescheduled_from` keeps the prior start and `reschedule_reason`
    # holds the mandatory operator explanation. SLA is NOT affected:
    # the schedule endpoints save with an explicit `update_fields` set
    # that excludes `status`, so the SLA post_save signal sees no
    # status change and never recomputes `sla_*`.
    scheduled_start_at = models.DateTimeField(
        null=True, blank=True, db_index=True, default=None
    )
    scheduled_end_at = models.DateTimeField(null=True, blank=True, default=None)
    time_window_label = models.CharField(max_length=64, blank=True, default="")
    schedule_status = models.CharField(
        max_length=16,
        choices=TicketScheduleStatus.choices,
        default=TicketScheduleStatus.UNSCHEDULED,
    )
    rescheduled_from = models.DateTimeField(null=True, blank=True, default=None)
    reschedule_reason = models.TextField(blank=True, default="")

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


class TicketManagerAssignment(models.Model):
    """
    Sprint 10B — EXPLICIT per-ticket responsible-manager M:N (SoT §4.2).

    Mirrors `TicketStaffAssignment` exactly: a ticket may carry more
    than one responsible BUILDING_MANAGER at the same time, with each
    assignment recording who made it and when.

    Relationship to the two neighbouring concepts (do NOT conflate):

      * `Ticket.assigned_to` stays the LEGACY / compat single "primary
        manager" pointer. This new table does not change its meaning,
        does not remove it, and is not a replacement for it — the two
        coexist (the single pointer is still what the existing UI and
        the `assign` endpoint read/write).
      * `BuildingManagerAssignment` (buildings app) remains the
        BUILDING-LEVEL authority / visibility grant. Holding it is the
        eligibility precondition for being added here, but it is NOT
        itself per-ticket responsibility — a BM can be authoritative on
        a building without being a named responsible manager on a given
        ticket.

    Removal is a hard delete (mirrors `TicketStaffAssignment`): there is
    no soft-remove column, matching the existing membership pattern.

    Validation (enforced at the endpoint / serializer layer, not via a
    DB check, mirroring `TicketStaffAssignment`):
      - user.role MUST be UserRole.BUILDING_MANAGER.
      - The user MUST hold a `BuildingManagerAssignment` for
        ticket.building.
    """

    ticket = models.ForeignKey(
        Ticket,
        on_delete=models.CASCADE,
        related_name="manager_assignments",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="ticket_manager_assignments",
    )
    assigned_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="manager_assignments_made",
    )
    assigned_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [("ticket", "user")]
        indexes = [models.Index(fields=["ticket", "user"])]

    def __str__(self):
        return f"{self.user.email} ⇒ {self.ticket}"


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
