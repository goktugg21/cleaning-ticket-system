"""W26.4 — THE WORKER'S HALF: a staff member finishes their own part.

RECON RESULT, pinned here because it is the reason this file adds no
permission: **`SubTask` has no status field.** `SubTask.is_done()` is a
DERIVED method — a part is done iff it holds >=1 slot and every one of
them is COMPLETED. So "mark this part done" is not a write to the part
at all; it is the staff member completing THEIR OWN SLOT inside it, and
`TicketStaffAssignmentDetailView.patch` has allowed exactly that since
Sprint 14E (`_STAFF_SELF_SLOT_WRITE_FIELDS`, the `is_self_staff` gate).
That same PATCH already calls `maybe_auto_complete_ticket_on_subtasks`.

The sub-task PATCH surface (`views_sub_tasks.py`) is a different door:
its serializer exposes `title / description / ordering` and NOTHING
else, and it is gated by `_gate_actor` — SA / CA / BM only. STAFF get
403 there and must keep getting 403.

So what these pin is that the worker's half WORKS and stays narrow:

  * a staff member completes the part they are on;
  * they cannot touch a part they are not on (someone else's slot);
  * they cannot create, rename or remove a part;
  * the auto-complete roll-up fires from a STAFF-driven completion, not
    only a manager-driven one — the case the roll-up's own docstring
    admits it can swallow;
  * a CUSTOMER_USER payload still carries no sub-task data at all.
"""
from __future__ import annotations

from rest_framework import status
from rest_framework.test import APITestCase

from accounts.models import StaffProfile, UserRole
from buildings.models import BuildingStaffVisibility
from test_utils import TenantFixtureMixin
from tickets.models import (
    StaffAssignmentSlotStatus,
    SubTask,
    TicketStaffAssignment,
    TicketStatus,
)


class _WorkerFixture(TenantFixtureMixin, APITestCase):
    """One IN_PROGRESS ticket, two staff, two parts, one part each."""

    def setUp(self):
        super().setUp()
        self.ahmet = self._make_staff("w264-ahmet@example.com")
        self.mehmet = self._make_staff("w264-mehmet@example.com")
        self.ticket.status = TicketStatus.IN_PROGRESS
        self.ticket.save(update_fields=["status"])

        self.windows = SubTask.objects.create(
            ticket=self.ticket, title="Windows 3rd floor"
        )
        self.kitchen = SubTask.objects.create(
            ticket=self.ticket, title="Kitchen"
        )
        # W26.3 (c): a base slot first, then the part slots.
        self.ahmet_base = self._slot(self.ahmet, None)
        self.mehmet_base = self._slot(self.mehmet, None)
        self.ahmet_part = self._slot(self.ahmet, self.windows)
        self.mehmet_part = self._slot(self.mehmet, self.kitchen)

    def _make_staff(self, email):
        staff = self.make_user(email, UserRole.STAFF)
        StaffProfile.objects.create(user=staff)
        # `staff_completion_routes_to_customer` defaults False, which is
        # the route the roll-up's hardcoded WAITING_MANAGER_REVIEW target
        # needs. The other route is pinned at the bottom of this file.
        BuildingStaffVisibility.objects.create(
            user=staff, building=self.building
        )
        return staff

    def _slot(self, user, sub_task):
        return TicketStaffAssignment.objects.create(
            ticket=self.ticket, user=user, sub_task=sub_task,
            assigned_by=self.company_admin,
        )

    def _slot_url(self, slot):
        return (
            f"/api/tickets/{self.ticket.id}/staff-assignments/{slot.id}/"
        )

    def _sub_tasks_url(self):
        return f"/api/tickets/{self.ticket.id}/sub-tasks/"

    def _sub_task_url(self, part):
        return f"/api/tickets/{self.ticket.id}/sub-tasks/{part.id}/"

    def _complete(self, slot, note="done"):
        # A ticket with no extra work falls to LEGACY_NOTE_OR_PHOTO, so a
        # bare COMPLETED is refused `completion_evidence_required`. The
        # note IS the evidence — the same thing the completion dialog
        # sends.
        return self.client.patch(
            self._slot_url(slot),
            {"slot_status": StaffAssignmentSlotStatus.COMPLETED,
             "completion_note": note},
            format="json",
        )


class AStaffMemberCompletesTheirOwnPartTests(_WorkerFixture):
    def test_staff_completes_own_part(self):
        self.authenticate(self.ahmet)
        response = self._complete(self.ahmet_part)
        self.assertEqual(response.status_code, 200, response.data)
        self.ahmet_part.refresh_from_db()
        self.assertEqual(
            self.ahmet_part.slot_status, StaffAssignmentSlotStatus.COMPLETED
        )
        self.windows.refresh_from_db()
        self.assertTrue(self.windows.is_done())

    def test_completing_their_part_leaves_the_other_part_alone(self):
        self.authenticate(self.ahmet)
        self.assertEqual(self._complete(self.ahmet_part).status_code, 200)
        self.kitchen.refresh_from_db()
        self.assertFalse(self.kitchen.is_done())

    def test_staff_blocked_on_someone_elses_part(self):
        """A STAFF actor PATCHing a slot they do not own falls through to
        the manager gate, which STAFF never passes."""
        self.authenticate(self.ahmet)
        response = self._complete(self.mehmet_part)
        self.assertEqual(
            response.status_code, status.HTTP_403_FORBIDDEN, response.data
        )
        self.mehmet_part.refresh_from_db()
        self.assertEqual(
            self.mehmet_part.slot_status, StaffAssignmentSlotStatus.ASSIGNED
        )

    def test_staff_cannot_reschedule_even_their_own_part(self):
        """The self-gate is status + completion evidence ONLY."""
        self.authenticate(self.ahmet)
        response = self.client.patch(
            self._slot_url(self.ahmet_part),
            {"time_window_label": "whenever I like"},
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.data)
        self.ahmet_part.refresh_from_db()
        self.assertEqual(
            self.ahmet_part.time_window_label,
            "",
            "a field outside the self-writable set is dropped, not written",
        )


class AStaffMemberCannotShapeTheJobTests(_WorkerFixture):
    """The sub-task CRUD door stays SA/CA/BM. Nothing here widened it."""

    def setUp(self):
        super().setUp()
        self.authenticate(self.ahmet)

    def test_staff_blocked_on_create(self):
        response = self.client.post(
            self._sub_tasks_url(), {"title": "One I invented"}, format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(SubTask.objects.filter(ticket=self.ticket).count(), 2)

    def test_staff_blocked_on_rename(self):
        response = self.client.patch(
            self._sub_task_url(self.windows), {"title": "Mine now"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.windows.refresh_from_db()
        self.assertEqual(self.windows.title, "Windows 3rd floor")

    def test_staff_blocked_on_remove(self):
        response = self.client.delete(self._sub_task_url(self.windows))
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertTrue(SubTask.objects.filter(pk=self.windows.pk).exists())

    def test_staff_blocked_on_assigning_anyone_to_a_part(self):
        response = self.client.post(
            f"/api/tickets/{self.ticket.id}/staff-assignments/",
            {"user_id": self.mehmet.id, "sub_task": self.kitchen.id},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)


class TheRollUpFiresFromAStaffCompletionTests(_WorkerFixture):
    """The case `sub_task_rollup`'s own docstring admits it can swallow."""

    def setUp(self):
        super().setUp()
        self.ticket.auto_complete_on_subtasks = True
        self.ticket.save(update_fields=["auto_complete_on_subtasks"])

    def _finish_everything_but(self, leave):
        """Complete every slot except `leave`, as its own owner."""
        for slot in TicketStaffAssignment.objects.filter(ticket=self.ticket):
            if slot.pk == leave.pk:
                continue
            self.authenticate(slot.user)
            self.assertEqual(self._complete(slot).status_code, 200)

    def test_rollup_fires_on_staff_completion(self):
        self._finish_everything_but(self.ahmet_part)
        self.ticket.refresh_from_db()
        self.assertEqual(
            str(self.ticket.status), str(TicketStatus.IN_PROGRESS),
            "still in progress while one part is outstanding",
        )
        self.authenticate(self.ahmet)
        response = self._complete(self.ahmet_part)
        self.assertEqual(response.status_code, 200, response.data)
        self.ticket.refresh_from_db()
        self.assertEqual(
            str(self.ticket.status),
            str(TicketStatus.WAITING_MANAGER_REVIEW),
            "the LAST part, completed by a STAFF actor, flips the ticket",
        )

    def test_no_rollup_while_a_part_is_outstanding(self):
        self.authenticate(self.ahmet)
        self.assertEqual(self._complete(self.ahmet_part).status_code, 200)
        self.ticket.refresh_from_db()
        self.assertEqual(
            str(self.ticket.status), str(TicketStatus.IN_PROGRESS)
        )

    def test_no_rollup_when_the_switch_is_off(self):
        self.ticket.auto_complete_on_subtasks = False
        self.ticket.save(update_fields=["auto_complete_on_subtasks"])
        self._finish_everything_but(self.ahmet_part)
        self.authenticate(self.ahmet)
        self.assertEqual(self._complete(self.ahmet_part).status_code, 200)
        self.ticket.refresh_from_db()
        self.assertEqual(
            str(self.ticket.status), str(TicketStatus.IN_PROGRESS)
        )

    def test_a_staff_routed_to_the_customer_does_not_flip_to_review(self):
        """NOT a regression — the documented swallow. The roll-up's
        target is hardcoded WAITING_MANAGER_REVIEW, and a staff member
        whose building routes completions to the customer is refused
        that leg (`staff_completion_route_mismatch`). The slot still
        completes; the ticket simply does not advance. Pinned so the
        limitation is visible rather than discovered in the field."""
        bsv = BuildingStaffVisibility.objects.get(
            user=self.ahmet, building=self.building
        )
        bsv.staff_completion_routes_to_customer = True
        bsv.save(update_fields=["staff_completion_routes_to_customer"])
        self._finish_everything_but(self.ahmet_part)
        self.authenticate(self.ahmet)
        self.assertEqual(self._complete(self.ahmet_part).status_code, 200)
        self.ahmet_part.refresh_from_db()
        self.assertEqual(
            self.ahmet_part.slot_status, StaffAssignmentSlotStatus.COMPLETED
        )
        self.ticket.refresh_from_db()
        self.assertEqual(
            str(self.ticket.status), str(TicketStatus.IN_PROGRESS)
        )


class TheCustomerStillSeesNoPartsTests(_WorkerFixture):
    """serializers.py:840 — `sub_tasks` is emptied for CUSTOMER_USER. The
    worker's half adds no read path, and this is the proof."""

    def test_customer_payload_carries_no_sub_task_data(self):
        self.authenticate(self.ahmet)
        self.assertEqual(self._complete(self.ahmet_part).status_code, 200)
        self.authenticate(self.customer_user)
        response = self.client.get(f"/api/tickets/{self.ticket.id}/")
        self.assertEqual(response.status_code, 200, response.data)
        self.assertIn("sub_tasks", response.data)
        self.assertEqual(response.data["sub_tasks"], [])

    def test_a_staff_viewer_still_receives_the_parts(self):
        self.authenticate(self.ahmet)
        response = self.client.get(f"/api/tickets/{self.ticket.id}/")
        self.assertEqual(response.status_code, 200, response.data)
        titles = [p["title"] for p in response.data["sub_tasks"]]
        self.assertIn("Windows 3rd floor", titles)
        self.assertIn("Kitchen", titles)
