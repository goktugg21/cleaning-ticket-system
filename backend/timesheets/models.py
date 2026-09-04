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
    # Sprint 172 §5 — the reference report's "Urencode" (e.g. GU),
    # printed in one column with the NAME in the next. We had the name.
    # Blank-by-default and NOT unique: a company that does not use codes
    # leaves it empty, and two companies may well use the same letters.
    code = models.CharField(
        max_length=16,
        blank=True,
        default="",
        help_text=(
            'Short payroll code for this hour type, e.g. "GU". Printed '
            "beside the name on the worker hour report."
        ),
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


class HourSource(models.TextChoices):
    """Where an hour came from — Sprint 173 §1.

    `TimeEntry` recorded hours, a date, an employee, an hour type and an
    optional building, and never which JOB produced them. That is why
    approval, the comparison report, the worker hour report and
    invoicing could not connect: all four ask questions about work from
    a record that never referenced any.

    ## Why a type + id, and not four nullable foreign keys

    `timesheets` imports nothing from `tickets` or `extra_work`. That is
    a hard rule in this repo, not a preference — the hours module has to
    keep working for a company that uses nothing else, and Sprint 152's
    docstring says so in as many words. Four FKs would make the module
    depend on both.

    So an entry carries a TYPE and an ID and resolves nothing itself.
    Turning an id into a title belongs in `reports/`, the app that may
    read across, exactly as `hours_comparison.py` already does.

    The consequence is deliberate and handled rather than discovered:
    an id can stop resolving (its ticket was deleted), and a resolver
    must render a plain label rather than break a screen.
    """

    CONTRACT = "CONTRACT", "Contract"
    EXTRA_WORK = "EXTRA_WORK", "Extra work"
    TICKET = "TICKET", "Ticket"
    # The default, and the reason there is one: every row written before
    # this column existed has a real source that nobody recorded.
    # Backfilling them as CONTRACT would be inventing an answer.
    OTHER = "OTHER", "Other"


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
    # Sprint 173 §1 — WHICH JOB produced this hour. See `HourSource`
    # for why this is a type + id rather than four foreign keys.
    source_type = models.CharField(
        max_length=16,
        choices=HourSource.choices,
        default=HourSource.OTHER,
        help_text=(
            "Which kind of work produced this hour. OTHER is the "
            "default so an existing row keeps its meaning rather than "
            "being backfilled with a guess."
        ),
    )
    source_id = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text=(
            "The id within `source_type`. NOT a foreign key: "
            "`timesheets` may not import `tickets` or `extra_work`. "
            "An id that no longer resolves renders as a plain label."
        ),
    )

    # Sprint 172 §5 — the reference's "Reiskosten", a money amount per
    # REPORT ROW. It goes on the time entry rather than on the
    # contract-hours row because it is an actual cost incurred on a
    # specific day by a specific person: a standing weekly agreement
    # cannot know that somebody drove to a site on Tuesday. The
    # contract-hours row is a plan; this is a fact.
    #
    # Decimal, never a float — money in this codebase never goes through
    # binary floating point.
    travel_costs = models.DecimalField(
        max_digits=9,
        decimal_places=2,
        null=True,
        blank=True,
        help_text=(
            "Travel costs claimed for this entry, in euros. NULL means "
            "none was claimed, which is different from a claim of 0.00."
        ),
    )
    # The reference's "MACHT". Its meaning is not evident from the
    # screenshots — it could be an authorisation flag, a mandate
    # reference or a payroll switch. A BOOLEAN is the narrowest honest
    # reading of a column that shows a tick, and a wrong guess here is
    # cheap to widen (bool -> char) and expensive to narrow. FLAGGED for
    # the owner to correct: if MACHT is a reference number rather than a
    # yes/no, this becomes a CharField and the migration is additive
    # again.
    is_authorised = models.BooleanField(
        default=False,
        help_text=(
            "Reference column MACHT. Meaning unconfirmed — modelled as "
            "a flag until the owner says otherwise."
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


class ContractHoursStatus(models.TextChoices):
    """Sprint 167 §4 — where a standing agreement is in its review.

    Three states, and the transitions are written down here because
    "what does Saved mean" is the question a reviewer asks first:

      * **DRAFT** — being written. The operator who owns the row may
        change anything on it. Nothing downstream reads a DRAFT row as
        an agreement.
      * **SAVED** — submitted for review. Still editable by a manager
        (SA / CA), because the point of review is to correct before
        approving; a reviewer who cannot fix a typo sends the row back
        for one character.
      * **APPROVED** — agreed. **Not editable.** A change to an approved
        agreement is a NEW row from a new `valid_from`, which is the
        same discipline `CustomerServicePrice` and `ContractRevision`
        already use: history is not edited, it is superseded.

    Who may move a row: DRAFT -> SAVED, anyone who may write timesheet
    rows for that company. SAVED -> APPROVED and APPROVED -> SAVED
    (reopening), SA / CA only — approving is the management act, and
    so is undoing it.

    An approved week CAN be reopened, deliberately: the alternative is
    that one wrong approval is permanent and the only escape is a
    superseding row with a date that lies about when the agreement
    changed. Reopening is recorded like every other transition.

    Every transition writes an `AuditLog` row (H-10) — the model is
    registered for the full CRUD trio, so a status change lands as an
    UPDATE with a before/after diff naming the two states.
    """

    DRAFT = "DRAFT", "Draft"
    SAVED = "SAVED", "Saved"
    APPROVED = "APPROVED", "Approved"


class WorkType(models.Model):
    """A company's own catalog of work kinds — "Vast werk", "Meerwerk".

    Sprint 168 §3. The reference system carries a *work type* on a
    contract-hours row, and it is NOT the same axis as `HourType`:

      HourType  answers "how is this hour WEIGHTED" — normal, overtime,
                sick leave. It carries a multiplier.
      WorkType  answers "what KIND of work is agreed" — fixed recurring
                work, extra work, machine work. It carries no weight and
                never touches money.

    Two axes, so two catalogs. Folding the second into the first would
    force every company to spell out the cross-product ("Overwerk
    meerwerk") and would give a work type a multiplier it has no
    business having.

    ## Why a per-company catalog and not an enum

    The same reason `HourType` is one: another tenant's work types will
    differ. This repo has made the hardcoded-enum mistake before, and a
    tenant that cannot name its own categories ends up filing everything
    under "Other". The four reference names are OFFERED to a company
    that has none (`work_types/standard-set/`, the shape
    `hour_types/standard-set/` already uses) — offered, not imposed.

    Uniqueness is per-company and case/whitespace-insensitive, created
    WITH the table rather than added later, so no two rows can race in
    before the constraint exists.
    """

    company = models.ForeignKey(
        "companies.Company",
        on_delete=models.PROTECT,
        related_name="work_types",
        help_text=(
            "Provider company that owns this work type. PROTECT mirrors "
            "HourType.company: a Company cannot be hard-deleted while it "
            "still owns work types."
        ),
    )
    # NOT `unique=True`: uniqueness is per-company, expressed below.
    name = models.CharField(
        max_length=128,
        help_text='Operator-facing name, e.g. "Vast werk", "Meerwerk".',
    )
    is_active = models.BooleanField(
        default=True,
        help_text=(
            "Archived types stay on existing rows but are not offerable "
            "for new ones — the HourType rule, for the same reason: "
            "deleting one would rewrite what an agreement said."
        ),
    )
    sort_order = models.PositiveIntegerField(
        default=0,
        help_text="Ascending display order in the pickers; ties break on name.",
    )
    # Sprint 170 §5 — which standard kind this row IS, or "" for a
    # company's own type. DERIVED from `name` in save(); never client-set.
    # The `HourType.standard_slot` pattern: it lets the UI show a
    # standard name in each reader's language while `name` stays one
    # operator-typed column.
    standard_slot = models.CharField(
        max_length=32,
        blank=True,
        default="",
        help_text=(
            "Derived from `name`: the standard kind this row is "
            "recognised as, or blank for a custom type."
        ),
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def save(self, *args, **kwargs):
        """Derive `standard_slot` on EVERY save — here rather than in a
        serializer, because a management command, a data migration and a
        shell write all go through save() and none goes through a
        serializer."""
        from .serializers_work_types import slot_for_name

        self.standard_slot = slot_for_name(self.name)
        super().save(*args, **kwargs)

    class Meta:
        ordering = ["sort_order", "name", "id"]
        verbose_name = "work type"
        verbose_name_plural = "work types"
        constraints = [
            # Trim() first so leading/trailing whitespace cannot bypass a
            # Lower()-only dedupe — the HourType shape exactly.
            models.UniqueConstraint(
                Lower(Trim("name")),
                "company",
                name="uniq_work_type_name_per_company_ci",
            ),
        ]

    def __str__(self) -> str:
        return self.name


class ContractHours(models.Model):
    """
    Sprint 167 §3 — the hours a worker is CONTRACTED for: a standing
    weekly pattern at one building, from a date.

    The counterpart to `TimeEntry`, which records hours actually
    WORKED. Together they answer "agreed 15, worked 13", which is what
    the comparison in `reports/hours_comparison.py` exists to say.

    ## Why this lives in `timesheets` and has no FK to a Contract

    It is an HOURS concept, and `timesheets` is the hours module. The
    word "contract" here is the operator's word for a standing
    agreement about a worker's hours — it is NOT a row of
    `contracts.Contract`, and there is deliberately no foreign key to
    one.

    That is not a shortcut. `timesheets` imports nothing from
    `contracts` and must keep working for a company that uses nothing
    else (Sprint 152's founding rule, restated every sprint since). An
    FK here would make the hours module unusable without the contracts
    module and would be the exact import the architecture forbids. A
    company that runs contracts AND hours gets the join in `reports`,
    which is the app allowed to read both.

    ## Versioning

    `valid_from` / `valid_to` give the discipline
    `extra_work.CustomerServicePrice` already uses, and the resolution
    shape is the same one `resolve_price` applies: the row in force on
    a date is the one with the latest `valid_from` at or before it,
    ties broken by `-id`. Changing an agreement writes a NEW row from a
    date; it never edits history, because last month's comparison must
    keep saying what it said last month.

    `valid_to` NULL means open-ended, which is the normal case.

    ## Scoping

    Through `timesheets/scope.py`, exactly like `TimeEntry`.
    CUSTOMER_* roles get NOTHING, ever: this is personnel and
    wage-adjacent data and no customer-side role has any business
    reading it.
    """

    company = models.ForeignKey(
        "companies.Company",
        on_delete=models.PROTECT,
        related_name="contract_hours",
        help_text=(
            "Denormalized tenant anchor, resolved from the employee's "
            "provider-company membership at write time — the same shape "
            "TimeEntry.company uses, and for the same reason."
        ),
    )
    employee = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="contract_hours",
        help_text=(
            "The provider-side employee this agreement is about. Never "
            "a customer-side user, never a SUPER_ADMIN."
        ),
    )
    building = models.ForeignKey(
        "buildings.Building",
        on_delete=models.PROTECT,
        related_name="contract_hours",
        null=True,
        blank=True,
        help_text=(
            "Where the agreed hours are worked. NULL is allowed for an "
            "agreement not tied to one location, and reads as 'no "
            "building' rather than being dropped from a report."
        ),
    )
    hour_type = models.ForeignKey(
        HourType,
        on_delete=models.PROTECT,
        related_name="contract_hours",
        help_text="PROTECT: a type in use can be archived, never deleted.",
    )
    # Sprint 168 §3 — nullable, and deliberately so: every row written
    # before this column existed has no work type, and inventing one for
    # them would be a fact the operator never stated.
    work_type = models.ForeignKey(
        WorkType,
        on_delete=models.PROTECT,
        related_name="contract_hours",
        null=True,
        blank=True,
        help_text=(
            "What KIND of work is agreed. NULL for rows written before "
            "the catalog existed, and for a company that keeps no work "
            "types — not a default, because a default here would be a "
            "claim nobody made."
        ),
    )

    valid_from = models.DateField(
        help_text="First day this agreement is in force."
    )
    valid_to = models.DateField(
        null=True,
        blank=True,
        help_text="Last day in force. NULL means open-ended.",
    )

    # Seven weekday values. Separate columns rather than a JSON blob:
    # they are aggregated (SUM per building, per employee) by the
    # comparison report, and a JSON field cannot be summed in the
    # database — which would turn a constant-cost report into a
    # per-row one.
    monday = models.DecimalField(max_digits=4, decimal_places=2, default=Decimal("0.00"))
    tuesday = models.DecimalField(max_digits=4, decimal_places=2, default=Decimal("0.00"))
    wednesday = models.DecimalField(max_digits=4, decimal_places=2, default=Decimal("0.00"))
    thursday = models.DecimalField(max_digits=4, decimal_places=2, default=Decimal("0.00"))
    friday = models.DecimalField(max_digits=4, decimal_places=2, default=Decimal("0.00"))
    saturday = models.DecimalField(max_digits=4, decimal_places=2, default=Decimal("0.00"))
    sunday = models.DecimalField(max_digits=4, decimal_places=2, default=Decimal("0.00"))

    status = models.CharField(
        max_length=16,
        choices=ContractHoursStatus.choices,
        default=ContractHoursStatus.DRAFT,
        help_text="See ContractHoursStatus for the transitions and who may make them.",
    )

    # W10 — does this agreement fill the weekly sheet by itself?
    #
    # The question "should this person's normal hours appear in their
    # weeks?" is answered ONCE, here, when the agreement is written.
    # Not every week by somebody who has to remember. With this on,
    # `timesheets.fill` writes a DRAFT TimeEntry per working day of
    # every week inside the validity window, and the sheet is never
    # blank.
    #
    # Default False so every row written before this column existed
    # keeps behaving exactly as it did. An agreement that silently
    # started generating hours for past weeks would be a fact nobody
    # stated.
    auto_fill = models.BooleanField(
        default=False,
        help_text=(
            "Fill this person's weekly sheet from this agreement, for "
            "every week inside the validity window. The filled rows are "
            "ordinary TimeEntry rows and stay editable until the week "
            "is closed."
        ),
    )

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="created_contract_hours",
    )
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="approved_contract_hours",
        help_text="Who approved it. Cleared when a row is reopened.",
    )
    approved_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "contract hours"
        verbose_name_plural = "contract hours"
        ordering = ["building__name", "employee__full_name", "-valid_from", "-id"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(valid_to__isnull=True)
                | models.Q(valid_to__gte=models.F("valid_from")),
                name="contract_hours_valid_to_after_from",
            ),
        ]
        indexes = [
            models.Index(
                fields=["company", "-valid_from"],
                name="ch_company_valid_idx",
            ),
            models.Index(
                fields=["employee", "building", "-valid_from"],
                name="ch_employee_building_idx",
            ),
        ]

    def __str__(self):
        return f"{self.employee_id}@{self.building_id} from {self.valid_from}"

    @property
    def weekly_total(self) -> Decimal:
        """The seven days summed. A property, not a stored column: a
        stored total is a second copy of numbers that already exist,
        and the copy is what drifts."""
        return (
            self.monday
            + self.tuesday
            + self.wednesday
            + self.thursday
            + self.friday
            + self.saturday
            + self.sunday
        )

    @property
    def is_locked(self) -> bool:
        """APPROVED rows are not editable — a change is a new row from a
        new date. See the status docstring."""
        return self.status == ContractHoursStatus.APPROVED
