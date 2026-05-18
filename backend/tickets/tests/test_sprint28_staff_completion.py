"""
Sprint 28 Batch 11 — STAFF completion routing.

A STAFF user marking their work done now drives a real workflow
transition. Where the ticket lands depends on a per-(staff, building)
flag on `BuildingStaffVisibility.staff_completion_routes_to_customer`:

  * False (default) — the ticket lands in the new
    `WAITING_MANAGER_REVIEW` interstitial. A BM accepts forward to
    `WAITING_CUSTOMER_APPROVAL` or rejects back to `IN_PROGRESS` (with
    a required rejection note).
  * True — the ticket goes directly to `WAITING_CUSTOMER_APPROVAL`,
    skipping manager review. The BSV row alone is the configuration
    surface; no new `osius.*` key.

What this file locks:

  * The new TicketStatus value and the four ALLOWED_TRANSITIONS rows
    that wire the routing.
  * Default-route + configured-route happy paths, including the
    `manager_review_at` / `sent_for_approval_at` timestamps.
  * The completion-evidence rule extends to the new STAFF route (no
    note + no visible attachment -> 400 code
    `completion_evidence_required`).
  * Mismatch between target and configured routing -> 400 code
    `staff_completion_route_mismatch`.
  * STAFF without a `TicketStaffAssignment` row -> 400 code
    `forbidden_transition`.
  * H-5 stays locked: STAFF cannot drive customer-decision transitions
    (`WAITING_CUSTOMER_APPROVAL -> APPROVED/REJECTED`).
  * BM accept / BM reject paths.
  * Rejection-note enforcement at the serializer AND state-machine
    layer (programmatic callers can't sneak around).
  * The new read-only `/api/tickets/<id>/staff-completion-route/`
    endpoint used by the frontend completion modal.
"""
from __future__ import annotations

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from rest_framework import status
from rest_framework.test import APIClient

from accounts.models import StaffProfile, UserRole
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
from tickets.models import (
    Ticket,
    TicketAttachment,
    TicketStaffAssignment,
    TicketStatus,
    TicketStatusHistory,
)
from tickets.state_machine import (
    ALLOWED_TRANSITIONS,
    TransitionError,
    apply_transition,
)


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


def _seed_basics():
    """
    Provider company + one building + one customer + one BM. Returned
    as a dict so individual tests can pick what they need.
    """
    company = Company.objects.create(name="Provider Co", slug="provider-co")
    building = Building.objects.create(company=company, name="B1")
    customer = Customer.objects.create(
        company=company, name="Cust A", building=building
    )
    CustomerBuildingMembership.objects.create(
        customer=customer, building=building
    )
    manager = _mk("mgr@example.com", UserRole.BUILDING_MANAGER)
    BuildingManagerAssignment.objects.create(user=manager, building=building)
    return {
        "company": company,
        "building": building,
        "customer": customer,
        "manager": manager,
    }


def _mk_in_progress_ticket(*, company, building, customer, created_by, assigned_to=None):
    """A ticket already in IN_PROGRESS so STAFF can complete it."""
    ticket = Ticket.objects.create(
        company=company,
        building=building,
        customer=customer,
        created_by=created_by,
        assigned_to=assigned_to,
        title="Work item",
        description="x",
        status=TicketStatus.IN_PROGRESS,
    )
    return ticket


# ===========================================================================
# 1. Structural tests — TicketStatus value + ALLOWED_TRANSITIONS shape.
# ===========================================================================


class StaffCompletionTransitionStructuralTests(TestCase):
    def test_waiting_manager_review_in_status_values(self):
        self.assertIn("WAITING_MANAGER_REVIEW", TicketStatus.values)

    def test_in_progress_to_waiting_manager_review_in_allowed_transitions(self):
        key = (TicketStatus.IN_PROGRESS, TicketStatus.WAITING_MANAGER_REVIEW)
        self.assertIn(key, ALLOWED_TRANSITIONS)
        scopes = ALLOWED_TRANSITIONS[key]
        self.assertIn(UserRole.STAFF, scopes)

    def test_in_progress_to_waiting_customer_approval_includes_staff(self):
        key = (
            TicketStatus.IN_PROGRESS,
            TicketStatus.WAITING_CUSTOMER_APPROVAL,
        )
        self.assertIn(key, ALLOWED_TRANSITIONS)
        self.assertIn(UserRole.STAFF, ALLOWED_TRANSITIONS[key])

    def test_waiting_manager_review_to_waiting_customer_approval_in_allowed_transitions(self):
        key = (
            TicketStatus.WAITING_MANAGER_REVIEW,
            TicketStatus.WAITING_CUSTOMER_APPROVAL,
        )
        self.assertIn(key, ALLOWED_TRANSITIONS)
        scopes = ALLOWED_TRANSITIONS[key]
        # STAFF must NOT be able to forward to customer approval — H-5.
        self.assertNotIn(UserRole.STAFF, scopes)
        self.assertIn(UserRole.BUILDING_MANAGER, scopes)
        self.assertIn(UserRole.COMPANY_ADMIN, scopes)
        self.assertIn(UserRole.SUPER_ADMIN, scopes)

    def test_waiting_manager_review_to_in_progress_in_allowed_transitions(self):
        key = (TicketStatus.WAITING_MANAGER_REVIEW, TicketStatus.IN_PROGRESS)
        self.assertIn(key, ALLOWED_TRANSITIONS)
        scopes = ALLOWED_TRANSITIONS[key]
        self.assertNotIn(UserRole.STAFF, scopes)
        self.assertIn(UserRole.BUILDING_MANAGER, scopes)


# ===========================================================================
# 2. STAFF default route — IN_PROGRESS -> WAITING_MANAGER_REVIEW.
# ===========================================================================


class StaffDefaultRouteTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        basics = _seed_basics()
        cls.company = basics["company"]
        cls.building = basics["building"]
        cls.customer = basics["customer"]
        cls.manager = basics["manager"]
        cls.cust_user = _mk("cust@example.com", UserRole.CUSTOMER_USER)
        cls.staff = _mk("staff@example.com", UserRole.STAFF)
        StaffProfile.objects.create(user=cls.staff)
        BuildingStaffVisibility.objects.create(
            user=cls.staff, building=cls.building
        )

    def setUp(self):
        self.ticket = _mk_in_progress_ticket(
            company=self.company,
            building=self.building,
            customer=self.customer,
            created_by=self.cust_user,
            assigned_to=self.manager,
        )
        TicketStaffAssignment.objects.create(ticket=self.ticket, user=self.staff)
        self.client = APIClient()
        self.client.force_authenticate(user=self.staff)

    def test_staff_completes_with_note_routes_to_manager_review(self):
        response = self.client.post(
            f"/api/tickets/{self.ticket.id}/status/",
            {"to_status": "WAITING_MANAGER_REVIEW", "note": "Done, please review"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.content)
        self.ticket.refresh_from_db()
        self.assertEqual(self.ticket.status, TicketStatus.WAITING_MANAGER_REVIEW)
        self.assertIsNotNone(self.ticket.manager_review_at)
        # The status history row was written inside the transition's
        # atomic block.
        self.assertTrue(
            TicketStatusHistory.objects.filter(
                ticket=self.ticket,
                old_status=TicketStatus.IN_PROGRESS,
                new_status=TicketStatus.WAITING_MANAGER_REVIEW,
                changed_by=self.staff,
            ).exists()
        )


# ===========================================================================
# 3. STAFF configured route — IN_PROGRESS -> WAITING_CUSTOMER_APPROVAL.
# ===========================================================================


class StaffConfiguredRouteTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        basics = _seed_basics()
        cls.company = basics["company"]
        cls.building = basics["building"]
        cls.customer = basics["customer"]
        cls.manager = basics["manager"]
        cls.cust_user = _mk("cust@example.com", UserRole.CUSTOMER_USER)
        cls.staff = _mk("staff@example.com", UserRole.STAFF)
        StaffProfile.objects.create(user=cls.staff)
        BuildingStaffVisibility.objects.create(
            user=cls.staff,
            building=cls.building,
            staff_completion_routes_to_customer=True,
        )

    def setUp(self):
        self.ticket = _mk_in_progress_ticket(
            company=self.company,
            building=self.building,
            customer=self.customer,
            created_by=self.cust_user,
            assigned_to=self.manager,
        )
        TicketStaffAssignment.objects.create(ticket=self.ticket, user=self.staff)
        self.client = APIClient()
        self.client.force_authenticate(user=self.staff)

    def test_staff_completes_with_flag_true_routes_to_customer(self):
        response = self.client.post(
            f"/api/tickets/{self.ticket.id}/status/",
            {
                "to_status": "WAITING_CUSTOMER_APPROVAL",
                "note": "Done, customer please approve",
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.content)
        self.ticket.refresh_from_db()
        self.assertEqual(
            self.ticket.status, TicketStatus.WAITING_CUSTOMER_APPROVAL
        )
        self.assertIsNotNone(self.ticket.sent_for_approval_at)


# ===========================================================================
# 4. Completion-evidence rule extends to the new STAFF route.
# ===========================================================================


class StaffCompletionEvidenceTests(TestCase):
    """The Sprint 25C rule (note or visible attachment) applies to both
    STAFF completion routes."""

    @classmethod
    def setUpTestData(cls):
        basics = _seed_basics()
        cls.company = basics["company"]
        cls.building = basics["building"]
        cls.customer = basics["customer"]
        cls.manager = basics["manager"]
        cls.cust_user = _mk("cust@example.com", UserRole.CUSTOMER_USER)

        cls.staff_default = _mk("staff-d@example.com", UserRole.STAFF)
        StaffProfile.objects.create(user=cls.staff_default)
        BuildingStaffVisibility.objects.create(
            user=cls.staff_default, building=cls.building
        )

        cls.staff_configured = _mk("staff-c@example.com", UserRole.STAFF)
        StaffProfile.objects.create(user=cls.staff_configured)
        BuildingStaffVisibility.objects.create(
            user=cls.staff_configured,
            building=cls.building,
            staff_completion_routes_to_customer=True,
        )

    # --- helpers -------------------------------------------------------

    def _mk_ticket(self):
        ticket = _mk_in_progress_ticket(
            company=self.company,
            building=self.building,
            customer=self.customer,
            created_by=self.cust_user,
            assigned_to=self.manager,
        )
        TicketStaffAssignment.objects.create(
            ticket=ticket, user=self.staff_default
        )
        TicketStaffAssignment.objects.create(
            ticket=ticket, user=self.staff_configured
        )
        return ticket

    def _client_for(self, user):
        c = APIClient()
        c.force_authenticate(user=user)
        return c

    def _add_visible_attachment(self, ticket, uploader):
        TicketAttachment.objects.create(
            ticket=ticket,
            uploaded_by=uploader,
            file=SimpleUploadedFile("evidence.jpg", b"x", content_type="image/jpeg"),
            original_filename="evidence.jpg",
            mime_type="image/jpeg",
            file_size=1,
            is_hidden=False,
        )

    def _add_hidden_attachment(self, ticket, uploader):
        TicketAttachment.objects.create(
            ticket=ticket,
            uploaded_by=uploader,
            file=SimpleUploadedFile("hidden.jpg", b"x", content_type="image/jpeg"),
            original_filename="hidden.jpg",
            mime_type="image/jpeg",
            file_size=1,
            is_hidden=True,
        )

    # --- default route (-> WAITING_MANAGER_REVIEW) --------------------

    def test_no_note_no_attachment_default_route_400(self):
        ticket = self._mk_ticket()
        response = self._client_for(self.staff_default).post(
            f"/api/tickets/{ticket.id}/status/",
            {"to_status": "WAITING_MANAGER_REVIEW"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data.get("code"), "completion_evidence_required")
        ticket.refresh_from_db()
        self.assertEqual(ticket.status, TicketStatus.IN_PROGRESS)

    def test_note_only_default_route_200(self):
        ticket = self._mk_ticket()
        response = self._client_for(self.staff_default).post(
            f"/api/tickets/{ticket.id}/status/",
            {"to_status": "WAITING_MANAGER_REVIEW", "note": "done"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.content)

    def test_visible_attachment_only_default_route_200(self):
        ticket = self._mk_ticket()
        self._add_visible_attachment(ticket, self.staff_default)
        response = self._client_for(self.staff_default).post(
            f"/api/tickets/{ticket.id}/status/",
            {"to_status": "WAITING_MANAGER_REVIEW"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.content)

    def test_hidden_attachment_no_note_default_route_400(self):
        ticket = self._mk_ticket()
        self._add_hidden_attachment(ticket, self.staff_default)
        response = self._client_for(self.staff_default).post(
            f"/api/tickets/{ticket.id}/status/",
            {"to_status": "WAITING_MANAGER_REVIEW"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data.get("code"), "completion_evidence_required")

    # --- configured route (-> WAITING_CUSTOMER_APPROVAL) --------------

    def test_no_note_no_attachment_configured_route_400(self):
        ticket = self._mk_ticket()
        response = self._client_for(self.staff_configured).post(
            f"/api/tickets/{ticket.id}/status/",
            {"to_status": "WAITING_CUSTOMER_APPROVAL"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data.get("code"), "completion_evidence_required")

    def test_note_only_configured_route_200(self):
        ticket = self._mk_ticket()
        response = self._client_for(self.staff_configured).post(
            f"/api/tickets/{ticket.id}/status/",
            {"to_status": "WAITING_CUSTOMER_APPROVAL", "note": "done"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.content)

    def test_visible_attachment_only_configured_route_200(self):
        ticket = self._mk_ticket()
        self._add_visible_attachment(ticket, self.staff_configured)
        response = self._client_for(self.staff_configured).post(
            f"/api/tickets/{ticket.id}/status/",
            {"to_status": "WAITING_CUSTOMER_APPROVAL"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.content)

    def test_hidden_attachment_no_note_configured_route_400(self):
        ticket = self._mk_ticket()
        self._add_hidden_attachment(ticket, self.staff_configured)
        response = self._client_for(self.staff_configured).post(
            f"/api/tickets/{ticket.id}/status/",
            {"to_status": "WAITING_CUSTOMER_APPROVAL"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data.get("code"), "completion_evidence_required")


# ===========================================================================
# 5. Routing-flag mismatch.
# ===========================================================================


class StaffRouteMismatchTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        basics = _seed_basics()
        cls.company = basics["company"]
        cls.building = basics["building"]
        cls.customer = basics["customer"]
        cls.manager = basics["manager"]
        cls.cust_user = _mk("cust@example.com", UserRole.CUSTOMER_USER)

        cls.staff_default = _mk("staff-d@example.com", UserRole.STAFF)
        StaffProfile.objects.create(user=cls.staff_default)
        BuildingStaffVisibility.objects.create(
            user=cls.staff_default,
            building=cls.building,
            staff_completion_routes_to_customer=False,
        )

        cls.staff_configured = _mk("staff-c@example.com", UserRole.STAFF)
        StaffProfile.objects.create(user=cls.staff_configured)
        BuildingStaffVisibility.objects.create(
            user=cls.staff_configured,
            building=cls.building,
            staff_completion_routes_to_customer=True,
        )

    def _mk_ticket_for(self, staff):
        ticket = _mk_in_progress_ticket(
            company=self.company,
            building=self.building,
            customer=self.customer,
            created_by=self.cust_user,
            assigned_to=self.manager,
        )
        TicketStaffAssignment.objects.create(ticket=ticket, user=staff)
        return ticket

    def test_flag_false_but_post_customer_approval_400(self):
        ticket = self._mk_ticket_for(self.staff_default)
        client = APIClient()
        client.force_authenticate(user=self.staff_default)
        response = client.post(
            f"/api/tickets/{ticket.id}/status/",
            {"to_status": "WAITING_CUSTOMER_APPROVAL", "note": "done"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            response.data.get("code"), "staff_completion_route_mismatch"
        )
        ticket.refresh_from_db()
        self.assertEqual(ticket.status, TicketStatus.IN_PROGRESS)

    def test_flag_true_but_post_manager_review_400(self):
        ticket = self._mk_ticket_for(self.staff_configured)
        client = APIClient()
        client.force_authenticate(user=self.staff_configured)
        response = client.post(
            f"/api/tickets/{ticket.id}/status/",
            {"to_status": "WAITING_MANAGER_REVIEW", "note": "done"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            response.data.get("code"), "staff_completion_route_mismatch"
        )
        ticket.refresh_from_db()
        self.assertEqual(ticket.status, TicketStatus.IN_PROGRESS)


# ===========================================================================
# 6. STAFF without a TicketStaffAssignment cannot complete.
# ===========================================================================


class StaffNotAssignedTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        basics = _seed_basics()
        cls.company = basics["company"]
        cls.building = basics["building"]
        cls.customer = basics["customer"]
        cls.manager = basics["manager"]
        cls.cust_user = _mk("cust@example.com", UserRole.CUSTOMER_USER)
        cls.staff = _mk("staff@example.com", UserRole.STAFF)
        StaffProfile.objects.create(user=cls.staff)
        # BSV row so the STAFF user can SEE the ticket — but no
        # TicketStaffAssignment, so SCOPE_STAFF_ASSIGNED fails.
        BuildingStaffVisibility.objects.create(
            user=cls.staff, building=cls.building
        )

    def test_staff_without_ticket_assignment_400(self):
        ticket = _mk_in_progress_ticket(
            company=self.company,
            building=self.building,
            customer=self.customer,
            created_by=self.cust_user,
            assigned_to=self.manager,
        )
        client = APIClient()
        client.force_authenticate(user=self.staff)
        response = client.post(
            f"/api/tickets/{ticket.id}/status/",
            {"to_status": "WAITING_MANAGER_REVIEW", "note": "done"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data.get("code"), "forbidden_transition")
        ticket.refresh_from_db()
        self.assertEqual(ticket.status, TicketStatus.IN_PROGRESS)


# ===========================================================================
# 7. H-5: STAFF cannot drive customer-decision transitions.
# ===========================================================================


class StaffCannotApproveCustomerCompletionTests(TestCase):
    """H-5 invariant lock — STAFF must never drive
    `WAITING_CUSTOMER_APPROVAL -> APPROVED/REJECTED`, even when STAFF
    holds a TicketStaffAssignment for the ticket."""

    @classmethod
    def setUpTestData(cls):
        basics = _seed_basics()
        cls.company = basics["company"]
        cls.building = basics["building"]
        cls.customer = basics["customer"]
        cls.manager = basics["manager"]
        cls.cust_user = _mk("cust@example.com", UserRole.CUSTOMER_USER)
        cls.staff = _mk("staff@example.com", UserRole.STAFF)
        StaffProfile.objects.create(user=cls.staff)
        BuildingStaffVisibility.objects.create(
            user=cls.staff, building=cls.building
        )

    def _mk_pending_customer_ticket(self):
        ticket = Ticket.objects.create(
            company=self.company,
            building=self.building,
            customer=self.customer,
            created_by=self.cust_user,
            assigned_to=self.manager,
            title="To approve",
            description="x",
            status=TicketStatus.WAITING_CUSTOMER_APPROVAL,
        )
        TicketStaffAssignment.objects.create(ticket=ticket, user=self.staff)
        return ticket

    def test_staff_cannot_drive_waiting_customer_approval_to_approved(self):
        ticket = self._mk_pending_customer_ticket()
        before_history = TicketStatusHistory.objects.filter(ticket=ticket).count()
        client = APIClient()
        client.force_authenticate(user=self.staff)
        response = client.post(
            f"/api/tickets/{ticket.id}/status/",
            {"to_status": "APPROVED", "note": "looks good"},
            format="json",
        )
        # STAFF is in `is_staff_role`, so the view-layer customer-user
        # gate passes; the state-machine layer is the real gate and
        # returns forbidden_transition.
        self.assertIn(
            response.status_code,
            (status.HTTP_400_BAD_REQUEST, status.HTTP_403_FORBIDDEN),
        )
        ticket.refresh_from_db()
        self.assertEqual(
            ticket.status, TicketStatus.WAITING_CUSTOMER_APPROVAL
        )
        self.assertEqual(
            TicketStatusHistory.objects.filter(ticket=ticket).count(),
            before_history,
        )

    def test_staff_cannot_drive_waiting_customer_approval_to_rejected(self):
        ticket = self._mk_pending_customer_ticket()
        before_history = TicketStatusHistory.objects.filter(ticket=ticket).count()
        client = APIClient()
        client.force_authenticate(user=self.staff)
        response = client.post(
            f"/api/tickets/{ticket.id}/status/",
            {"to_status": "REJECTED", "note": "looks wrong"},
            format="json",
        )
        self.assertIn(
            response.status_code,
            (status.HTTP_400_BAD_REQUEST, status.HTTP_403_FORBIDDEN),
        )
        ticket.refresh_from_db()
        self.assertEqual(
            ticket.status, TicketStatus.WAITING_CUSTOMER_APPROVAL
        )
        self.assertEqual(
            TicketStatusHistory.objects.filter(ticket=ticket).count(),
            before_history,
        )


# ===========================================================================
# 8. BM accepts a STAFF completion.
# ===========================================================================


class BMAcceptsStaffCompletionTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        basics = _seed_basics()
        cls.company = basics["company"]
        cls.building = basics["building"]
        cls.customer = basics["customer"]
        cls.manager = basics["manager"]
        cls.cust_user = _mk("cust@example.com", UserRole.CUSTOMER_USER)
        cls.staff = _mk("staff@example.com", UserRole.STAFF)
        StaffProfile.objects.create(user=cls.staff)
        BuildingStaffVisibility.objects.create(
            user=cls.staff, building=cls.building
        )

    def setUp(self):
        self.ticket = Ticket.objects.create(
            company=self.company,
            building=self.building,
            customer=self.customer,
            created_by=self.cust_user,
            assigned_to=self.manager,
            title="Already at MR",
            description="x",
            status=TicketStatus.WAITING_MANAGER_REVIEW,
        )
        TicketStaffAssignment.objects.create(ticket=self.ticket, user=self.staff)

    def test_bm_accepts_routes_to_waiting_customer_approval(self):
        client = APIClient()
        client.force_authenticate(user=self.manager)
        response = client.post(
            f"/api/tickets/{self.ticket.id}/status/",
            {"to_status": "WAITING_CUSTOMER_APPROVAL", "note": "looks good"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.content)
        self.ticket.refresh_from_db()
        self.assertEqual(
            self.ticket.status, TicketStatus.WAITING_CUSTOMER_APPROVAL
        )
        self.assertIsNotNone(self.ticket.sent_for_approval_at)


# ===========================================================================
# 9. BM rejects a STAFF completion.
# ===========================================================================


class BMRejectsStaffCompletionTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        basics = _seed_basics()
        cls.company = basics["company"]
        cls.building = basics["building"]
        cls.customer = basics["customer"]
        cls.manager = basics["manager"]
        cls.cust_user = _mk("cust@example.com", UserRole.CUSTOMER_USER)
        cls.staff = _mk("staff@example.com", UserRole.STAFF)
        StaffProfile.objects.create(user=cls.staff)
        BuildingStaffVisibility.objects.create(
            user=cls.staff, building=cls.building
        )

    def setUp(self):
        self.ticket = Ticket.objects.create(
            company=self.company,
            building=self.building,
            customer=self.customer,
            created_by=self.cust_user,
            assigned_to=self.manager,
            title="Already at MR",
            description="x",
            status=TicketStatus.WAITING_MANAGER_REVIEW,
        )
        TicketStaffAssignment.objects.create(ticket=self.ticket, user=self.staff)

    def test_bm_rejects_with_note_routes_back_to_in_progress(self):
        client = APIClient()
        client.force_authenticate(user=self.manager)
        response = client.post(
            f"/api/tickets/{self.ticket.id}/status/",
            {"to_status": "IN_PROGRESS", "note": "redo step 3 please"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.content)
        self.ticket.refresh_from_db()
        self.assertEqual(self.ticket.status, TicketStatus.IN_PROGRESS)

    def test_bm_rejects_without_note_400_from_serializer(self):
        client = APIClient()
        client.force_authenticate(user=self.manager)
        response = client.post(
            f"/api/tickets/{self.ticket.id}/status/",
            {"to_status": "IN_PROGRESS"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        # Serializer-layer rejection: error attached to the `note` key.
        self.assertIn("note", response.data)
        self.ticket.refresh_from_db()
        self.assertEqual(self.ticket.status, TicketStatus.WAITING_MANAGER_REVIEW)

    def test_state_machine_rejection_note_required_on_programmatic_call(self):
        # Drive the state machine directly with no note — the
        # serializer is bypassed but the state-machine defence catches.
        with self.assertRaises(TransitionError) as ctx:
            apply_transition(
                ticket=self.ticket,
                user=self.manager,
                to_status=TicketStatus.IN_PROGRESS,
                note="",
            )
        self.assertEqual(ctx.exception.code, "rejection_note_required")
        self.ticket.refresh_from_db()
        self.assertEqual(self.ticket.status, TicketStatus.WAITING_MANAGER_REVIEW)


# ===========================================================================
# 10. Staff-completion-route endpoint.
# ===========================================================================


class StaffCompletionRouteEndpointTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        basics = _seed_basics()
        cls.company = basics["company"]
        cls.building = basics["building"]
        cls.customer = basics["customer"]
        cls.manager = basics["manager"]
        cls.cust_user = _mk("cust@example.com", UserRole.CUSTOMER_USER)
        cls.cust_membership = CustomerUserMembership.objects.create(
            user=cls.cust_user, customer=cls.customer
        )
        CustomerUserBuildingAccess.objects.create(
            membership=cls.cust_membership, building=cls.building
        )

        cls.staff_default = _mk("staff-d@example.com", UserRole.STAFF)
        StaffProfile.objects.create(user=cls.staff_default)
        BuildingStaffVisibility.objects.create(
            user=cls.staff_default, building=cls.building
        )

        cls.staff_configured = _mk("staff-c@example.com", UserRole.STAFF)
        StaffProfile.objects.create(user=cls.staff_configured)
        BuildingStaffVisibility.objects.create(
            user=cls.staff_configured,
            building=cls.building,
            staff_completion_routes_to_customer=True,
        )

        cls.super_admin = _mk(
            "super@example.com",
            UserRole.SUPER_ADMIN,
            is_staff=True,
            is_superuser=True,
        )

        # A completely separate company + STAFF — for the out-of-scope
        # provider negative case.
        cls.other_company = Company.objects.create(
            name="Other Co", slug="other-co"
        )
        cls.other_company_admin = _mk(
            "co-admin@other.example.com", UserRole.COMPANY_ADMIN
        )
        CompanyUserMembership.objects.create(
            user=cls.other_company_admin, company=cls.other_company
        )

    def setUp(self):
        self.ticket_default = _mk_in_progress_ticket(
            company=self.company,
            building=self.building,
            customer=self.customer,
            created_by=self.cust_user,
            assigned_to=self.manager,
        )
        TicketStaffAssignment.objects.create(
            ticket=self.ticket_default, user=self.staff_default
        )

        self.ticket_configured = _mk_in_progress_ticket(
            company=self.company,
            building=self.building,
            customer=self.customer,
            created_by=self.cust_user,
            assigned_to=self.manager,
        )
        TicketStaffAssignment.objects.create(
            ticket=self.ticket_configured, user=self.staff_configured
        )

    def _client(self, user):
        c = APIClient()
        c.force_authenticate(user=user)
        return c

    def _url(self, ticket):
        return f"/api/tickets/{ticket.id}/staff-completion-route/"

    def test_staff_assigned_in_progress_returns_manager_review(self):
        response = self._client(self.staff_default).get(self._url(self.ticket_default))
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.content)
        self.assertEqual(response.data, {"route": "manager_review"})

    def test_staff_assigned_in_progress_returns_customer_approval(self):
        response = self._client(self.staff_configured).get(
            self._url(self.ticket_configured)
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.content)
        self.assertEqual(response.data, {"route": "customer_approval"})

    def test_staff_not_assigned_returns_404(self):
        # staff_default is NOT on ticket_configured.
        response = self._client(self.staff_default).get(
            self._url(self.ticket_configured)
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_customer_user_returns_404(self):
        response = self._client(self.cust_user).get(self._url(self.ticket_default))
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_super_admin_without_staff_id_returns_manager_review(self):
        response = self._client(self.super_admin).get(
            self._url(self.ticket_default)
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.content)
        self.assertEqual(response.data, {"route": "manager_review"})

    def test_super_admin_with_staff_id_returns_correct_route(self):
        response = self._client(self.super_admin).get(
            self._url(self.ticket_configured)
            + f"?staff_id={self.staff_configured.id}"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.content)
        self.assertEqual(response.data, {"route": "customer_approval"})

        response2 = self._client(self.super_admin).get(
            self._url(self.ticket_default)
            + f"?staff_id={self.staff_default.id}"
        )
        self.assertEqual(response2.status_code, status.HTTP_200_OK)
        self.assertEqual(response2.data, {"route": "manager_review"})

    def test_out_of_scope_provider_returns_404(self):
        response = self._client(self.other_company_admin).get(
            self._url(self.ticket_default)
        )
        # Out-of-scope provider gets 404 from `get_object` (queryset
        # filter excludes the ticket entirely).
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
