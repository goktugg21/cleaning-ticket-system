from decimal import Decimal

from django.conf import settings
from django.db import models


class Frequency(models.TextChoices):
    WEEKLY = "WEEKLY", "Weekly"
    BIWEEKLY = "BIWEEKLY", "Biweekly"
    MONTHLY = "MONTHLY", "Monthly"


class PricingMode(models.TextChoices):
    CONTRACT_INCLUDED = "CONTRACT_INCLUDED", "Contract included"
    FIXED = "FIXED", "Fixed price"
    # HOURLY is reserved enum space only: 11B ships NO hourly finalization
    # (actual-hours plumbing) for planned work, and the serializer restricts
    # writes to CONTRACT_INCLUDED / FIXED. The slot exists so a later sprint
    # can add hourly without a choices migration churning historical rows.
    HOURLY = "HOURLY", "Hourly (reserved — no actual-hours plumbing in 11B)"


class RecurringJob(models.Model):
    """Template describing a recurring cleaning job for one building.

    The job is the plan-of-record; the daily generator materializes
    `PlannedOccurrence` rows from it and (Batch 2) spawns operational
    Tickets per occurrence. Scope FKs are PROTECT so an in-use job blocks
    accidental deletion of its company / building / customer.
    """

    company = models.ForeignKey(
        "companies.Company",
        on_delete=models.PROTECT,
        related_name="recurring_jobs",
    )
    building = models.ForeignKey(
        "buildings.Building",
        on_delete=models.PROTECT,
        related_name="recurring_jobs",
    )
    customer = models.ForeignKey(
        "customers.Customer",
        on_delete=models.PROTECT,
        related_name="recurring_jobs",
    )

    title = models.CharField(max_length=255)
    description = models.TextField(blank=True, default="")

    frequency = models.CharField(max_length=16, choices=Frequency.choices)
    start_date = models.DateField()
    end_date = models.DateField(null=True, blank=True)
    preferred_start_time = models.TimeField(null=True, blank=True)
    time_window_label = models.CharField(max_length=64, blank=True, default="")

    pricing_mode = models.CharField(
        max_length=24,
        choices=PricingMode.choices,
        default=PricingMode.CONTRACT_INCLUDED,
    )
    fixed_price = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True
    )
    vat_pct = models.DecimalField(
        max_digits=5, decimal_places=2, default=Decimal("21.00")
    )

    # Project convention is is_active (not "active"). archived_at records
    # the soft-archive moment; PlannedOccurrence PROTECTs this job so we
    # archive rather than hard-delete and preserve occurrences for reports.
    is_active = models.BooleanField(default=True)
    archived_at = models.DateTimeField(null=True, blank=True)

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="created_recurring_jobs",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.title} ({self.frequency})"


class RecurringJobDefaultStaff(models.Model):
    """Default crew copied onto each Ticket the job's occurrences spawn."""

    recurring_job = models.ForeignKey(
        RecurringJob,
        on_delete=models.CASCADE,
        related_name="default_staff",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="recurring_job_default_staff",
    )
    added_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [("recurring_job", "user")]


class RecurringJobDefaultManager(models.Model):
    """Default managers copied onto each Ticket the job's occurrences spawn."""

    recurring_job = models.ForeignKey(
        RecurringJob,
        on_delete=models.CASCADE,
        related_name="default_managers",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="recurring_job_default_managers",
    )
    added_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [("recurring_job", "user")]


class PlannedOccurrenceStatus(models.TextChoices):
    PLANNED = "PLANNED", "Planned"
    TICKET_CREATED = "TICKET_CREATED", "Ticket created"
    COMPLETED = "COMPLETED", "Completed"
    MISSED = "MISSED", "Missed"
    RESCHEDULED = "RESCHEDULED", "Rescheduled"
    SKIPPED = "SKIPPED", "Skipped"
    CANCELLED = "CANCELLED", "Cancelled"


class PlannedOccurrence(models.Model):
    """One materialized instance of a RecurringJob on a specific date.

    `planned_date` is the immutable plan-of-record; `actual_date` carries
    the real execution date once the spawned Ticket is rescheduled or
    completed. Scope FKs are denormalized copies of the job's scope taken
    at materialization time and are NEVER rewritten on a later template
    edit — they pin the occurrence to the scope that was true when it was
    planned, for stable reporting.
    """

    # PROTECT forces archive over delete so occurrences survive for reporting.
    recurring_job = models.ForeignKey(
        RecurringJob,
        on_delete=models.PROTECT,
        related_name="occurrences",
    )

    # Denormalized scope, copied at materialization, NEVER rewritten on
    # template edit.
    company = models.ForeignKey(
        "companies.Company",
        on_delete=models.PROTECT,
        related_name="planned_occurrences",
    )
    building = models.ForeignKey(
        "buildings.Building",
        on_delete=models.PROTECT,
        related_name="planned_occurrences",
    )
    customer = models.ForeignKey(
        "customers.Customer",
        on_delete=models.PROTECT,
        related_name="planned_occurrences",
    )

    planned_date = models.DateField(db_index=True)  # IMMUTABLE plan-of-record
    # set when the ticket is rescheduled / completed
    actual_date = models.DateField(null=True, blank=True)

    status = models.CharField(
        max_length=16,
        choices=PlannedOccurrenceStatus.choices,
        default=PlannedOccurrenceStatus.PLANNED,
    )

    completed_at = models.DateTimeField(null=True, blank=True)
    missed_at = models.DateTimeField(null=True, blank=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)
    skipped_at = models.DateTimeField(null=True, blank=True)
    generated_at = models.DateTimeField(null=True, blank=True)  # when ticket spawned

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        # (recurring_job, planned_date) is THE idempotency anchor — the
        # daily generator upserts on it so re-runs never duplicate.
        unique_together = [("recurring_job", "planned_date")]
        ordering = ["planned_date"]
        indexes = [
            models.Index(fields=["status", "planned_date"]),
            models.Index(fields=["building", "planned_date"]),
        ]

    def __str__(self) -> str:
        return f"{self.recurring_job_id}@{self.planned_date} [{self.status}]"

    # NOTE: the occurrence<->ticket link is a OneToOneField declared on the
    # Ticket side; the reverse accessor is `occurrence.ticket`. There is
    # deliberately NO `ticket` FK field on this model.


class PlannedOccurrenceStatusHistory(models.Model):
    """Append-only status-change log for a PlannedOccurrence.

    Mirrors tickets.TicketStatusHistory. THIS row IS the H-11 workflow
    audit trail for planned-work transitions and must NOT be registered in
    the generic AuditLog `_*_TRACKED_FIELDS` — doing so would double-write
    the same fact.
    """

    occurrence = models.ForeignKey(
        PlannedOccurrence,
        on_delete=models.CASCADE,
        related_name="status_history",
    )
    old_status = models.CharField(max_length=16, blank=True)
    new_status = models.CharField(max_length=16)
    # SET_NULL / null because the system (Celery generator) writes
    # transitions with no human actor.
    changed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="planned_occurrence_status_changes",
    )
    note = models.TextField(blank=True, default="")
    reason = models.TextField(blank=True, default="")  # skip / cancel explanation
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]
        verbose_name_plural = "Planned occurrence status history"
