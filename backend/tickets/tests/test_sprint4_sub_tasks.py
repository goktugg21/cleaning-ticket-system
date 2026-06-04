"""
Sprint 4 — sub-tasks (backend): model, nullable assignment FK, PA/SA
auto-complete-on-sub-tasks roll-up, audit.

Covers:
  * SubTask CRUD happy paths + audit rows (create/update/delete).
  * SubTask CRUD RBAC (SA/CA/BM-in-scope allowed; out-of-scope BM 404;
    STAFF 403; customer 404) + terminal-ticket mutation blocked.
  * Placing a slot into a sub-task + cross-ticket placement rejected +
    terminal placement blocked.
  * Back-compat: a loose (sub_task=NULL) slot and a ticket with no
    sub-tasks behave exactly as before.
  * Completion roll-up matrix (flag on/off, all-done, one-pending,
    empty-sub-task, loose-incomplete, no-sub-tasks vacuous guard).
  * auto_complete_on_subtasks flag gate (PA/SA set; BM/STAFF/customer
    rejected) + explicit audit row + terminal block.
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
from tickets.models import (
    StaffAssignmentSlotStatus,
    SubTask,
    Ticket,
    TicketStaffAssignment,
    TicketStatus,
    TicketStatusHistory,
)

User = get_user_model()
PASSWORD = "StrongerTestPassword123!"
COMPLETED = StaffAssignmentSlotStatus.COMPLETED
ASSIGNED = StaffAssignmentSlotStatus.ASSIGNED


def _mk(email, role, **extra):
    return User.objects.create_user(
        email=email, password=PASSWORD, role=role,
        full_name=email.split("@")[0], **extra,
    )


class SubTaskFixture(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.company_a = Company.objects.create(name="Co A", slug="co-a")
        cls.company_b = Company.objects.create(name="Co B", slug="co-b")
        cls.building_a = Building.objects.create(company=cls.company_a, name="B A1")
        cls.building_a2 = Building.objects.create(company=cls.company_a, name="B A2")
        cls.building_b = Building.objects.create(company=cls.company_b, name="B B1")
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
            "super@example.com", UserRole.SUPER_ADMIN,
            is_staff=True, is_superuser=True,
        )
        cls.admin_a = _mk("admin-a@example.com", UserRole.COMPANY_ADMIN)
        CompanyUserMembership.objects.create(user=cls.admin_a, company=cls.company_a)

        cls.manager_a = _mk("mgr-a@example.com", UserRole.BUILDING_MANAGER)
        BuildingManagerAssignment.objects.create(
            user=cls.manager_a, building=cls.building_a
        )
        # A BM scoped to a DIFFERENT building in the same company — out of
        # scope for ticket_a (no osius.ticket.assign_staff for building_a).
        cls.manager_a2 = _mk("mgr-a2@example.com", UserRole.BUILDING_MANAGER)
        BuildingManagerAssignment.objects.create(
            user=cls.manager_a2, building=cls.building_a2
        )

        cls.staff_a = _mk("staff-a@example.com", UserRole.STAFF)
        StaffProfile.objects.create(user=cls.staff_a)
        BuildingStaffVisibility.objects.create(
            user=cls.staff_a, building=cls.building_a
        )

        cls.cust_user_a = _mk("cust-a@example.com", UserRole.CUSTOMER_USER)
        mem_a = CustomerUserMembership.objects.create(
            customer=cls.customer_a, user=cls.cust_user_a
        )
        CustomerUserBuildingAccess.objects.create(
            membership=mem_a, building=cls.building_a
        )

        # ticket_a (building_a) + ticket_b (building_b, cross-company).
        cls.ticket_b = Ticket.objects.create(
            company=cls.company_b, building=cls.building_b,
            customer=cls.customer_b, created_by=cls.admin_a,
            title="Ticket B", description="x",
        )

    def setUp(self):
        # A fresh IN_PROGRESS ticket on building_a per test (mutated by the
        # roll-up tests; created here so each test is isolated).
        self.ticket_a = Ticket.objects.create(
            company=self.company_a, building=self.building_a,
            customer=self.customer_a, created_by=self.cust_user_a,
            title="Ticket A", description="x", status=TicketStatus.IN_PROGRESS,
        )

    def _api(self, user):
        c = APIClient()
        c.force_authenticate(user=user)
        return c

    def _st_list_url(self, ticket):
        return f"/api/tickets/{ticket.id}/sub-tasks/"

    def _st_detail_url(self, ticket, sub_task_id):
        return f"/api/tickets/{ticket.id}/sub-tasks/{sub_task_id}/"

    def _slot_list_url(self, ticket):
        return f"/api/tickets/{ticket.id}/staff-assignments/"

    def _slot_detail_url(self, ticket, slot_id):
        return f"/api/tickets/{ticket.id}/staff-assignments/{slot_id}/"

    def _mk_slot(self, ticket, sub_task=None, slot_status=ASSIGNED):
        return TicketStaffAssignment.objects.create(
            ticket=ticket, user=self.staff_a, assigned_by=self.admin_a,
            sub_task=sub_task, slot_status=slot_status,
        )

    def _complete_slot_via_api(self, ticket, slot, actor=None):
        actor = actor or self.staff_a
        return self._api(actor).patch(
            self._slot_detail_url(ticket, slot.id),
            {"slot_status": COMPLETED, "completion_note": "done"},
            format="json",
        )


# ===========================================================================
# SubTask CRUD + audit + RBAC
# ===========================================================================
class SubTaskCrudTests(SubTaskFixture):
    def test_crud_happy_path(self):
        c = self._api(self.super_admin)
        # create
        resp = c.post(
            self._st_list_url(self.ticket_a),
            {"title": "Clean lobby", "description": "wet mop", "ordering": 2},
            format="json",
        )
        self.assertEqual(resp.status_code, 201, resp.data)
        sid = resp.data["id"]
        self.assertEqual(resp.data["title"], "Clean lobby")
        self.assertEqual(resp.data["ordering"], 2)
        self.assertFalse(resp.data["is_done"])  # empty sub-task
        self.assertEqual(resp.data["staff_assignments"], [])
        # list
        resp = c.get(self._st_list_url(self.ticket_a))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.data["results"]), 1)
        # retrieve
        resp = c.get(self._st_detail_url(self.ticket_a, sid))
        self.assertEqual(resp.status_code, 200)
        # patch
        resp = c.patch(
            self._st_detail_url(self.ticket_a, sid),
            {"title": "Clean lobby + windows", "ordering": 5},
            format="json",
        )
        self.assertEqual(resp.status_code, 200, resp.data)
        self.assertEqual(resp.data["title"], "Clean lobby + windows")
        self.assertEqual(resp.data["ordering"], 5)
        # delete
        resp = c.delete(self._st_detail_url(self.ticket_a, sid))
        self.assertEqual(resp.status_code, 204)
        self.assertFalse(SubTask.objects.filter(pk=sid).exists())

    def test_crud_emits_audit_rows(self):
        c = self._api(self.super_admin)
        sid = c.post(
            self._st_list_url(self.ticket_a),
            {"title": "Audit me"}, format="json",
        ).data["id"]
        self.assertEqual(
            AuditLog.objects.filter(
                target_model="tickets.SubTask", action=AuditAction.CREATE,
                target_id=sid,
            ).count(),
            1,
        )
        c.patch(
            self._st_detail_url(self.ticket_a, sid),
            {"title": "Audit me twice"}, format="json",
        )
        self.assertEqual(
            AuditLog.objects.filter(
                target_model="tickets.SubTask", action=AuditAction.UPDATE,
                target_id=sid,
            ).count(),
            1,
        )
        c.delete(self._st_detail_url(self.ticket_a, sid))
        self.assertEqual(
            AuditLog.objects.filter(
                target_model="tickets.SubTask", action=AuditAction.DELETE,
                target_id=sid,
            ).count(),
            1,
        )

    def test_company_admin_and_building_manager_in_scope_allowed(self):
        for actor in (self.admin_a, self.manager_a):
            resp = self._api(actor).post(
                self._st_list_url(self.ticket_a),
                {"title": f"by {actor.email}"}, format="json",
            )
            self.assertEqual(resp.status_code, 201, (actor.email, resp.data))

    def test_out_of_scope_building_manager_blocked(self):
        # manager_a2 manages building_a2, not ticket_a's building_a. The
        # scoped ticket lookup hides ticket_a -> 404 (H-1/H-2: no 403 leak),
        # mirroring the staff-assignment endpoints' out-of-building behaviour.
        resp = self._api(self.manager_a2).post(
            self._st_list_url(self.ticket_a),
            {"title": "nope"}, format="json",
        )
        self.assertEqual(resp.status_code, 404)
        self.assertFalse(SubTask.objects.filter(ticket=self.ticket_a).exists())

    def test_staff_forbidden(self):
        resp = self._api(self.staff_a).post(
            self._st_list_url(self.ticket_a),
            {"title": "nope"}, format="json",
        )
        self.assertEqual(resp.status_code, 403)

    def test_customer_forbidden(self):
        # The scoped ticket lookup 404s a customer before the gate.
        resp = self._api(self.cust_user_a).post(
            self._st_list_url(self.ticket_a),
            {"title": "nope"}, format="json",
        )
        self.assertIn(resp.status_code, (403, 404))
        self.assertFalse(SubTask.objects.filter(ticket=self.ticket_a).exists())

    def test_cross_ticket_sub_task_id_404(self):
        # A sub-task of ticket_a addressed under ticket_b -> 404.
        st = SubTask.objects.create(ticket=self.ticket_a, title="A")
        resp = self._api(self.super_admin).get(
            self._st_detail_url(self.ticket_b, st.id)
        )
        self.assertEqual(resp.status_code, 404)

    def test_terminal_ticket_blocks_mutation(self):
        self.ticket_a.status = TicketStatus.CLOSED
        self.ticket_a.save(update_fields=["status"])
        c = self._api(self.super_admin)
        resp = c.post(
            self._st_list_url(self.ticket_a), {"title": "x"}, format="json"
        )
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.data["code"], "sub_task_not_allowed_terminal")


# ===========================================================================
# Sub-task placement onto staff slots
# ===========================================================================
class SubTaskPlacementTests(SubTaskFixture):
    def test_create_slot_inside_sub_task(self):
        st = SubTask.objects.create(ticket=self.ticket_a, title="A")
        resp = self._api(self.admin_a).post(
            self._slot_list_url(self.ticket_a),
            {"user_id": self.staff_a.id, "sub_task": st.id},
            format="json",
        )
        self.assertEqual(resp.status_code, 201, resp.data)
        self.assertEqual(resp.data["sub_task"], st.id)
        self.assertTrue(
            TicketStaffAssignment.objects.filter(
                ticket=self.ticket_a, sub_task=st, user=self.staff_a
            ).exists()
        )

    def test_cross_ticket_sub_task_rejected(self):
        st_other = SubTask.objects.create(ticket=self.ticket_b, title="other")
        resp = self._api(self.admin_a).post(
            self._slot_list_url(self.ticket_a),
            {"user_id": self.staff_a.id, "sub_task": st_other.id},
            format="json",
        )
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.data["sub_task"][0].code, "sub_task_ticket_mismatch")

    def test_loose_assignment_has_null_sub_task(self):
        # Back-compat: a slot created without sub_task stays loose.
        resp = self._api(self.admin_a).post(
            self._slot_list_url(self.ticket_a),
            {"user_id": self.staff_a.id}, format="json",
        )
        self.assertEqual(resp.status_code, 201, resp.data)
        self.assertIsNone(resp.data["sub_task"])

    def test_place_into_sub_task_blocked_on_terminal(self):
        st = SubTask.objects.create(ticket=self.ticket_a, title="A")
        self.ticket_a.status = TicketStatus.APPROVED
        self.ticket_a.save(update_fields=["status"])
        resp = self._api(self.admin_a).post(
            self._slot_list_url(self.ticket_a),
            {"user_id": self.staff_a.id, "sub_task": st.id},
            format="json",
        )
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.data["sub_task"][0].code, "sub_task_ticket_terminal")


# ===========================================================================
# Completion roll-up matrix
# ===========================================================================
class SubTaskRollUpTests(SubTaskFixture):
    def _enable_flag(self, ticket):
        ticket.auto_complete_on_subtasks = True
        ticket.save(update_fields=["auto_complete_on_subtasks"])

    def test_flag_off_all_done_no_advance(self):
        st = SubTask.objects.create(ticket=self.ticket_a, title="A")
        slot = self._mk_slot(self.ticket_a, sub_task=st, slot_status=ASSIGNED)
        # flag stays OFF (default)
        resp = self._complete_slot_via_api(self.ticket_a, slot)
        self.assertEqual(resp.status_code, 200, resp.data)
        self.ticket_a.refresh_from_db()
        self.assertEqual(self.ticket_a.status, TicketStatus.IN_PROGRESS)

    def test_all_sub_tasks_done_advances_with_staff_as_changed_by(self):
        self._enable_flag(self.ticket_a)
        st1 = SubTask.objects.create(ticket=self.ticket_a, title="A", ordering=1)
        st2 = SubTask.objects.create(ticket=self.ticket_a, title="B", ordering=2)
        self._mk_slot(self.ticket_a, sub_task=st1, slot_status=COMPLETED)
        last = self._mk_slot(self.ticket_a, sub_task=st2, slot_status=ASSIGNED)
        resp = self._complete_slot_via_api(self.ticket_a, last)  # staff_a
        self.assertEqual(resp.status_code, 200, resp.data)
        self.ticket_a.refresh_from_db()
        self.assertEqual(self.ticket_a.status, TicketStatus.WAITING_MANAGER_REVIEW)
        hist = TicketStatusHistory.objects.filter(
            ticket=self.ticket_a,
            new_status=TicketStatus.WAITING_MANAGER_REVIEW,
        ).latest("id")
        self.assertEqual(hist.changed_by_id, self.staff_a.id)

    def test_one_sub_task_still_pending_no_advance(self):
        self._enable_flag(self.ticket_a)
        st1 = SubTask.objects.create(ticket=self.ticket_a, title="A")
        st2 = SubTask.objects.create(ticket=self.ticket_a, title="B")
        st3 = SubTask.objects.create(ticket=self.ticket_a, title="C")
        self._mk_slot(self.ticket_a, sub_task=st1, slot_status=COMPLETED)
        last = self._mk_slot(self.ticket_a, sub_task=st2, slot_status=ASSIGNED)
        self._mk_slot(self.ticket_a, sub_task=st3, slot_status=ASSIGNED)
        self._complete_slot_via_api(self.ticket_a, last)
        self.ticket_a.refresh_from_db()
        self.assertEqual(self.ticket_a.status, TicketStatus.IN_PROGRESS)

    def test_empty_sub_task_blocks_advance(self):
        self._enable_flag(self.ticket_a)
        st1 = SubTask.objects.create(ticket=self.ticket_a, title="A")
        SubTask.objects.create(ticket=self.ticket_a, title="empty")  # no slots
        last = self._mk_slot(self.ticket_a, sub_task=st1, slot_status=ASSIGNED)
        self._complete_slot_via_api(self.ticket_a, last)
        self.ticket_a.refresh_from_db()
        self.assertEqual(self.ticket_a.status, TicketStatus.IN_PROGRESS)

    def test_loose_incomplete_blocks_advance(self):
        self._enable_flag(self.ticket_a)
        st1 = SubTask.objects.create(ticket=self.ticket_a, title="A")
        # a loose (sub_task=NULL) slot still ASSIGNED
        self._mk_slot(self.ticket_a, sub_task=None, slot_status=ASSIGNED)
        last = self._mk_slot(self.ticket_a, sub_task=st1, slot_status=ASSIGNED)
        self._complete_slot_via_api(self.ticket_a, last)
        self.ticket_a.refresh_from_db()
        self.assertEqual(self.ticket_a.status, TicketStatus.IN_PROGRESS)

    def test_flag_on_no_sub_tasks_no_advance_vacuous_guard(self):
        self._enable_flag(self.ticket_a)
        # NO sub-tasks; a single loose slot.
        loose = self._mk_slot(self.ticket_a, sub_task=None, slot_status=ASSIGNED)
        self._complete_slot_via_api(self.ticket_a, loose)
        self.ticket_a.refresh_from_db()
        self.assertEqual(self.ticket_a.status, TicketStatus.IN_PROGRESS)

    def test_delete_sub_task_preserves_assignment(self):
        # Deleting a sub-task SET_NULLs its slot back to the loose pool —
        # never deletes the assignment or its completion evidence.
        st = SubTask.objects.create(ticket=self.ticket_a, title="A")
        slot = self._mk_slot(self.ticket_a, sub_task=st, slot_status=COMPLETED)
        TicketStaffAssignment.objects.filter(pk=slot.pk).update(
            completion_note="evidence"
        )
        resp = self._api(self.super_admin).delete(
            self._st_detail_url(self.ticket_a, st.id)
        )
        self.assertEqual(resp.status_code, 204)
        slot.refresh_from_db()
        self.assertIsNone(slot.sub_task_id)
        self.assertEqual(slot.slot_status, COMPLETED)
        self.assertEqual(slot.completion_note, "evidence")


# ===========================================================================
# auto_complete_on_subtasks flag gate
# ===========================================================================
class AutoCompleteFlagTests(SubTaskFixture):
    def _flag_url(self, ticket):
        return f"/api/tickets/{ticket.id}/auto-complete-flag/"

    def test_super_admin_and_company_admin_can_set(self):
        for actor in (self.super_admin, self.admin_a):
            resp = self._api(actor).patch(
                self._flag_url(self.ticket_a),
                {"auto_complete_on_subtasks": True}, format="json",
            )
            self.assertEqual(resp.status_code, 200, (actor.email, resp.data))
            self.assertTrue(resp.data["auto_complete_on_subtasks"])
            self.ticket_a.refresh_from_db()
            self.assertTrue(self.ticket_a.auto_complete_on_subtasks)

    def test_building_manager_rejected(self):
        resp = self._api(self.manager_a).patch(
            self._flag_url(self.ticket_a),
            {"auto_complete_on_subtasks": True}, format="json",
        )
        self.assertEqual(resp.status_code, 403)
        self.assertEqual(resp.data["code"], "auto_complete_flag_forbidden")
        self.ticket_a.refresh_from_db()
        self.assertFalse(self.ticket_a.auto_complete_on_subtasks)

    def test_staff_and_customer_rejected(self):
        for actor in (self.staff_a, self.cust_user_a):
            resp = self._api(actor).patch(
                self._flag_url(self.ticket_a),
                {"auto_complete_on_subtasks": True}, format="json",
            )
            self.assertIn(resp.status_code, (403, 404))
        self.ticket_a.refresh_from_db()
        self.assertFalse(self.ticket_a.auto_complete_on_subtasks)

    def test_flag_flip_writes_audit_row(self):
        self._api(self.super_admin).patch(
            self._flag_url(self.ticket_a),
            {"auto_complete_on_subtasks": True}, format="json",
        )
        rows = AuditLog.objects.filter(
            target_model="tickets.Ticket", action=AuditAction.UPDATE,
            target_id=self.ticket_a.id,
        )
        self.assertEqual(rows.count(), 1)
        self.assertEqual(
            rows.first().changes["auto_complete_on_subtasks"],
            {"before": False, "after": True},
        )

    def test_no_op_flip_writes_no_audit_row(self):
        # Setting the flag to its current value writes no audit row.
        self._api(self.super_admin).patch(
            self._flag_url(self.ticket_a),
            {"auto_complete_on_subtasks": False}, format="json",
        )
        self.assertEqual(
            AuditLog.objects.filter(
                target_model="tickets.Ticket", action=AuditAction.UPDATE,
                target_id=self.ticket_a.id,
            ).count(),
            0,
        )

    def test_flag_blocked_on_terminal(self):
        self.ticket_a.status = TicketStatus.CLOSED
        self.ticket_a.save(update_fields=["status"])
        resp = self._api(self.super_admin).patch(
            self._flag_url(self.ticket_a),
            {"auto_complete_on_subtasks": True}, format="json",
        )
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(
            resp.data["code"], "auto_complete_flag_not_allowed_terminal"
        )

    def test_detail_exposes_sub_tasks_and_flag(self):
        st = SubTask.objects.create(ticket=self.ticket_a, title="A")
        self._mk_slot(self.ticket_a, sub_task=st, slot_status=COMPLETED)
        resp = self._api(self.super_admin).get(
            f"/api/tickets/{self.ticket_a.id}/"
        )
        self.assertEqual(resp.status_code, 200)
        self.assertIn("auto_complete_on_subtasks", resp.data)
        self.assertIn("sub_tasks", resp.data)
        self.assertEqual(len(resp.data["sub_tasks"]), 1)
        self.assertTrue(resp.data["sub_tasks"][0]["is_done"])
        self.assertEqual(len(resp.data["sub_tasks"][0]["staff_assignments"]), 1)
