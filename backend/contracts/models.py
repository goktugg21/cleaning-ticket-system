"""
Sprint 160 — contracts (the recurring-revenue side of the business).

An INDEPENDENT business module, in the same sense `timesheets` is: it
records what a customer has AGREED to pay on a recurring basis, and it
imports nothing from `extra_work` or `invoicing`. The one direction of
travel that is planned (Sprint 158 turning a due forecast row into a
real `Invoice`) is a future caller of this app, not a dependency of it.

**Two price sources, one clear division — do not "unify" them.**

  * A CONTRACT carries its OWN prices, on its own lines
    (`ContractLine.amount`). It does NOT read `CustomerServicePrice`
    and must never learn to. A contract price is the agreed recurring
    fee for a named project; it is negotiated once and versioned by
    `ContractRevision`.
  * EXTRA WORK continues to price through
    `extra_work.pricing.resolve_price` / `CustomerServicePrice`,
    unchanged and untouched by this app. That price answers a different
    question: what one ad-hoc service costs this customer today.

The two look similar (both are per-customer agreed money with a
validity window) and are NOT the same fact. Merging them would make a
contract's agreed monthly fee mutable by a catalog edit.

Five models:

  * `ContractType`           — per-company catalog of contract kinds
                              ("Schoonmaak", "Machines"). Same
                              architecture as `timesheets.HourType`.
  * `Contract`              — the agreement itself: who, where, when,
                              and how it bills.
  * `ContractBuilding`      — the M:N between a contract and the
                              buildings ("locations") it covers.
  * `ContractRevision`      — a VERSION of the contract's agreed scope,
                              effective from a date. Not an audit log.
  * `ContractLine`          — one project on a REVISION: name, hours,
                              area, money.
  * `ContractNumberSequence`— the per-(company, year) counter behind
                              gapless `CNT-YYYY-NNNN` numbering.

Money is `Decimal` everywhere and never passes through a float; see
`contracts/billing.py` for the rounding discipline.
"""
from __future__ import annotations

from decimal import Decimal

from django.conf import settings
from django.core.validators import MinValueValidator, MaxValueValidator
from django.db import models
from django.db.models.functions import Lower, Trim

from .standard_types import STANDARD_CONTRACT_TYPE_CHOICES, slot_for_name
from django.utils import timezone


# Repeated as module constants so the serializer layer can quote the
# SAME bounds in its friendly-400 messages instead of re-typing them
# (and drifting from the validators below) — the `timesheets` pattern.
BILLING_DAY_MIN = 1
# Capped at 28 so the day exists in EVERY month, which is the same
# reasoning `Customer.invoice_day_of_month` already uses. A contract
# billing on the 31st would silently move in February.
BILLING_DAY_MAX = 28
PAYMENT_TERMS_MIN = 0
PAYMENT_TERMS_MAX = 365


class ContractLifecycle(models.TextChoices):
    """The operator-CHOSEN part of a contract's status — the only part
    that is stored.

    `EXPIRED` is deliberately absent: it is DERIVED from `end_date` by
    `Contract.status`. Storing it would create a second source of truth
    that can silently contradict the dates (a contract flagged EXPIRED
    whose end_date is next year, or the reverse). A CheckConstraint on
    the table enforces that only these three values can ever be
    persisted, so the contradiction is not merely discouraged — it is
    unrepresentable.
    """

    DRAFT = "DRAFT", "Draft"
    ACTIVE = "ACTIVE", "Active"
    CANCELLED = "CANCELLED", "Cancelled"


class ContractKind(models.TextChoices):
    """W16 — what a contract row IS. Two things, and they are not the
    same kind of object.

    `STANDARD` is the recurring agreement: a price per billing period,
    revisions that version it, and `contracts/invoice_generation.py`
    raising a DRAFT invoice per period. That is the whole module up to
    now.

    `EXTRA_WORK` is the **register** the owner's father's system calls
    an "Extra Works Contract" -- one per customer, auto-created,
    carrying one line per piece of chargeable work so a customer's
    ad-hoc spend has a page and a total. His
    `ContractController::getOrCreateExtraWorksContract` is the shape
    this copies.

    ## THE REGISTER NEVER RAISES AN INVOICE

    This is the one rule that makes copying his idea safe, and it is
    why `kind` is a stored column rather than a convention.

    His extra-works lines are hand-typed: an operator retypes a
    description and an amount, and nothing connects the line to the
    actual job. Ours are PROJECTED from the real `ExtraWorkRequest`
    rows through the same `_earned_amounts` the invoice generator uses,
    so the register cannot disagree with the invoice.

    But our Extra Work ALREADY reaches an invoice, through the unbilled
    pool in `invoicing/selectors.py` -- a pool whose whole definition is
    "no live `InvoiceLine` claims this row". If the register also
    generated invoice lines, every piece of chargeable work would be
    billed twice: once by the pool, once by the contract run. So
    `invoice_generation.generate_invoices_for_contract` refuses a
    register outright and `billing.build_forecast` returns an empty
    forecast for one. Both refusals are tested. A register is a MIRROR
    of money that is billed elsewhere, never a second source of it.
    """

    STANDARD = "STANDARD", "Standard"
    EXTRA_WORK = "EXTRA_WORK", "Extra work register"


class ContractStatus(models.TextChoices):
    """The status an operator SEES. Derived, never stored — see
    `Contract.status` and `annotate_status`."""

    DRAFT = "DRAFT", "Draft"
    ACTIVE = "ACTIVE", "Active"
    EXPIRED = "EXPIRED", "Expired"
    CANCELLED = "CANCELLED", "Cancelled"


class BillingPeriod(models.TextChoices):
    MONTHLY = "MONTHLY", "Monthly"
    QUARTERLY = "QUARTERLY", "Quarterly"
    YEARLY = "YEARLY", "Yearly"


class BillingType(models.TextChoices):
    ADVANCE = "ADVANCE", "In advance"
    ARREARS = "ARREARS", "In arrears"


# How many billing periods one calendar year holds, per period kind.
# Used by the forecast's "invoices per year" figure and by the
# monthly/yearly normalisation. Expressed once here so the API, the
# forecast and the tests cannot disagree.
PERIODS_PER_YEAR = {
    BillingPeriod.MONTHLY: 12,
    BillingPeriod.QUARTERLY: 4,
    BillingPeriod.YEARLY: 1,
}

# Calendar months spanned by one billing period.
MONTHS_PER_PERIOD = {
    BillingPeriod.MONTHLY: 1,
    BillingPeriod.QUARTERLY: 3,
    BillingPeriod.YEARLY: 12,
}


class ContractType(models.Model):
    """A per-provider-company catalog of contract kinds.

    NOT a hardcoded enum, and that is the point: the reference system
    shows "Cleaning" and "Machine", and the next tenant will have
    others. Same architecture as `timesheets.HourType` /
    `extra_work.ServiceCategory` — company FK plus a
    case/whitespace-insensitive per-company unique name, with the
    constraint created WITH the table so there is never a window in
    which the column exists without its uniqueness rule.

    Archiving (`is_active=False`) removes the type from the pickers for
    NEW contracts while every existing `Contract` keeps its FK. Hard
    DELETE is only possible while the type is unused —
    `Contract.contract_type` is PROTECT.
    """

    company = models.ForeignKey(
        "companies.Company",
        on_delete=models.PROTECT,
        related_name="contract_types",
        help_text=(
            "Provider company that owns this contract type. PROTECT "
            "mirrors HourType.company: a Company cannot be hard-deleted "
            "while it still owns contract types."
        ),
    )
    # NOT `unique=True`: uniqueness is per-company and
    # case/whitespace-insensitive, expressed as the constraint below.
    name = models.CharField(
        max_length=128,
        help_text='Operator-facing name, e.g. "Schoonmaak", "Machines".',
    )
    is_active = models.BooleanField(
        default=True,
        help_text=(
            "Archived types stay on existing contracts but are not "
            "offerable for new ones."
        ),
    )
    sort_order = models.PositiveIntegerField(
        default=0,
        help_text="Ascending display order in the pickers; ties break on name.",
    )
    # Sprint 169 §4 — which of the standard kinds this row IS, or "" for
    # a company's own type. DERIVED from `name` in `save()`; never set
    # by a client, never hand-edited. The `HourType.standard_slot`
    # pattern, for the same reason: it lets the UI show a standard name
    # in each reader's own language while `name` stays a single
    # operator-typed column.
    standard_slot = models.CharField(
        max_length=32,
        blank=True,
        default="",
        choices=STANDARD_CONTRACT_TYPE_CHOICES,
        help_text=(
            "Derived from `name`: the standard kind this row is "
            "recognised as, or blank for a custom type."
        ),
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def save(self, *args, **kwargs):
        """Derive `standard_slot` from `name` on EVERY save.

        Here rather than in the serializer, exactly as
        `HourType.save()` does it: a management command, a data
        migration and a shell write all go through `save()`, and none
        of them goes through a serializer. Deriving it anywhere else
        means a stored slot that contradicts the name beside it.

        The consequence is the intended one: renaming a standard type
        to the company's own wording DETACHES it (slot -> ""), and
        renaming it back, in either language, re-attaches it.
        """
        self.standard_slot = slot_for_name(self.name)
        super().save(*args, **kwargs)

    class Meta:
        verbose_name = "contract type"
        verbose_name_plural = "contract types"
        ordering = ["sort_order", "name", "id"]
        constraints = [
            models.UniqueConstraint(
                Lower(Trim("name")),
                models.F("company"),
                name="uniq_contract_type_name_per_company_ci",
            ),
        ]

    def __str__(self):
        return self.name


class Contract(models.Model):
    """A recurring agreement between a provider company and a customer.

    What is stored here is the HEADER: who, where, when, and how it
    bills. What the contract is actually FOR — the projects, their
    hours and their money — hangs off `ContractRevision`, never off
    this row, so that raising a price next month does not rewrite what
    was agreed last month.

    `contract_no` is assigned at CREATE, not at activation: a draft
    contract still needs to be referred to in a conversation.
    """

    company = models.ForeignKey(
        "companies.Company",
        on_delete=models.PROTECT,
        related_name="contracts",
        help_text="Tenant anchor. Every scoping question resolves through this.",
    )
    customer = models.ForeignKey(
        "customers.Customer",
        on_delete=models.PROTECT,
        related_name="contracts",
        help_text=(
            "The customer organisation that signed. PROTECT: a customer "
            "with a contract cannot be hard-deleted out from under it."
        ),
    )
    buildings = models.ManyToManyField(
        "buildings.Building",
        through="contracts.ContractBuilding",
        related_name="contracts",
        blank=True,
        help_text=(
            "The locations this contract covers. Every building must "
            "belong to the SAME company as the contract; the serializer "
            "rejects a cross-company id with a 400 and the picker never "
            "offers one."
        ),
    )
    contract_type = models.ForeignKey(
        ContractType,
        on_delete=models.PROTECT,
        related_name="contracts",
        null=True,
        blank=True,
        help_text=(
            "Per-company catalog row. Nullable because a company's "
            "catalog may still be empty when its first contract is "
            "drafted."
        ),
    )

    contract_no = models.CharField(
        max_length=32,
        help_text=(
            "Human reference, CNT-YYYY-NNNN. Gapless per (company, "
            "year), assigned at CREATE by contracts.numbering."
        ),
    )

    kind = models.CharField(
        max_length=16,
        choices=ContractKind.choices,
        default=ContractKind.STANDARD,
        db_index=True,
        help_text=(
            "STANDARD is the recurring agreement that raises invoices. "
            "EXTRA_WORK is the per-customer register of chargeable "
            "work, which never raises one -- see `ContractKind`."
        ),
    )
    start_date = models.DateField(
        help_text="First day the contract is in force."
    )
    end_date = models.DateField(
        null=True,
        blank=True,
        help_text=(
            "Last day in force. NULL means open-ended, which is a legal "
            "and common shape — do not treat NULL as an error."
        ),
    )

    lifecycle = models.CharField(
        max_length=16,
        choices=ContractLifecycle.choices,
        default=ContractLifecycle.DRAFT,
        help_text=(
            "The stored, operator-chosen part of the status. EXPIRED is "
            "NOT storable here — it is derived from end_date by "
            "`Contract.status`. See ContractLifecycle."
        ),
    )

    description = models.TextField(blank=True, default="")
    notes = models.TextField(blank=True, default="")

    # --- Billing settings -------------------------------------------------
    billing_period = models.CharField(
        max_length=16,
        choices=BillingPeriod.choices,
        default=BillingPeriod.MONTHLY,
    )
    billing_day = models.PositiveSmallIntegerField(
        default=1,
        validators=[
            MinValueValidator(BILLING_DAY_MIN),
            MaxValueValidator(BILLING_DAY_MAX),
        ],
        help_text=(
            "Day-of-month the invoice is dated (1..28). Capped at 28 so "
            "the day exists in every month — the same reasoning "
            "Customer.invoice_day_of_month uses."
        ),
    )
    billing_type = models.CharField(
        max_length=16,
        choices=BillingType.choices,
        default=BillingType.ADVANCE,
        help_text=(
            "ADVANCE bills at the start of the period it covers; "
            "ARREARS bills after the period has ended."
        ),
    )
    payment_terms_days = models.PositiveSmallIntegerField(
        default=30,
        validators=[
            MinValueValidator(PAYMENT_TERMS_MIN),
            MaxValueValidator(PAYMENT_TERMS_MAX),
        ],
        help_text="Days from invoice date to due date.",
    )
    start_proration = models.BooleanField(
        default=True,
        help_text=(
            "When on, a contract starting mid-period bills a part "
            "period first (and a contract ending mid-period bills a "
            "part period last). When off, every period bills in full."
        ),
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "contract"
        verbose_name_plural = "contracts"
        ordering = ["-start_date", "-id"]
        constraints = [
            models.UniqueConstraint(
                fields=["company", "contract_no"],
                name="uniq_contract_no_per_company",
            ),
            # The stored status can never be EXPIRED. This is what makes
            # "status cannot contradict the dates" a schema fact rather
            # than a convention somebody has to remember.
            models.CheckConstraint(
                condition=models.Q(
                    lifecycle__in=[
                        ContractLifecycle.DRAFT,
                        ContractLifecycle.ACTIVE,
                        ContractLifecycle.CANCELLED,
                    ]
                ),
                name="contract_lifecycle_is_storable",
            ),
            models.CheckConstraint(
                condition=models.Q(end_date__isnull=True)
                | models.Q(end_date__gte=models.F("start_date")),
                name="contract_end_after_start",
            ),
            # W16 — ONE extra work register per customer, enforced by
            # the database rather than by the get_or_create that makes
            # it. Two registers would each show half the customer's
            # money and neither would look wrong, which is the worst
            # kind of wrong. Partial (`condition=`) so it constrains
            # only registers: a customer may hold any number of
            # STANDARD contracts, and does.
            models.UniqueConstraint(
                fields=["company", "customer"],
                condition=models.Q(kind=ContractKind.EXTRA_WORK),
                name="uniq_extra_work_register_per_customer",
            ),
        ]
        indexes = [
            models.Index(
                fields=["company", "start_date"],
                name="contract_company_start_idx",
            ),
            models.Index(
                fields=["customer", "start_date"],
                name="contract_customer_start_idx",
            ),
        ]

    def __str__(self):
        return f"{self.contract_no} — {self.customer_id}"

    def status(self, on=None) -> str:
        """The status an operator sees, DERIVED — never stored.

        CANCELLED and DRAFT are operator statements and win over the
        dates: a cancelled contract does not become "expired" when its
        end date passes, and a draft that was never activated does not
        silently become active because its start date arrived. Only an
        ACTIVE contract can expire, and it expires exactly when
        `end_date` is in the past. An open-ended contract (end_date
        NULL) never expires.
        """
        today = on or timezone.localdate()
        if self.lifecycle == ContractLifecycle.CANCELLED:
            return ContractStatus.CANCELLED
        if self.lifecycle == ContractLifecycle.DRAFT:
            return ContractStatus.DRAFT
        if self.end_date is not None and self.end_date < today:
            return ContractStatus.EXPIRED
        return ContractStatus.ACTIVE


class ContractBuilding(models.Model):
    """The M:N between a contract and the buildings it covers.

    An explicit through-model rather than a bare `ManyToManyField`
    table, for the reason `ContactBuildingLink` is one: the row is a
    business fact somebody adds and removes, and the audit layer
    registers it in the membership-shape CREATE/DELETE trio. An
    auto-created m2m table has no model to register.
    """

    contract = models.ForeignKey(
        Contract,
        on_delete=models.CASCADE,
        related_name="building_links",
    )
    building = models.ForeignKey(
        "buildings.Building",
        on_delete=models.PROTECT,
        related_name="contract_links",
        help_text=(
            "PROTECT: a building named on a live contract cannot be "
            "hard-deleted out from under it."
        ),
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "contract building"
        verbose_name_plural = "contract buildings"
        ordering = ["building__name", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["contract", "building"],
                name="uniq_contract_building",
            ),
        ]

    def __str__(self):
        return f"{self.contract_id}:{self.building_id}"


class ContractRevision(models.Model):
    """A VERSION of a contract's agreed scope and money, effective from
    a date. **NOT an audit log** — the distinction is load-bearing.

    `AuditLog` answers "who changed this field, and when": an
    after-the-fact record of an edit. A revision answers "what is this
    contract's agreed scope as of a date": a business fact, with money
    attached, that may have a FUTURE effective date and that invoices
    are computed against. AuditLog cannot serve that and must not be
    used for it.

    So raising a price is not an edit of the current lines — it is a
    new revision effective next month. Last month's invoices still
    reflect what was agreed last month, because they resolve against
    the revision that was active then.

    The ACTIVE revision is DERIVED (`contracts.revisions.active_revision`
    — the latest `effective_from` at or before the date, ties broken by
    id). There is deliberately no `is_active` flag: that is the same
    trap `Contract.lifecycle` avoids for EXPIRED.

    The shape mirrors the RESOLUTION DISCIPLINE of
    `extra_work.pricing.resolve_price` over `CustomerServicePrice`'s
    validity windows — latest row at or before the date, `-id` as the
    tie-break — because that is the same problem solved once already in
    this codebase. It imports nothing from it: different module,
    different entity.

    Immutability: a revision whose `effective_from` has passed is
    closed to edits. A correction to a past revision is a NEW revision,
    exactly as a SENT invoice is corrected by a reversal rather than an
    edit.
    """

    contract = models.ForeignKey(
        Contract,
        on_delete=models.CASCADE,
        related_name="revisions",
    )
    label = models.CharField(
        max_length=200,
        help_text=(
            'Free text — "Oorspronkelijk contract", "Prijsverhoging '
            '2027". Shown as the active revision on the contract.'
        ),
    )
    effective_from = models.DateField(
        help_text=(
            "The date this version of the scope takes over. May be in "
            "the future; the contract keeps resolving to the previous "
            "revision until then."
        ),
    )
    notes = models.TextField(blank=True, default="")
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="created_contract_revisions",
        null=True,
        blank=True,
        help_text=(
            "Who authored the revision. Nullable only for the "
            "system-authored first revision of a contract created "
            "outside a request (fixtures, data migrations)."
        ),
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "contract revision"
        verbose_name_plural = "contract revisions"
        # Newest agreement first — the order the Revision History tab
        # reads in. Ties break on -id, matching the resolver's tie-break
        # so "first in the list" and "the active one" cannot disagree.
        ordering = ["-effective_from", "-id"]
        indexes = [
            models.Index(
                fields=["contract", "-effective_from"],
                name="contract_rev_effective_idx",
            ),
        ]

    def __str__(self):
        return f"{self.label} ({self.effective_from})"


class ContractLine(models.Model):
    """One project on a contract REVISION — the "Projects" tab.

    Hangs off the revision, NOT off the contract. See
    `ContractRevision`.

    `amount` is the money this line contributes to ONE BILLING PERIOD
    of its contract (a MONTHLY contract's line amount is a month's
    money; a QUARTERLY contract's is a quarter's). The forecast in
    `contracts/billing.py` normalises to monthly / yearly figures from
    `contract.billing_period` — nothing here stores a second copy of
    those totals, because a stored total is a copy that drifts.

    `hours` follows the same per-billing-period basis, and carries an
    optional `building` so a later sprint can compare AGREED hours
    against WORKED hours (`timesheets.TimeEntry`) per building without
    a schema change. That comparison is explicitly NOT built here; the
    field exists so the shape does not have to be broken to build it.
    """

    revision = models.ForeignKey(
        ContractRevision,
        on_delete=models.CASCADE,
        related_name="lines",
    )
    name = models.CharField(
        max_length=200,
        help_text='The project, e.g. "Dagelijkse schoonmaak kantoren".',
    )
    building = models.ForeignKey(
        "buildings.Building",
        on_delete=models.PROTECT,
        related_name="contract_lines",
        null=True,
        blank=True,
        help_text=(
            "Optional: which of the contract's buildings this project "
            "covers. NULL means the contract as a whole. Present so the "
            "planned agreed-vs-worked hours comparison has a building "
            "to group by; nothing in this sprint reads it for money."
        ),
    )
    extra_work = models.ForeignKey(
        "extra_work.ExtraWorkRequest",
        on_delete=models.CASCADE,
        related_name="contract_register_lines",
        null=True,
        blank=True,
        help_text=(
            "W16 -- the chargeable job this line MIRRORS, on an "
            "EXTRA_WORK register. NULL on every STANDARD contract "
            "line, where the line is the agreement itself and there is "
            "no job behind it yet.\n\n"
            "The reference system's equivalent lines carry no such "
            "link: an operator retypes a description and an amount, so "
            "its register can and does disagree with its invoices. "
            "This FK is what makes ours a projection rather than a "
            "second set of books -- `sync_extra_work_register` "
            "rebuilds the amount from `_earned_amounts`, the same rule "
            "the invoice reads.\n\n"
            "CASCADE, not PROTECT: a register line is a mirror of the "
            "job, so a deleted job must take its reflection with it. "
            "PROTECT would make the register able to block a delete "
            "that has nothing to do with it."
        ),
    )
    sort_order = models.PositiveIntegerField(
        default=0,
        help_text="Ascending display order; ties break on id.",
    )

    hours = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal("0.00"),
        validators=[MinValueValidator(Decimal("0.00"))],
        help_text=(
            "Budgeted hours for ONE billing period of this contract. "
            "The per-period basis is what makes a later comparison "
            "against worked hours well-defined."
        ),
    )
    area_m2 = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[MinValueValidator(Decimal("0.00"))],
        help_text=(
            "Square metres this project covers. New and additive — the "
            "system held square metres nowhere before this sprint "
            "(extra_work's SQUARE_METERS is a pricing UNIT, which is a "
            "different thing). NULL means not recorded."
        ),
    )

    # W20 — the three planning fields the reference system's contract
    # lines carry and ours lacked. All additive; none of them is money.
    frequency_per_year = models.PositiveSmallIntegerField(
        null=True,
        blank=True,
        help_text=(
            "How many times per YEAR this line's work is performed "
            "(the reference system's `frequency`). NULL means the line "
            "is not planned by count. The 52-week planning grid of a "
            "later sprint buckets on exactly this number — it is a "
            "COUNT of performances, never a divisor or multiplier for "
            "`amount`, which stays per billing period."
        ),
    )
    norm = models.CharField(
        max_length=200,
        blank=True,
        default="",
        help_text=(
            "The operator's norm / spec note for this line, e.g. "
            "'180 m2/uur'. Free text; nothing computes from it."
        ),
    )
    department = models.ForeignKey(
        "customers.Department",
        on_delete=models.SET_NULL,
        related_name="contract_lines",
        null=True,
        blank=True,
        help_text=(
            "Optional: which of the CUSTOMER'S department labels this "
            "line serves (the per-customer list Extra Work already "
            "uses). The serializer rejects a department of any other "
            "customer — a cross-customer label on a contract line is a "
            "tenant-scoping violation. SET_NULL: deleting a label must "
            "not take agreed scope lines with it."
        ),
    )

    # Money shape MIRRORS `extra_work.ProposalLine` / `invoicing.
    # InvoiceLine` (amount + vat_pct at the same precision) so the
    # eventual contract invoice line is a COPY, not a conversion.
    amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal("0.00"),
        help_text="This line's money for ONE billing period, excl. VAT.",
    )
    vat_pct = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=Decimal("21.00"),
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "contract line"
        verbose_name_plural = "contract lines"
        ordering = ["sort_order", "id"]
        indexes = [
            models.Index(
                fields=["revision", "sort_order"],
                name="contract_line_revision_idx",
            ),
        ]

    def __str__(self):
        return self.name


class ContractNumberSequence(models.Model):
    """Per-(company, year) counter behind gapless `CNT-YYYY-NNNN`.

    A DEDICATED counter row, locked with `select_for_update` by
    `contracts.numbering.allocate_contract_number`. Mirrors the SHAPE
    of `invoicing.InvoiceNumberSequence` — there is always exactly ONE
    row to lock per sequence, so there is no empty-set / phantom-row
    race — and imports nothing from it. Two independent modules, two
    independent sequences; a contract number and an invoice number are
    not the same counter and must never share one.
    """

    company = models.ForeignKey(
        "companies.Company",
        on_delete=models.CASCADE,
        related_name="contract_number_sequences",
    )
    year = models.PositiveIntegerField()
    last_number = models.PositiveIntegerField(default=0)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "contract number sequence"
        verbose_name_plural = "contract number sequences"
        ordering = ["company_id", "-year"]
        constraints = [
            models.UniqueConstraint(
                fields=["company", "year"],
                name="uniq_contract_number_seq_per_company_year",
            ),
        ]

    def __str__(self):
        return f"{self.company_id}/{self.year}: {self.last_number}"


class ContractInvoice(models.Model):
    """
    Sprint 164 §8 — the claim that ONE period of ONE contract has been
    invoiced.

    This is the idempotency mechanism, and it is a database constraint
    rather than a check in code. `UniqueConstraint(contract,
    period_start)` means a second generator run — or a concurrent one —
    asks Postgres for a row that already exists and is refused. Nothing
    is inferred from amounts, dates or invoice contents, and there is no
    read-then-write window for two processes to both pass. This codebase
    already shipped one check-then-act race (`ensure_default_labels`);
    that shape is not repeated here.

    It also keeps the dependency ONE-WAY. `invoicing` knows nothing
    about contracts: no column was added to `Invoice`, no behaviour of
    it changed. This table lives in `contracts`, which is the app that
    grew the new need, and `contracts.invoice_generation` is the only
    module that imports `invoicing` at all.

    `invoice_date` lives here rather than on `Invoice` because `Invoice`
    has no such field — it carries `period_year` / `period_month` and
    the issue/send timestamps. Adding one would have been a change to
    the invoicing schema, which this sprint is explicitly not making.

    `revision` records WHICH agreed scope priced the period, so a later
    reader can answer "why is this invoice this amount" without
    re-deriving it from dates.
    """

    contract = models.ForeignKey(
        Contract,
        on_delete=models.CASCADE,
        related_name="generated_invoices",
    )
    invoice = models.OneToOneField(
        "invoicing.Invoice",
        on_delete=models.CASCADE,
        related_name="contract_period",
        help_text=(
            "CASCADE: this row is a CLAIM about an invoice, so it must "
            "not outlive it. A deleted invoice releases its period to be "
            "generated again, which is the behaviour a hard delete "
            "should have."
        ),
    )
    revision = models.ForeignKey(
        ContractRevision,
        on_delete=models.PROTECT,
        related_name="generated_invoices",
        help_text="The agreed scope this period was priced from.",
    )

    period_start = models.DateField(
        help_text="First day of the billed period. Half of the uniqueness key."
    )
    period_end = models.DateField()
    invoice_date = models.DateField(
        help_text=(
            "The forecast's date for this period. Kept here because "
            "`invoicing.Invoice` has no invoice_date column and this "
            "sprint does not change its schema."
        ),
    )

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "contract invoice"
        verbose_name_plural = "contract invoices"
        ordering = ["-period_start", "-id"]
        constraints = [
            # THE idempotency mechanism. See the class docstring.
            models.UniqueConstraint(
                fields=["contract", "period_start"],
                name="uniq_contract_invoice_per_period",
            ),
        ]
        indexes = [
            models.Index(
                fields=["contract", "-period_start"],
                name="contract_invoice_period_idx",
            ),
        ]

    def __str__(self):
        return f"{self.contract_id}@{self.period_start}"
