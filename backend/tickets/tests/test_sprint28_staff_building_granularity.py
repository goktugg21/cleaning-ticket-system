"""
Sprint 28 Batch 10 — STAFF per-building visibility granularity.

The `BuildingStaffVisibility` row now carries a per-row
`visibility_level` enum with three steps:

  - ASSIGNED_ONLY:       recognise the STAFF user at the building (for
                         direct-assignment eligibility) but do NOT
                         widen ticket visibility beyond their explicit
                         `TicketStaffAssignment` rows. (H-4 floor
                         preserved.)
  - BUILDING_READ:       default. STAFF user sees every ticket in the
                         building. CANNOT call POST
                         `/api/tickets/<id>/assign/` (403).
  - BUILDING_READ_AND_ASSIGN:
                         BUILDING_READ plus the ability to call POST
                         `/api/tickets/<id>/assign/` to set
                         `ticket.assigned_to` to a building manager.

Boundaries this file locks:
  * Default behaviour is unchanged — every BSV row created without an
    explicit `visibility_level=` falls back to `BUILDING_READ`.
  * The B3 (BUILDING_READ_AND_ASSIGN) grant is scoped per building.
    A B3 row in building X does NOT grant assign rights in building Y.
  * Cross-company isolation holds at every level — no STAFF user can
    see / assign tickets in a building outside their company.
  * The multi-staff endpoint at
    `/api/tickets/<id>/staff-assignments/` remains admin-only (PM Q5)
    even for a STAFF user with BUILDING_READ_AND_ASSIGN — the per-row
    B3 grant maps only to the single-target `assigned_to` field on
    Ticket, never to the M:N TicketStaffAssignment surface.
  * `_validate_target_staff` still accepts ASSIGNED_ONLY rows as a
    valid direct-assignment target (the BSV row is the recognition;
    `visibility_level` is the per-row READ/ASSIGN flag).
  * H-4 floor: STAFF assigned to a ticket via `TicketStaffAssignment`
    ALWAYS sees that ticket, regardless of BSV presence or level.
"""
from __future__ import annotations

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from accounts.models import StaffProfile, UserRole
from accounts.scoping import scope_tickets_for
from audit.models import AuditAction, AuditLog
from buildings.models import (
    Building,
    BuildingManagerAssignment,
    BuildingStaffVisibility,
)
from companies.models import Company, CompanyUserMembership
from customers.models import (
    Customer,
    CustomerBuildingMembership,
    CustomerUserBuildingAccess,
    CustomerUserMembership,
)
from tickets.models import Ticket, TicketStaffAssignment


User = get_user_model()
PASSWORD = "StrongerTestPassword123!"


def _mk(email, role, **extra):
    return User.objects.create_user(
        email=email,
        password=PASSWORD,
        role=role,
        full_name=email.split("@")[0],
        **extra,
    )


class StaffVisibilityLevelDefaultTests(TestCase):
    """
    The migration default + model default must keep pre-Batch-10
    behaviour intact: today's BSV-row-bearing STAFF user sees every
    ticket in their building exactly as they did before the field
    landed.
    """

    @classmethod
    def setUpTestData(cls):
        cls.company = Company.objects.create(name="Co A", slug="co-a")
        cls.building = Building.objects.create(
            company=cls.company, name="B1"
        )
        cls.customer = Customer.objects.create(
            company=cls.company, name="Cust A", building=cls.building
        )
        CustomerBuildingMembership.objects.create(
            customer=cls.customer, building=cls.building
        )
        cls.cust_user = _mk("cust@example.com", UserRole.CUSTOMER_USER)
        cls.staff = _mk("staff@example.com", UserRole.STAFF)
        StaffProfile.objects.create(user=cls.staff)
        cls.ticket = Ticket.objects.create(
            company=cls.company,
            building=cls.building,
            customer=cls.customer,
            created_by=cls.cust_user,
            title="Default-level ticket",
            description="x",
        )

    def test_default_is_building_read(self):
        bsv = BuildingStaffVisibility.objects.create(
            user=self.staff, building=self.building
        )
        self.assertEqual(
            bsv.visibility_level,
            BuildingStaffVisibility.VisibilityLevel.BUILDING_READ,
            "Default `visibility_level` must be BUILDING_READ — the "
            "migration backfill + every existing test depends on this.",
        )

    def test_default_grant_sees_all_building_tickets(self):
        BuildingStaffVisibility.objects.create(
            user=self.staff, building=self.building
        )
        # With the default level (BUILDING_READ) the STAFF user sees the
        # ticket exactly as they did pre-Batch-10.
        self.assertIn(
            self.ticket.id,
            set(scope_tickets_for(self.staff).values_list("id", flat=True)),
        )


# ===========================================================================
# B1 ASSIGNED_ONLY scope behaviour
# ===========================================================================


class StaffB1AssignedOnlyTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.company = Company.objects.create(name="Co A", slug="co-a")
        cls.building = Building.objects.create(
            company=cls.company, name="B1"
        )
        cls.customer = Customer.objects.create(
            company=cls.company, name="Cust A", building=cls.building
        )
        CustomerBuildingMembership.objects.create(
            customer=cls.customer, building=cls.building
        )
        cls.cust_user = _mk("cust@example.com", UserRole.CUSTOMER_USER)
        cls.staff = _mk("staff@example.com", UserRole.STAFF)
        StaffProfile.objects.create(user=cls.staff)
        BuildingStaffVisibility.objects.create(
            user=cls.staff,
            building=cls.building,
            visibility_level=BuildingStaffVisibility.VisibilityLevel.ASSIGNED_ONLY,
        )
        cls.other_staff = _mk("other-staff@example.com", UserRole.STAFF)
        StaffProfile.objects.create(user=cls.other_staff)
        BuildingStaffVisibility.objects.create(
            user=cls.other_staff,
            building=cls.building,
            visibility_level=BuildingStaffVisibility.VisibilityLevel.ASSIGNED_ONLY,
        )

        cls.assigned_ticket = Ticket.objects.create(
            company=cls.company,
            building=cls.building,
            customer=cls.customer,
            created_by=cls.cust_user,
            title="Mine",
            description="x",
        )
        TicketStaffAssignment.objects.create(
            ticket=cls.assigned_ticket, user=cls.staff
        )
        cls.other_assigned_ticket = Ticket.objects.create(
            company=cls.company,
            building=cls.building,
            customer=cls.customer,
            created_by=cls.cust_user,
            title="Theirs",
            description="x",
        )
        TicketStaffAssignment.objects.create(
            ticket=cls.other_assigned_ticket, user=cls.other_staff
        )
        cls.unassigned_ticket = Ticket.objects.create(
            company=cls.company,
            building=cls.building,
            customer=cls.customer,
            created_by=cls.cust_user,
            title="Nobody's",
            description="x",
        )

    def _client(self):
        c = APIClient()
        c.force_authenticate(user=self.staff)
        return c

    def test_assigned_ticket_visible(self):
        visible = set(scope_tickets_for(self.staff).values_list("id", flat=True))
        self.assertIn(self.assigned_ticket.id, visible)

    def test_other_staff_ticket_404(self):
        # Different STAFF assigned at the same building — must NOT be
        # visible under ASSIGNED_ONLY (this is the Batch 10 narrowing).
        c = self._client()
        response = c.get(f"/api/tickets/{self.other_assigned_ticket.id}/")
        self.assertEqual(response.status_code, 404)
        visible = set(scope_tickets_for(self.staff).values_list("id", flat=True))
        self.assertNotIn(self.other_assigned_ticket.id, visible)

    def test_unassigned_ticket_404(self):
        c = self._client()
        response = c.get(f"/api/tickets/{self.unassigned_ticket.id}/")
        self.assertEqual(response.status_code, 404)
        visible = set(scope_tickets_for(self.staff).values_list("id", flat=True))
        self.assertNotIn(self.unassigned_ticket.id, visible)


# ===========================================================================
# B2 BUILDING_READ scope + assign-gate behaviour
# ===========================================================================


class StaffB2BuildingReadTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.company = Company.objects.create(name="Co A", slug="co-a")
        cls.building = Building.objects.create(
            company=cls.company, name="B1"
        )
        cls.customer = Customer.objects.create(
            company=cls.company, name="Cust A", building=cls.building
        )
        CustomerBuildingMembership.objects.create(
            customer=cls.customer, building=cls.building
        )
        cls.cust_user = _mk("cust@example.com", UserRole.CUSTOMER_USER)

        cls.manager = _mk("mgr@example.com", UserRole.BUILDING_MANAGER)
        BuildingManagerAssignment.objects.create(
            user=cls.manager, building=cls.building
        )
        cls.other_manager = _mk("mgr2@example.com", UserRole.BUILDING_MANAGER)
        BuildingManagerAssignment.objects.create(
            user=cls.other_manager, building=cls.building
        )

        cls.staff = _mk("staff@example.com", UserRole.STAFF)
        StaffProfile.objects.create(user=cls.staff)
        BuildingStaffVisibility.objects.create(
            user=cls.staff,
            building=cls.building,
            visibility_level=BuildingStaffVisibility.VisibilityLevel.BUILDING_READ,
        )

        cls.ticket = Ticket.objects.create(
            company=cls.company,
            building=cls.building,
            customer=cls.customer,
            created_by=cls.cust_user,
            assigned_to=cls.manager,
            title="B2 ticket",
            description="x",
        )
        cls.unassigned_ticket = Ticket.objects.create(
            company=cls.company,
            building=cls.building,
            customer=cls.customer,
            created_by=cls.cust_user,
            title="B2 unassigned",
            description="x",
        )

    def _client(self):
        c = APIClient()
        c.force_authenticate(user=self.staff)
        return c

    def test_sees_all_tickets_in_building(self):
        visible = set(scope_tickets_for(self.staff).values_list("id", flat=True))
        self.assertIn(self.ticket.id, visible)
        self.assertIn(self.unassigned_ticket.id, visible)

    def test_cannot_assign_ticket(self):
        c = self._client()
        response = c.post(
            f"/api/tickets/{self.ticket.id}/assign/",
            {"assigned_to": self.other_manager.id},
            format="json",
        )
        self.assertEqual(response.status_code, 403)
        self.ticket.refresh_from_db()
        self.assertEqual(self.ticket.assigned_to_id, self.manager.id)


# ===========================================================================
# B3 BUILDING_READ_AND_ASSIGN scope + assign-gate behaviour
# ===========================================================================


class StaffB3BuildingReadAndAssignTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.company = Company.objects.create(name="Co A", slug="co-a")
        cls.building = Building.objects.create(
            company=cls.company, name="B1"
        )
        cls.customer = Customer.objects.create(
            company=cls.company, name="Cust A", building=cls.building
        )
        CustomerBuildingMembership.objects.create(
            customer=cls.customer, building=cls.building
        )
        cls.cust_user = _mk("cust@example.com", UserRole.CUSTOMER_USER)

        cls.manager = _mk("mgr@example.com", UserRole.BUILDING_MANAGER)
        BuildingManagerAssignment.objects.create(
            user=cls.manager, building=cls.building
        )
        cls.other_manager = _mk("mgr2@example.com", UserRole.BUILDING_MANAGER)
        BuildingManagerAssignment.objects.create(
            user=cls.other_manager, building=cls.building
        )

        cls.staff = _mk("staff@example.com", UserRole.STAFF)
        StaffProfile.objects.create(user=cls.staff)
        BuildingStaffVisibility.objects.create(
            user=cls.staff,
            building=cls.building,
            visibility_level=BuildingStaffVisibility.VisibilityLevel.BUILDING_READ_AND_ASSIGN,
        )

    def _build_ticket(self, **extra):
        defaults = dict(
            company=self.company,
            building=self.building,
            customer=self.customer,
            created_by=self.cust_user,
            assigned_to=self.manager,
            title="B3 ticket",
            description="x",
        )
        defaults.update(extra)
        return Ticket.objects.create(**defaults)

    def _client(self):
        c = APIClient()
        c.force_authenticate(user=self.staff)
        return c

    def test_sees_all_tickets_in_building(self):
        ticket = self._build_ticket(title="visible to B3")
        visible = set(scope_tickets_for(self.staff).values_list("id", flat=True))
        self.assertIn(ticket.id, visible)

    def test_can_assign_ticket_to_building_manager(self):
        ticket = self._build_ticket(title="reassign me")
        c = self._client()
        response = c.post(
            f"/api/tickets/{ticket.id}/assign/",
            {"assigned_to": self.other_manager.id},
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.content)
        ticket.refresh_from_db()
        self.assertEqual(ticket.assigned_to_id, self.other_manager.id)

    def test_assign_does_not_break_audit_pipeline(self):
        # The `Ticket` model is intentionally NOT registered for the
        # generic CRUD audit pipeline (see `audit/signals.py` — only
        # `TicketStaffAssignment` and `StaffAssignmentRequest` from
        # the tickets app are listed). The Sprint 28 Batch 10 widening
        # of the BM-assign gate for B3 STAFF must not break the
        # surrounding audit pipeline for related rows. This test pins
        # that a B3 STAFF-driven assignment:
        #   * succeeds end-to-end (200),
        #   * persists `assigned_to` on the row,
        #   * and does not introduce a spurious AuditLog row keyed at
        #     the Ticket (the BSV row's authorization is captured by
        #     its own `_BSV_TRACKED_FIELDS` audit; the workflow
        #     transition has its own history surface). The
        #     pre-existing audit contract for B3 STAFF actions
        #     therefore stays clean.
        ticket = self._build_ticket(title="audit me")
        before_ticket_rows = AuditLog.objects.filter(
            target_model="tickets.Ticket", target_id=ticket.id
        ).count()
        c = self._client()
        response = c.post(
            f"/api/tickets/{ticket.id}/assign/",
            {"assigned_to": self.other_manager.id},
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.content)
        ticket.refresh_from_db()
        self.assertEqual(ticket.assigned_to_id, self.other_manager.id)
        after_ticket_rows = AuditLog.objects.filter(
            target_model="tickets.Ticket", target_id=ticket.id
        ).count()
        # No spurious Ticket-keyed AuditLog row appeared — Ticket is
        # not registered for generic audit by design.
        self.assertEqual(after_ticket_rows, before_ticket_rows)


# ===========================================================================
# Cross-building isolation inside the same company
# ===========================================================================


class StaffCrossBuildingIsolationTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.company = Company.objects.create(name="Co A", slug="co-a")
        cls.building_x = Building.objects.create(
            company=cls.company, name="X"
        )
        cls.building_y = Building.objects.create(
            company=cls.company, name="Y"
        )
        cls.customer = Customer.objects.create(
            company=cls.company, name="Cust", building=cls.building_x
        )
        CustomerBuildingMembership.objects.create(
            customer=cls.customer, building=cls.building_x
        )
        CustomerBuildingMembership.objects.create(
            customer=cls.customer, building=cls.building_y
        )
        cls.cust_user = _mk("cust@example.com", UserRole.CUSTOMER_USER)

        cls.manager_x = _mk("mgr-x@example.com", UserRole.BUILDING_MANAGER)
        BuildingManagerAssignment.objects.create(
            user=cls.manager_x, building=cls.building_x
        )
        cls.manager_x2 = _mk("mgr-x2@example.com", UserRole.BUILDING_MANAGER)
        BuildingManagerAssignment.objects.create(
            user=cls.manager_x2, building=cls.building_x
        )
        cls.manager_y = _mk("mgr-y@example.com", UserRole.BUILDING_MANAGER)
        BuildingManagerAssignment.objects.create(
            user=cls.manager_y, building=cls.building_y
        )
        cls.manager_y2 = _mk("mgr-y2@example.com", UserRole.BUILDING_MANAGER)
        BuildingManagerAssignment.objects.create(
            user=cls.manager_y2, building=cls.building_y
        )

        cls.staff = _mk("staff@example.com", UserRole.STAFF)
        StaffProfile.objects.create(user=cls.staff)
        # B3 on X
        BuildingStaffVisibility.objects.create(
            user=cls.staff,
            building=cls.building_x,
            visibility_level=BuildingStaffVisibility.VisibilityLevel.BUILDING_READ_AND_ASSIGN,
        )
        # B1 on Y
        BuildingStaffVisibility.objects.create(
            user=cls.staff,
            building=cls.building_y,
            visibility_level=BuildingStaffVisibility.VisibilityLevel.ASSIGNED_ONLY,
        )

        cls.ticket_y = Ticket.objects.create(
            company=cls.company,
            building=cls.building_y,
            customer=cls.customer,
            created_by=cls.cust_user,
            assigned_to=cls.manager_y,
            title="Y assigned BM",
            description="x",
        )
        cls.ticket_y_assigned = Ticket.objects.create(
            company=cls.company,
            building=cls.building_y,
            customer=cls.customer,
            created_by=cls.cust_user,
            title="Y assigned to staff",
            description="x",
        )
        TicketStaffAssignment.objects.create(
            ticket=cls.ticket_y_assigned, user=cls.staff
        )
        cls.ticket_y_other = Ticket.objects.create(
            company=cls.company,
            building=cls.building_y,
            customer=cls.customer,
            created_by=cls.cust_user,
            title="Y unrelated",
            description="x",
        )

    def _client(self):
        c = APIClient()
        c.force_authenticate(user=self.staff)
        return c

    def test_cannot_assign_ticket_in_y(self):
        # Building Y has no B3 row — STAFF is B1 (ASSIGNED_ONLY) there.
        # The assign endpoint must 403 even though the staff user holds
        # B3 elsewhere (building X) in the same company.
        #
        # NB: The ticket itself must be reachable for the gate to fire,
        # so we use the staff-assigned ticket (ticket_y_assigned).
        c = self._client()
        response = c.post(
            f"/api/tickets/{self.ticket_y_assigned.id}/assign/",
            {"assigned_to": self.manager_y2.id},
            format="json",
        )
        self.assertEqual(response.status_code, 403)

    def test_visible_tickets_in_y_assigned_only(self):
        visible = set(scope_tickets_for(self.staff).values_list("id", flat=True))
        # Only the directly-assigned ticket in Y is visible; the other
        # two Y-tickets are hidden by the ASSIGNED_ONLY narrowing.
        self.assertIn(self.ticket_y_assigned.id, visible)
        self.assertNotIn(self.ticket_y.id, visible)
        self.assertNotIn(self.ticket_y_other.id, visible)


# ===========================================================================
# Cross-company isolation
# ===========================================================================


class StaffCrossCompanyIsolationTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.company_a = Company.objects.create(name="Co A", slug="co-a")
        cls.company_b = Company.objects.create(name="Co B", slug="co-b")
        cls.building_a = Building.objects.create(
            company=cls.company_a, name="A"
        )
        cls.building_b = Building.objects.create(
            company=cls.company_b, name="B"
        )
        cls.customer_a = Customer.objects.create(
            company=cls.company_a, name="Cust A", building=cls.building_a
        )
        cls.customer_b = Customer.objects.create(
            company=cls.company_b, name="Cust B", building=cls.building_b
        )
        CustomerBuildingMembership.objects.create(
            customer=cls.customer_a, building=cls.building_a
        )
        CustomerBuildingMembership.objects.create(
            customer=cls.customer_b, building=cls.building_b
        )
        cls.cust_a = _mk("cust-a@example.com", UserRole.CUSTOMER_USER)
        cls.cust_b = _mk("cust-b@example.com", UserRole.CUSTOMER_USER)

        cls.manager_b = _mk("mgr-b@example.com", UserRole.BUILDING_MANAGER)
        BuildingManagerAssignment.objects.create(
            user=cls.manager_b, building=cls.building_b
        )
        cls.manager_b2 = _mk("mgr-b2@example.com", UserRole.BUILDING_MANAGER)
        BuildingManagerAssignment.objects.create(
            user=cls.manager_b2, building=cls.building_b
        )

        # STAFF in Company A only, with B3 on A.
        cls.staff = _mk("staff@example.com", UserRole.STAFF)
        StaffProfile.objects.create(user=cls.staff)
        BuildingStaffVisibility.objects.create(
            user=cls.staff,
            building=cls.building_a,
            visibility_level=BuildingStaffVisibility.VisibilityLevel.BUILDING_READ_AND_ASSIGN,
        )

        cls.ticket_b = Ticket.objects.create(
            company=cls.company_b,
            building=cls.building_b,
            customer=cls.customer_b,
            created_by=cls.cust_b,
            assigned_to=cls.manager_b,
            title="Company B ticket",
            description="x",
        )

    def _client(self):
        c = APIClient()
        c.force_authenticate(user=self.staff)
        return c

    def test_company_b_tickets_404(self):
        c = self._client()
        response = c.get(f"/api/tickets/{self.ticket_b.id}/")
        self.assertEqual(response.status_code, 404)
        visible = set(scope_tickets_for(self.staff).values_list("id", flat=True))
        self.assertNotIn(self.ticket_b.id, visible)

    def test_cannot_assign_in_company_b(self):
        c = self._client()
        response = c.post(
            f"/api/tickets/{self.ticket_b.id}/assign/",
            {"assigned_to": self.manager_b2.id},
            format="json",
        )
        # Scope hides the ticket → 404 (object-level gate runs after
        # the queryset filter via `self.get_object()`).
        self.assertEqual(response.status_code, 404)
        self.ticket_b.refresh_from_db()
        self.assertEqual(self.ticket_b.assigned_to_id, self.manager_b.id)


# ===========================================================================
# `_validate_target_staff` — ASSIGNED_ONLY rows still recognise the staff
# as a valid direct-assignment target (admin POST /staff-assignments/).
# ===========================================================================


class StaffAssignmentTargetValidationUnchangedTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.company = Company.objects.create(name="Co A", slug="co-a")
        cls.building = Building.objects.create(
            company=cls.company, name="B1"
        )
        cls.customer = Customer.objects.create(
            company=cls.company, name="Cust", building=cls.building
        )
        CustomerBuildingMembership.objects.create(
            customer=cls.customer, building=cls.building
        )
        cls.admin = _mk("admin@example.com", UserRole.SUPER_ADMIN,
                        is_staff=True, is_superuser=True)
        cls.cust_user = _mk("cust@example.com", UserRole.CUSTOMER_USER)

        cls.staff = _mk("staff@example.com", UserRole.STAFF)
        StaffProfile.objects.create(user=cls.staff, is_active=True)
        # ASSIGNED_ONLY recognition — staff is "at" the building but
        # without building-wide read.
        BuildingStaffVisibility.objects.create(
            user=cls.staff,
            building=cls.building,
            visibility_level=BuildingStaffVisibility.VisibilityLevel.ASSIGNED_ONLY,
        )

        cls.ticket = Ticket.objects.create(
            company=cls.company,
            building=cls.building,
            customer=cls.customer,
            created_by=cls.cust_user,
            title="Target",
            description="x",
        )

    def test_assigned_only_staff_is_valid_target(self):
        # SUPER_ADMIN can attach an ASSIGNED_ONLY staff to a ticket —
        # the BSV row's mere existence is enough for the
        # `_validate_target_staff` gate; `visibility_level` is the
        # READ/ASSIGN flag, not the eligibility flag.
        c = APIClient()
        c.force_authenticate(user=self.admin)
        response = c.post(
            f"/api/tickets/{self.ticket.id}/staff-assignments/",
            {"user_id": self.staff.id},
            format="json",
        )
        self.assertIn(response.status_code, (200, 201), response.content)
        self.assertTrue(
            TicketStaffAssignment.objects.filter(
                ticket=self.ticket, user=self.staff
            ).exists()
        )


# ===========================================================================
# H-4 floor — STAFF assigned to a ticket ALWAYS sees that ticket
# regardless of BSV row presence or level.
# ===========================================================================


class StaffH4FloorTests(TestCase):
    """H-4 invariant lock — Sprint 28 Batch 10 dedicated coverage.

    The matrix doc (§3 row H-4) calls out this floor: STAFF always
    sees work assigned to them via `TicketStaffAssignment`, and the
    floor "cannot be removed" by any per-row toggle. Batch 10 makes
    that structural by leaving the `Q(_assigned=True)` branch in
    `scope_tickets_for` STAFF branch untouched while the BSV row
    contribution is narrowed by `visibility_level`.
    """

    @classmethod
    def setUpTestData(cls):
        cls.company = Company.objects.create(name="Co A", slug="co-a")
        cls.building = Building.objects.create(
            company=cls.company, name="B1"
        )
        cls.customer = Customer.objects.create(
            company=cls.company, name="Cust", building=cls.building
        )
        CustomerBuildingMembership.objects.create(
            customer=cls.customer, building=cls.building
        )
        cls.cust_user = _mk("cust@example.com", UserRole.CUSTOMER_USER)

        cls.staff_no_bsv = _mk("staff-no-bsv@example.com", UserRole.STAFF)
        StaffProfile.objects.create(user=cls.staff_no_bsv)
        cls.staff_b1 = _mk("staff-b1@example.com", UserRole.STAFF)
        StaffProfile.objects.create(user=cls.staff_b1)
        BuildingStaffVisibility.objects.create(
            user=cls.staff_b1,
            building=cls.building,
            visibility_level=BuildingStaffVisibility.VisibilityLevel.ASSIGNED_ONLY,
        )

        cls.ticket = Ticket.objects.create(
            company=cls.company,
            building=cls.building,
            customer=cls.customer,
            created_by=cls.cust_user,
            title="Assigned-to-staff ticket",
            description="x",
        )
        TicketStaffAssignment.objects.create(
            ticket=cls.ticket, user=cls.staff_no_bsv
        )
        TicketStaffAssignment.objects.create(
            ticket=cls.ticket, user=cls.staff_b1
        )

    def test_no_bsv_row_assigned_ticket_visible(self):
        visible = set(
            scope_tickets_for(self.staff_no_bsv).values_list("id", flat=True)
        )
        self.assertIn(self.ticket.id, visible)

    def test_assigned_only_bsv_assigned_ticket_visible(self):
        visible = set(
            scope_tickets_for(self.staff_b1).values_list("id", flat=True)
        )
        self.assertIn(self.ticket.id, visible)


# ===========================================================================
# The multi-staff endpoint stays admin-only — B3 is NOT a back-door into it.
# ===========================================================================


class StaffStaffAssignmentsEndpointUnchangedForStaffTests(TestCase):
    """B3 (BUILDING_READ_AND_ASSIGN) maps only to the single-target
    `assigned_to` field on Ticket via POST /api/tickets/<id>/assign/.

    The Sprint 25A multi-staff M:N endpoint at
    POST /api/tickets/<id>/staff-assignments/ remains admin-only via
    `views_staff_assignments.py::_gate_actor`. PM Q5 is explicit: do
    not widen `_gate_actor` for STAFF.
    """

    @classmethod
    def setUpTestData(cls):
        cls.company = Company.objects.create(name="Co A", slug="co-a")
        cls.building = Building.objects.create(
            company=cls.company, name="B1"
        )
        cls.customer = Customer.objects.create(
            company=cls.company, name="Cust", building=cls.building
        )
        CustomerBuildingMembership.objects.create(
            customer=cls.customer, building=cls.building
        )
        cls.cust_user = _mk("cust@example.com", UserRole.CUSTOMER_USER)
        cls.staff = _mk("staff@example.com", UserRole.STAFF)
        StaffProfile.objects.create(user=cls.staff)
        BuildingStaffVisibility.objects.create(
            user=cls.staff,
            building=cls.building,
            visibility_level=BuildingStaffVisibility.VisibilityLevel.BUILDING_READ_AND_ASSIGN,
        )
        cls.target_staff = _mk("target@example.com", UserRole.STAFF)
        StaffProfile.objects.create(user=cls.target_staff, is_active=True)
        BuildingStaffVisibility.objects.create(
            user=cls.target_staff,
            building=cls.building,
            visibility_level=BuildingStaffVisibility.VisibilityLevel.BUILDING_READ,
        )
        cls.ticket = Ticket.objects.create(
            company=cls.company,
            building=cls.building,
            customer=cls.customer,
            created_by=cls.cust_user,
            title="Multi-staff endpoint test",
            description="x",
        )

    def test_b3_staff_cannot_use_multi_staff_endpoint(self):
        c = APIClient()
        c.force_authenticate(user=self.staff)
        response = c.post(
            f"/api/tickets/{self.ticket.id}/staff-assignments/",
            {"user_id": self.target_staff.id},
            format="json",
        )
        # `_gate_actor` returns 403 for STAFF with an explicit message.
        self.assertEqual(response.status_code, 403)
        self.assertFalse(
            TicketStaffAssignment.objects.filter(
                ticket=self.ticket, user=self.target_staff
            ).exists()
        )
