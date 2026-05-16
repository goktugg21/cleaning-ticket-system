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
from django.core.validators import MinValueValidator
from django.db import models


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
    Sprint 26B MVP statuses — customer-pricing loop only.

    Operational-execution statuses (ASSIGNED / IN_PROGRESS /
    WAITING_MANAGER_REVIEW / WAITING_CUSTOMER_APPROVAL / COMPLETED)
    are deferred to a follow-up sprint and are not added here so
    the state machine stays small and obvious.
    """

    REQUESTED = "REQUESTED", "Requested"
    UNDER_REVIEW = "UNDER_REVIEW", "Under review"
    PRICING_PROPOSED = "PRICING_PROPOSED", "Pricing proposed"
    CUSTOMER_APPROVED = "CUSTOMER_APPROVED", "Customer approved"
    CUSTOMER_REJECTED = "CUSTOMER_REJECTED", "Customer rejected"
    CANCELLED = "CANCELLED", "Cancelled"


class ExtraWorkPricingUnitType(models.TextChoices):
    HOURS = "HOURS", "Hours"
    SQUARE_METERS = "SQUARE_METERS", "Square meters"
    FIXED = "FIXED", "Fixed"
    ITEM = "ITEM", "Item"
    OTHER = "OTHER", "Other"


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
    """

    category = models.ForeignKey(
        ServiceCategory,
        on_delete=models.PROTECT,
        related_name="services",
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
            "before a line can skip the proposal phase."
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
            models.UniqueConstraint(
                fields=["category", "name"],
                name="uniq_service_name_per_category",
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
