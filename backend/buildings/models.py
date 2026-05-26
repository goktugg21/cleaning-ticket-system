from django.conf import settings
from django.db import models


class Building(models.Model):
    company = models.ForeignKey(
        "companies.Company",
        on_delete=models.CASCADE,
        related_name="buildings",
    )

    name = models.CharField(max_length=255)
    address = models.CharField(max_length=500, blank=True)
    city = models.CharField(max_length=120, blank=True)
    country = models.CharField(max_length=120, blank=True)
    postal_code = models.CharField(max_length=32, blank=True)

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
