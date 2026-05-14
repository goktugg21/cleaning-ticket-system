"""
Sprint 26A — regression safety net for the generic provider /
customer scope model.

These tests do NOT introduce new product behavior. They lock down
three existing-but-untested code paths that would silently break if
a future refactor reorders permission checks or relaxes a queryset
filter. The intended business model (per the Sprint 26A brief):

  * SUPER_ADMIN sees everything globally.
  * Provider COMPANY_ADMIN sees only their own provider company.
  * Provider BUILDING_MANAGER is scoped to assigned buildings.
  * Provider STAFF is scoped to direct ticket assignment OR
    BuildingStaffVisibility.
  * Customer-side users (User.role=CUSTOMER_USER) are scoped via
    CustomerUserBuildingAccess and never see provider-internal
    workflow (internal notes, hidden attachments, staff-assignment
    requests, direct staff-assignment admin data).

Coverage gaps explicitly addressed here (the other Sprint 26A
brief targets are already covered by existing tests in
test_sprint23a_foundation.py, test_seed_demo_data.py,
test_sprint24c_staff_cancel.py, test_sprint25a_direct_staff_assignment.py,
and test_sprint23c_access_role_editor.py):

  1. Cross-ticket attachment-id smuggling: a customer authorised
     for ticket A guesses an attachment-id belonging to ticket B
     and calls /api/tickets/<A>/attachments/<aid-of-B>/download/.
     The view's get_object_or_404(..., ticket=ticket) filter must
     reject this (404), not download B's file.

  2. Sprint 25C auth-order regression with a satisfying note:
     existing test_customer_user_blocked_by_auth_gate_not_evidence_gate
     POSTs WITHOUT a note, so it would still pass if a regression
     swapped the order of auth vs evidence (evidence would 400 on
     missing note before auth got to run). This test POSTs WITH a
     valid note so a regression in ordering surfaces immediately.

  3. Cross-building manager DELETE of direct staff assignment:
     test_cross_building_manager_cannot_add (Sprint 25A) covers
     POST. The DELETE endpoint shares _gate_actor but is not
     independently regression-locked. A future refactor that
     accidentally widens DELETE's queryset would leak.
"""

from __future__ import annotations

import tempfile

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
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
)
from tickets.state_machine import apply_transition


User = get_user_model()
PASSWORD = "StrongerTestPassword123!"


# Random uploads land under MEDIA_ROOT. Override to a tmpdir so the
# test suite runs cleanly on any host (mirrors the Sprint 25C
# completion-evidence test pattern).
_TMP_MEDIA = tempfile.mkdtemp(prefix="sprint26a-media-")


def _mk(email, role, **extra):
    return User.objects.create_user(
        email=email,
        password=PASSWORD,
        role=role,
        full_name=email.split("@")[0],
        **extra,
    )


# ===========================================================================
# Gap 1 — Cross-ticket attachment-id smuggling
# ===========================================================================
@override_settings(MEDIA_ROOT=_TMP_MEDIA)
class CrossTicketAttachmentIdSmugglingTests(TestCase):
    """
    A customer with legitimate access to ticket A must not be able
    to download an attachment that belongs to ticket B by composing
    a URL like /api/tickets/<A.id>/attachments/<B-attachment-id>/.

    The download view fetches the attachment via
        get_object_or_404(TicketAttachment, pk=aid, ticket=ticket)
    so a smuggled id should 404 even if both tickets are in the
    same company and the actor has full visibility on ticket A.
    """

    @classmethod
    def setUpTestData(cls):
        cls.company = Company.objects.create(name="Co A", slug="co-a")
        cls.building = Building.objects.create(
            company=cls.company, name="B1"
        )
        cls.customer = Customer.objects.create(
            company=cls.company,
            name="Cust",
            building=cls.building,
        )
        CustomerBuildingMembership.objects.create(
            customer=cls.customer, building=cls.building
        )

        cls.cust_user = _mk("cust@example.com", UserRole.CUSTOMER_USER)
        mem = CustomerUserMembership.objects.create(
            customer=cls.customer, user=cls.cust_user
        )
        CustomerUserBuildingAccess.objects.create(
            membership=mem, building=cls.building
        )

        cls.admin = _mk("admin@example.com", UserRole.COMPANY_ADMIN)
        CompanyUserMembership.objects.create(
            user=cls.admin, company=cls.company
        )

        # Ticket A: customer is creator, so view_own scope grants
        # visibility.
        cls.ticket_a = Ticket.objects.create(
            company=cls.company,
            building=cls.building,
            customer=cls.customer,
            created_by=cls.cust_user,
            title="Customer ticket A",
            description="x",
        )

        # Ticket B: created by the admin (NOT visible to the
        # customer because they're not the creator and there's no
        # view_location/view_company permission on the access row).
        cls.ticket_b = Ticket.objects.create(
            company=cls.company,
            building=cls.building,
            customer=cls.customer,
            created_by=cls.admin,
            title="Admin ticket B",
            description="x",
        )

        # An attachment on ticket B uploaded by the admin.
        cls.attachment_b = TicketAttachment.objects.create(
            ticket=cls.ticket_b,
            uploaded_by=cls.admin,
            file=SimpleUploadedFile(
                "b.pdf", b"%PDF-1.4 fake", content_type="application/pdf"
            ),
            original_filename="b.pdf",
            mime_type="application/pdf",
            file_size=12,
            is_hidden=False,
        )

    def test_customer_cannot_download_attachment_b_via_ticket_a_url(self):
        # Sanity: customer can see ticket A.
        client = APIClient()
        client.force_authenticate(user=self.cust_user)
        ticket_a_detail = client.get(f"/api/tickets/{self.ticket_a.id}/")
        self.assertEqual(ticket_a_detail.status_code, 200)

        # And the customer canNOT see ticket B directly — proves
        # the scope shape we're relying on.
        ticket_b_detail = client.get(f"/api/tickets/{self.ticket_b.id}/")
        self.assertEqual(ticket_b_detail.status_code, 404)

        # The smuggle: ticket A's URL + ticket B's attachment id.
        url = (
            f"/api/tickets/{self.ticket_a.id}"
            f"/attachments/{self.attachment_b.id}/download/"
        )
        response = client.get(url)
        # The download view's get_object_or_404 filters on
        # (pk=aid, ticket=ticket_a) so attachment_b cannot bind.
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)


# ===========================================================================
# Gap 2 — Sprint 25C auth-order regression WITH a satisfying note
# ===========================================================================
class CompletionEvidenceAuthOrderTests(TestCase):
    """
    Sprint 25C added the IN_PROGRESS → WAITING_CUSTOMER_APPROVAL
    completion-evidence rule. A CUSTOMER_USER is also blocked from
    that transition by the view-layer role gate (only APPROVED /
    REJECTED are open to customers). The existing
    test_customer_user_blocked_by_auth_gate_not_evidence_gate in
    test_sprint25c_completion_evidence.py POSTs WITHOUT a note —
    so a regression that reordered the checks (evidence fires
    first → 400 missing-note) would still pass that test because
    the note is missing on the wire.

    This test POSTs WITH a non-empty note (which would satisfy the
    evidence rule). If the auth gate is still in front, the
    response must be 403 with `forbidden_transition`-shaped error,
    NOT 400 with `completion_evidence_required`. Either way the
    transition must NOT succeed.
    """

    @classmethod
    def setUpTestData(cls):
        cls.company = Company.objects.create(name="Co A", slug="co-a")
        cls.building = Building.objects.create(
            company=cls.company, name="B1"
        )
        cls.customer = Customer.objects.create(
            company=cls.company,
            name="Cust",
            building=cls.building,
        )
        CustomerBuildingMembership.objects.create(
            customer=cls.customer, building=cls.building
        )

        cls.cust_user = _mk("cust@example.com", UserRole.CUSTOMER_USER)
        mem = CustomerUserMembership.objects.create(
            customer=cls.customer, user=cls.cust_user
        )
        CustomerUserBuildingAccess.objects.create(
            membership=mem, building=cls.building
        )

        cls.manager = _mk("mgr@example.com", UserRole.BUILDING_MANAGER)
        BuildingManagerAssignment.objects.create(
            user=cls.manager, building=cls.building
        )

        ticket = Ticket.objects.create(
            company=cls.company,
            building=cls.building,
            customer=cls.customer,
            created_by=cls.cust_user,
            title="T",
            description="x",
        )
        # Move to IN_PROGRESS via the state machine so the evidence
        # gate is reachable.
        cls.ticket = apply_transition(
            ticket, cls.manager, TicketStatus.IN_PROGRESS
        )

    def test_customer_user_with_satisfying_note_still_blocked(self):
        client = APIClient()
        client.force_authenticate(user=self.cust_user)
        response = client.post(
            f"/api/tickets/{self.ticket.id}/status/",
            {
                "to_status": TicketStatus.WAITING_CUSTOMER_APPROVAL,
                # The note alone WOULD satisfy the Sprint 25C
                # evidence rule if it ran. Auth must fire first.
                "note": "I am finished — please mark for approval.",
            },
            format="json",
        )
        # Transition must not succeed.
        self.assertNotEqual(
            response.status_code,
            status.HTTP_200_OK,
            "CUSTOMER_USER must not be able to drive IN_PROGRESS -> "
            "WAITING_CUSTOMER_APPROVAL even with a note that would "
            "otherwise satisfy the Sprint 25C evidence rule.",
        )
        # The view's pre-serializer gate raises PermissionDenied
        # for non-staff customers attempting non-{APPROVED,REJECTED}
        # transitions, which DRF maps to 403.
        self.assertEqual(
            response.status_code,
            status.HTTP_403_FORBIDDEN,
            f"Auth gate must fire BEFORE evidence gate; got "
            f"{response.status_code}: {response.content!r}",
        )
        # Critically: the error must NOT be the evidence code,
        # because the auth gate runs first.
        body = response.json() if response.content else {}
        code = body.get("code") if isinstance(body, dict) else None
        if isinstance(code, list):
            code = code[0] if code else None
        self.assertNotEqual(
            code,
            "completion_evidence_required",
            "Evidence gate fired before auth gate — ordering "
            "regression. Auth must always run first.",
        )

        # And the ticket status must remain unchanged.
        self.ticket.refresh_from_db()
        self.assertEqual(self.ticket.status, TicketStatus.IN_PROGRESS)


# ===========================================================================
# Gap 3 — Cross-building manager DELETE of direct staff assignment
# ===========================================================================
class CrossBuildingManagerDeleteTests(TestCase):
    """
    Sprint 25A's test_cross_building_manager_cannot_add covers POST
    (a BUILDING_MANAGER assigned to one building tries to ADD a
    staff member to a ticket in a DIFFERENT building of the same
    company). The DELETE endpoint shares the same _gate_actor but
    has no independent regression test. If a future refactor
    diverges the two paths, an out-of-scope manager could remove
    legitimate assignments without being caught.
    """

    @classmethod
    def setUpTestData(cls):
        cls.company = Company.objects.create(name="Co A", slug="co-a")
        cls.building_a = Building.objects.create(
            company=cls.company, name="Building A1"
        )
        cls.building_a2 = Building.objects.create(
            company=cls.company, name="Building A2"
        )
        cls.customer = Customer.objects.create(
            company=cls.company,
            name="Customer A",
            building=cls.building_a,
        )
        CustomerBuildingMembership.objects.create(
            customer=cls.customer, building=cls.building_a
        )

        # Manager assigned ONLY to building_a2 — must not reach
        # tickets in building_a.
        cls.manager_a2 = _mk("mgr-a2@example.com", UserRole.BUILDING_MANAGER)
        BuildingManagerAssignment.objects.create(
            user=cls.manager_a2, building=cls.building_a2
        )

        # An admin pre-creates a legitimate assignment on a
        # building_a ticket so there is something for the
        # out-of-scope manager to attempt to DELETE.
        cls.admin = _mk("admin@example.com", UserRole.COMPANY_ADMIN)
        CompanyUserMembership.objects.create(
            user=cls.admin, company=cls.company
        )

        cls.staff = _mk("staff@example.com", UserRole.STAFF)
        StaffProfile.objects.create(user=cls.staff)
        BuildingStaffVisibility.objects.create(
            user=cls.staff, building=cls.building_a
        )

        cls.ticket_a = Ticket.objects.create(
            company=cls.company,
            building=cls.building_a,
            customer=cls.customer,
            created_by=cls.admin,
            title="Ticket on building A",
            description="x",
        )

        cls.assignment = TicketStaffAssignment.objects.create(
            ticket=cls.ticket_a,
            user=cls.staff,
            assigned_by=cls.admin,
        )

    def test_cross_building_manager_cannot_delete(self):
        client = APIClient()
        client.force_authenticate(user=self.manager_a2)
        response = client.delete(
            f"/api/tickets/{self.ticket_a.id}"
            f"/staff-assignments/{self.staff.id}/"
        )
        # scope_tickets_for hides ticket_a from manager_a2 so the
        # ticket resolution 404s. Either 404 or 403 is acceptable
        # — what matters is that the assignment row survives.
        self.assertIn(
            response.status_code,
            (status.HTTP_404_NOT_FOUND, status.HTTP_403_FORBIDDEN),
            f"Cross-building manager DELETE must not succeed; got "
            f"{response.status_code}: {response.content!r}",
        )
        self.assertTrue(
            TicketStaffAssignment.objects.filter(
                pk=self.assignment.pk
            ).exists(),
            "Cross-building manager managed to DELETE an assignment "
            "outside their assigned building — scope leak.",
        )
