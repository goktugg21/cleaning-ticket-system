"""
Sprint 23A — foundation tests for the new domain & permission model.

Maps 1:1 onto the 17 cases the sprint brief listed. Each test
isolates exactly one rule so a regression points at one root
cause.

The fixture builds three customer organisations and three
buildings:

  Building B1 ─┬─ Customer A (locations: B1, B2)
               └─ Customer C (location: B1 only) — second tenant
                              in the same building
  Building B2 ─┬─ Customer A (locations: B1, B2)
               └─ (nothing else)
  Building B3 ─── Customer A (location: B3 only)

This proves both:
  (a) one building can host multiple customer companies, and
  (b) one customer company can span multiple buildings.

Customer-A users get varying roles across buildings to exercise
the per-building `access_role` field; Customer-C users prove
cross-customer isolation in the same building.

OSIUS-side has three test users:
  - manager_b1  → BuildingManagerAssignment on B1
  - staff_visible_b1  → BuildingStaffVisibility on B1, can request
  - staff_no_visibility → just role=STAFF, no visibility row
"""
from __future__ import annotations

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from accounts.models import StaffProfile, UserRole
from accounts.permissions_v2 import user_has_osius_permission
from accounts.scoping import scope_tickets_for
from audit.models import AuditLog
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
from customers.permissions import access_has_permission
from tickets.models import (
    AssignmentRequestStatus,
    StaffAssignmentRequest,
    Ticket,
    TicketStaffAssignment,
)


User = get_user_model()
PASSWORD = "StrongerTestPassword123!"


class Sprint23AFoundationTests(TestCase):
    """All 17 brief-listed cases as one fixture, one test each."""

    @classmethod
    def setUpTestData(cls):
        cls.company = Company.objects.create(
            name="OSIUS Test Co", slug="osius-test"
        )

        # Three buildings.
        cls.b1 = Building.objects.create(company=cls.company, name="B1")
        cls.b2 = Building.objects.create(company=cls.company, name="B2")
        cls.b3 = Building.objects.create(company=cls.company, name="B3")

        # Two customer organisations.
        cls.customer_a = Customer.objects.create(
            company=cls.company, name="Customer A", building=None
        )
        cls.customer_c = Customer.objects.create(
            company=cls.company, name="Customer C", building=None
        )

        # Customer A spans B1, B2, B3. Customer C is only at B1.
        # This exercises "one customer in many buildings" AND
        # "one building hosting two customers" in the same fixture.
        for b in (cls.b1, cls.b2, cls.b3):
            CustomerBuildingMembership.objects.create(
                customer=cls.customer_a, building=b
            )
        CustomerBuildingMembership.objects.create(
            customer=cls.customer_c, building=cls.b1
        )

        # Customer-side users.
        cls.cust_user_a = _mk(
            "cust-user-a@example.com", UserRole.CUSTOMER_USER
        )
        cls.cust_user_a_loc_mgr = _mk(
            "cust-loc-mgr-a@example.com", UserRole.CUSTOMER_USER
        )
        cls.cust_user_a_company_admin = _mk(
            "cust-co-admin-a@example.com", UserRole.CUSTOMER_USER
        )
        cls.cust_user_c = _mk(
            "cust-user-c@example.com", UserRole.CUSTOMER_USER
        )

        # Customer A membership graph:
        #   cust_user_a            → CUSTOMER_USER on B1 only
        #   cust_user_a_loc_mgr    → LOCATION_MANAGER on B2 only
        #   cust_user_a_company_admin → COMPANY_ADMIN on B1 (any one
        #                              building entry is enough for
        #                              the company-wide visibility)
        mem_a_user = CustomerUserMembership.objects.create(
            customer=cls.customer_a, user=cls.cust_user_a
        )
        cls.access_a_user_b1 = CustomerUserBuildingAccess.objects.create(
            membership=mem_a_user, building=cls.b1
        )  # default access_role = CUSTOMER_USER

        mem_a_loc_mgr = CustomerUserMembership.objects.create(
            customer=cls.customer_a, user=cls.cust_user_a_loc_mgr
        )
        cls.access_a_loc_mgr_b2 = CustomerUserBuildingAccess.objects.create(
            membership=mem_a_loc_mgr,
            building=cls.b2,
            access_role=(
                CustomerUserBuildingAccess.AccessRole.CUSTOMER_LOCATION_MANAGER
            ),
        )

        mem_a_co_admin = CustomerUserMembership.objects.create(
            customer=cls.customer_a, user=cls.cust_user_a_company_admin
        )
        cls.access_a_co_admin_b1 = CustomerUserBuildingAccess.objects.create(
            membership=mem_a_co_admin,
            building=cls.b1,
            access_role=(
                CustomerUserBuildingAccess.AccessRole.CUSTOMER_COMPANY_ADMIN
            ),
        )

        mem_c_user = CustomerUserMembership.objects.create(
            customer=cls.customer_c, user=cls.cust_user_c
        )
        cls.access_c_user_b1 = CustomerUserBuildingAccess.objects.create(
            membership=mem_c_user, building=cls.b1
        )

        # OSIUS-side users.
        cls.manager_b1 = _mk("mgr-b1@example.com", UserRole.BUILDING_MANAGER)
        BuildingManagerAssignment.objects.create(
            user=cls.manager_b1, building=cls.b1
        )
        cls.manager_b3 = _mk("mgr-b3@example.com", UserRole.BUILDING_MANAGER)
        BuildingManagerAssignment.objects.create(
            user=cls.manager_b3, building=cls.b3
        )

        cls.staff_visible_b1 = _mk(
            "staff-visible-b1@example.com", UserRole.STAFF
        )
        StaffProfile.objects.create(user=cls.staff_visible_b1)
        BuildingStaffVisibility.objects.create(
            user=cls.staff_visible_b1, building=cls.b1
        )
        cls.staff_no_visibility = _mk(
            "staff-no-visibility@example.com", UserRole.STAFF
        )
        StaffProfile.objects.create(user=cls.staff_no_visibility)

        cls.super_admin = _mk(
            "super-23a@example.com",
            UserRole.SUPER_ADMIN,
            is_staff=True,
            is_superuser=True,
        )

        # Tickets — one per customer-building combination so each
        # scope rule has a row to find or NOT find.
        cls.t_a_b1 = Ticket.objects.create(
            company=cls.company,
            building=cls.b1,
            customer=cls.customer_a,
            created_by=cls.cust_user_a,
            title="Customer A @ B1",
            description="x",
        )
        cls.t_a_b2 = Ticket.objects.create(
            company=cls.company,
            building=cls.b2,
            customer=cls.customer_a,
            created_by=cls.cust_user_a_loc_mgr,
            title="Customer A @ B2",
            description="x",
        )
        cls.t_a_b3 = Ticket.objects.create(
            company=cls.company,
            building=cls.b3,
            customer=cls.customer_a,
            created_by=cls.cust_user_a_company_admin,
            title="Customer A @ B3",
            description="x",
        )
        cls.t_c_b1 = Ticket.objects.create(
            company=cls.company,
            building=cls.b1,
            customer=cls.customer_c,
            created_by=cls.cust_user_c,
            title="Customer C @ B1",
            description="x",
        )

    # ---- 1. Building can host multiple customer companies. ----

    def test_01_building_hosts_multiple_customer_companies(self):
        customers_at_b1 = set(
            CustomerBuildingMembership.objects.filter(
                building=self.b1
            ).values_list("customer_id", flat=True)
        )
        self.assertEqual(
            customers_at_b1, {self.customer_a.id, self.customer_c.id}
        )

    # ---- 2. One customer company can be linked to many buildings. ----

    def test_02_customer_company_spans_multiple_buildings(self):
        buildings_of_a = set(
            CustomerBuildingMembership.objects.filter(
                customer=self.customer_a
            ).values_list("building_id", flat=True)
        )
        self.assertEqual(buildings_of_a, {self.b1.id, self.b2.id, self.b3.id})

    # ---- 3. Customer A cannot see Customer C tickets in the same building. ----

    def test_03_customer_isolation_in_shared_building(self):
        scoped = scope_tickets_for(self.cust_user_a)
        self.assertIn(self.t_a_b1, scoped)
        self.assertNotIn(self.t_c_b1, scoped)
        # Reverse: customer C cannot see customer A's B1 ticket.
        scoped_c = scope_tickets_for(self.cust_user_c)
        self.assertIn(self.t_c_b1, scoped_c)
        self.assertNotIn(self.t_a_b1, scoped_c)

    # ---- 4. CUSTOMER_USER default sees own tickets (pair access). ----

    def test_04_customer_user_sees_own_pair(self):
        scoped = list(scope_tickets_for(self.cust_user_a))
        self.assertEqual([t.id for t in scoped], [self.t_a_b1.id])

    # ---- 5. CUSTOMER_LOCATION_MANAGER sees customer-company tickets only in assigned buildings. ----

    def test_05_location_manager_sees_only_assigned_buildings(self):
        scoped = scope_tickets_for(self.cust_user_a_loc_mgr)
        self.assertIn(self.t_a_b2, scoped)  # access on B2
        self.assertNotIn(self.t_a_b1, scoped)  # no access on B1
        self.assertNotIn(self.t_a_b3, scoped)  # no access on B3
        self.assertNotIn(self.t_c_b1, scoped)  # never see other customer

    # ---- 6. CUSTOMER_COMPANY_ADMIN sees all customer tickets across buildings. ----

    def test_06_company_admin_sees_all_customer_tickets(self):
        scoped = scope_tickets_for(self.cust_user_a_company_admin)
        self.assertIn(self.t_a_b1, scoped)
        self.assertIn(self.t_a_b2, scoped)
        self.assertIn(self.t_a_b3, scoped)
        self.assertNotIn(self.t_c_b1, scoped)  # other customer still blocked

    # ---- 7. OSIUS BUILDING_MANAGER sees tickets in assigned buildings. ----

    def test_07_osius_building_manager_sees_assigned_buildings(self):
        scoped = scope_tickets_for(self.manager_b1)
        self.assertIn(self.t_a_b1, scoped)
        self.assertIn(self.t_c_b1, scoped)  # second customer in same building
        self.assertNotIn(self.t_a_b2, scoped)
        self.assertNotIn(self.t_a_b3, scoped)

    # ---- 8. OSIUS STAFF sees their assigned tickets. ----

    def test_08_staff_sees_assigned_tickets(self):
        TicketStaffAssignment.objects.create(
            ticket=self.t_a_b2, user=self.staff_no_visibility
        )
        scoped = scope_tickets_for(self.staff_no_visibility)
        self.assertIn(self.t_a_b2, scoped)
        # No other ticket visible — no visibility row.
        self.assertNotIn(self.t_a_b1, scoped)

    # ---- 9. STAFF with building visibility sees visible building tickets. ----

    def test_09_staff_with_visibility_sees_building_tickets(self):
        scoped = scope_tickets_for(self.staff_visible_b1)
        self.assertIn(self.t_a_b1, scoped)
        self.assertIn(self.t_c_b1, scoped)
        # No visibility on B2/B3 → tickets there hidden.
        self.assertNotIn(self.t_a_b2, scoped)
        self.assertNotIn(self.t_a_b3, scoped)

    # ---- 10. STAFF without visibility cannot see unassigned building tickets. ----

    def test_10_staff_without_visibility_sees_nothing(self):
        scoped = scope_tickets_for(self.staff_no_visibility)
        self.assertEqual(list(scoped), [])

    # ---- 11. Staff can request assignment only for visible eligible work. ----

    def test_11_staff_can_request_for_visible_eligible(self):
        client = APIClient()
        client.force_authenticate(user=self.staff_visible_b1)
        # Visible building → request allowed.
        r = client.post(
            "/api/staff-assignment-requests/", {"ticket": self.t_a_b1.id}
        )
        self.assertEqual(r.status_code, 201, r.data)

        # Same ticket, different staff WITHOUT visibility → blocked.
        client.force_authenticate(user=self.staff_no_visibility)
        r2 = client.post(
            "/api/staff-assignment-requests/", {"ticket": self.t_a_b1.id}
        )
        self.assertEqual(r2.status_code, 403, r2.data)

    # ---- 12. Customer cannot see staff assignment requests. ----

    def test_12_customer_cannot_list_assignment_requests(self):
        StaffAssignmentRequest.objects.create(
            staff=self.staff_visible_b1, ticket=self.t_a_b1
        )
        client = APIClient()
        client.force_authenticate(user=self.cust_user_a)
        r = client.get("/api/staff-assignment-requests/")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data.get("count", 0), 0)
        # Also: direct detail on the request returns 404.
        existing = StaffAssignmentRequest.objects.first()
        r2 = client.get(f"/api/staff-assignment-requests/{existing.id}/")
        self.assertEqual(r2.status_code, 404)

    # ---- 13. Building Manager can approve only for their managed buildings. ----

    def test_13_manager_approves_only_managed_building_requests(self):
        # Request on B1 — manager_b1 can approve; manager_b3 cannot.
        req = StaffAssignmentRequest.objects.create(
            staff=self.staff_visible_b1, ticket=self.t_a_b1
        )
        client = APIClient()
        client.force_authenticate(user=self.manager_b3)
        r = client.post(f"/api/staff-assignment-requests/{req.id}/approve/")
        # manager_b3 is not in scope → queryset 404 (request invisible).
        self.assertEqual(r.status_code, 404)

        client.force_authenticate(user=self.manager_b1)
        r2 = client.post(f"/api/staff-assignment-requests/{req.id}/approve/")
        self.assertEqual(r2.status_code, 200, r2.data)
        req.refresh_from_db()
        self.assertEqual(req.status, AssignmentRequestStatus.APPROVED)
        # Approving creates the TicketStaffAssignment row.
        self.assertTrue(
            TicketStaffAssignment.objects.filter(
                ticket=self.t_a_b1, user=self.staff_visible_b1
            ).exists()
        )

    # ---- 14. SUPER_ADMIN can approve/reject anything. ----

    def test_14_super_admin_can_approve_any_request(self):
        req = StaffAssignmentRequest.objects.create(
            staff=self.staff_visible_b1, ticket=self.t_a_b3
        )
        client = APIClient()
        client.force_authenticate(user=self.super_admin)
        r = client.post(f"/api/staff-assignment-requests/{req.id}/reject/")
        self.assertEqual(r.status_code, 200, r.data)
        req.refresh_from_db()
        self.assertEqual(req.status, AssignmentRequestStatus.REJECTED)

    # ---- 15. Assigned staff contact visibility policy controls customer payload. ----

    def test_15_contact_visibility_policy_hides_staff_details(self):
        from tickets.serializers import TicketDetailSerializer

        # Assign a staff member with a phone.
        StaffProfile.objects.filter(user=self.staff_visible_b1).update(
            phone="+31 6 0123 4567"
        )
        TicketStaffAssignment.objects.create(
            ticket=self.t_a_b1, user=self.staff_visible_b1
        )

        # Customer A by default sees full record.
        request = _fake_request(self.cust_user_a)
        data = TicketDetailSerializer(
            self.t_a_b1, context={"request": request}
        ).data
        self.assertTrue(
            any(
                "email" in s and s.get("email") == self.staff_visible_b1.email
                for s in data["assigned_staff"]
            )
        )

        # Hide ALL three flags → anonymous label.
        Customer.objects.filter(pk=self.customer_a.pk).update(
            show_assigned_staff_name=False,
            show_assigned_staff_email=False,
            show_assigned_staff_phone=False,
        )
        self.t_a_b1.refresh_from_db()
        data2 = TicketDetailSerializer(
            self.t_a_b1, context={"request": request}
        ).data
        self.assertEqual(
            data2["assigned_staff"],
            [{"anonymous": True, "label_key": "tickets.assigned_team_anonymous"}],
        )

        # OSIUS-side viewer (manager) always sees full record
        # regardless of policy.
        mgr_request = _fake_request(self.manager_b1)
        data3 = TicketDetailSerializer(
            self.t_a_b1, context={"request": mgr_request}
        ).data
        self.assertTrue(
            any(
                "email" in s and s.get("email") == self.staff_visible_b1.email
                for s in data3["assigned_staff"]
            )
        )

    # ---- 16. Permission override grants / revokes specific capability. ----

    def test_16_permission_override_grant_and_revoke(self):
        # Default: CUSTOMER_USER role does NOT have approve_location.
        self.assertFalse(
            access_has_permission(
                self.access_a_user_b1, "customer.ticket.approve_location"
            )
        )
        # Override grants it.
        self.access_a_user_b1.permission_overrides = {
            "customer.ticket.approve_location": True
        }
        self.access_a_user_b1.save(update_fields=["permission_overrides"])
        self.assertTrue(
            access_has_permission(
                self.access_a_user_b1, "customer.ticket.approve_location"
            )
        )
        # Reverse: a LOCATION_MANAGER's default approve_own can be revoked.
        self.assertTrue(
            access_has_permission(
                self.access_a_loc_mgr_b2, "customer.ticket.approve_own"
            )
        )
        self.access_a_loc_mgr_b2.permission_overrides = {
            "customer.ticket.approve_own": False
        }
        self.access_a_loc_mgr_b2.save(update_fields=["permission_overrides"])
        self.assertFalse(
            access_has_permission(
                self.access_a_loc_mgr_b2, "customer.ticket.approve_own"
            )
        )
        # An inactive row resolves every permission to False.
        self.access_a_user_b1.is_active = False
        self.access_a_user_b1.save(update_fields=["is_active"])
        self.assertFalse(
            access_has_permission(
                self.access_a_user_b1, "customer.ticket.approve_location"
            )
        )
        self.assertFalse(
            access_has_permission(
                self.access_a_user_b1, "customer.ticket.view_own"
            )
        )

    # ---- 17. Audit log is created for new-model changes. ----

    def test_17_audit_logs_for_new_model_changes(self):
        # Clear out anything from setUpTestData (signals fired there too).
        AuditLog.objects.all().delete()

        # Create a StaffAssignmentRequest — should produce CREATE log.
        req = StaffAssignmentRequest.objects.create(
            staff=self.staff_visible_b1, ticket=self.t_a_b1
        )
        # Update it — should produce UPDATE log.
        req.status = AssignmentRequestStatus.APPROVED
        req.reviewed_by = self.manager_b1
        req.reviewed_at = timezone.now()
        req.save(update_fields=["status", "reviewed_by", "reviewed_at"])

        # Create a TicketStaffAssignment — should produce CREATE log.
        TicketStaffAssignment.objects.create(
            ticket=self.t_a_b3, user=self.staff_visible_b1
        )
        # Create a BuildingStaffVisibility — should produce CREATE log.
        BuildingStaffVisibility.objects.create(
            user=self.staff_no_visibility, building=self.b2
        )

        logged_models = set(
            AuditLog.objects.values_list("target_model", flat=True)
        )
        self.assertIn("tickets.StaffAssignmentRequest", logged_models)
        self.assertIn("tickets.TicketStaffAssignment", logged_models)
        self.assertIn("buildings.BuildingStaffVisibility", logged_models)
        # At least one UPDATE on StaffAssignmentRequest (the review).
        self.assertTrue(
            AuditLog.objects.filter(
                target_model="tickets.StaffAssignmentRequest", action="UPDATE"
            ).exists()
        )

    # ---- 18-21. is_staff_role() must include the new STAFF role. ----

    def test_18_staff_can_post_internal_note_and_customer_cannot_see_it(self):
        """
        STAFF must be treated as service-provider-side in
        tickets/serializers.py + tickets/views.py. Internal notes
        should be:
          - creatable by a STAFF actor.
          - hidden from a CUSTOMER_USER reading the same ticket.
        Without is_staff_role() including STAFF, the serializer's
        message_type=INTERNAL_NOTE validation 403s the STAFF user
        and the message list view re-tags the message as PUBLIC
        for them.
        """
        # Assign the staff user so they can post on the ticket.
        TicketStaffAssignment.objects.create(
            ticket=self.t_a_b1, user=self.staff_visible_b1
        )
        client = APIClient()
        client.force_authenticate(user=self.staff_visible_b1)
        post = client.post(
            f"/api/tickets/{self.t_a_b1.id}/messages/",
            {
                "message": "Internal: customer phoned — quote ready",
                "message_type": "INTERNAL_NOTE",
            },
            format="json",
        )
        self.assertEqual(post.status_code, 201, post.data)
        self.assertEqual(post.data["message_type"], "INTERNAL_NOTE")

        # Customer A's user on B1 must NOT see this note.
        client.force_authenticate(user=self.cust_user_a)
        listing = client.get(f"/api/tickets/{self.t_a_b1.id}/messages/")
        self.assertEqual(listing.status_code, 200, listing.data)
        msg_rows = listing.data.get("results", listing.data)
        bodies = [m.get("message", "") for m in msg_rows]
        self.assertFalse(
            any("Internal:" in b for b in bodies),
            f"Customer leaked internal note: {bodies}",
        )

    def test_19_staff_can_access_hidden_attachment_only_when_in_scope(self):
        """
        Hidden attachments (or attachments tied to an internal-note
        message) must be downloadable only by service-provider-side
        users. STAFF must be on that side AND still respect the
        scope helper — a STAFF user without visibility / assignment
        on a ticket cannot reach its attachments.
        """
        # Build a hidden attachment on the B1 ticket. The file is
        # required (FieldFile is not nullable on the model); a 1-byte
        # placeholder is enough — the view never opens it during a
        # list request.
        from django.core.files.uploadedfile import SimpleUploadedFile
        from tickets.models import TicketAttachment

        attachment = TicketAttachment.objects.create(
            ticket=self.t_a_b1,
            uploaded_by=self.manager_b1,
            file=SimpleUploadedFile(
                "internal-budget.pdf",
                b"x",
                content_type="application/pdf",
            ),
            original_filename="internal-budget.pdf",
            mime_type="application/pdf",
            file_size=1,
            is_hidden=True,
        )

        client = APIClient()
        # staff_visible_b1 has BuildingStaffVisibility on B1 →
        # scope_tickets_for returns t_a_b1 → request enters the
        # hidden-attachment branch with is_staff_role=True → allowed.
        client.force_authenticate(user=self.staff_visible_b1)
        list_resp = client.get(
            f"/api/tickets/{self.t_a_b1.id}/attachments/"
        )
        self.assertEqual(list_resp.status_code, 200, list_resp.data)
        rows = list_resp.data.get("results", list_resp.data)
        ids = [a["id"] for a in rows]
        self.assertIn(attachment.id, ids)

        # staff_no_visibility has no scope on B1 → 404 at the
        # ticket-level scope check (_get_ticket raises Http404).
        client.force_authenticate(user=self.staff_no_visibility)
        list_resp2 = client.get(
            f"/api/tickets/{self.t_a_b1.id}/attachments/"
        )
        self.assertEqual(list_resp2.status_code, 404)

        # Customer A's user on B1 cannot see the hidden attachment
        # (already covered by other tests but we re-assert here
        # because the regression target overlaps).
        client.force_authenticate(user=self.cust_user_a)
        list_resp3 = client.get(
            f"/api/tickets/{self.t_a_b1.id}/attachments/"
        )
        self.assertEqual(list_resp3.status_code, 200)
        cust_rows = list_resp3.data.get("results", list_resp3.data)
        cust_ids = [a["id"] for a in cust_rows]
        self.assertNotIn(attachment.id, cust_ids)

    def test_20_staff_first_message_stamps_first_response_at(self):
        """
        Posting the first non-customer message must set
        ticket.first_response_at. Without STAFF in is_staff_role(),
        a STAFF user's first message is silently downgraded to a
        PUBLIC_REPLY and the `mark_first_response_if_needed` branch
        below it is skipped → the SLA "time-to-first-response"
        metric is wrong for every STAFF-handled ticket.
        """
        # Build a fresh ticket so no other staff message has fired.
        ticket = Ticket.objects.create(
            company=self.company,
            building=self.b1,
            customer=self.customer_a,
            created_by=self.cust_user_a,
            title="New for first-response stamp",
            description="x",
        )
        TicketStaffAssignment.objects.create(
            ticket=ticket, user=self.staff_visible_b1
        )
        self.assertIsNone(ticket.first_response_at)
        client = APIClient()
        client.force_authenticate(user=self.staff_visible_b1)
        r = client.post(
            f"/api/tickets/{ticket.id}/messages/",
            {"message": "On it.", "message_type": "PUBLIC_REPLY"},
            format="json",
        )
        self.assertEqual(r.status_code, 201, r.data)
        ticket.refresh_from_db()
        self.assertIsNotNone(
            ticket.first_response_at,
            "STAFF first message should stamp first_response_at",
        )

    def test_21_staff_is_not_treated_as_customer_in_change_status_gate(self):
        """
        TicketViewSet.change_status blocks customer users from
        every transition except APPROVED / REJECTED (their own
        approval). STAFF must NOT trip that gate when they perform
        a staff-side transition like OPEN→IN_PROGRESS.

        Concretely: with the broken (Sprint 22) version of
        is_staff_role(), a STAFF user POSTing to_status=IN_PROGRESS
        on an OPEN ticket would 403 with the customer-only
        message; after the Sprint 23A fix the gate accepts it.
        """
        # Fresh OPEN ticket, staff assigned to it.
        ticket = Ticket.objects.create(
            company=self.company,
            building=self.b1,
            customer=self.customer_a,
            created_by=self.cust_user_a,
            title="Status gate check",
            description="x",
        )
        TicketStaffAssignment.objects.create(
            ticket=ticket, user=self.staff_visible_b1
        )
        client = APIClient()
        client.force_authenticate(user=self.staff_visible_b1)
        r = client.post(
            f"/api/tickets/{ticket.id}/status/",
            {"to_status": "IN_PROGRESS"},
            format="json",
        )
        # We do NOT assert 200 here, because the underlying state-
        # machine may still reject the transition for a different
        # reason (Sprint 23B will widen the allowed-set for STAFF).
        # The specific assertion is: the response is NOT the
        # customer-only 403 message. If the gate broke, this would
        # be 403 with that text.
        self.assertNotEqual(
            r.status_code,
            403,
            f"STAFF was treated as customer in change_status gate: {r.data!r}",
        )

    # ---- 22. CustomerUserBuildingAccess UPDATE audit coverage. ----

    def test_22_customeruserbuildingaccess_update_emits_audit(self):
        """
        Spec requires audit for customer-user-building-access
        changes — explicitly role changes, permission overrides,
        and active/inactive toggles. Sprint 14 only logged CREATE
        and DELETE. Sprint 23A adds an UPDATE path keyed on the
        three editable fields (`access_role`, `permission_overrides`,
        `is_active`).
        """
        AuditLog.objects.all().delete()
        access = self.access_a_user_b1
        # 1. Change access_role.
        access.access_role = (
            CustomerUserBuildingAccess.AccessRole.CUSTOMER_LOCATION_MANAGER
        )
        access.save(update_fields=["access_role"])

        # 2. Change permission_overrides.
        access.permission_overrides = {
            "customer.ticket.approve_location": True
        }
        access.save(update_fields=["permission_overrides"])

        # 3. Change is_active.
        access.is_active = False
        access.save(update_fields=["is_active"])

        updates = list(
            AuditLog.objects.filter(
                target_model="customers.CustomerUserBuildingAccess",
                action="UPDATE",
            )
        )
        self.assertEqual(
            len(updates),
            3,
            f"Expected 3 UPDATE rows (one per save). Got: "
            f"{[(u.action, u.changes) for u in updates]}",
        )

        changes_by_field = set()
        for log in updates:
            for field in log.changes.keys():
                changes_by_field.add(field)
        self.assertIn("access_role", changes_by_field)
        self.assertIn("permission_overrides", changes_by_field)
        self.assertIn("is_active", changes_by_field)

        # Spot-check one diff body: access_role should record the
        # before/after correctly.
        role_log = next(
            log for log in updates if "access_role" in log.changes
        )
        self.assertEqual(
            role_log.changes["access_role"]["before"],
            CustomerUserBuildingAccess.AccessRole.CUSTOMER_USER,
        )
        self.assertEqual(
            role_log.changes["access_role"]["after"],
            CustomerUserBuildingAccess.AccessRole.CUSTOMER_LOCATION_MANAGER,
        )

        # An update that touches NONE of the three tracked fields
        # must NOT emit an UPDATE row (regression guard against
        # noisy audit log when downstream code rewrites the row).
        before_count = AuditLog.objects.filter(
            target_model="customers.CustomerUserBuildingAccess",
            action="UPDATE",
        ).count()
        access.save()  # no changes
        after_count = AuditLog.objects.filter(
            target_model="customers.CustomerUserBuildingAccess",
            action="UPDATE",
        ).count()
        self.assertEqual(after_count, before_count)


# ---------------------------------------------------------------- helpers


def _mk(email, role, **extra):
    return User.objects.create_user(
        email=email,
        password=PASSWORD,
        full_name=email.split("@")[0],
        role=role,
        **extra,
    )


class _FakeRequest:
    def __init__(self, user):
        self.user = user


def _fake_request(user):
    return _FakeRequest(user)
