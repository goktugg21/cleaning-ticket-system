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


def _two_places(value: Decimal) -> Decimal:
    """Quantize a Decimal to 2 places, the canonical money rounding
    used everywhere in the Extra Work domain."""
    return value.quantize(Decimal("0.01"))


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

    urgency = models.CharField(
        max_length=16,
        choices=ExtraWorkUrgency.choices,
        default=ExtraWorkUrgency.NORMAL,
    )
    preferred_date = models.DateField(null=True, blank=True)

    status = models.CharField(
        max_length=32,
        choices=ExtraWorkStatus.choices,
        default=ExtraWorkStatus.REQUESTED,
    )

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


class ServiceCategory(models.Model):
    """
    Sprint 28 Batch 5 — provider-side service catalog: top-level
    category groupings.

    Categories are global (provider-wide). They are the parent rows
    for `Service` entries that customers eventually pick from when
    composing an Extra Work cart. A category can be soft-deactivated
    by toggling `is_active=False`; deletion is blocked while any
    `Service` row still references it (`PROTECT` on the FK below).

    Distinct from `ExtraWorkCategory` (the legacy text-choices enum
    on `ExtraWorkRequest.category`): that enum classifies a single
    ad-hoc Extra Work request; this row drives the catalog of
    bookable services with their own per-customer pricing tables.
    """

    name = models.CharField(max_length=128, unique=True)
    description = models.TextField(blank=True, default="")
    is_active = models.BooleanField(default=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name", "id"]
        verbose_name = "service category"
        verbose_name_plural = "service categories"

    def __str__(self):
        return self.name


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
        # Stored totals always recomputed from the inputs.
        self.line_subtotal = _two_places(self.quantity * self.unit_price)
        self.line_vat = _two_places(
            self.line_subtotal * self.vat_pct / Decimal("100")
        )
        self.line_total = _two_places(self.line_subtotal + self.line_vat)
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
