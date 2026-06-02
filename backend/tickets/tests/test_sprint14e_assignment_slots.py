"""
Sprint 14E — dated staff-assignment slots (transcript: same planned
work/day may carry Ahmet's morning task + Mehmet's evening task; each
staff sees their own dated job; the manager splits work into
dated/time-window staff assignments).

Schema + read/write contract + scope/visibility tests. The ticket state
machine is intentionally UNCHANGED — slot completion is additive
metadata; the ticket still completes via the manager double-check flow.
"""
from __future__ import annotations

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone
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
    StaffAssignmentSlotStatus,
    Ticket,
    TicketStaffAssignment,
)


User = get_user_model()
PASSWORD = "StrongerTestPassword123!"


def _mk(email, role, **extra):
    return User.objects.create_user(
        email=email, password=PASSWORD, role=role,
        full_name=email.split("@")[0], **extra,
    )


class _SlotFixture(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.company = Company.objects.create(name="Prov 14E", slug="prov-slot-14e")
        cls.building = Building.objects.create(company=cls.company, name="B-slot")
        cls.customer = Customer.objects.create(
            company=cls.company, name="Cust-slot", building=cls.building
        )
        CustomerBuildingMembership.objects.create(
            customer=cls.customer, building=cls.building
        )

        cls.admin = _mk("ca-slot@example.com", UserRole.COMPANY_ADMIN)
        CompanyUserMembership.objects.create(user=cls.admin, company=cls.company)

        cls.bm = _mk("bm-slot@example.com", UserRole.BUILDING_MANAGER)
        BuildingManagerAssignment.objects.create(user=cls.bm, building=cls.building)

        cls.ahmet = _mk("ahmet-slot@example.com", UserRole.STAFF)
        StaffProfile.objects.create(user=cls.ahmet)
        BuildingStaffVisibility.objects.create(user=cls.ahmet, building=cls.building)

        cls.mehmet = _mk("mehmet-slot@example.com", UserRole.STAFF)
        StaffProfile.objects.create(user=cls.mehmet)
        BuildingStaffVisibility.objects.create(user=cls.mehmet, building=cls.building)

        cls.cust_user = _mk("cust-slot@example.com", UserRole.CUSTOMER_USER)
        m = CustomerUserMembership.objects.create(
            customer=cls.customer, user=cls.cust_user
        )
        CustomerUserBuildingAccess.objects.create(
            membership=m,
            building=cls.building,
            access_role=CustomerUserBuildingAccess.AccessRole.CUSTOMER_COMPANY_ADMIN,
        )

        # Out-of-scope provider company + building + BM.
        cls.other_company = Company.objects.create(
            name="Other 14E", slug="other-slot-14e"
        )
        cls.other_building = Building.objects.create(
            company=cls.other_company, name="B-other"
        )
        cls.other_bm = _mk("bm-other-slot@example.com", UserRole.BUILDING_MANAGER)
        BuildingManagerAssignment.objects.create(
            user=cls.other_bm, building=cls.other_building
        )

        cls.ticket = Ticket.objects.create(
            company=cls.company,
            building=cls.building,
            customer=cls.customer,
            created_by=cls.admin,
            title="Slot ticket",
            description="desc",
            status="IN_PROGRESS",
        )

        cls.morning = "2026-06-15T08:00:00Z"
        cls.morning_end = "2026-06-15T10:00:00Z"
        cls.evening = "2026-06-15T18:00:00Z"

    def _api(self, user):
        c = APIClient()
        c.force_authenticate(user=user)
        return c

    def _slots_url(self, ticket_id=None):
        tid = ticket_id or self.ticket.id
        return f"/api/tickets/{tid}/staff-assignments/"

    def _slot_detail_url(self, user_id, ticket_id=None):
        tid = ticket_id or self.ticket.id
        return f"/api/tickets/{tid}/staff-assignments/{user_id}/"

    def _add_slot(self, actor, staff, **slot):
        return self._api(actor).post(
            self._slots_url(), {"user_id": staff.id, **slot}, format="json"
        )


class SlotCreateTests(_SlotFixture):
    def test_create_two_slots_same_ticket_different_windows(self):
        r1 = self._add_slot(
            self.admin, self.ahmet,
            time_window_label="morning",
            scheduled_start_at=self.morning,
            scheduled_end_at=self.morning_end,
        )
        self.assertEqual(r1.status_code, 201, r1.data)
        r2 = self._add_slot(
            self.admin, self.mehmet,
            time_window_label="evening",
            scheduled_start_at=self.evening,
        )
        self.assertEqual(r2.status_code, 201, r2.data)

        rows = TicketStaffAssignment.objects.filter(ticket=self.ticket)
        self.assertEqual(rows.count(), 2)
        self.assertEqual(
            rows.get(user=self.ahmet).time_window_label, "morning"
        )
        self.assertEqual(
            rows.get(user=self.mehmet).time_window_label, "evening"
        )
        # Both default to ASSIGNED.
        self.assertEqual(
            rows.get(user=self.ahmet).slot_status,
            StaffAssignmentSlotStatus.ASSIGNED,
        )

    def test_window_end_before_start_rejected(self):
        r = self._add_slot(
            self.admin, self.ahmet,
            scheduled_start_at=self.evening,
            scheduled_end_at=self.morning,  # before start
        )
        self.assertEqual(r.status_code, 400, r.data)

    def test_bm_in_scope_can_create_slot(self):
        r = self._add_slot(self.bm, self.ahmet, time_window_label="morning")
        self.assertEqual(r.status_code, 201, r.data)


class SlotVisibilityTests(_SlotFixture):
    def setUp(self):
        self._add_slot(
            self.admin, self.ahmet,
            time_window_label="morning",
            scheduled_start_at=self.morning,
        )
        self._add_slot(
            self.admin, self.mehmet,
            time_window_label="evening",
            scheduled_start_at=self.evening,
        )

    def test_ahmet_sees_only_his_slot_in_my_slots(self):
        resp = self._api(self.ahmet).get("/api/tickets/my-slots/")
        self.assertEqual(resp.status_code, 200, resp.data)
        rows = resp.data["results"] if isinstance(resp.data, dict) else resp.data
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["time_window_label"], "morning")
        self.assertEqual(rows[0]["ticket_id"], self.ticket.id)

    def test_mehmet_sees_only_his_slot_in_my_slots(self):
        resp = self._api(self.mehmet).get("/api/tickets/my-slots/")
        self.assertEqual(resp.status_code, 200, resp.data)
        rows = resp.data["results"] if isinstance(resp.data, dict) else resp.data
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["time_window_label"], "evening")

    def test_manager_sees_both_slots(self):
        resp = self._api(self.admin).get(self._slots_url())
        self.assertEqual(resp.status_code, 200, resp.data)
        rows = resp.data["results"] if isinstance(resp.data, dict) else resp.data
        self.assertEqual(len(rows), 2)

    def test_out_of_scope_bm_cannot_list(self):
        resp = self._api(self.other_bm).get(self._slots_url())
        self.assertIn(resp.status_code, (403, 404))

    def test_out_of_scope_bm_cannot_create(self):
        resp = self._add_slot(self.other_bm, self.ahmet)
        self.assertIn(resp.status_code, (403, 404))

    def test_customer_cannot_list_slot_details(self):
        resp = self._api(self.cust_user).get(self._slots_url())
        self.assertEqual(resp.status_code, 403, resp.data)

    def test_customer_my_slots_is_empty(self):
        resp = self._api(self.cust_user).get("/api/tickets/my-slots/")
        self.assertEqual(resp.status_code, 200, resp.data)
        rows = resp.data["results"] if isinstance(resp.data, dict) else resp.data
        self.assertEqual(len(rows), 0)


class SlotDeleteTests(_SlotFixture):
    def test_delete_one_slot_keeps_the_other(self):
        self._add_slot(self.admin, self.ahmet, time_window_label="morning")
        self._add_slot(self.admin, self.mehmet, time_window_label="evening")

        resp = self._api(self.admin).delete(self._slot_detail_url(self.ahmet.id))
        self.assertEqual(resp.status_code, 204, getattr(resp, "data", None))

        remaining = TicketStaffAssignment.objects.filter(ticket=self.ticket)
        self.assertEqual(remaining.count(), 1)
        self.assertEqual(remaining.first().user_id, self.mehmet.id)


class SlotCompletionTests(_SlotFixture):
    def setUp(self):
        self._add_slot(
            self.admin, self.ahmet,
            time_window_label="morning",
            scheduled_start_at=self.morning,
        )

    def test_staff_completes_own_slot(self):
        resp = self._api(self.ahmet).patch(
            self._slot_detail_url(self.ahmet.id),
            {
                "slot_status": StaffAssignmentSlotStatus.COMPLETED,
                "completion_note": "Done, photo on file.",
            },
            format="json",
        )
        self.assertEqual(resp.status_code, 200, resp.data)
        slot = TicketStaffAssignment.objects.get(
            ticket=self.ticket, user=self.ahmet
        )
        self.assertEqual(slot.slot_status, StaffAssignmentSlotStatus.COMPLETED)
        self.assertIsNotNone(slot.completed_at)
        self.assertEqual(slot.completed_by_id, self.ahmet.id)
        # Ticket status is UNCHANGED — slot completion does not drive the
        # ticket state machine (manager double-check still owns it).
        self.ticket.refresh_from_db()
        self.assertEqual(self.ticket.status, "IN_PROGRESS")

    def test_staff_unable_without_reason_rejected(self):
        resp = self._api(self.ahmet).patch(
            self._slot_detail_url(self.ahmet.id),
            {"slot_status": StaffAssignmentSlotStatus.UNABLE_TO_COMPLETE},
            format="json",
        )
        self.assertEqual(resp.status_code, 400, resp.data)

    def test_staff_unable_with_reason_ok(self):
        resp = self._api(self.ahmet).patch(
            self._slot_detail_url(self.ahmet.id),
            {
                "slot_status": StaffAssignmentSlotStatus.UNABLE_TO_COMPLETE,
                "unable_to_complete_reason": "Door was locked; no key.",
            },
            format="json",
        )
        self.assertEqual(resp.status_code, 200, resp.data)
        slot = TicketStaffAssignment.objects.get(
            ticket=self.ticket, user=self.ahmet
        )
        self.assertEqual(
            slot.slot_status, StaffAssignmentSlotStatus.UNABLE_TO_COMPLETE
        )

    def test_staff_cannot_patch_another_staff_slot(self):
        # Add Mehmet's slot, then Ahmet tries to PATCH it.
        self._add_slot(self.admin, self.mehmet, time_window_label="evening")
        resp = self._api(self.ahmet).patch(
            self._slot_detail_url(self.mehmet.id),
            {"slot_status": StaffAssignmentSlotStatus.COMPLETED},
            format="json",
        )
        self.assertEqual(resp.status_code, 403, getattr(resp, "data", None))

    def test_manager_patches_slot_schedule(self):
        resp = self._api(self.admin).patch(
            self._slot_detail_url(self.ahmet.id),
            {"time_window_label": "afternoon", "scheduled_start_at": self.evening},
            format="json",
        )
        self.assertEqual(resp.status_code, 200, resp.data)
        slot = TicketStaffAssignment.objects.get(
            ticket=self.ticket, user=self.ahmet
        )
        self.assertEqual(slot.time_window_label, "afternoon")

    def test_staff_cannot_reschedule_self_via_patch(self):
        # STAFF self-PATCH allow-list excludes schedule fields, so the
        # window label is silently ignored (not written).
        resp = self._api(self.ahmet).patch(
            self._slot_detail_url(self.ahmet.id),
            {
                "slot_status": StaffAssignmentSlotStatus.COMPLETED,
                "completion_note": "done",
                "time_window_label": "HACKED",
            },
            format="json",
        )
        self.assertEqual(resp.status_code, 200, resp.data)
        slot = TicketStaffAssignment.objects.get(
            ticket=self.ticket, user=self.ahmet
        )
        self.assertEqual(slot.time_window_label, "morning")
