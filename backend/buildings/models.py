from django.conf import settings
from django.db import models
from django.db.models.functions import Lower, Trim


class BuildingType(models.Model):
    """
    Sprint 178 §1 — a per-provider-company catalog of building kinds.

    The owner's own example is the reason this exists, and it is worth
    quoting because it sets the requirement precisely:

        Ramazan may want one building to be of type "health building"
        even though no other building uses it — but it should still
        appear in the filters.

    So: no enum, no fixed list, no deployment to add a type. A company
    types the name it wants, one building carries it, and it appears in
    the buildings-list filter from that moment. That last clause is the
    whole point — a catalog whose values do not reach the filters is a
    dropdown, not a taxonomy.

    Deliberately the `HourType` shape, field for field, because that
    shape is settled: company FK under PROTECT, a `name` that is NOT
    `unique=True`, `is_active` for archiving, `sort_order` for picker
    order, and the case/whitespace-insensitive uniqueness expressed as
    the expression constraint below.

    The constraint is created WITH the table, so there is never a window
    in which the column exists without it — the thing `ServiceCategory`
    and `ManagedUnit` had to be retrofitted with.

    NO `standard_slot`, unlike `HourType` and `WorkType`. Those two have
    recognised standard kinds worth naming in the reader's language; a
    building type is bespoke by nature, which is exactly what the owner's
    example says. Inventing a standard set here would be inventing
    product content nobody asked for.

    Archiving keeps the type on every building that already carries it
    and removes it from the picker for new ones. `Building.building_type`
    is SET_NULL rather than PROTECT: a building outlives its
    classification, and refusing to delete a type because one building
    was once tagged with it would make the catalog unmanageable.
    """

    company = models.ForeignKey(
        "companies.Company",
        on_delete=models.PROTECT,
        related_name="building_types",
        help_text=(
            "Provider company that owns this building type. PROTECT "
            "mirrors HourType.company: a Company cannot be hard-deleted "
            "while it still owns building types."
        ),
    )
    # NOT `unique=True`: uniqueness is per-company and
    # case/whitespace-insensitive, expressed as the constraint below.
    name = models.CharField(
        max_length=128,
        help_text='Operator-facing name, e.g. "Zorggebouw", "Kantoor".',
    )
    is_active = models.BooleanField(
        default=True,
        help_text=(
            "Archived types stay on the buildings that carry them but "
            "are not offerable for new ones."
        ),
    )
    sort_order = models.PositiveIntegerField(
        default=0,
        help_text="Ascending display order in the pickers; ties break on name.",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["sort_order", "name", "id"]
        verbose_name = "building type"
        verbose_name_plural = "building types"
        constraints = [
            # Trim() first so leading/trailing whitespace cannot bypass a
            # Lower()-only dedupe, Lower() for case — the HourType shape.
            models.UniqueConstraint(
                Lower(Trim("name")),
                "company",
                name="uniq_building_type_name_per_company_ci",
            ),
        ]

    def __str__(self):
        return self.name


class Building(models.Model):
    company = models.ForeignKey(
        "companies.Company",
        on_delete=models.CASCADE,
        related_name="buildings",
    )

    name = models.CharField(max_length=255)
    # Sprint 178 §1 — the building's kind, from the per-company catalog
    # above. Optional: every existing building predates the catalog and
    # none of them is going to be classified by a migration guessing.
    #
    # SET_NULL, not PROTECT: a building outlives its classification, and
    # a type that can never be deleted because one building was once
    # tagged with it makes the catalog unmanageable. Losing the tag is
    # recoverable; an undeletable catalog row is not.
    building_type = models.ForeignKey(
        "buildings.BuildingType",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="buildings",
        help_text="Optional classification from this company's own catalog.",
    )
    address = models.CharField(max_length=500, blank=True)
    city = models.CharField(max_length=120, blank=True)
    country = models.CharField(max_length=120, blank=True)
    postal_code = models.CharField(max_length=32, blank=True)

    # Sprint 172 §5 — the reference report's "Kostenplaats" pair. In
    # that system the cost centre IS the building, so the NAME column is
    # `Building.name` (already here) and only the CODE was missing.
    cost_centre_code = models.CharField(
        max_length=32,
        blank=True,
        default="",
        help_text=(
            "The accounting code for this building as a cost centre. "
            "Free text: it is the customer's own coding scheme."
        ),
    )
    # The reference's "Ordernr.". Put on the BUILDING rather than on the
    # contract because the reference prints one per report ROW, and a
    # row is (week, worker, building, hour type) — it varies with the
    # building, not with the contract, and a building can be under more
    # than one contract over time.
    order_number = models.CharField(
        max_length=64,
        blank=True,
        default="",
        help_text=(
            "The customer's order or work-order number for this "
            "location, printed on the hour report."
        ),
    )
    is_active = models.BooleanField(default=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]
        unique_together = [("company", "name")]

    def __str__(self):
        return self.name


class BuildingManagerAssignment(models.Model):
    building = models.ForeignKey(
        Building,
        on_delete=models.CASCADE,
        related_name="manager_assignments",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="building_assignments",
    )

    assigned_at = models.DateTimeField(auto_now_add=True)

    # B6 — per-(BM, building) override map for BM-revocable osius.* keys.
    #
    # The two B6 keys
    # `osius.building_manager.override_customer_decision` and
    # `osius.building_manager.prepare_extra_work_proposal` resolve True
    # by default for every BM assigned to this building. Setting
    # `permission_overrides[<key>] = False` on this row narrows that
    # default to False — used to selectively revoke a single BM's
    # customer-decision override or proposal-preparation authority
    # without removing the building assignment itself. Only `False`
    # values have semantic effect (a `True` value or a missing key
    # both resolve to the role default).
    #
    # The resolver
    # `accounts.permissions_v2.user_has_osius_permission` is the
    # single read site. The PATCH write surface
    # (`buildings.views_memberships.BuildingManagerAssignmentUpdateView`)
    # validates the allow-list — only the two B6 keys are writable
    # through it, so other osius.* keys cannot leak in via the
    # override map. A dedicated audit handler emits one AuditLog row
    # per change with the before/after diff.
    permission_overrides = models.JSONField(
        default=dict,
        blank=True,
        help_text=(
            "B6 — per-(BM, building) override map for the two BM-"
            "revocable osius.* keys "
            "(`osius.building_manager.override_customer_decision`, "
            "`osius.building_manager.prepare_extra_work_proposal`). "
            "Setting a key to False narrows the BM's default for "
            "this building. Only Super Admin and Provider Company "
            "Admin may edit this map."
        ),
    )

    class Meta:
        unique_together = [("building", "user")]

    def __str__(self):
        return f"{self.user} → {self.building}"


class BuildingStaffVisibility(models.Model):
    """
    Sprint 23A — grants a STAFF user read visibility on every
    ticket / work item in a building.

    Sprint 28 Batch 10 — per-row visibility level. The row now carries
    a `visibility_level` enum with three steps:

      - ASSIGNED_ONLY: the STAFF user is *recognised* at this building
        (e.g. for direct-assignment eligibility via
        `_validate_target_staff`) but visibility on the building's
        tickets stays narrow — they see only the tickets they're
        explicitly listed on via `TicketStaffAssignment`. The H-4
        floor (always sees their own assigned tickets) is preserved by
        the `_assigned=True` branch in `scope_tickets_for`.
      - BUILDING_READ (default; preserves pre-Batch-10 behaviour): the
        STAFF user sees every ticket in the building, in addition to
        any TicketStaffAssignment-bound tickets elsewhere.
      - BUILDING_READ_AND_ASSIGN: BUILDING_READ plus the ability to
        call `POST /api/tickets/<id>/assign/` for tickets at this
        building. This is a per-row admin-style grant; the multi-staff
        endpoint at `/api/tickets/<id>/staff-assignments/` stays
        admin-only (`views_staff_assignments.py::_gate_actor`
        explicitly rejects STAFF).

    The independent `can_request_assignment` flag continues to gate
    self-driven `StaffAssignmentRequest` POSTs for unassigned tickets
    in this building.

    Sprint 28 Batch 11 — per-staff-per-building completion-routing flag
    `staff_completion_routes_to_customer`. False (default) routes a
    STAFF completion through manager review (the WAITING_MANAGER_REVIEW
    interstitial); True routes it directly to WAITING_CUSTOMER_APPROVAL
    and skips manager review. The flag is consulted by
    `tickets.state_machine.apply_transition` whenever STAFF drives
    `IN_PROGRESS -> {WAITING_MANAGER_REVIEW, WAITING_CUSTOMER_APPROVAL}`;
    a mismatch between the target and the configured destination raises
    `TransitionError(code="staff_completion_route_mismatch")`. Provider
    operators (SUPER_ADMIN / COMPANY_ADMIN / BUILDING_MANAGER) driving
    the same transition on-behalf bypass the gate — the flag is a
    STAFF-only routing policy.
    """

    class VisibilityLevel(models.TextChoices):
        ASSIGNED_ONLY = "ASSIGNED_ONLY", "Assigned only"
        BUILDING_READ = "BUILDING_READ", "Building read"
        BUILDING_READ_AND_ASSIGN = (
            "BUILDING_READ_AND_ASSIGN",
            "Building read and assign",
        )

    building = models.ForeignKey(
        Building,
        on_delete=models.CASCADE,
        related_name="staff_visibility",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="building_visibility",
    )
    can_request_assignment = models.BooleanField(default=True)
    # Default `BUILDING_READ` preserves the pre-Sprint-28-Batch-10
    # behaviour — existing rows are backfilled by the migration default,
    # and every Sprint 23-28 test that does
    # `BuildingStaffVisibility.objects.create(user, building)` continues
    # to grant building-wide read access.
    visibility_level = models.CharField(
        max_length=32,
        choices=VisibilityLevel.choices,
        default=VisibilityLevel.BUILDING_READ,
    )
    staff_completion_routes_to_customer = models.BooleanField(
        default=False,
        help_text=(
            "Sprint 28 Batch 11 — per-staff-per-building routing flag. "
            "False (default): STAFF completion goes to manager review "
            "(WAITING_MANAGER_REVIEW); BM accepts → WAITING_CUSTOMER_APPROVAL "
            "or rejects → IN_PROGRESS. True: STAFF completion goes directly "
            "to WAITING_CUSTOMER_APPROVAL (skips manager review)."
        ),
    )

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [("building", "user")]

    def __str__(self):
        return f"{self.user} 👁 {self.building}"


class BuildingCostShare(models.Model):
    """
    Sprint 185 E §2 — WHO OWES WHAT on a building several customers share.

    A building with several tenants is the ordinary case in this
    business, and until now the customer-to-building link table held
    three columns — customer, building, created-at — with no weight
    anywhere in the system. The arithmetic lived in somebody's head, and
    the invoice it produced could not be checked against anything.

    The owner's decision, and it is the reason this is not a report: the
    percentages ACTUALLY SPLIT THE INVOICE. Work on a shared building is
    billed to each customer in its share.

    ## Why the shares live here and not on `CustomerBuildingMembership`

    A share is a property OF THE BUILDING — "how is this building's cost
    divided" — and it is meaningless one row at a time: a single share
    is only correct in the context of the other shares that make it up
    to 100. The membership row answers a different question ("does this
    customer operate here"), it is written by a different screen, and it
    is legitimately created and removed without anyone thinking about
    money. Hanging a money weight off it would mean every membership
    edit silently became a billing edit.

    ## The invariant, and where it is enforced

    **The shares of a building sum to exactly 100.** That cannot be
    expressed as a database constraint — it is a condition over a SET of
    rows, and no `CheckConstraint` spans rows — so it is enforced at the
    write path, which is a whole-set replace (`PUT
    /api/buildings/<id>/cost-shares/`). One row at a time could never be
    valid: going from two shares to three has to pass through a state
    that does not sum to 100, so a per-row endpoint would have to accept
    invalid states and hope somebody finished the job.

    **A building with NO shares behaves exactly as it always has.** That
    is the safety property this whole item rests on: absence means "not
    shared", never "shared 0%", so not one existing invoice changes.

    `customer` is PROTECT: a customer that still holds a share of a
    building cannot be hard-deleted, because removing it would leave the
    remaining shares summing to less than 100 — every other tenant's
    bill would silently change. Clearing the share first is a deliberate
    act, and it is the one that should be recorded.

    `building` is CASCADE: the shares describe the building and have no
    meaning without it.
    """

    building = models.ForeignKey(
        Building,
        on_delete=models.CASCADE,
        related_name="cost_shares",
        help_text="The shared building whose cost this row divides.",
    )
    customer = models.ForeignKey(
        "customers.Customer",
        on_delete=models.PROTECT,
        related_name="building_cost_shares",
        help_text=(
            "The customer carrying this share. PROTECT: removing a "
            "share-holder would silently change every other tenant's "
            "bill, so the share must be cleared deliberately first."
        ),
    )
    share_pct = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        help_text=(
            "This customer's percentage of the building's cost, 0.01 to "
            "100.00. The shares of one building sum to exactly 100, "
            "enforced at the write path (a sum is a condition over rows, "
            "which no database constraint can express)."
        ),
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-share_pct", "customer_id"]
        verbose_name = "building cost share"
        verbose_name_plural = "building cost shares"
        constraints = [
            models.UniqueConstraint(
                fields=["building", "customer"],
                name="uniq_cost_share_per_building_customer",
            ),
            # A single share is a percentage. The SUM is the write path's
            # job; this is the part a constraint can hold, and it stops a
            # negative or absurd row reaching the allocator.
            models.CheckConstraint(
                condition=models.Q(share_pct__gt=0)
                & models.Q(share_pct__lte=100),
                name="cost_share_pct_between_0_and_100",
            ),
        ]

    def __str__(self):
        return f"{self.customer} {self.share_pct}% of {self.building}"
