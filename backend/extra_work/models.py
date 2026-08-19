"""
Sprint 26B — Extra Work MVP.

Extra Work is a separate operational domain from Ticket. Tickets are
inbound complaints / requests / questions; Extra Work is "we agree
to do this extra job for an additional invoice". The domain has its
own state machine (customer-pricing loop in MVP — REQUESTED ->
UNDER_REVIEW -> PRICING_PROPOSED -> CUSTOMER_APPROVED/REJECTED) and
its own per-line-item pricing model that the customer-side approves
before any work is scheduled.

The data shape mirrors Ticket where the existing patterns are sound
(company / building / customer FKs, soft-delete fields, status
history), but the workflow and scope helpers live entirely under
this app so the two domains can evolve independently.

Operational-execution statuses (ASSIGNED / IN_PROGRESS /
WAITING_MANAGER_REVIEW / WAITING_CUSTOMER_APPROVAL / COMPLETED) are
intentionally NOT included in this sprint per the Sprint 26B brief
("If this is too large for one sprint, implement the minimal
customer-pricing loop first"). They land as a follow-up sprint
together with attachments and the staff assignment surface for
Extra Work jobs.
"""
from __future__ import annotations

from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models
from django.db.models import Q
from django.db.models.functions import Lower, Trim


class ExtraWorkCategory(models.TextChoices):
    """
    Default Extra Work categories per the Sprint 26B brief.
    Provider operators see exactly this dropdown when creating /
    classifying an Extra Work request. `OTHER` requires the
    creator (or operator) to fill in `category_other_text`; the
    requirement is enforced by the serializer.

    These are intentionally separate from `tickets.TicketType` —
    Extra Work is a different domain and the category list has no
    overlap with normal "melding / klacht / verzoek" ticket
    classification.
    """

    DEEP_CLEANING = "DEEP_CLEANING", "Deep cleaning"
    WINDOW_CLEANING = "WINDOW_CLEANING", "Window cleaning"
    FLOOR_MAINTENANCE = "FLOOR_MAINTENANCE", "Floor maintenance"
    SANITARY_SERVICE = "SANITARY_SERVICE", "Sanitary service"
    WASTE_REMOVAL = "WASTE_REMOVAL", "Waste removal"
    FURNITURE_MOVING = "FURNITURE_MOVING", "Furniture moving"
    EVENT_CLEANING = "EVENT_CLEANING", "Event cleaning"
    EMERGENCY_CLEANING = "EMERGENCY_CLEANING", "Emergency cleaning"
    OTHER = "OTHER", "Other"


class ExtraWorkUrgency(models.TextChoices):
    """Mirrors TicketPriority but kept independent on purpose so the
    Extra Work domain can grow its own urgency taxonomy later."""

    NORMAL = "NORMAL", "Normal"
    HIGH = "HIGH", "High"
    URGENT = "URGENT", "Urgent"


class ExtraWorkStatus(models.TextChoices):
    """
    Extra Work request lifecycle.

    Sprint 26B introduced the customer-pricing loop (REQUESTED ->
    UNDER_REVIEW -> PRICING_PROPOSED -> CUSTOMER_APPROVED /
    CUSTOMER_REJECTED / CANCELLED).

    Sprint 29 Batch 29.8 added the operational-execution segment
    IN_PROGRESS and COMPLETED so customer-approved Extra Work rows
    become visible to STAFF (via spawned-ticket scope) and stop
    being mis-counted as terminal on the operational dashboard.
    The two new states are driven both manually by provider
    operators (SUPER_ADMIN / COMPANY_ADMIN / BUILDING_MANAGER) and
    automatically by `tickets.state_machine.apply_transition` when
    spawned tickets progress.

    Commercial-execution statuses (FULFILLED / BILLED) remain
    deferred to a follow-up sprint and are not added here so the
    state machine stays focused on the operational loop.
    """

    REQUESTED = "REQUESTED", "Requested"
    UNDER_REVIEW = "UNDER_REVIEW", "Under review"
    PRICING_PROPOSED = "PRICING_PROPOSED", "Pricing proposed"
    CUSTOMER_APPROVED = "CUSTOMER_APPROVED", "Customer approved"
    IN_PROGRESS = "IN_PROGRESS", "In progress"
    COMPLETED = "COMPLETED", "Completed"
    CUSTOMER_REJECTED = "CUSTOMER_REJECTED", "Customer rejected"
    CANCELLED = "CANCELLED", "Cancelled"


class ExtraWorkPricingUnitType(models.TextChoices):
    HOURS = "HOURS", "Hours"
    SQUARE_METERS = "SQUARE_METERS", "Square meters"
    FIXED = "FIXED", "Fixed"
    ITEM = "ITEM", "Item"
    OTHER = "OTHER", "Other"


class ExtraWorkRequestIntent(models.TextChoices):
    """
    Sprint 2A — explicit customer-facing intent on an Extra Work
    request. Separate from `ExtraWorkStatus` (lifecycle) and from
    `ExtraWorkRoutingDecision` (internal cart classification).

    DIRECT_AGREED_PRICE_ORDER:
        Every cart line resolves to an active customer-specific
        agreed price. No proposal phase, no customer approval step
        — the submission IS the order; operational work is spawned
        immediately.
    AUTO_START_AFTER_PRICING:
        At least one cart line needs provider pricing or is ad-hoc.
        Provider enters prices and operational work starts WITHOUT
        a customer approval step (the customer pre-authorised
        starting the work after pricing).
    REQUEST_QUOTE:
        At least one cart line needs provider pricing or is ad-hoc.
        Provider sends a quote/proposal; customer must accept or
        reject. Accept → spawn; reject → REJECTED.

    Intent is nullable on the row so legacy pre-Sprint-2A requests
    (which never carried an explicit intent) survive without a
    forced default. The Sprint 2A backfill stamps a best-effort
    historical value (see migration 0006).
    """

    DIRECT_AGREED_PRICE_ORDER = (
        "DIRECT_AGREED_PRICE_ORDER",
        "Direct agreed-price order",
    )
    AUTO_START_AFTER_PRICING = (
        "AUTO_START_AFTER_PRICING",
        "Auto-start after pricing",
    )
    REQUEST_QUOTE = "REQUEST_QUOTE", "Request a quote"


class ExtraWorkLinePriceSource(models.TextChoices):
    """
    Sprint 2A — per-line price-source classification stamped at
    request-create time.

    AGREED_CUSTOMER_PRICE:
        The line's `service` resolved to an active
        `CustomerServicePrice` row at submit time and its
        unit_price / vat_pct were snapshotted onto the line.
    NEEDS_PROVIDER_PRICING:
        The line references a catalog `Service` but no active
        contract row exists for the (service, customer) pair on
        the requested date. The provider must enter a price.
    AD_HOC:
        The line has NO catalog `Service` FK — it is a free-text /
        operator-typed line described by `custom_description`. By
        definition the provider must enter a price.

    Stamped on `ExtraWorkRequestItem` at create time so a future
    `CustomerServicePrice` edit cannot retroactively rewrite the
    source label or the snapshot prices.
    """

    AGREED_CUSTOMER_PRICE = "AGREED_CUSTOMER_PRICE", "Agreed customer price"
    NEEDS_PROVIDER_PRICING = (
        "NEEDS_PROVIDER_PRICING",
        "Needs provider pricing",
    )
    AD_HOC = "AD_HOC", "Ad-hoc / free-text"


class ExtraWorkRoutingDecision(models.TextChoices):
    """
    Sprint 28 Batch 6 — routing taxonomy computed at submission time
    from the cart's line items.

    INSTANT  -> every line item resolved to an active
                `CustomerServicePrice` (per `extra_work.pricing.
                resolve_price`); the request is eligible for the
                instant-ticket flow in Batch 7.
    PROPOSAL -> at least one line had no active contract price
                (resolver returned None) or the line has no `service`
                FK (legacy / ad-hoc). The whole request goes to the
                provider proposal flow.

    The default is PROPOSAL — safer for legacy and partially-resolved
    carts. Batch 7 will act on the value; Batch 6 only stores it.
    """

    INSTANT = "INSTANT", "Instant ticket"
    PROPOSAL = "PROPOSAL", "Proposal"


class ExtraWorkBilledTo(models.TextChoices):
    """Sprint 180 §3 — WHO the finished work is charged to.

    Exactly two values, and the pair is the whole feature: the owner
    said the answer is the building 99% of the time and the customer
    the rest. A third value would be a grouping rule wearing a billing
    target's clothes.

    NOT `Customer.invoice_granularity_default`
    (CUSTOMER / PER_BUILDING / PER_BUILDING_DEPARTMENT_WORK_TYPE) —
    that one decides how many invoice DOCUMENTS a month's work is cut
    into for one customer, and it lives on the customer because it is a
    property of the customer's paperwork. This one is a property of the
    JOB and says who the charge belongs to. They read alike and are not
    alike: a customer invoiced PER_BUILDING can still have a single
    extra work that the customer's own head office pays for.

    Nothing in `generate_draft_invoices` reads this field yet. That is
    deliberate — the month-end job is a separate piece of work; this
    sprint records the answer so the job has something to read.
    """

    BUILDING = "BUILDING", "Building"
    CUSTOMER = "CUSTOMER", "Customer"


def _two_places(value: Decimal) -> Decimal:
    """Quantize a Decimal to 2 places, the canonical money rounding
    used everywhere in the Extra Work domain."""
    return value.quantize(Decimal("0.01"))


def compute_line_amounts(quantity, unit_price, vat_pct):
    """Pure money calculator for a single proposal line.

    Returns (line_subtotal, line_vat, line_total) all quantized to
    two places. Shared by `ProposalLine.save()` (persisted path) and
    the compute-only line-preview endpoint so the live preview is
    byte-equal to what gets stored.
    """
    line_subtotal = _two_places(quantity * unit_price)
    line_vat = _two_places(line_subtotal * vat_pct / Decimal("100"))
    line_total = _two_places(line_subtotal + line_vat)
    return line_subtotal, line_vat, line_total


class ExtraWorkRequest(models.Model):
    """
    The single entity a customer-side user creates and a provider-
    side operator turns into a priced proposal. Companies /
    buildings / customers FK to existing tenant models; the rest
    of the lifecycle lives in this app.
    """

    company = models.ForeignKey(
        "companies.Company",
        on_delete=models.CASCADE,
        related_name="extra_work_requests",
        help_text="Provider company that will perform the work.",
    )
    building = models.ForeignKey(
        "buildings.Building",
        on_delete=models.PROTECT,
        related_name="extra_work_requests",
    )
    customer = models.ForeignKey(
        "customers.Customer",
        on_delete=models.PROTECT,
        related_name="extra_work_requests",
    )

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="created_extra_work_requests",
    )

    # Sprint 7B — the original normal Ticket this Extra Work request was
    # converted FROM. Populated only by the conversion flow
    # (`extra_work.conversion.convert_ticket_to_extra_work`); NULL for
    # every other creation path. SET_NULL so the EW survives if the
    # source ticket is later hard-deleted.
    #
    # DISTINCT from `tickets.Ticket.extra_work_request` (the reverse of
    # `related_name="operational_tickets"`): that FK means "this ticket
    # is the operational ticket SPAWNED from an EW" and is the
    # spawn-idempotency anchor. `source_ticket` is the opposite
    # direction — "this EW was born from that pre-existing ticket". Do
    # NOT overload one for the other.
    source_ticket = models.ForeignKey(
        "tickets.Ticket",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="converted_extra_work_requests",
        default=None,
    )

    title = models.CharField(max_length=255)
    description = models.TextField()
    category = models.CharField(
        max_length=32,
        choices=ExtraWorkCategory.choices,
        default=ExtraWorkCategory.OTHER,
    )
    category_other_text = models.CharField(
        max_length=128,
        blank=True,
        help_text=(
            "Required when category=OTHER. Free-text description of "
            "the unlisted category."
        ),
    )

    # Sprint 127 — per-customer label lists (Department + Work Type) used
    # for filtering, reporting and invoice grouping. Both are pure labels
    # and orthogonal to the fixed-choice `category` enum above (they do NOT
    # replace it — see customers.models.WorkType).
    #
    # Nullable is REQUIRED, not a convenience: every existing EW row
    # predates both fields (no backfill), and one real customer has twelve
    # departments and ZERO work types. PROTECT mirrors `building`/`customer`
    # above — a label still referenced by any EW cannot be hard-deleted;
    # the CRUD delete endpoint turns that into a coded 400 that points the
    # operator at the `is_active=False` soft-retire path instead. The
    # same-customer invariant (a label must belong to THIS EW's customer)
    # is enforced by ExtraWorkRequestCreateSerializer, the sole write path.
    department = models.ForeignKey(
        "customers.Department",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="extra_work_requests",
    )
    work_type = models.ForeignKey(
        "customers.WorkType",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="extra_work_requests",
    )

    # Sprint 144 §1 — what the operator ACTUALLY classifies a request as
    # now: one of the company's own `ServiceCategory` rows, or one of the
    # customer's own `CustomerPriceFolder`s. AT MOST ONE is set.
    #
    # These replace the `category` enum above as the QUESTION the create
    # form asks. The enum itself is untouched and keeps its
    # `default=OTHER`: the form simply stops asking, so new rows take the
    # default and every one of the 65 live crmtest rows keeps the value
    # it already has. Migrating the enum away is its own job (`## NEXT`
    # item 18); this is not that, it just stops asking for it.
    #
    # Nullable is required, not a convenience — no backfill, and a
    # request created before this sprint has neither. PROTECT mirrors
    # `department` / `work_type` above: a category or folder still
    # referenced by any request cannot be hard-deleted. That matters
    # doubly for the folder, whose "delete with contents" path
    # (Sprint 143) must not be able to take request history with it.
    service_category = models.ForeignKey(
        "ServiceCategory",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="extra_work_requests",
        help_text=(
            "Sprint 144 — the company catalog category this request is "
            "filed under. Mutually exclusive with `price_folder`."
        ),
    )
    price_folder = models.ForeignKey(
        "CustomerPriceFolder",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="extra_work_requests",
        help_text=(
            "Sprint 144 — the customer's own price folder this request "
            "is filed under. Mutually exclusive with `service_category`."
        ),
    )

    urgency = models.CharField(
        max_length=16,
        choices=ExtraWorkUrgency.choices,
        default=ExtraWorkUrgency.NORMAL,
    )
    # Sprint 173 §4 — the PLANNED WINDOW, not a single date.
    #
    # `preferred_date` keeps its name deliberately: everything that
    # reads it today keeps working, and renaming it would be a
    # migration's worth of risk for a word. Read the pair as
    # start -> end; an end with no start is not a window and the
    # serializer refuses it.
    #
    # A window is what lets a week view place a job that spans days,
    # which is the whole reason the reference holds two.
    preferred_date = models.DateField(null=True, blank=True)
    planned_end_date = models.DateField(
        null=True,
        blank=True,
        help_text=(
            "Last planned day. With `preferred_date` this is the "
            "planned WINDOW; NULL means the job is planned for the one "
            "day rather than for a span."
        ),
    )
    # "By when this must be finished." Distinct from the planned window:
    # a job can be planned for next week and due at the end of the
    # month, and only the deadline decides whether it is late.
    deadline = models.DateField(
        null=True,
        blank=True,
        help_text=(
            "The date by which this must be finished. A record past it "
            "and not finished is marked overdue."
        ),
    )

    status = models.CharField(
        max_length=32,
        choices=ExtraWorkStatus.choices,
        default=ExtraWorkStatus.REQUESTED,
    )

    # Sprint 180 §3 / Sprint 182 §6 — who pays for this one. See
    # `ExtraWorkBilledTo` for why this is NOT the customer's invoice
    # granularity.
    #
    # NULLABLE since Sprint 182, and the null is the point: NULL means
    # "follow the customer's setting", a SET value overrides it for this
    # one job.
    #
    # Sprint 180 shipped it non-null with `default=BUILDING`, which was
    # right while nothing read it and wrong the moment something did: if
    # invoice generation simply started reading the column, every
    # customer configured for one-invoice-per-customer would silently
    # begin to be invoiced per building, because every pre-182 row says
    # BUILDING whether or not anybody chose it. Migration 0032 sets
    # every existing row to NULL for exactly that reason — those rows
    # took a default, they did not record a decision, and NULL is how
    # the column says so.
    #
    # PRECEDENCE, in one line: the extra work wins when it is set,
    # being the more specific statement; NULL defers to the customer.
    billed_to = models.CharField(
        max_length=16,
        choices=ExtraWorkBilledTo.choices,
        null=True,
        blank=True,
        default=None,
        help_text=(
            "Who the finished work is charged to: the BUILDING or the "
            "CUSTOMER organisation. NULL means follow the customer's "
            "own setting; a value set here overrides it for this job."
        ),
    )

    # Sprint 182 §6 — WHEN THE PROVIDER WILL DO IT.
    #
    # The only date this row had was `preferred_date`, and Sprint 176 §3
    # settled what that is: the CUSTOMER's wish. "I would like it around
    # then" is not a plan, and the provider had nowhere to write one —
    # which is why extra work shows up in the Work Plan as undated and
    # cannot be planned from there.
    #
    # So this is the provider's own answer, deliberately a SEPARATE
    # column rather than a reinterpretation of the customer's:
    #
    #   preferred_date        the customer's wish (unchanged, untouched)
    #   provider_planned_date the provider's commitment to a day
    #   planned_end_date      the last planned day, when the job spans
    #                         several (Sprint 173's window END)
    #   deadline              by when it must be finished; the only one
    #                         that decides whether a row is late
    #
    # W2-D added the sixth, `provider_planned_end_date`, which finishes
    # the provider's own pair. Read the six as TWO PAIRS and one due
    # date:
    #
    #   ASKED FOR / OWED   preferred_date -> planned_end_date, deadline
    #   COMMITTED TO       provider_planned_date -> provider_planned_end_date
    #
    # The plan action writes the second pair ONLY. That is the whole
    # point of holding two: months later "did we do what we promised, or
    # what they asked for?" is a question with an answer, and a plan can
    # never quietly move the date the provider is measured against.
    #
    # Nullable and with no default: an extra work nobody has planned yet
    # must be distinguishable from one planned for today, which is the
    # whole distinction the Work Plan's undated lane rests on.
    provider_planned_date = models.DateField(
        null=True,
        blank=True,
        default=None,
        help_text=(
            "Sprint 182 — the day the PROVIDER plans to do the work. "
            "Distinct from `preferred_date` (the customer's wish) and "
            "from `deadline` (when it must be finished). NULL means "
            "nobody has planned it yet."
        ),
    )

    # W2-D — the second half of the provider's pair. Set by the plan
    # action (`extra_work.planning`), never by anything that touches
    # the customer's dates.
    #
    # Nullable with no default for the same reason its start is: a job
    # planned for one day and a job whose end nobody has committed to
    # are different facts, and a default would erase the difference on
    # every row that predates this column.
    provider_planned_end_date = models.DateField(
        null=True,
        blank=True,
        default=None,
        help_text=(
            "W2-D — the day the PROVIDER expects to finish. With "
            "`provider_planned_date` this is the COMMITTED window, held "
            "separately from the customer's requested window "
            "(`preferred_date` -> `planned_end_date`). NULL means the "
            "provider has committed to a start but not to an end."
        ),
    )

    # W2-D — BUDGET HOURS. The planned total for the job.
    #
    # THIS FIELD NEVER TOUCHES MONEY, and that is a rule, not an
    # accident of the current wiring. `rowAmounts()` in
    # `frontend/src/lib/billing.ts` and its server-side mirror
    # (`extra_work.final_amounts`) are the one billing-total rule; a
    # budget is a PLANNING and CONTROL number that answers "how long did
    # we say this would take", and the moment an hours field reaches a
    # price there are two money rules and they disagree by cents. Grep
    # before wiring: nothing in `final_amounts.py`, `pricing.py`,
    # `billing.py` or `invoicing/` reads this, and nothing should.
    #
    # NULL is "nobody has budgeted this", which is NOT the same fact as
    # 0.00 ("we budgeted no hours"). Same distinction Sprint 188 drew
    # for price: unpriced and free must never render the same.
    budget_hours = models.DecimalField(
        max_digits=8,
        decimal_places=2,
        null=True,
        blank=True,
        default=None,
        validators=[MinValueValidator(Decimal("0"))],
        help_text=(
            "W2-D — planned total hours for the job. A planning and "
            "control number ONLY: it reaches no price anywhere. NULL "
            "means unbudgeted, which is not the same as 0.00."
        ),
    )

    # W2-D — the two completion requirements, set when the work is
    # planned. BOTH DEFAULT FALSE.
    #
    # Stored and exposed here; ENFORCEMENT is deliberately not here. It
    # belongs in the completion transition, in one place (wave 3), for
    # the reason the reference system demonstrates: over there both
    # flags are checked in the frontend only, so the same work completed
    # through the API skips the check entirely.
    file_upload_required = models.BooleanField(
        default=False,
        help_text=(
            "W2-D — a file must be attached before this work may be "
            "completed. Stored here; enforced in the completion "
            "transition (wave 3)."
        ),
    )
    completion_notes_required = models.BooleanField(
        default=False,
        help_text=(
            "W2-D — a completion note must be written before this work "
            "may be completed. Stored here; enforced in the completion "
            "transition (wave 3)."
        ),
    )

    @property
    def is_overdue(self) -> bool:
        """Past its deadline and not finished.

        Sprint 173 §4. One rule, here, so the list badge, the detail
        page and the Work Plan cannot disagree about what "late" means —
        three copies of a date comparison is how two screens end up
        marking different rows.

        A record with no deadline is never overdue: nobody said when it
        was due, and inventing a due date to call something late is
        worse than not marking it.
        """
        from django.utils import timezone

        if self.deadline is None:
            return False
        # Finished work is never late, whatever its deadline says.
        if self.status in {
            ExtraWorkStatus.COMPLETED,
            ExtraWorkStatus.CANCELLED,
            ExtraWorkStatus.CUSTOMER_REJECTED,
        }:
            return False
        return self.deadline < timezone.localdate()

    @property
    def started_before_plan(self) -> bool:
        """Work began before its planned window opened.

        The father's own example: a job entered today, started today,
        and planned for September. That is not blocked — he was explicit
        that people do it deliberately — but it IS shown, so it can be
        found and cleaned up rather than discovered months later.

        Derived from the STATUS HISTORY rather than a started_at column,
        for the reason recorded in the product docs: eleven date columns
        are that history flattened, and a flattened history cannot say
        who did something or whether it went backwards.

        Sprint 180 §2 — the narrowing happens in PYTHON over
        `status_history.all()`, deliberately, and it is the whole fix
        for the list's N+1. A `.filter(...)` on the related manager
        builds a NEW queryset, which ignores any prefetch cache and
        issues one query per row; `.all()` on a prefetched relation is
        free. The list queryset prefetches `status_history`, so a page
        of a hundred rows costs one extra query instead of a hundred.
        A single-object read (detail, create read-back) has no prefetch
        and pays exactly one query here, same as before.

        The rule itself is unchanged, and `ExtraWorkRequestFilter.
        filter_started_early` still expresses the same rule as a
        database `Min(...)` for the ?started_early= filter — a filter
        must not materialise the table to answer one question. A test
        pins that the two agree.
        """
        if self.preferred_date is None:
            return False
        starts = [
            row.created_at
            for row in self.status_history.all()
            if row.new_status
            in (ExtraWorkStatus.IN_PROGRESS, ExtraWorkStatus.COMPLETED)
        ]
        if not starts:
            return False
        return min(starts).date() < self.preferred_date

    # Sprint 28 Batch 6 — routing taxonomy computed at submission time
    # by `ExtraWorkRequestCreateSerializer.create()` from the cart's
    # line items + `extra_work.pricing.resolve_price`. PROPOSAL is the
    # safe default until the serializer has run the per-line resolver.
    # Batch 7 will branch on this field to spawn tickets vs hand off to
    # the proposal flow; Batch 6 only stores it.
    routing_decision = models.CharField(
        max_length=10,
        choices=ExtraWorkRoutingDecision.choices,
        default=ExtraWorkRoutingDecision.PROPOSAL,
    )

    # Sprint 2A — explicit customer-facing intent (see
    # ExtraWorkRequestIntent docstring). Nullable on the row so legacy
    # pre-Sprint-2A requests survive; the create serializer derives a
    # safe value when the caller does not send one (preserves
    # backward compatibility with Batch 6/7/8 clients) and fully
    # validates when the caller sends one explicitly.
    request_intent = models.CharField(
        max_length=32,
        choices=ExtraWorkRequestIntent.choices,
        null=True,
        blank=True,
        default=None,
        help_text=(
            "Sprint 2A — DIRECT_AGREED_PRICE_ORDER / "
            "AUTO_START_AFTER_PRICING / REQUEST_QUOTE. Separate from "
            "lifecycle status."
        ),
    )

    # Visible notes — provider operators write these for the customer
    # to see (e.g. pricing context, schedule notes).
    customer_visible_note = models.TextField(blank=True)
    pricing_note = models.TextField(
        blank=True,
        help_text=(
            "Customer-visible note specifically about pricing "
            "(e.g. 'price includes weekend surcharge')."
        ),
    )

    # Provider-only notes — never serialized for CUSTOMER_USER.
    manager_note = models.TextField(blank=True)
    internal_cost_note = models.TextField(
        blank=True,
        help_text=(
            "Provider-internal cost / margin / supplier note. "
            "Never returned in customer-facing serializers."
        ),
    )

    # Stored aggregate totals — also derivable from line items, but
    # kept on the request row so list endpoints don't have to
    # aggregate per row. Recomputed by the serializer / view layer
    # whenever pricing line items change.
    subtotal_amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal("0.00"),
    )
    vat_amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal("0.00"),
    )
    total_amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal("0.00"),
    )

    # Provider override audit — populated only when a provider
    # operator forces a customer-side decision (e.g. admin override
    # of a customer rejection). Always paired with a reason.
    override_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="extra_work_overrides_made",
    )
    override_reason = models.TextField(blank=True)
    override_at = models.DateTimeField(null=True, blank=True)

    # Soft-delete (mirrors Ticket pattern for consistency).
    deleted_at = models.DateTimeField(null=True, blank=True, db_index=True)
    deleted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="deleted_extra_work_requests",
    )

    requested_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    pricing_proposed_at = models.DateTimeField(null=True, blank=True)
    customer_decided_at = models.DateTimeField(null=True, blank=True)

    # Sprint 8B — final billable amounts. Distinct from the
    # `subtotal_amount` / `vat_amount` / `total_amount` quote/cache
    # above: those mirror the proposed (or contract) line prices at the
    # quantities the customer ordered. The `final_*` columns are the
    # ACTUAL amounts after hourly lines have their `actual_hours`
    # entered by the provider, and are FROZEN when the operational
    # ticket reaches customer approval (APPROVED). NULL until the first
    # `recompute_final_amounts` call. See `extra_work.final_amounts`.
    final_subtotal_amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
        default=None,
    )
    final_vat_amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
        default=None,
    )
    final_total_amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
        default=None,
    )

    # --- M4: billing month / invoice run (schema only in this commit) ---
    # `invoice_date` is the provider-set billing date, deliberately DECOUPLED
    # from `customer_decided_at` (final-approval): work completed May 31 but
    # approved Jun 7 must bill in MAY. NULL until a provider sets it; the
    # revenue report will later bucket on COALESCE(invoice_date, completion
    # date) by month. `is_invoiced` / `invoiced_at` record that a monthly
    # invoice run has issued this row — ORTHOGONAL to ExtraWorkStatus (no new
    # lifecycle status), so the state machine and revenue classifier stay
    # untouched. API/report/UI that read & write these land in later commits.
    invoice_date = models.DateField(null=True, blank=True)
    is_invoiced = models.BooleanField(default=False)
    invoiced_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-requested_at"]
        indexes = [
            models.Index(fields=["company", "status"]),
            models.Index(fields=["building", "status"]),
            models.Index(fields=["customer", "status"]),
            models.Index(fields=["deleted_at"]),
        ]

    def __str__(self):
        return f"ExtraWork #{self.pk}: {self.title}"

    def recompute_totals(self) -> None:
        """
        Recompute subtotal / vat / total from the current set of
        pricing line items. Called by the serializer / view layer
        after every pricing-item create / update / delete. The
        existing line-item rows are the source of truth — the
        aggregates on this row are a denormalised cache for list
        endpoints.
        """
        subtotal = Decimal("0.00")
        vat = Decimal("0.00")
        for item in self.pricing_line_items.all():
            subtotal += item.subtotal
            vat += item.vat_amount
        self.subtotal_amount = _two_places(subtotal)
        self.vat_amount = _two_places(vat)
        self.total_amount = _two_places(subtotal + vat)
        self.save(
            update_fields=[
                "subtotal_amount",
                "vat_amount",
                "total_amount",
                "updated_at",
            ]
        )

    def recompute_final_amounts(self) -> None:
        """Sprint 8B — recompute and persist the `final_*` amounts from
        the active priced-line set (proposal / cart / legacy), honouring
        `actual_hours` on hourly lines. Delegates to
        `extra_work.final_amounts.recompute_final_amounts` so the
        line-set resolution + billable-quantity rules live in one
        module. Imported locally to avoid an import cycle
        (final_amounts imports from this module)."""
        from .final_amounts import recompute_final_amounts

        recompute_final_amounts(self)


class ExtraWorkPricingLineItem(models.Model):
    """
    A single line in the provider's pricing proposal. Quantity,
    unit price, and VAT rate are stored; subtotal, VAT amount, and
    total are computed by the backend (frontend-supplied values are
    never trusted).
    """

    extra_work = models.ForeignKey(
        ExtraWorkRequest,
        on_delete=models.CASCADE,
        related_name="pricing_line_items",
    )

    description = models.CharField(max_length=255)
    unit_type = models.CharField(
        max_length=16,
        choices=ExtraWorkPricingUnitType.choices,
        default=ExtraWorkPricingUnitType.FIXED,
    )
    quantity = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0"))],
    )
    unit_price = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0"))],
    )
    # VAT rate expressed as a percentage (e.g. 21.00 means 21%).
    # Not hardcoded to Dutch BTW — each row carries its own rate so
    # multi-jurisdiction support is a serializer change away.
    vat_rate = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0"))],
    )

    # Stored computed values. The save() method below populates
    # them from quantity / unit_price / vat_rate on every save so
    # they cannot drift from the inputs.
    subtotal = models.DecimalField(max_digits=12, decimal_places=2)
    vat_amount = models.DecimalField(max_digits=12, decimal_places=2)
    total = models.DecimalField(max_digits=12, decimal_places=2)

    # Notes — customer-visible explanation vs provider-only cost note.
    customer_visible_note = models.TextField(blank=True)
    internal_cost_note = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["id"]
        indexes = [models.Index(fields=["extra_work"])]

    def __str__(self):
        return f"{self.extra_work_id} / {self.description}"

    def save(self, *args, **kwargs):
        # Stored totals always recomputed from the inputs — frontend
        # input never trusted. quantize() is applied so the values
        # round to 2dp consistently with the request-level aggregate.
        self.subtotal = _two_places(self.quantity * self.unit_price)
        self.vat_amount = _two_places(self.subtotal * self.vat_rate / Decimal("100"))
        self.total = _two_places(self.subtotal + self.vat_amount)
        super().save(*args, **kwargs)


class ManagedUnit(models.Model):
    """
    Sprint 123 — a provider-company-scoped catalog of unit names for
    `unit_type=OTHER` pricing lines.

    Before this model, the OTHER unit name was pure free text
    (`custom_unit_label` on `Service` / `CustomerCustomPrice` /
    `ProposalLine`), retyped per row with no consistency check — "m3"
    and "M3 " are the same unit typed two ways, and nothing could
    aggregate across them. The uniqueness rule below (and the backfill
    migration's dedupe) is case- and whitespace-insensitive ONLY: "m3"
    and "m³" are NOT treated as the same label, because "³" (U+00B3) is
    a distinct Unicode code point from "3" (U+0033) — Python's
    `.lower()` does not fold one into the other. Merging Unicode symbol
    variants would need an explicit normalization table, which is not
    part of this sprint's scope.

    Owner decision (2026-07-27): units are scoped **per provider
    company**, not per customer/building/room. Rationale: a unit is a
    physical measure (what changes per customer is the PRICE, not the
    unit itself); a per-customer unit list would just reintroduce the
    same drift one level up. Company-scoping mirrors `Service.company`
    (read that model's docstring first) rather than inventing a new
    scoping shape.

    `is_active` (default True) lets an operator archive a rarely-used
    unit out of the everyday picker WITHOUT breaking any row that
    already references it — the owner's own framing: "sometimes for
    only one customer we have a very weird unit, but usually we go
    with defaults."

    Only `Service` and `CustomerCustomPrice` link here (both nullable
    FKs, additive). `ProposalLine.custom_unit_label` is deliberately
    NOT touched — a Proposal is a document already shown to the
    customer, and `ProposalLine.unit_type` is explicitly "denormalised
    at create time so a later catalog edit... does not rewrite
    history"; repointing it at a mutable catalog row would let a later
    unit rename silently change what a customer was historically
    quoted. The free-text fields on `Service` / `CustomerCustomPrice`
    also stay: `custom_unit_label` remains the single rendered value
    everywhere (PDF, exports, lists) whether or not a row has adopted
    the managed catalog, so every existing consumer of that field
    keeps working unmodified. When a row IS linked to a `ManagedUnit`,
    the catalog serializers keep `custom_unit_label` in sync with the
    unit's current `label` at every write (see
    `serializers_catalog.py`).
    """

    company = models.ForeignKey(
        "companies.Company",
        on_delete=models.PROTECT,
        related_name="managed_units",
        help_text=(
            "Provider company that owns this unit. PROTECT mirrors "
            "Service.company: a Company cannot be hard-deleted while "
            "it still has managed units."
        ),
    )
    label = models.CharField(
        max_length=50,
        help_text='Operator-facing display label, e.g. "m³", "strekkende meter".',
    )
    is_active = models.BooleanField(
        default=True,
        help_text=(
            "Archiving (is_active=False) removes a unit from the "
            "everyday picker without breaking rows that already "
            "reference it."
        ),
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["company__name", "label", "id"]
        constraints = [
            # Case- AND whitespace-insensitive uniqueness, enforced at
            # the DB layer (not just app-level validation) so a race
            # condition or a direct-ORM write cannot create "m3" and
            # "M3 " as two rows in the same company. Trim() first so
            # leading/trailing whitespace can't bypass Lower()-only
            # dedupe; Lower() handles case. Postgres builds this as a
            # real expression index.
            models.UniqueConstraint(
                Lower(Trim("label")),
                "company",
                name="uniq_managed_unit_label_per_company_ci",
            ),
        ]

    def __str__(self):
        return f"{self.company.name} / {self.label}"


class ServiceCategory(models.Model):
    """
    Sprint 28 Batch 5 — provider-side service catalog: top-level
    category groupings.

    Categories are the parent rows for `Service` entries that customers
    eventually pick from when composing an Extra Work cart. A category
    can be soft-deactivated by toggling `is_active=False`; deletion is
    blocked while any `Service` row still references it (`PROTECT` on
    the FK below).

    Sprint 142 — categories are PER-COMPANY, reversing the Sprint 3B
    decision that left them global. Pre-142 there was no `company` FK
    and `name` was unique platform-wide, which meant (a) one provider's
    category could hold another provider's services and Sprint 138's
    cascade-archive would deactivate all of them, and (b) any
    authenticated user — including a CUSTOMER_USER — could read every
    provider's category names, because `catalog_scope.
    filter_categories_for` was the identity. Both are closed by the
    `company` FK plus the per-company uniqueness constraint below.
    Migration set `0023/0024/0025` mirrors the `Service.company`
    precedent (`0007`/`0008`/`0009`): nullable column + the new
    constraint, backfill, then NOT NULL.

    `name`'s `max_length=128` is deliberately unchanged — it is in
    lockstep with `ExtraWorkRequestItem.snapshot_service_category_name`,
    which stores a frozen copy of it.

    Distinct from `ExtraWorkCategory` (the legacy text-choices enum
    on `ExtraWorkRequest.category`): that enum classifies a single
    ad-hoc Extra Work request; this row drives the catalog of
    bookable services with their own per-customer pricing tables.
    """

    # Sprint 142 — provider-company scope, same shape as
    # `Service.company` / `ManagedUnit.company`. PROTECT so a Company
    # cannot be hard-deleted while it still owns catalog groupings.
    company = models.ForeignKey(
        "companies.Company",
        on_delete=models.PROTECT,
        related_name="service_categories",
        help_text=(
            "Sprint 142 — provider company that owns this category. "
            "Pre-142 rows are backfilled from the single company of "
            "their services by migration 0024."
        ),
    )
    # NOT `unique=True` since Sprint 142: uniqueness is per-company and
    # case/whitespace-insensitive, expressed as the constraint below.
    name = models.CharField(max_length=128)
    description = models.TextField(blank=True, default="")
    is_active = models.BooleanField(default=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name", "id"]
        verbose_name = "service category"
        verbose_name_plural = "service categories"
        constraints = [
            # Sprint 142 — same shape as `ManagedUnit`'s constraint:
            # Trim() first so leading/trailing whitespace cannot bypass
            # a Lower()-only dedupe, Lower() for case. Two DIFFERENT
            # providers may now both carry a "Cleaning" category; one
            # provider may not carry it twice.
            models.UniqueConstraint(
                Lower(Trim("name")),
                "company",
                name="uniq_service_category_name_per_company_ci",
            ),
        ]

    def __str__(self):
        return f"{self.company.name} / {self.name}"


class Service(models.Model):
    """
    Sprint 28 Batch 5 — provider-side service catalog row.

    A `Service` is one bookable line in the catalog: it sits under a
    `ServiceCategory`, declares its `unit_type` (re-using the existing
    `ExtraWorkPricingUnitType` enum — HOURS / SQUARE_METERS / FIXED /
    ITEM / OTHER), and ships with a `default_unit_price` that is the
    provider-side reference number shown in the catalog UI.

    The default price is NOT used by the instant-ticket resolver
    (`extra_work.pricing.resolve_price`). Per the master plan §5 rule
    #9, the only price that triggers the instant-ticket flow is the
    customer-specific `CustomerServicePrice` row. The default lives
    here purely as catalog metadata: a baseline operators can quote
    from when no contract row exists yet.

    `default_vat_pct` defaults to 21.00 (Dutch BTW) per the
    2026-05-15 stakeholder meeting spec §5; per-customer rows can
    override.

    Sprint 3B — `company` FK ties each Service to a single provider
    `companies.Company`. Pre-Sprint-3B the catalog was global; the
    Sprint 3B migration set
    (`extra_work/0007/0008/0009`) adds a nullable column,
    backfills it from CustomerServicePrice ownership (or pins to
    the single Company when the DB has exactly one), then flips it
    NOT NULL. The PROTECT delete reflects that a Company with a
    catalog cannot be hard-deleted; archival lives on the Company
    side as `is_active=False`.
    """

    category = models.ForeignKey(
        ServiceCategory,
        on_delete=models.PROTECT,
        related_name="services",
    )
    # Sprint 3B — provider-company scope. PROTECT so a Company
    # cannot be hard-deleted while it still has Services pointing
    # at it. `related_name="services"` mirrors the catalog noun.
    #
    # NOT NULL after Sprint 3B migration 0009 — 0007 adds the
    # column nullable, 0008 backfills it (aborting on ambiguous
    # data), 0009 flips NOT NULL. Tests and API consumers must
    # always supply company; the few legacy ORM-direct test
    # creates were updated in Sprint 3B to pass it.
    company = models.ForeignKey(
        "companies.Company",
        on_delete=models.PROTECT,
        related_name="services",
        help_text=(
            "Sprint 3B — provider company that owns this catalog "
            "row. Required on every API-created Service; pre-3B "
            "legacy rows are backfilled via migration 0008."
        ),
    )
    name = models.CharField(max_length=200)
    description = models.TextField(blank=True, default="")
    unit_type = models.CharField(
        max_length=20,
        choices=ExtraWorkPricingUnitType.choices,
    )
    # RF-2 (mirror of CustomerCustomPrice.custom_unit_label) — the
    # operator-supplied unit name for `unit_type == OTHER` (e.g. "cm",
    # "m3", "pallet"). `OTHER` is otherwise an opaque enum member with
    # nothing to render. Only meaningful for OTHER; the serializer forces
    # it blank for every concrete unit type and REQUIRES a non-blank label
    # for OTHER (stable code `custom_unit_label_required`).
    custom_unit_label = models.CharField(max_length=50, blank=True, default="")
    # Sprint 123 — optional link into the company's managed-unit catalog
    # (see ManagedUnit). Nullable: a pre-Sprint-123 row, or one whose
    # label never got linked, stays valid. `custom_unit_label` remains
    # the rendered text either way — the catalog serializer keeps it in
    # sync with the linked unit's current label at every write.
    managed_unit = models.ForeignKey(
        "ManagedUnit",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="services",
        help_text=(
            "Sprint 123 — optional managed-unit catalog link, only "
            "meaningful when unit_type=OTHER. PROTECT: archiving a "
            "unit is always safe; deleting one still in use is not."
        ),
    )
    default_unit_price = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0"))],
        help_text=(
            "Provider-side reference price for the catalog UI. NOT "
            "consumed by the instant-ticket pricing resolver — a "
            "customer-specific CustomerServicePrice row is required "
            "before a line can skip the proposal phase. Sprint 3B "
            "stripped from CUSTOMER_USER / STAFF API reads."
        ),
    )
    default_vat_pct = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=Decimal("21.00"),
        validators=[MinValueValidator(Decimal("0"))],
    )
    is_active = models.BooleanField(default=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["category__name", "name", "id"]
        constraints = [
            # Sprint 3B — uniqueness now includes the provider
            # company FK. Two different providers may carry a
            # Service with the same (category, name) tuple because
            # they are independent catalogs.
            models.UniqueConstraint(
                fields=["company", "category", "name"],
                name="uniq_service_name_per_company_category",
            ),
        ]

    def __str__(self):
        return f"{self.category.name} / {self.name}"


class CustomerPriceFolder(models.Model):
    """
    Sprint 143 §3 — a folder that belongs to ONE CUSTOMER and groups
    that customer's price rows.

    Distinct from `ServiceCategory`, and deliberately so. A
    `ServiceCategory` is the PROVIDER's catalog grouping, shared by every
    customer under that company (and company-scoped since Sprint 142). A
    `CustomerPriceFolder` is the CUSTOMER's own arrangement of the prices
    agreed with them. Renaming one never touches the other, and a folder
    copied from a category keeps no link back to it — the copy seeds
    price rows, it does not adopt the category.

    A folder holds PRICE ROWS, never catalog services: the service is
    shared and is not moved. Both price models get a nullable `folder`
    FK below, so a row belongs to at most one folder and a FOLDERLESS
    row stays perfectly legal — every pre-143 row is one, and they must
    remain visible on the pricing page.

    Shaped after `documents.models.DocumentFolder`, the proven
    per-customer folder in this codebase: `customer` CASCADE (a folder
    is owned by its customer and should not outlive it), a nullable
    `created_by` on PROTECT (system writes have no actor, but a user who
    created folders cannot be deleted), and case-insensitive name
    uniqueness per customer. The constraint uses `Lower(Trim(...))`
    rather than DocumentFolder's `Lower(...)` — the same normalization
    `uniq_service_category_name_per_company_ci` settled on in Sprint 142,
    so leading/trailing whitespace cannot bypass the dedupe. There is no
    `parent`: these are flat, so DocumentFolder's two partial
    constraints collapse to one.
    """

    customer = models.ForeignKey(
        "customers.Customer",
        on_delete=models.CASCADE,
        related_name="price_folders",
    )
    name = models.CharField(max_length=128)
    is_active = models.BooleanField(
        default=True,
        help_text=(
            "Archiving a folder hides it from the Extra Work form's "
            "picker without touching the price rows inside it."
        ),
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="created_price_folders",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name", "id"]
        verbose_name = "customer price folder"
        verbose_name_plural = "customer price folders"
        constraints = [
            models.UniqueConstraint(
                Lower(Trim("name")),
                "customer",
                name="uniq_price_folder_name_per_customer_ci",
            ),
        ]

    def __str__(self):
        return f"{self.customer.name} / {self.name}"


class CustomerServicePrice(models.Model):
    """
    Sprint 28 Batch 5 — per-customer contract price for a Service.

    A `CustomerServicePrice` row is the only thing the instant-ticket
    pricing resolver (`extra_work.pricing.resolve_price`) cares about.
    Its presence, validity window and `is_active` flag together decide
    whether an Extra Work cart line skips the proposal phase and
    spawns operational tickets directly (master plan §5 rule #9 +
    2026-05-15 decision log).

    `valid_from` is required. `valid_to` is optional — leaving it
    NULL means the contract row applies open-endedly from
    `valid_from` onward. `is_active=False` disables the row without
    losing its audit history (mirrors the `CustomerUserBuildingAccess`
    pattern).

    `service` uses PROTECT so a Service cannot be deleted while any
    customer still has a contract pointing at it. `customer` uses
    CASCADE: contract rows are owned by their customer and should not
    outlive a customer-org deletion.
    """

    service = models.ForeignKey(
        Service,
        on_delete=models.PROTECT,
        related_name="customer_prices",
    )
    customer = models.ForeignKey(
        "customers.Customer",
        on_delete=models.CASCADE,
        related_name="service_prices",
    )

    # Sprint 143 §3 — optional per-customer folder. NULLABLE and
    # SET_NULL: every pre-143 row has no folder and must keep working,
    # and "delete the folder, keep the prices" is one of the two delete
    # modes the UI offers — SET_NULL is what makes that a one-liner
    # instead of a cascade the operator did not ask for.
    folder = models.ForeignKey(
        "CustomerPriceFolder",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="prices",
    )

    unit_price = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0"))],
    )
    vat_pct = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=Decimal("21.00"),
        validators=[MinValueValidator(Decimal("0"))],
    )

    valid_from = models.DateField()
    valid_to = models.DateField(null=True, blank=True)
    is_active = models.BooleanField(default=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["customer__name", "service__name", "-valid_from", "id"]
        indexes = [
            # Hot path for the resolver (filter by service + customer,
            # order by -valid_from). The composite index keeps it index-
            # only even as the table grows.
            models.Index(
                fields=["service", "customer", "-valid_from"],
                name="idx_csp_lookup",
            ),
        ]

    def __str__(self):
        return (
            f"{self.customer.name} — {self.service.name} @ {self.unit_price}"
        )

    def clean(self):
        super().clean()
        from django.core.exceptions import ValidationError

        if self.valid_to is not None and self.valid_from is not None:
            if self.valid_to < self.valid_from:
                raise ValidationError(
                    {"valid_to": "valid_to must be on or after valid_from."}
                )


class CustomerCustomPrice(models.Model):
    """M5 A — per-customer ad-hoc / custom price line for a service
    NOT in the provider catalog. Parallel to CustomerServicePrice but
    with NO `service` FK: carries a free-text `custom_name` and its
    own `unit_type`. Isolation: with no `service`, a row here can
    never be returned by `resolve_price(service, customer)`, so the
    instant-ticket / cart / proposal / billing paths are untouched.
    Provider-internal price record for non-catalog work.
    """

    customer = models.ForeignKey(
        "customers.Customer",
        on_delete=models.CASCADE,
        related_name="custom_prices",
    )
    # Sprint 143 §3 — see `CustomerServicePrice.folder`. A customer-only
    # line is exactly the kind of row an operator adds INTO a folder.
    folder = models.ForeignKey(
        "CustomerPriceFolder",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="custom_prices",
    )
    custom_name = models.CharField(max_length=200)
    unit_type = models.CharField(
        max_length=20,
        choices=ExtraWorkPricingUnitType.choices,
    )
    # RF-2 — the operator-supplied unit name for `unit_type == OTHER`
    # (e.g. "cm", "m3", "pallet"). `OTHER` is otherwise an opaque enum
    # member with nothing to render. Only meaningful for OTHER; the
    # serializer forces it blank for every other unit type so the two
    # cannot drift out of sync.
    custom_unit_label = models.CharField(max_length=50, blank=True, default="")
    # Sprint 123 — optional link into the owning company's managed-unit
    # catalog (see ManagedUnit; company is reached via customer.company,
    # this model has no direct company FK). Nullable + additive, same
    # rationale as Service.managed_unit.
    managed_unit = models.ForeignKey(
        "ManagedUnit",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="custom_prices",
        help_text=(
            "Sprint 123 — optional managed-unit catalog link, only "
            "meaningful when unit_type=OTHER. Must belong to the same "
            "company as customer.company (enforced in the view — see "
            "views_catalog.py::_enforce_same_company_managed_unit)."
        ),
    )
    unit_price = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0"))],
    )
    vat_pct = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=Decimal("21.00"),
        validators=[MinValueValidator(Decimal("0"))],
    )
    valid_from = models.DateField()
    valid_to = models.DateField(null=True, blank=True)
    is_active = models.BooleanField(default=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["customer__name", "custom_name", "-valid_from", "id"]
        indexes = [
            models.Index(
                fields=["customer", "-valid_from"],
                name="idx_ccp_lookup",
            ),
        ]

    def __str__(self):
        return f"{self.customer.name} — {self.custom_name} @ {self.unit_price}"

    def clean(self):
        super().clean()
        from django.core.exceptions import ValidationError

        if self.valid_to is not None and self.valid_from is not None:
            if self.valid_to < self.valid_from:
                raise ValidationError(
                    {"valid_to": "valid_to must be on or after valid_from."}
                )


class ExtraWorkStatusHistory(models.Model):
    """
    Append-only audit log of every successful state transition on an
    Extra Work request. Mirrors `tickets.TicketStatusHistory` so any
    operator already familiar with the ticket timeline UI can map
    one-to-one.
    """

    extra_work = models.ForeignKey(
        ExtraWorkRequest,
        on_delete=models.CASCADE,
        related_name="status_history",
    )
    old_status = models.CharField(max_length=32, choices=ExtraWorkStatus.choices)
    new_status = models.CharField(max_length=32, choices=ExtraWorkStatus.choices)
    changed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="extra_work_status_changes",
    )
    note = models.TextField(blank=True)
    is_override = models.BooleanField(
        default=False,
        help_text=(
            "True when a provider operator overrode a customer-side "
            "decision. Always paired with a non-empty `note`."
        ),
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]
        indexes = [models.Index(fields=["extra_work", "created_at"])]

    def __str__(self):
        return (
            f"{self.extra_work_id}: {self.old_status} -> {self.new_status}"
        )


class ExtraWorkRequestItem(models.Model):
    """
    Sprint 28 Batch 6 — per-line shopping-cart entry on an
    `ExtraWorkRequest`.

    Distinct from `ExtraWorkPricingLineItem`: the pricing model is the
    provider-side, post-hoc quoted line (`description` + `unit_price`
    + `vat_rate` etc.) on the legacy single-line request. The item
    model below is the customer-facing cart line: a `service` FK to
    the Batch 5 service catalog, the requested quantity, a per-line
    `requested_date`, and an optional per-line `customer_note`.

    `service` is NULL-allowed so the Batch 6 data migration can
    backfill exactly one item row per legacy `ExtraWorkRequest`
    without inventing a synthetic Service catalog entry. New
    submissions through the serializer enforce non-null + active
    Service.

    `unit_type` is denormalised from `Service.unit_type` at create
    time. A later edit to the catalog row's `unit_type` therefore
    does NOT retroactively rewrite the historical line's pricing
    semantics — the cart line stays pinned to the unit it was
    booked under.
    """

    extra_work_request = models.ForeignKey(
        ExtraWorkRequest,
        on_delete=models.CASCADE,
        related_name="line_items",
    )
    service = models.ForeignKey(
        Service,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="cart_items",
        help_text=(
            "Catalog row for this cart line. NULL on rows backfilled "
            "from legacy single-line ExtraWorkRequests; new "
            "submissions enforce non-null + Service.is_active."
        ),
    )
    quantity = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0"))],
    )
    unit_type = models.CharField(
        max_length=20,
        choices=ExtraWorkPricingUnitType.choices,
        help_text=(
            "Denormalised from Service.unit_type at create time so a "
            "later catalog edit cannot rewrite the historical cart "
            "line's pricing semantics."
        ),
    )
    requested_date = models.DateField()
    customer_note = models.TextField(
        blank=True,
        default="",
        help_text=(
            "Per-line free-text note from the customer. Distinct from "
            "the request-level `description` which describes the cart "
            "as a whole."
        ),
    )

    # Sprint 2A — ad-hoc / free-text cart line. When `service is
    # NULL` and `custom_description` is non-empty, the line is an
    # ad-hoc line: no catalog row, provider must enter a price.
    # Ad-hoc lines never auto-create a catalog `Service` row; they
    # only live on this cart entry. The serializer enforces "service
    # OR custom_description, never both blank, never both set."
    custom_description = models.CharField(
        max_length=255,
        blank=True,
        default="",
        help_text=(
            "Sprint 2A — free-text label for ad-hoc cart lines. "
            "Required when `service` is NULL; must be empty when "
            "`service` is set."
        ),
    )

    # Sprint 2A — per-line price-source classification stamped at
    # request-create time. See ExtraWorkLinePriceSource docstring.
    # Nullable to keep the schema additive — legacy rows are
    # backfilled in migration 0006 from their parent's
    # routing_decision, but the column stays nullable in case a
    # later forward-compat row sneaks through with no classification.
    line_price_source = models.CharField(
        max_length=32,
        choices=ExtraWorkLinePriceSource.choices,
        null=True,
        blank=True,
        default=None,
    )

    # Sprint 2A — agreed-price snapshot. Populated by the create
    # serializer ONLY when the line resolves to an active
    # `CustomerServicePrice` at submit time (`line_price_source ==
    # AGREED_CUSTOMER_PRICE`). NULL for NEEDS_PROVIDER_PRICING /
    # AD_HOC lines. Future edits to the resolved
    # `CustomerServicePrice` row (or to `Service.default_unit_price`)
    # MUST NOT rewrite these columns.
    snapshot_unit_price = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
        default=None,
        validators=[MinValueValidator(Decimal("0"))],
    )
    snapshot_vat_pct = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        null=True,
        blank=True,
        default=None,
        validators=[MinValueValidator(Decimal("0"))],
    )
    snapshot_service_name = models.CharField(
        max_length=200,
        blank=True,
        default="",
    )
    snapshot_service_category_name = models.CharField(
        max_length=128,
        blank=True,
        default="",
    )
    # Sprint 137 item 6 — the CustomerCustomPrice row an ORDERED custom
    # price line came from. Custom prices carry `custom_name` +
    # `unit_type` + an amount but have NO `service` FK by design, so
    # before Sprint 137 they could never reach a cart at all: the
    # operator priced work here and was then baffled it was unorderable.
    #
    # A line sourced from one is still an AD_HOC line — `service` stays
    # NULL and `line_price_source` stays AD_HOC, so routing, the
    # `all_agreed` predicate and the instant-ticket spawn are all
    # untouched (see classification.classify_line). What this FK adds is
    # the durable "which custom price row produced this line?" link, the
    # exact counterpart of `snapshot_customer_service_price` above — and
    # SET_NULL for the same reason: archiving the price row must never
    # delete operational history.
    snapshot_customer_custom_price = models.ForeignKey(
        "extra_work.CustomerCustomPrice",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        default=None,
        related_name="snapshotted_line_items",
        help_text=(
            "Sprint 137 item 6 — the CustomerCustomPrice row this "
            "ad-hoc line was ordered from. SET_NULL: the snapshot_* "
            "columns are the durable record."
        ),
    )
    snapshot_customer_service_price = models.ForeignKey(
        "extra_work.CustomerServicePrice",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        default=None,
        related_name="snapshotted_line_items",
        help_text=(
            "Sprint 2A — the CustomerServicePrice row resolved at "
            "create time. SET_NULL so deleting the contract row does "
            "not delete operational history; the snapshot_* columns "
            "are the durable audit trail."
        ),
    )

    # Sprint 8B — actual hours worked on an HOURS-unit cart line. Entered
    # provider-side after the work is done (before customer approval of
    # the operational ticket); drives `final_*` on the parent EW. NULL
    # for non-hourly lines and for hourly lines not yet finalised. NEVER
    # overwrites `quantity` (the ordered amount); `final_amounts`
    # substitutes `actual_hours` for `quantity` only when computing the
    # final billable total.
    actual_hours = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
        default=None,
        validators=[MinValueValidator(Decimal("0"))],
    )
    actual_hours_entered_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )
    actual_hours_entered_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["id"]
        indexes = [models.Index(fields=["extra_work_request"])]

    def __str__(self):
        if self.service is not None:
            label = self.service.name
        elif self.custom_description:
            label = self.custom_description
        else:
            label = "legacy"
        return f"{label} × {self.quantity}"


# ---------------------------------------------------------------------------
# Sprint 28 Batch 8 — provider-built proposal flow
# ---------------------------------------------------------------------------
class ProposalStatus(models.TextChoices):
    """
    Sprint 28 Batch 8 — proposal lifecycle.

    Distinct from `ExtraWorkStatus` on the parent request. A proposal
    starts as DRAFT (operator composing), moves to SENT (customer can
    decide), and lands on CUSTOMER_APPROVED / CUSTOMER_REJECTED. A
    provider may also CANCEL a draft / sent proposal — replacing it
    with a new one is done by creating a fresh DRAFT row after a
    rejection, not by transitioning the existing row backward.
    """

    DRAFT = "DRAFT", "Draft"
    SENT = "SENT", "Sent"
    CUSTOMER_APPROVED = "CUSTOMER_APPROVED", "Customer approved"
    CUSTOMER_REJECTED = "CUSTOMER_REJECTED", "Customer rejected"
    CANCELLED = "CANCELLED", "Cancelled"


class ProposalTimelineEventType(models.TextChoices):
    """
    Sprint 28 Batch 8 — proposal timeline event taxonomy.

    `CREATED` fires on POST proposals; the lifecycle transitions
    (SENT / CUSTOMER_APPROVED / CUSTOMER_REJECTED / CANCELLED) fire
    inside `apply_proposal_transition`. `ADMIN_OVERRIDDEN` is emitted
    alongside the customer-decision event when a provider drives the
    transition on the customer's behalf — the override fact lives on
    the proposal's `ProposalStatusHistory` row (H-11), this event is
    the operator-facing timeline marker. `CUSTOMER_VIEWED` is fired
    by the customer-facing read endpoint when a customer first opens
    a SENT proposal.
    """

    CREATED = "CREATED", "Created"
    SENT = "SENT", "Sent"
    CUSTOMER_VIEWED = "CUSTOMER_VIEWED", "Customer viewed"
    CUSTOMER_APPROVED = "CUSTOMER_APPROVED", "Customer approved"
    CUSTOMER_REJECTED = "CUSTOMER_REJECTED", "Customer rejected"
    ADMIN_OVERRIDDEN = "ADMIN_OVERRIDDEN", "Admin overridden"
    CANCELLED = "CANCELLED", "Cancelled"


class Proposal(models.Model):
    """
    Sprint 28 Batch 8 — provider-built proposal for an
    `ExtraWorkRequest` whose cart routed to PROPOSAL.

    A proposal carries N `ProposalLine` rows the operator composes,
    is sent to the customer, and is then approved or rejected. The
    customer-decision approval path spawns one operational Ticket per
    line (via `extra_work.proposal_tickets.spawn_tickets_for_proposal`).

    A single ExtraWorkRequest may have at most one DRAFT-or-SENT
    proposal at a time (enforced by the partial UniqueConstraint
    below). After CUSTOMER_REJECTED / CANCELLED the operator may
    create a new DRAFT proposal — keeping the old row as historical
    record. 1:N parent->proposals is therefore allowed; the
    constraint only blocks parallel open drafts.
    """

    extra_work_request = models.ForeignKey(
        ExtraWorkRequest,
        on_delete=models.CASCADE,
        related_name="proposals",
    )
    status = models.CharField(
        max_length=32,
        choices=ProposalStatus.choices,
        default=ProposalStatus.DRAFT,
    )

    subtotal_amount = models.DecimalField(
        max_digits=12, decimal_places=2, default=Decimal("0.00")
    )
    vat_amount = models.DecimalField(
        max_digits=12, decimal_places=2, default=Decimal("0.00")
    )
    total_amount = models.DecimalField(
        max_digits=12, decimal_places=2, default=Decimal("0.00")
    )

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="created_proposals",
    )

    sent_at = models.DateTimeField(null=True, blank=True)
    customer_decided_at = models.DateTimeField(null=True, blank=True)

    # Provider override audit — populated only when a provider operator
    # forces a customer-side decision (mirror ExtraWorkRequest pattern).
    override_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="extra_work_proposal_overrides_made",
    )
    override_reason = models.TextField(blank=True)
    override_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            # At most one DRAFT-or-SENT proposal per request. 1:N is
            # allowed (post-rejection re-quote), but two parallel open
            # drafts is ambiguous.
            models.UniqueConstraint(
                fields=["extra_work_request"],
                condition=Q(status__in=["DRAFT", "SENT"]),
                name="uniq_proposal_open_per_request",
            ),
        ]

    def __str__(self):
        return f"Proposal #{self.pk} for EW #{self.extra_work_request_id}"

    def recompute_totals(self) -> None:
        """
        Recompute subtotal / vat / total from the current set of
        proposal lines. Called by the serializer / view layer after
        every line-item create / update / delete. Mirrors
        `ExtraWorkRequest.recompute_totals`.
        """
        subtotal = Decimal("0.00")
        vat = Decimal("0.00")
        total = Decimal("0.00")
        for line in self.lines.all():
            subtotal += line.line_subtotal
            vat += line.line_vat
            total += line.line_total
        self.subtotal_amount = _two_places(subtotal)
        self.vat_amount = _two_places(vat)
        self.total_amount = _two_places(total)
        self.save(
            update_fields=[
                "subtotal_amount",
                "vat_amount",
                "total_amount",
                "updated_at",
            ]
        )


class ProposalLine(models.Model):
    """
    Sprint 28 Batch 8 — single line on a `Proposal`.

    `service` is NULL-allowed for ad-hoc lines that don't come from
    the catalog; the serializer enforces a non-empty `description`
    in that case (see `clean()` below and the serializer's
    `validate()` mirror).

    The line carries both a customer-visible explanation
    (`customer_explanation`, surfaced on the customer serializer)
    and a provider-internal note (`internal_note`, stripped from
    the customer-facing read). The naming follows the 2026-05-15
    stakeholder meeting spec §6 verbatim.

    `is_approved_for_spawn` defaults to True. Nothing in Batch 8
    flips it to False, but the ticket-spawn helper respects it as
    forward-compat for a future per-line approval UX.
    """

    proposal = models.ForeignKey(
        Proposal,
        on_delete=models.CASCADE,
        related_name="lines",
    )
    service = models.ForeignKey(
        Service,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="proposal_lines",
        help_text="NULL when this is an ad-hoc line (no catalog link).",
    )
    description = models.CharField(
        max_length=255,
        blank=True,
        help_text=(
            "Free-text label for ad-hoc lines. Required when "
            "`service` is NULL."
        ),
    )

    quantity = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0"))],
    )
    unit_type = models.CharField(
        max_length=20,
        choices=ExtraWorkPricingUnitType.choices,
        help_text=(
            "Denormalised at create time so a later catalog edit to "
            "the linked Service does not rewrite history."
        ),
    )
    # #108 Part B — operator-supplied unit name for `unit_type == OTHER`
    # (e.g. "cm", "m3", "pallet"), mirroring the RF-2 field on
    # CustomerCustomPrice. Only meaningful for OTHER; the serializer
    # forces it blank for every other unit type. Unlike the catalog rule,
    # a blank label on an OTHER line stays legal (plain "Other" and
    # "Custom…" are both offered in the composer — owner decision).
    custom_unit_label = models.CharField(max_length=50, blank=True, default="")
    unit_price = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0"))],
    )
    vat_pct = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=Decimal("21.00"),
        validators=[MinValueValidator(Decimal("0"))],
    )

    customer_explanation = models.TextField(
        blank=True,
        default="",
        help_text=(
            "Customer-visible per-line explanation. Surfaced on the "
            "customer-facing proposal serializer and on the spawned "
            "Ticket description (Batch 8 spec §6)."
        ),
    )
    internal_note = models.TextField(
        blank=True,
        default="",
        help_text=(
            "Provider-only per-line note. NEVER serialized for "
            "CUSTOMER_USER; never propagated into spawned Ticket "
            "descriptions (Batch 8 spec §6)."
        ),
    )

    is_approved_for_spawn = models.BooleanField(
        default=True,
        help_text=(
            "Per-line approval slot. When False the ticket-spawn "
            "helper skips this line on customer approval. Forward-"
            "compat for a future per-line approval UX."
        ),
    )

    # Stored computed values — backend always recomputes from
    # quantity / unit_price / vat_pct in save() so frontend-supplied
    # values are never trusted.
    line_subtotal = models.DecimalField(max_digits=12, decimal_places=2)
    line_vat = models.DecimalField(max_digits=12, decimal_places=2)
    line_total = models.DecimalField(max_digits=12, decimal_places=2)

    # Sprint 8B — actual hours worked on an HOURS-unit proposal line.
    # Mirror of `ExtraWorkRequestItem.actual_hours`: entered
    # provider-side after the work is done, drives the parent EW's
    # `final_*`, NEVER overwrites `quantity` / `unit_price`. NULL for
    # non-hourly lines and for hourly lines not yet finalised.
    actual_hours = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
        default=None,
        validators=[MinValueValidator(Decimal("0"))],
    )
    actual_hours_entered_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )
    actual_hours_entered_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["id"]
        indexes = [models.Index(fields=["proposal"])]

    def __str__(self):
        if self.service is not None:
            label = self.service.name
        elif self.description:
            label = self.description
        else:
            label = "(ad-hoc)"
        return f"{label} × {self.quantity}"

    def clean(self):
        super().clean()
        if self.service is None and not (self.description or "").strip():
            raise ValidationError(
                {"description": "Required when service is not set."}
            )

    def save(self, *args, **kwargs):
        # Stored totals always recomputed from the inputs via the
        # shared pure helper so the live-preview endpoint and the
        # persisted row never diverge.
        (
            self.line_subtotal,
            self.line_vat,
            self.line_total,
        ) = compute_line_amounts(
            self.quantity, self.unit_price, self.vat_pct
        )
        super().save(*args, **kwargs)


class ProposalStatusHistory(models.Model):
    """
    Sprint 28 Batch 8 — append-only audit row for every successful
    state transition on a `Proposal`. Mirrors
    `ExtraWorkStatusHistory` / `TicketStatusHistory` (Sprint 27F-B1).

    The `is_override` + `override_reason` columns ARE the audit trail
    for provider-driven customer-decision overrides — by design they
    are NOT registered in the generic AuditLog (matrix H-11: workflow
    override and permission override are separate concepts).
    """

    proposal = models.ForeignKey(
        Proposal,
        on_delete=models.CASCADE,
        related_name="status_history",
    )
    old_status = models.CharField(
        max_length=32, choices=ProposalStatus.choices
    )
    new_status = models.CharField(
        max_length=32, choices=ProposalStatus.choices
    )
    changed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="proposal_status_changes",
    )
    note = models.TextField(blank=True)
    is_override = models.BooleanField(
        default=False,
        help_text=(
            "True when a provider operator drove a customer-decision "
            "transition. Always paired with a non-empty override_reason."
        ),
    )
    override_reason = models.TextField(blank=True, default="")

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]
        indexes = [models.Index(fields=["proposal", "created_at"])]

    def __str__(self):
        return (
            f"{self.proposal_id}: {self.old_status} -> {self.new_status}"
        )


class ProposalTimelineEvent(models.Model):
    """
    Sprint 28 Batch 8 — per-action timeline marker on a `Proposal`.

    The status-history row captures the bare transition. The timeline
    event row captures the same fact PLUS additional context (e.g.
    `metadata.override_reason` on `ADMIN_OVERRIDDEN`) and is
    customer-visible-by-default. The customer-facing serializer
    strips the `metadata` JSON entirely so provider-only context
    cannot leak.

    H-11 invariant: this model is NOT registered in the generic
    AuditLog. The row itself IS the audit trail.
    """

    proposal = models.ForeignKey(
        Proposal,
        on_delete=models.CASCADE,
        related_name="timeline_events",
    )
    event_type = models.CharField(
        max_length=32, choices=ProposalTimelineEventType.choices
    )
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="proposal_timeline_events",
    )
    customer_visible = models.BooleanField(
        default=True,
        help_text=(
            "Set at emission time. The customer-facing timeline "
            "endpoint filters `customer_visible=True`."
        ),
    )
    metadata = models.JSONField(
        default=dict,
        blank=True,
        help_text=(
            "Provider-side context (e.g. {'override_reason': ...}). "
            "Stripped from the customer-facing serializer entirely."
        ),
    )

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["created_at"]
        indexes = [models.Index(fields=["proposal", "created_at"])]

    def __str__(self):
        return f"{self.proposal_id}: {self.event_type}"


# ---------------------------------------------------------------------------
# M1 B6 — Extra Work message thread.
# ---------------------------------------------------------------------------
class ExtraWorkMessageType(models.TextChoices):
    """M1 B6 — three-channel EW message taxonomy. Mirrors
    `tickets.TicketMessageType` MINUS the two staff tiers (STAFF_OPERATIONAL /
    STAFF_COMPLETION): staff have NO Extra Work scope and never see or post an
    EW message. Read-visibility (SA = Super Admin, MGMT = Company Admin /
    Building Manager, CUST = customer-side):

      * PUBLIC_REPLY      — customer <-> management conversation (SA+MGMT+CUST).
      * INTERNAL_NOTE     — provider-management-internal (SA+MGMT). NOT CUST.
      * CUSTOMER_INTERNAL — the customer side's OWN internal note (SA forensic
                            + CUST). NOT MGMT. The mirror of INTERNAL_NOTE.

    Posting (enforced in `extra_work.message_permissions`): PUBLIC_REPLY =
    CUST+MGMT+SA; INTERNAL_NOTE = MGMT+SA; CUSTOMER_INTERNAL = CUST. Staff
    never.
    """

    PUBLIC_REPLY = "PUBLIC_REPLY", "Public Reply"
    INTERNAL_NOTE = "INTERNAL_NOTE", "Internal Note (provider-internal)"
    CUSTOMER_INTERNAL = "CUSTOMER_INTERNAL", "Customer Internal Note"


class ExtraWorkMessageVisibility(models.TextChoices):
    """Visibility mode orthogonal to `message_type` (parallels
    `tickets.TicketMessageVisibility`). NORMAL = visible to the full tier
    audience; RESTRICTED = visible only to author + `directed_to`."""

    NORMAL = "NORMAL", "Normal"
    RESTRICTED = "RESTRICTED", "Restricted"


class ExtraWorkMessage(models.Model):
    """M1 B6 — one message on an Extra Work request thread.

    Mirrors `tickets.TicketMessage` MINUS the staff dimension, attachments,
    and the `is_hidden` moderation flag (EW has no staff scope and no
    moderation surface). Text only. Read-visibility + posting are enforced
    server-side by `extra_work.message_permissions`; the in-app fan-out reuses
    the B1 `Notification` + its `extra_work` FK.
    """

    extra_work = models.ForeignKey(
        "extra_work.ExtraWorkRequest",
        on_delete=models.CASCADE,
        related_name="messages",
    )
    # Mirror TicketMessage.author — SET_NULL so deleting the author never
    # destroys the thread row.
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="extra_work_messages",
    )
    message_type = models.CharField(
        max_length=32,
        choices=ExtraWorkMessageType.choices,
        default=ExtraWorkMessageType.PUBLIC_REPLY,
    )
    visibility_mode = models.CharField(
        max_length=16,
        choices=ExtraWorkMessageVisibility.choices,
        default=ExtraWorkMessageVisibility.NORMAL,
        db_index=True,
    )
    directed_to = models.ManyToManyField(
        settings.AUTH_USER_MODEL,
        blank=True,
        related_name="directed_extra_work_messages",
    )
    message = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]
        indexes = [models.Index(fields=["extra_work", "created_at"])]

    def __str__(self):
        return f"{self.extra_work_id}: {self.message_type}"


class ExtraWorkAssignmentRole(models.TextChoices):
    """Which hat a person wears on a request.

    Deliberately NOT the same thing as `User.role`. A BUILDING_MANAGER
    may be assigned as a WORKER on a small job, and a STAFF member is
    never a MANAGER here — the assignment role says what they are doing
    on THIS request, and the endpoint checks the account role separately.
    """

    WORKER = "WORKER", "Worker"
    MANAGER = "MANAGER", "Manager"


class ExtraWorkAssignment(models.Model):
    """
    Sprint 157 §2 — who is doing an Extra Work request.

    `ExtraWorkRequest` had NO people-assignment of any kind before this:
    no field, no through-model. `tickets.TicketStaffAssignment` is the
    equivalent for tickets and this mirrors its SHAPE — a thin link row
    with the role gate and the scoping enforced above it — while
    importing nothing from `tickets`. The two modules are separate and
    stay separate; sharing a model would couple an extra-work change to
    the ticket state machine.

    What this deliberately does NOT copy from `TicketStaffAssignment`:
    its dated operational slots (Sprint 14E's scheduled_start_at /
    time_window_label / per-slot completion evidence). Extra work has no
    slot concept, and inventing one here would be building a scheduling
    subsystem nobody asked for.

    `unique_together (extra_work_request, user, role)` — the same person
    may be BOTH a worker and a manager on one request, which is why
    `role` is in the key. Assigning somebody twice in the same role is a
    no-op rather than an error; the bulk endpoint counts it as
    `already_assigned`.

    `user` is PROTECT: an assignment is a record of who was put on a job,
    and deleting the account should not silently erase it. The request
    side is CASCADE — if the request itself is gone there is nothing to
    be assigned to.
    """

    extra_work_request = models.ForeignKey(
        ExtraWorkRequest,
        on_delete=models.CASCADE,
        related_name="assignments",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="extra_work_assignments",
    )
    role = models.CharField(
        max_length=16,
        choices=ExtraWorkAssignmentRole.choices,
        default=ExtraWorkAssignmentRole.WORKER,
    )
    assigned_at = models.DateTimeField(auto_now_add=True)
    assigned_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="extra_work_assignments_made",
    )

    class Meta:
        unique_together = [("extra_work_request", "user", "role")]
        ordering = ["role", "id"]
        indexes = [
            models.Index(fields=["extra_work_request", "role"]),
            # The "what am I assigned to" query, from the person's side.
            models.Index(fields=["user", "role"]),
        ]

    def __str__(self):
        return f"{self.extra_work_request_id}: {self.user_id} ({self.role})"


class ExtraWorkPlannedHours(models.Model):
    """
    W2-D — the budget, distributed. One row per person on the job.

    `ExtraWorkRequest.budget_hours` is the planned total; this is how
    that total is spread across the people who will do the work. The two
    are held apart on purpose: a budget nobody has distributed yet is a
    real and normal state, and a total derived from the rows could never
    express "we have eight hours for this and have not decided who does
    what".

    WHY THIS IS ITS OWN MODEL IN THIS APP, and not somewhere else:

      * not on `tickets` — an extra work is planned before, and
        independently of, the tickets it spawns, and one plan can span
        several tickets;
      * not in `timesheets` — that module has a deliberate no-money rule
        and a different lifecycle (entered, saved, approved). These are
        PLANNED hours: what we said the job would take, written once,
        before anyone works. Actual hours live there and must keep
        living there, or "planned vs actual" becomes one number
        comparing itself.

    THE PERSON, NOT THE ASSIGNMENT ROW. The FK is to the user, and the
    write path requires that user to be assigned to this request at the
    time of writing. Un-assigning them afterwards does NOT delete this
    row, and the read surface reports it with `is_assigned: false`
    rather than dropping it.

    That is a deliberate answer to a live defect in the reference
    system, recorded in `docs/reference/osius-reference-system/`
    §4.4: over there the hours grid is built from the worker assignment
    list and hours are matched onto it, so hours belonging to a removed
    worker VANISH FROM THE SCREEN BUT STAY IN EVERY TOTAL. The screen
    and the total then disagree and nobody can see why. Here the row
    stays visible, stays counted, and says that the person is no longer
    on the job — which is a thing an operator can act on.

    `hours` has no upper bound and no cap against the parent's budget.
    Overrun is a WARNING, never a block: in the reference system a
    complete hard-cap function (`validateTotalHours()`) exists and is
    never called, with the comment `// Hours validation removed per user
    request` in the model's boot. Somebody built the block and the
    business had it removed. We warn (see `extra_work.planning`).

    Zero is legal and is not the same as no row at all: a person on the
    crew with no hours budgeted yet is a real plan, and deleting their
    row to say so would lose the fact that they are on it.
    """

    extra_work_request = models.ForeignKey(
        ExtraWorkRequest,
        on_delete=models.CASCADE,
        related_name="planned_hours",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="extra_work_planned_hours",
    )
    hours = models.DecimalField(
        max_digits=8,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0"))],
        help_text=(
            "Planned hours for this person on this job. A planning "
            "number: it reaches no price anywhere."
        ),
    )
    set_at = models.DateTimeField(auto_now=True)
    set_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="extra_work_planned_hours_set",
    )

    class Meta:
        unique_together = [("extra_work_request", "user")]
        ordering = ["id"]
        indexes = [
            models.Index(fields=["extra_work_request"]),
        ]
        verbose_name_plural = "extra work planned hours"

    def __str__(self):
        return f"{self.extra_work_request_id}: {self.user_id} = {self.hours}h"
