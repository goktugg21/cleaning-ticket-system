"""
Sprint 152 — employee hours (urenregistratie).

An INDEPENDENT business module: it records how much an employee
worked, never what work was performed. There is deliberately NO
relationship to `tickets`, `extra_work` or `planned_work` — no FK, no
import, no derived value. A provider company that uses nothing else in
this system must still be able to run its timesheets here, and a later
"link hours to a ticket" idea has to be designed as its own sprint
rather than discovered as a field that quietly grew here.

Payroll is out of scope by the same rule: the module records HOURS and
WEIGHTED hours (`hours * multiplier_snapshot`). It never holds a wage,
never multiplies by one, and never computes money.

Three models:

  * `HourType`   — the per-company catalog of hour kinds and their
    multipliers ("Overwerk" 1.50). Same architecture as
    `extra_work.ServiceCategory` / `ManagedUnit` post-Sprint 142:
    company FK + a case/whitespace-insensitive per-company unique name.
  * `TimeEntry`  — one amount of work, one employee, one day.
  * `WeekLock`   — a company-wide week close. ABSENCE of a row means
    the week is OPEN; weeks are never pre-created.
"""
from __future__ import annotations

from decimal import Decimal

from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models.functions import Lower, Trim

from .standard_set import STANDARD_SLOT_CHOICES, slot_for_name


# The bounds are repeated as module constants so the serializer layer
# can quote the SAME numbers in its friendly-400 messages instead of
# re-typing them (and drifting from the validators below).
MULTIPLIER_MIN = Decimal("0.00")
MULTIPLIER_MAX = Decimal("9.99")
HOURS_MIN = Decimal("0.25")
HOURS_MAX = Decimal("24.00")


class HourType(models.Model):
    """
    Sprint 152 — a per-provider-company catalog of hour kinds.

    `multiplier` is the weighting factor an hour of this kind carries:
    1.00 for ordinary hours, 1.50 for overtime, 2.00 for a public
    holiday. **0.00 is a legal value** and is the reason the lower bound
    is not `0.01` — unpaid leave is recorded as hours worked zero-times,
    not as an absent row. A report that silently dropped those entries
    would under-count someone's registered absence.

    A multiplier is a WEIGHT, not a rate: nothing in this app multiplies
    it by money. See the module docstring.

    Uniqueness is per company and case/whitespace-insensitive, expressed
    as the expression constraint below rather than a field-level
    `unique=True` — the exact shape `ServiceCategory` and `ManagedUnit`
    settled on. Two providers may each carry "Overwerk"; one provider
    may not carry it twice. Unlike those two models this constraint is
    created WITH the table, so there is never a window in which the
    column exists without it.

    Archiving (`is_active=False`) removes the type from the pickers for
    NEW entries while every existing `TimeEntry` keeps its FK and its
    `multiplier_snapshot`. Hard DELETE is only possible while the type
    is unused — `TimeEntry.hour_type` is PROTECT, and the view turns the
    resulting `ProtectedError` into a friendly 400 the way the catalog
    views do.
    """

    company = models.ForeignKey(
        "companies.Company",
        on_delete=models.PROTECT,
        related_name="hour_types",
        help_text=(
            "Provider company that owns this hour type. PROTECT mirrors "
            "ServiceCategory.company: a Company cannot be hard-deleted "
            "while it still owns hour types."
        ),
    )
    # NOT `unique=True`: uniqueness is per-company and
    # case/whitespace-insensitive, expressed as the constraint below.
    name = models.CharField(
        max_length=128,
        help_text='Operator-facing name, e.g. "Normale uren", "Overwerk".',
    )
    multiplier = models.DecimalField(
        max_digits=4,
        decimal_places=2,
        default=Decimal("1.00"),
        validators=[
            MinValueValidator(MULTIPLIER_MIN),
            MaxValueValidator(MULTIPLIER_MAX),
        ],
        help_text=(
            "Weighting factor for an hour of this kind (1.00 = normal, "
            "1.50 = overtime). 0.00 is legal — unpaid leave. This is a "
            "weight, never a wage: nothing here computes money."
        ),
    )
    is_active = models.BooleanField(
        default=True,
        help_text=(
            "Archived types stay on existing entries but are not "
            "offerable for new ones."
        ),
    )
    sort_order = models.PositiveIntegerField(
        default=0,
        help_text="Ascending display order in the pickers; ties break on name.",
    )
    # Sprint 152.3 — which of the six standard kinds this row IS, or ""
    # for a company's own custom type. DERIVED from `name` in `save()`;
    # never set by a client, never hand-edited.
    standard_slot = models.CharField(
        max_length=32,
        blank=True,
        default="",
        choices=STANDARD_SLOT_CHOICES,
        help_text=(
            "Derived from `name`: the standard kind this row is "
            "recognised as, or blank for a custom type. Lets the UI show "
            "a standard name in each reader's own language while `name` "
            "stays a single operator-typed column."
        ),
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["sort_order", "name", "id"]
        verbose_name = "hour type"
        verbose_name_plural = "hour types"
        constraints = [
            # Trim() first so leading/trailing whitespace cannot bypass a
            # Lower()-only dedupe, Lower() for case — the ManagedUnit /
            # ServiceCategory shape.
            models.UniqueConstraint(
                Lower(Trim("name")),
                "company",
                name="uniq_hour_type_name_per_company_ci",
            ),
        ]

    def save(self, *args, **kwargs):
        """Derive `standard_slot` from `name` on EVERY save.

        Here rather than in the serializer, for the same reason
        `TimeEntry.save` derives `iso_year` / `iso_week` here: a
        management command, a data migration or a shell write must not be
        able to produce a row whose stored slot contradicts its own name.
        There is exactly one derivation (`slot_for_name`) and every write
        path goes through it.

        `update_fields` is widened when `name` is among them — otherwise
        a targeted `save(update_fields=["name"])` would persist the new
        name and leave the old slot behind, which is the precise
        contradiction this method exists to prevent.
        """
        self.standard_slot = slot_for_name(self.name)
        update_fields = kwargs.get("update_fields")
        if update_fields is not None and "name" in set(update_fields):
            kwargs["update_fields"] = list(
                set(update_fields) | {"standard_slot"}
            )
        return super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.name} (x{self.multiplier})"


class TimeEntry(models.Model):
    """
    Sprint 152 — one amount of work, one employee, one day.

    `company` is a DENORMALIZED tenant anchor resolved from the
    employee's provider-company membership at write time (see
    `resolution.resolve_entry_company`). It is denormalized rather than
    joined through the employee because an employee's memberships can
    change and a historical entry must keep the tenant it was filed
    under — and because every scoping query in this app filters on it.

    `iso_year` / `iso_week` are DERIVED from `date` on every save via
    `date.isocalendar()` and are never client-supplied. They are stored
    rather than computed on read so the week-lock lookup and the
    per-week report grouping are plain indexed equality tests instead of
    a function over a column. ISO weeks are the reason both halves are
    stored: 2027-01-01 belongs to ISO week 53 of 2026, so the year on
    the date and the year on the week genuinely differ.

    `date` accepts PAST AND FUTURE days on purpose — vacation is planned
    ahead, and a module that refused tomorrow's date could not record it.

    `multiplier_snapshot` is the immutability core. It is copied from
    `hour_type.multiplier` on every create and every update, and EVERY
    weighted computation in this app reads the snapshot, never the live
    multiplier. Editing a type's multiplier refreshes the snapshot on
    that type's entries in OPEN weeks only (see
    `views_hour_types.HourTypeDetailView.perform_update`); a closed
    week's weighted totals are therefore byte-identical before and after
    such an edit.

    Multiple entries per employee per day are allowed and expected — a
    day can hold normal hours in one building and overtime in another.
    There is deliberately no cross-entry per-day sum validation in v1:
    the rule people actually want ("no more than 24h in a day") is a
    company policy with exceptions, and guessing it would block legal
    corrections mid-edit.
    """

    company = models.ForeignKey(
        "companies.Company",
        on_delete=models.PROTECT,
        related_name="time_entries",
        help_text=(
            "Denormalized tenant anchor, resolved from the employee's "
            "provider-company membership at write time."
        ),
    )
    employee = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="time_entries",
        help_text=(
            "The provider-side employee whose hours these are. Must hold "
            "an active membership in `company` with a provider role "
            "(STAFF / BUILDING_MANAGER / COMPANY_ADMIN) — never a "
            "customer-side user, never a SUPER_ADMIN."
        ),
    )
    date = models.DateField(
        help_text="The day worked. Past AND future dates are allowed.",
    )
    iso_year = models.PositiveIntegerField(
        help_text="Derived from `date` on save; never client-supplied.",
    )
    iso_week = models.PositiveIntegerField(
        help_text="Derived from `date` on save; never client-supplied.",
    )
    hour_type = models.ForeignKey(
        HourType,
        on_delete=models.PROTECT,
        related_name="time_entries",
        help_text=(
            "PROTECT: an hour type in use can never be hard-deleted, "
            "only archived."
        ),
    )
    hours = models.DecimalField(
        max_digits=4,
        decimal_places=2,
        validators=[
            MinValueValidator(HOURS_MIN),
            MaxValueValidator(HOURS_MAX),
        ],
        help_text="Hours worked on this entry (0.25 - 24.00).",
    )
    multiplier_snapshot = models.DecimalField(
        max_digits=4,
        decimal_places=2,
        help_text=(
            "Copy of hour_type.multiplier at write time. Every weighted "
            "total reads THIS, never the live multiplier."
        ),
    )
    building = models.ForeignKey(
        "buildings.Building",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="time_entries",
        help_text=(
            "Optional: where the hours were worked. Must belong to the "
            "entry's own company. SET_NULL so retiring a building never "
            "destroys an hours record."
        ),
    )
    note = models.TextField(blank=True, default="")
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="created_time_entries",
        help_text=(
            "Who filed the entry. Differs from `employee` when an admin "
            "records hours on someone's behalf."
        ),
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-date", "-id"]
        verbose_name = "time entry"
        verbose_name_plural = "time entries"
        indexes = [
            models.Index(
                fields=["company", "date"], name="ts_entry_company_date_idx"
            ),
            models.Index(
                fields=["employee", "date"], name="ts_entry_employee_date_idx"
            ),
            # The week-lock lookup and the per-week report grouping both
            # hit exactly this triple.
            models.Index(
                fields=["company", "iso_year", "iso_week"],
                name="ts_entry_company_week_idx",
            ),
        ]

    def save(self, *args, **kwargs):
        """Derive `iso_year` / `iso_week` from `date` on EVERY save.

        Done here rather than in the serializer so a management command,
        a data migration or a shell write cannot produce a row whose
        stored week contradicts its date — which would make it invisible
        to the week lock that is supposed to govern it.

        `update_fields` is widened when present, otherwise a targeted
        `save(update_fields=["date"])` would persist the new date while
        leaving the old week behind.
        """
        if self.date is not None:
            iso_year, iso_week, _weekday = self.date.isocalendar()
            self.iso_year = iso_year
            self.iso_week = iso_week
            update_fields = kwargs.get("update_fields")
            if update_fields is not None and "date" in set(update_fields):
                kwargs["update_fields"] = list(
                    set(update_fields) | {"iso_year", "iso_week"}
                )
        return super().save(*args, **kwargs)

    @property
    def weighted_hours(self) -> Decimal:
        """`hours * multiplier_snapshot` — the ONE weighted-hours rule.

        Reads the snapshot, never `hour_type.multiplier`. Every other
        consumer in this app (the summary, the CSV export, the
        serializer) goes through this property or the identical DB-side
        expression in `summary.py`, so there is a single place the rule
        lives.
        """
        if self.hours is None or self.multiplier_snapshot is None:
            return Decimal("0.00")
        return (self.hours * self.multiplier_snapshot).quantize(
            Decimal("0.01")
        )

    def __str__(self):
        return f"{self.employee_id} {self.date} {self.hours}h"


class WeekLock(models.Model):
    """
    Sprint 152 — a company-wide week close.

    INVARIANT: the ABSENCE of a row means the week is OPEN. Weeks are
    never pre-created, so there is no "open" state to keep in sync and
    no backfill to run when a new company appears — the table holds only
    the weeks somebody deliberately closed.

    A closed week rejects create / update / delete of any `TimeEntry`
    dated inside it, and rejects date edits that would move an entry
    INTO or OUT OF it.

    Reopening DELETES the row. That is deliberate and owner-approved:
    corrections and late sick-leave entries are routine, so a week close
    has to be reversible. The AuditLog DELETE row is the reopen trail —
    `WeekLock` is registered for full-CRUD generic audit, so the CREATE
    row records the close and the DELETE row records the reopen, both
    with actor and timestamp.
    """

    company = models.ForeignKey(
        "companies.Company",
        on_delete=models.PROTECT,
        related_name="week_locks",
    )
    iso_year = models.PositiveIntegerField()
    iso_week = models.PositiveIntegerField()
    closed_at = models.DateTimeField(auto_now_add=True)
    closed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="closed_week_locks",
    )

    class Meta:
        ordering = ["-iso_year", "-iso_week", "id"]
        verbose_name = "week lock"
        verbose_name_plural = "week locks"
        constraints = [
            models.UniqueConstraint(
                fields=["company", "iso_year", "iso_week"],
                name="uniq_week_lock_per_company_week",
            ),
        ]

    def __str__(self):
        return f"{self.company_id} {self.iso_year}-W{self.iso_week:02d}"
