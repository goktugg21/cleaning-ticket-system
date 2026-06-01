"""
Sprint 10B — multi-manager ticket assignment + staff unable-to-complete.

Two additive surfaces, modelled 1:1 on the Sprint 25A staff-assignment
work:

  GET    /api/tickets/<id>/manager-assignments/            list rows
  POST   /api/tickets/<id>/manager-assignments/  {user_id}|{user_ids}
  DELETE /api/tickets/<id>/manager-assignments/<user_id>/  remove
  POST   /api/tickets/<id>/unable-to-complete/   {reason}

The manager-assignment endpoints populate the new
`TicketManagerAssignment` M:N — the EXPLICIT per-ticket responsible
manager list (SoT §4.2), distinct from the legacy single
`Ticket.assigned_to` pointer and from the building-level
`BuildingManagerAssignment` authority grant.

`unable-to-complete` is a thin wrapper over the EXISTING state machine:
an assigned STAFF member drives `IN_PROGRESS -> WAITING_MANAGER_REVIEW`
with an "[UNABLE TO COMPLETE]" note; it never completes the ticket and
never reaches customer approval.

Stable codes pinned here:
  manager_assignment_forbidden, manager_assignment_terminal,
  manager_assignment_target_invalid, manager_not_eligible,
  manager_assignment_scope_forbidden, unable_reason_required,
  unable_not_assigned, unable_invalid_state, unable_forbidden.
"""

from __future__ import annotations

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from accounts.models import StaffProfile, UserRole
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
from extra_work.models import ExtraWorkRequest
from tickets.models import (
    Ticket,
    TicketManagerAssignment,
    TicketStaffAssignment,
    TicketStatus,
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


class _Sprint10BFixture(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.company_a = Company.objects.create(name="Co A", slug="co-a")
        cls.company_b = Company.objects.create(name="Co B", slug="co-b")

        cls.building_a = Building.objects.create(
            company=cls.company_a, name="Building A1"
        )
        cls.building_a2 = Building.objects.create(
            company=cls.company_a, name="Building A2"
        )
        cls.building_b = Building.objects.create(
            company=cls.company_b, name="Building B1"
        )

        cls.customer_a = Customer.objects.create(
            company=cls.company_a, name="Customer A", building=cls.building_a
        )
        cls.customer_b = Customer.objects.create(
            company=cls.company_b, name="Customer B", building=cls.building_b
        )
        CustomerBuildingMembership.objects.create(
            customer=cls.customer_a, building=cls.building_a
        )
        CustomerBuildingMembership.objects.create(
            customer=cls.customer_b, building=cls.building_b
        )

        cls.super_admin = _mk(
            "super@example.com",
            UserRole.SUPER_ADMIN,
            is_staff=True,
            is_superuser=True,
        )
        cls.admin_a = _mk("admin-a@example.com", UserRole.COMPANY_ADMIN)
        cls.admin_b = _mk("admin-b@example.com", UserRole.COMPANY_ADMIN)
        CompanyUserMembership.objects.create(
            user=cls.admin_a, company=cls.company_a
        )
        CompanyUserMembership.objects.create(
            user=cls.admin_b, company=cls.company_b
        )

        # Two managers eligible on building_a (BM assignment present).
        cls.mgr_a = _mk("mgr-a@example.com", UserRole.BUILDING_MANAGER)
        BuildingManagerAssignment.objects.create(
            user=cls.mgr_a, building=cls.building_a
        )
        cls.mgr_a_two = _mk("mgr-a-two@example.com", UserRole.BUILDING_MANAGER)
        BuildingManagerAssignment.objects.create(
            user=cls.mgr_a_two, building=cls.building_a
        )

        # Manager assigned only to building_a2 (same company, wrong
        # building) — eligible to be the actor on A2 but NOT a valid
        # target / actor for a building_a ticket.
        cls.mgr_a2_only = _mk("mgr-a2-only@example.com", UserRole.BUILDING_MANAGER)
        BuildingManagerAssignment.objects.create(
            user=cls.mgr_a2_only, building=cls.building_a2
        )

        # Manager assigned only in company B — cross-company target.
        cls.mgr_b = _mk("mgr-b@example.com", UserRole.BUILDING_MANAGER)
        BuildingManagerAssignment.objects.create(
            user=cls.mgr_b, building=cls.building_b
        )

        # A BM with NO building assignments at all.
        cls.mgr_unassigned = _mk(
            "mgr-unassigned@example.com", UserRole.BUILDING_MANAGER
        )

        # Staff assigned to building_a (used for unable-to-complete + the
        # "STAFF cannot assign managers" gate).
        cls.staff_a = _mk("staff-a@example.com", UserRole.STAFF)
        StaffProfile.objects.create(user=cls.staff_a)
        BuildingStaffVisibility.objects.create(
            user=cls.staff_a, building=cls.building_a
        )
        cls.staff_a_two = _mk("staff-a-two@example.com", UserRole.STAFF)
        StaffProfile.objects.create(user=cls.staff_a_two)
        BuildingStaffVisibility.objects.create(
            user=cls.staff_a_two, building=cls.building_a
        )
        # A staff NOT assigned to ticket_a (for unable_not_assigned).
        cls.staff_a_unassigned = _mk(
            "staff-a-unassigned@example.com", UserRole.STAFF
        )
        StaffProfile.objects.create(user=cls.staff_a_unassigned)
        BuildingStaffVisibility.objects.create(
            user=cls.staff_a_unassigned, building=cls.building_a
        )

        cls.cust_user_a = _mk("cust-a@example.com", UserRole.CUSTOMER_USER)
        mem_a = CustomerUserMembership.objects.create(
            customer=cls.customer_a, user=cls.cust_user_a
        )
        CustomerUserBuildingAccess.objects.create(
            membership=mem_a, building=cls.building_a
        )

        cls.ticket_a = Ticket.objects.create(
            company=cls.company_a,
            building=cls.building_a,
            customer=cls.customer_a,
            created_by=cls.cust_user_a,
            title="Ticket A",
            description="x",
        )
        cls.ticket_b = Ticket.objects.create(
            company=cls.company_b,
            building=cls.building_b,
            customer=cls.customer_b,
            created_by=cls.admin_b,
            title="Ticket B",
            description="x",
        )

    def _api(self, user):
        c = APIClient()
        c.force_authenticate(user=user)
        return c

    def _list_url(self, ticket):
        return f"/api/tickets/{ticket.id}/manager-assignments/"

    def _detail_url(self, ticket, user):
        return f"/api/tickets/{ticket.id}/manager-assignments/{user.id}/"


# ===========================================================================
# Multi-manager assignment
# ===========================================================================


class ManagerAssignmentWriteTests(_Sprint10BFixture):
    # (1) assign 2+ BMs to one ticket -> both in assigned_managers
    def test_assign_two_managers_both_in_payload(self):
        client = self._api(self.admin_a)
        first = client.post(
            self._list_url(self.ticket_a),
            {"user_id": self.mgr_a.id},
            format="json",
        )
        self.assertEqual(first.status_code, 201, first.data)
        second = client.post(
            self._list_url(self.ticket_a),
            {"user_id": self.mgr_a_two.id},
            format="json",
        )
        self.assertEqual(second.status_code, 201, second.data)

        detail = client.get(f"/api/tickets/{self.ticket_a.id}/")
        self.assertEqual(detail.status_code, 200)
        ids = [
            row.get("id")
            for row in detail.data["assigned_managers"]
            if not row.get("anonymous")
        ]
        self.assertIn(self.mgr_a.id, ids)
        self.assertIn(self.mgr_a_two.id, ids)
        # assigned_to single pointer is untouched by manager-assignments.
        self.assertIsNone(detail.data["assigned_to"])

    # (2) bulk user_ids list works
    def test_bulk_user_ids_creates_all(self):
        client = self._api(self.admin_a)
        response = client.post(
            self._list_url(self.ticket_a),
            {"user_ids": [self.mgr_a.id, self.mgr_a_two.id]},
            format="json",
        )
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(len(response.data), 2)
        self.assertEqual(
            TicketManagerAssignment.objects.filter(
                ticket=self.ticket_a
            ).count(),
            2,
        )

    # (3) remove one
    def test_remove_one_manager(self):
        TicketManagerAssignment.objects.create(
            ticket=self.ticket_a, user=self.mgr_a, assigned_by=self.admin_a
        )
        TicketManagerAssignment.objects.create(
            ticket=self.ticket_a, user=self.mgr_a_two, assigned_by=self.admin_a
        )
        client = self._api(self.admin_a)
        response = client.delete(self._detail_url(self.ticket_a, self.mgr_a))
        self.assertEqual(response.status_code, 204)
        self.assertFalse(
            TicketManagerAssignment.objects.filter(
                ticket=self.ticket_a, user=self.mgr_a
            ).exists()
        )
        self.assertTrue(
            TicketManagerAssignment.objects.filter(
                ticket=self.ticket_a, user=self.mgr_a_two
            ).exists()
        )

    def test_remove_unknown_returns_404(self):
        client = self._api(self.admin_a)
        response = client.delete(self._detail_url(self.ticket_a, self.mgr_a))
        self.assertEqual(response.status_code, 404)

    # (4) duplicate POST idempotent (200, no dup row)
    def test_duplicate_post_is_idempotent(self):
        client = self._api(self.admin_a)
        first = client.post(
            self._list_url(self.ticket_a),
            {"user_id": self.mgr_a.id},
            format="json",
        )
        self.assertEqual(first.status_code, 201)
        second = client.post(
            self._list_url(self.ticket_a),
            {"user_id": self.mgr_a.id},
            format="json",
        )
        self.assertEqual(second.status_code, 200)
        self.assertEqual(
            TicketManagerAssignment.objects.filter(
                ticket=self.ticket_a, user=self.mgr_a
            ).count(),
            1,
        )

    def test_bulk_partial_existing_returns_201_no_dup(self):
        # One row pre-exists; bulk adds it + a new one. 201 because a row
        # was created; the pre-existing row is not duplicated.
        TicketManagerAssignment.objects.create(
            ticket=self.ticket_a, user=self.mgr_a, assigned_by=self.admin_a
        )
        client = self._api(self.admin_a)
        response = client.post(
            self._list_url(self.ticket_a),
            {"user_ids": [self.mgr_a.id, self.mgr_a_two.id]},
            format="json",
        )
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(
            TicketManagerAssignment.objects.filter(
                ticket=self.ticket_a
            ).count(),
            2,
        )

    # (5) non-BM target -> 400 manager_assignment_target_invalid
    def test_non_bm_target_rejected(self):
        client = self._api(self.admin_a)
        response = client.post(
            self._list_url(self.ticket_a),
            {"user_id": self.staff_a.id},
            format="json",
        )
        self.assertEqual(response.status_code, 400, response.data)
        self.assertEqual(
            response.data["code"], "manager_assignment_target_invalid"
        )
        self.assertFalse(
            TicketManagerAssignment.objects.filter(
                ticket=self.ticket_a, user=self.staff_a
            ).exists()
        )

    # (6) BM without BuildingManagerAssignment for building -> manager_not_eligible
    def test_bm_without_building_assignment_rejected(self):
        client = self._api(self.admin_a)
        response = client.post(
            self._list_url(self.ticket_a),
            {"user_id": self.mgr_unassigned.id},
            format="json",
        )
        self.assertEqual(response.status_code, 400, response.data)
        self.assertEqual(response.data["code"], "manager_not_eligible")

    def test_bm_assigned_wrong_building_same_company_not_eligible(self):
        # mgr_a2_only is a BM in the SAME company (building_a2) but not on
        # ticket_a's building_a -> manager_not_eligible (NOT scope_forbidden,
        # because it has a same-company assignment).
        client = self._api(self.admin_a)
        response = client.post(
            self._list_url(self.ticket_a),
            {"user_id": self.mgr_a2_only.id},
            format="json",
        )
        self.assertEqual(response.status_code, 400, response.data)
        self.assertEqual(response.data["code"], "manager_not_eligible")

    def test_cross_company_bm_target_scope_forbidden(self):
        # super_admin can reach ticket_a; mgr_b is a BM only in company B
        # -> manager_assignment_scope_forbidden.
        client = self._api(self.super_admin)
        response = client.post(
            self._list_url(self.ticket_a),
            {"user_id": self.mgr_b.id},
            format="json",
        )
        self.assertEqual(response.status_code, 400, response.data)
        self.assertEqual(
            response.data["code"], "manager_assignment_scope_forbidden"
        )

    # All-or-nothing: an invalid target in a bulk list writes nothing.
    def test_bulk_all_or_nothing_on_invalid_target(self):
        client = self._api(self.admin_a)
        response = client.post(
            self._list_url(self.ticket_a),
            {"user_ids": [self.mgr_a.id, self.staff_a.id]},
            format="json",
        )
        self.assertEqual(response.status_code, 400, response.data)
        self.assertEqual(
            response.data["code"], "manager_assignment_target_invalid"
        )
        # mgr_a (valid) must NOT have been written.
        self.assertEqual(
            TicketManagerAssignment.objects.filter(
                ticket=self.ticket_a
            ).count(),
            0,
        )

    # ---- actor scope ---------------------------------------------------

    def test_super_admin_can_assign_anywhere(self):
        client = self._api(self.super_admin)
        response = client.post(
            self._list_url(self.ticket_a),
            {"user_id": self.mgr_a.id},
            format="json",
        )
        self.assertEqual(response.status_code, 201, response.data)

    def test_building_manager_actor_can_assign_for_their_building(self):
        client = self._api(self.mgr_a)
        response = client.post(
            self._list_url(self.ticket_a),
            {"user_id": self.mgr_a_two.id},
            format="json",
        )
        self.assertEqual(response.status_code, 201, response.data)

    # (7) out-of-scope CA -> 404; out-of-scope BM -> 404
    def test_cross_company_admin_gets_404(self):
        client = self._api(self.admin_b)
        response = client.post(
            self._list_url(self.ticket_a),
            {"user_id": self.mgr_a.id},
            format="json",
        )
        self.assertEqual(response.status_code, 404)
        self.assertFalse(
            TicketManagerAssignment.objects.filter(
                ticket=self.ticket_a
            ).exists()
        )

    def test_out_of_building_manager_actor_gets_404(self):
        # mgr_a2_only is assigned to building_a2; ticket_a is building_a.
        # scope_tickets_for hides the ticket -> 404.
        client = self._api(self.mgr_a2_only)
        response = client.post(
            self._list_url(self.ticket_a),
            {"user_id": self.mgr_a.id},
            format="json",
        )
        self.assertEqual(response.status_code, 404)

    # (8) STAFF -> 403, CUSTOMER_USER -> 403
    def test_staff_actor_forbidden(self):
        client = self._api(self.staff_a)
        response = client.post(
            self._list_url(self.ticket_a),
            {"user_id": self.mgr_a.id},
            format="json",
        )
        self.assertEqual(response.status_code, 403, response.data)
        self.assertEqual(response.data["code"], "manager_assignment_forbidden")

    def test_customer_user_actor_forbidden(self):
        client = self._api(self.cust_user_a)
        response = client.post(
            self._list_url(self.ticket_a),
            {"user_id": self.mgr_a.id},
            format="json",
        )
        self.assertEqual(response.status_code, 403, response.data)
        self.assertEqual(response.data["code"], "manager_assignment_forbidden")

    # (9) terminal ticket -> blocked
    def test_terminal_ticket_blocks_assignment(self):
        self.ticket_a.status = TicketStatus.CLOSED
        self.ticket_a.save(update_fields=["status"])
        client = self._api(self.admin_a)
        response = client.post(
            self._list_url(self.ticket_a),
            {"user_id": self.mgr_a.id},
            format="json",
        )
        self.assertEqual(response.status_code, 400, response.data)
        self.assertEqual(response.data["code"], "manager_assignment_terminal")
        self.assertFalse(
            TicketManagerAssignment.objects.filter(
                ticket=self.ticket_a
            ).exists()
        )

    def test_converted_ticket_blocks_assignment(self):
        self.ticket_a.status = TicketStatus.CONVERTED_TO_EXTRA_WORK
        self.ticket_a.save(update_fields=["status"])
        client = self._api(self.admin_a)
        response = client.post(
            self._list_url(self.ticket_a),
            {"user_id": self.mgr_a.id},
            format="json",
        )
        self.assertEqual(response.status_code, 400, response.data)
        self.assertEqual(response.data["code"], "manager_assignment_terminal")

    def test_missing_user_id_returns_400(self):
        client = self._api(self.admin_a)
        response = client.post(
            self._list_url(self.ticket_a), {}, format="json"
        )
        self.assertEqual(response.status_code, 400)

    # ---- list ----------------------------------------------------------

    def test_list_returns_rows(self):
        TicketManagerAssignment.objects.create(
            ticket=self.ticket_a, user=self.mgr_a, assigned_by=self.admin_a
        )
        client = self._api(self.admin_a)
        response = client.get(self._list_url(self.ticket_a))
        self.assertEqual(response.status_code, 200)
        ids = [row["user_id"] for row in response.data["results"]]
        self.assertIn(self.mgr_a.id, ids)


# ===========================================================================
# (10) Customer redaction parity with staff
# ===========================================================================


class ManagerAssignmentCustomerRedactionTests(_Sprint10BFixture):
    def test_customer_sees_full_record_when_flags_on(self):
        TicketManagerAssignment.objects.create(
            ticket=self.ticket_a, user=self.mgr_a, assigned_by=self.admin_a
        )
        TicketStaffAssignment.objects.create(
            ticket=self.ticket_a, user=self.staff_a, assigned_by=self.admin_a
        )
        client = self._api(self.cust_user_a)
        detail = client.get(f"/api/tickets/{self.ticket_a.id}/")
        self.assertEqual(detail.status_code, 200)
        mgr_entry = detail.data["assigned_managers"][0]
        self.assertEqual(mgr_entry["id"], self.mgr_a.id)
        self.assertIn("full_name", mgr_entry)
        self.assertIn("email", mgr_entry)

    def test_customer_redaction_consistent_between_staff_and_managers(self):
        # All three flags False -> BOTH staff and manager payloads collapse
        # to the same anonymous label shape.
        self.customer_a.show_assigned_staff_name = False
        self.customer_a.show_assigned_staff_email = False
        self.customer_a.show_assigned_staff_phone = False
        self.customer_a.save(
            update_fields=[
                "show_assigned_staff_name",
                "show_assigned_staff_email",
                "show_assigned_staff_phone",
            ]
        )
        TicketManagerAssignment.objects.create(
            ticket=self.ticket_a, user=self.mgr_a, assigned_by=self.admin_a
        )
        TicketStaffAssignment.objects.create(
            ticket=self.ticket_a, user=self.staff_a, assigned_by=self.admin_a
        )
        client = self._api(self.cust_user_a)
        detail = client.get(f"/api/tickets/{self.ticket_a.id}/")
        self.assertEqual(detail.status_code, 200)
        self.assertEqual(
            detail.data["assigned_managers"],
            detail.data["assigned_staff"],
        )
        self.assertTrue(detail.data["assigned_managers"][0]["anonymous"])

    def test_provider_always_sees_full_manager_record(self):
        self.customer_a.show_assigned_staff_name = False
        self.customer_a.show_assigned_staff_email = False
        self.customer_a.show_assigned_staff_phone = False
        self.customer_a.save()
        TicketManagerAssignment.objects.create(
            ticket=self.ticket_a, user=self.mgr_a, assigned_by=self.admin_a
        )
        client = self._api(self.admin_a)
        detail = client.get(f"/api/tickets/{self.ticket_a.id}/")
        entry = detail.data["assigned_managers"][0]
        self.assertEqual(entry["email"], self.mgr_a.email)
        self.assertNotIn("anonymous", entry)


# ===========================================================================
# (11) Audit coverage
# ===========================================================================


class ManagerAssignmentAuditTests(_Sprint10BFixture):
    def test_create_writes_audit_log(self):
        AuditLog.objects.all().delete()
        client = self._api(self.admin_a)
        response = client.post(
            self._list_url(self.ticket_a),
            {"user_id": self.mgr_a.id},
            format="json",
        )
        self.assertEqual(response.status_code, 201, response.data)
        row = TicketManagerAssignment.objects.get(
            ticket=self.ticket_a, user=self.mgr_a
        )
        logs = AuditLog.objects.filter(
            target_model="tickets.TicketManagerAssignment",
            action=AuditAction.CREATE,
        )
        self.assertEqual(logs.count(), 1)
        log = logs.first()
        self.assertEqual(log.actor, self.admin_a)
        self.assertEqual(log.target_id, row.id)

    def test_delete_writes_audit_log(self):
        row = TicketManagerAssignment.objects.create(
            ticket=self.ticket_a, user=self.mgr_a, assigned_by=self.admin_a
        )
        AuditLog.objects.all().delete()
        client = self._api(self.admin_a)
        response = client.delete(self._detail_url(self.ticket_a, self.mgr_a))
        self.assertEqual(response.status_code, 204)
        log = AuditLog.objects.filter(
            target_model="tickets.TicketManagerAssignment",
            action=AuditAction.DELETE,
        ).get()
        self.assertEqual(log.actor, self.admin_a)
        self.assertEqual(log.target_id, row.id)


# ===========================================================================
# (12) Multi-staff regression (light)
# ===========================================================================


class MultiStaffRegressionTests(_Sprint10BFixture):
    def test_two_staff_assignments_coexist(self):
        client = self._api(self.admin_a)
        first = client.post(
            f"/api/tickets/{self.ticket_a.id}/staff-assignments/",
            {"user_id": self.staff_a.id},
            format="json",
        )
        self.assertEqual(first.status_code, 201, first.data)
        second = client.post(
            f"/api/tickets/{self.ticket_a.id}/staff-assignments/",
            {"user_id": self.staff_a_two.id},
            format="json",
        )
        self.assertEqual(second.status_code, 201, second.data)
        self.assertEqual(
            TicketStaffAssignment.objects.filter(
                ticket=self.ticket_a
            ).count(),
            2,
        )

    def test_any_assigned_staff_can_complete(self):
        # Two staff assigned; either one driving the completion works.
        TicketStaffAssignment.objects.create(
            ticket=self.ticket_a, user=self.staff_a, assigned_by=self.admin_a
        )
        TicketStaffAssignment.objects.create(
            ticket=self.ticket_a, user=self.staff_a_two, assigned_by=self.admin_a
        )
        self.ticket_a.status = TicketStatus.IN_PROGRESS
        self.ticket_a.save(update_fields=["status"])
        client = self._api(self.staff_a_two)
        response = client.post(
            f"/api/tickets/{self.ticket_a.id}/status/",
            {"to_status": "WAITING_MANAGER_REVIEW", "note": "done"},
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.data)
        self.ticket_a.refresh_from_db()
        self.assertEqual(self.ticket_a.status, TicketStatus.WAITING_MANAGER_REVIEW)


# ===========================================================================
# Staff unable-to-complete (13)-(18)
# ===========================================================================


class UnableToCompleteTests(_Sprint10BFixture):
    def setUp(self):
        super().setUp()
        # ticket_a starts IN_PROGRESS with staff_a assigned.
        self.ticket_a.status = TicketStatus.IN_PROGRESS
        self.ticket_a.save(update_fields=["status"])
        TicketStaffAssignment.objects.create(
            ticket=self.ticket_a, user=self.staff_a, assigned_by=self.admin_a
        )

    def _url(self, ticket):
        return f"/api/tickets/{ticket.id}/unable-to-complete/"

    # (13) assigned STAFF submits reason -> IN_PROGRESS -> WAITING_MANAGER_REVIEW
    def test_assigned_staff_with_reason_moves_to_manager_review(self):
        client = self._api(self.staff_a)
        response = client.post(
            self._url(self.ticket_a),
            {"reason": "Locked out, no key available"},
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.data)
        self.ticket_a.refresh_from_db()
        self.assertEqual(
            self.ticket_a.status, TicketStatus.WAITING_MANAGER_REVIEW
        )
        # The history row note contains the unable reason marker.
        last = self.ticket_a.status_history.order_by("-created_at").first()
        self.assertIn("[UNABLE TO COMPLETE]", last.note)
        self.assertIn("Locked out", last.note)
        self.assertEqual(last.changed_by, self.staff_a)
        self.assertEqual(last.old_status, TicketStatus.IN_PROGRESS)
        self.assertEqual(last.new_status, TicketStatus.WAITING_MANAGER_REVIEW)

    # (14) missing reason -> unable_reason_required
    def test_missing_reason_rejected(self):
        client = self._api(self.staff_a)
        response = client.post(
            self._url(self.ticket_a), {"reason": "   "}, format="json"
        )
        self.assertEqual(response.status_code, 400, response.data)
        self.assertEqual(response.data["code"], "unable_reason_required")
        self.ticket_a.refresh_from_db()
        self.assertEqual(self.ticket_a.status, TicketStatus.IN_PROGRESS)

    def test_absent_reason_key_rejected(self):
        client = self._api(self.staff_a)
        response = client.post(self._url(self.ticket_a), {}, format="json")
        self.assertEqual(response.status_code, 400, response.data)
        self.assertEqual(response.data["code"], "unable_reason_required")

    # (15) non-assigned STAFF -> unable_not_assigned
    def test_non_assigned_staff_rejected(self):
        client = self._api(self.staff_a_unassigned)
        response = client.post(
            self._url(self.ticket_a),
            {"reason": "I want to report this"},
            format="json",
        )
        self.assertEqual(response.status_code, 403, response.data)
        self.assertEqual(response.data["code"], "unable_not_assigned")

    # (16) wrong state -> unable_invalid_state
    def test_wrong_state_rejected_open(self):
        self.ticket_a.status = TicketStatus.OPEN
        self.ticket_a.save(update_fields=["status"])
        client = self._api(self.staff_a)
        response = client.post(
            self._url(self.ticket_a), {"reason": "x"}, format="json"
        )
        self.assertEqual(response.status_code, 400, response.data)
        self.assertEqual(response.data["code"], "unable_invalid_state")

    def test_wrong_state_rejected_waiting_customer_approval(self):
        self.ticket_a.status = TicketStatus.WAITING_CUSTOMER_APPROVAL
        self.ticket_a.save(update_fields=["status"])
        client = self._api(self.staff_a)
        response = client.post(
            self._url(self.ticket_a), {"reason": "x"}, format="json"
        )
        self.assertEqual(response.status_code, 400, response.data)
        self.assertEqual(response.data["code"], "unable_invalid_state")

    # (17) non-STAFF -> unable_forbidden
    def test_non_staff_forbidden(self):
        client = self._api(self.admin_a)
        response = client.post(
            self._url(self.ticket_a), {"reason": "x"}, format="json"
        )
        self.assertEqual(response.status_code, 403, response.data)
        self.assertEqual(response.data["code"], "unable_forbidden")

    def test_customer_user_forbidden(self):
        client = self._api(self.cust_user_a)
        response = client.post(
            self._url(self.ticket_a), {"reason": "x"}, format="json"
        )
        self.assertEqual(response.status_code, 403, response.data)
        self.assertEqual(response.data["code"], "unable_forbidden")

    # (18) does NOT reach WAITING_CUSTOMER_APPROVAL / does NOT complete
    def test_does_not_reach_customer_approval_or_complete(self):
        client = self._api(self.staff_a)
        response = client.post(
            self._url(self.ticket_a),
            {"reason": "blocked"},
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.data)
        self.ticket_a.refresh_from_db()
        self.assertNotEqual(
            self.ticket_a.status, TicketStatus.WAITING_CUSTOMER_APPROVAL
        )
        self.assertNotEqual(self.ticket_a.status, TicketStatus.APPROVED)
        self.assertNotEqual(self.ticket_a.status, TicketStatus.CLOSED)
        self.assertIsNone(self.ticket_a.resolved_at)

    def test_only_one_history_row_written(self):
        before = self.ticket_a.status_history.count()
        client = self._api(self.staff_a)
        client.post(
            self._url(self.ticket_a),
            {"reason": "blocked"},
            format="json",
        )
        after = self.ticket_a.status_history.count()
        self.assertEqual(after - before, 1)


# ===========================================================================
# (19)-(20) Interactions: EW-origin + scheduling untouched
# ===========================================================================


class InteractionTests(_Sprint10BFixture):
    def _make_ew_ticket(self):
        ew = ExtraWorkRequest.objects.create(
            company=self.company_a,
            building=self.building_a,
            customer=self.customer_a,
            created_by=self.cust_user_a,
            title="EW parent",
            description="x",
        )
        return Ticket.objects.create(
            company=self.company_a,
            building=self.building_a,
            customer=self.customer_a,
            created_by=self.admin_a,
            title="EW-spawned operational ticket",
            description="x",
            extra_work_request=ew,
        )

    # (19) EW-origin ticket supports manager assignment
    def test_ew_origin_ticket_supports_manager_assignment(self):
        ew_ticket = self._make_ew_ticket()
        client = self._api(self.admin_a)
        response = client.post(
            self._list_url(ew_ticket),
            {"user_id": self.mgr_a.id},
            format="json",
        )
        self.assertEqual(response.status_code, 201, response.data)
        self.assertTrue(
            TicketManagerAssignment.objects.filter(
                ticket=ew_ticket, user=self.mgr_a
            ).exists()
        )

    # (20) scheduled ticket schedule + sla_* unchanged after manager-assign
    #      and after unable-to-complete
    def test_schedule_and_sla_unchanged_by_manager_assign_and_unable(self):
        from django.utils import timezone

        ticket = self.ticket_a
        # Give it a schedule + sla snapshot.
        ticket.status = TicketStatus.IN_PROGRESS
        ticket.scheduled_start_at = timezone.now()
        ticket.schedule_status = "SCHEDULED"
        ticket.sla_due_at = timezone.now()
        ticket.sla_status = "ON_TRACK"
        ticket.save(
            update_fields=[
                "status",
                "scheduled_start_at",
                "schedule_status",
                "sla_due_at",
                "sla_status",
            ]
        )
        snap = Ticket.objects.get(pk=ticket.pk)

        # Manager-assign.
        admin = self._api(self.admin_a)
        assign = admin.post(
            self._list_url(ticket),
            {"user_id": self.mgr_a.id},
            format="json",
        )
        self.assertEqual(assign.status_code, 201, assign.data)
        ticket.refresh_from_db()
        self.assertEqual(ticket.scheduled_start_at, snap.scheduled_start_at)
        self.assertEqual(ticket.schedule_status, snap.schedule_status)
        self.assertEqual(ticket.sla_due_at, snap.sla_due_at)
        self.assertEqual(ticket.sla_status, snap.sla_status)

        # Unable-to-complete (assigned staff).
        TicketStaffAssignment.objects.create(
            ticket=ticket, user=self.staff_a, assigned_by=self.admin_a
        )
        staff = self._api(self.staff_a)
        unable = staff.post(
            f"/api/tickets/{ticket.id}/unable-to-complete/",
            {"reason": "blocked"},
            format="json",
        )
        self.assertEqual(unable.status_code, 200, unable.data)
        ticket.refresh_from_db()
        # Status moved (expected), but schedule + sla_* are untouched.
        self.assertEqual(ticket.status, TicketStatus.WAITING_MANAGER_REVIEW)
        self.assertEqual(ticket.scheduled_start_at, snap.scheduled_start_at)
        self.assertEqual(ticket.schedule_status, snap.schedule_status)
        self.assertEqual(ticket.sla_due_at, snap.sla_due_at)
