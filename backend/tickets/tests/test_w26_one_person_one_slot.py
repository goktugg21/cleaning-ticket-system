"""W26 §1 — ONE PERSON, ONE SLOT.

The `(ticket, user)` uniqueness on `TicketStaffAssignment` was
deliberately dropped at the DB layer (`tickets/models.py`) and stays
dropped: tickets in the field already carry duplicate rows and they must
keep loading, rendering, completing and deleting exactly as they do
today. W26 restores the rule at the VALIDATION layer instead, through
ONE chokepoint —
`tickets.views_staff_assignments.reject_if_staff_already_assigned` — so
it governs what is created from now on and rewrites nothing that exists.

What these pin:

  * every user-driven CREATE path refuses a person who already holds ANY
    slot on the ticket, with the stable code `staff_already_assigned`;
  * this SUPERSEDES W13-FIX §6c's narrower `duplicate_flat_assignment`
    test, which allowed a second row as long as it carried a start time
    or a different window label — under the new rule a second window for
    the same person is an EDIT of their slot, not another slot;
  * EDITING an existing slot stays free;
  * the two BATCH paths (bulk assign, assignment-request approval) still
    create nothing for someone already on the ticket, and keep their own
    idempotent contracts rather than 400-ing a whole batch;
  * the picker's own source omits anyone already holding a slot, so
    "offerable" and "acceptable" cannot disagree;
  * a ticket that ALREADY holds legacy duplicate rows still reads,
    edits and deletes per slot.
"""
from __future__ import annotations

from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from accounts.models import StaffProfile, UserRole
from buildings.models import BuildingStaffVisibility
from test_utils import TenantFixtureMixin
from tickets.models import (
    AssignmentRequestStatus,
    StaffAssignmentRequest,
    SubTask,
    TicketStaffAssignment,
    TicketStatus,
)
from tickets.views_staff_assignments import ERR_STAFF_ALREADY_ASSIGNED


User = get_user_model()


class _OneSlotFixture(TenantFixtureMixin, APITestCase):
    """One building, two eligible STAFF members, one ticket."""

    def setUp(self):
        super().setUp()
        self.ahmet = self._make_staff("w26-ahmet@example.com")
        self.mehmet = self._make_staff("w26-mehmet@example.com")

    def _make_staff(self, email):
        staff = self.make_user(email, UserRole.STAFF)
        StaffProfile.objects.create(user=staff)
        BuildingStaffVisibility.objects.create(
            user=staff, building=self.building
        )
        return staff

    def _slots_url(self, ticket=None):
        return f"/api/tickets/{(ticket or self.ticket).id}/staff-assignments/"

    def _slot_url(self, slot_id, ticket=None):
        return (
            f"/api/tickets/{(ticket or self.ticket).id}"
            f"/staff-assignments/{slot_id}/"
        )

    def _assignable_url(self, ticket=None):
        return f"/api/tickets/{(ticket or self.ticket).id}/assignable-staff/"

    def _add(self, staff, **slot):
        return self.client.post(
            self._slots_url(), {"user_id": staff.id, **slot}, format="json"
        )


class SlotCreateIsRefusedForSomeoneAlreadyOnTheTicketTests(_OneSlotFixture):
    """`POST /api/tickets/<id>/staff-assignments/` — the single create."""

    def setUp(self):
        super().setUp()
        self.authenticate(self.company_admin)

    def _assert_refused(self, response):
        self.assertEqual(
            response.status_code, status.HTTP_400_BAD_REQUEST, response.data
        )
        self.assertEqual(response.data["code"], ERR_STAFF_ALREADY_ASSIGNED)
        self.assertEqual(
            TicketStaffAssignment.objects.filter(
                ticket=self.ticket, user=self.ahmet
            ).count(),
            1,
        )

    def test_a_second_bare_slot_for_the_same_person_is_refused(self):
        self.assertEqual(self._add(self.ahmet).status_code, 201)
        self._assert_refused(self._add(self.ahmet))

    def test_a_second_slot_with_a_start_time_is_refused(self):
        """W13-FIX §6c allowed this — the AM/PM split as a second ROW.
        W26 refuses it: the second window is an edit of the one slot."""
        self.assertEqual(self._add(self.ahmet).status_code, 201)
        self._assert_refused(
            self._add(self.ahmet, scheduled_start_at=timezone.now().isoformat())
        )

    def test_a_second_slot_with_a_different_window_label_is_refused(self):
        """Also allowed by W13-FIX §6c ("morning" then "afternoon")."""
        self.assertEqual(
            self._add(self.ahmet, time_window_label="morning").status_code, 201
        )
        self._assert_refused(
            self._add(self.ahmet, time_window_label="afternoon")
        )

    def test_a_second_slot_filed_under_a_part_is_refused(self):
        """ANY slot on the ticket counts — including one placed inside a
        SubTask, which is the sub-task assignment create path."""
        part = SubTask.objects.create(ticket=self.ticket, title="Boiler room")
        self.assertEqual(self._add(self.ahmet).status_code, 201)
        self._assert_refused(self._add(self.ahmet, sub_task=part.id))

    def test_a_first_slot_filed_under_a_part_still_succeeds(self):
        part = SubTask.objects.create(ticket=self.ticket, title="Boiler room")
        response = self._add(self.ahmet, sub_task=part.id)
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data["sub_task"], part.id)

    def test_a_different_person_is_still_added(self):
        self.assertEqual(self._add(self.ahmet).status_code, 201)
        self.assertEqual(self._add(self.mehmet).status_code, 201)
        self.assertEqual(
            TicketStaffAssignment.objects.filter(ticket=self.ticket).count(), 2
        )

    def test_the_same_person_on_a_different_ticket_is_still_added(self):
        """The rule is per TICKET, not per person."""
        from tickets.models import Ticket

        second = Ticket.objects.create(
            company=self.company,
            building=self.building,
            customer=self.customer,
            created_by=self.company_admin,
            title="Ticket A2",
            description="x",
        )
        self.assertEqual(self._add(self.ahmet).status_code, 201)
        response = self.client.post(
            self._slots_url(second), {"user_id": self.ahmet.id}, format="json"
        )
        self.assertEqual(response.status_code, 201, response.data)


class EditingASlotStaysFreeTests(_OneSlotFixture):
    """Changing someone's time is a PATCH on their own row — the
    chokepoint is on CREATE only and never sees an edit."""

    def setUp(self):
        super().setUp()
        self.authenticate(self.company_admin)
        self.slot_id = self._add(self.ahmet).data["id"]

    def test_moving_the_window_still_succeeds(self):
        response = self.client.patch(
            self._slot_url(self.slot_id),
            {
                "scheduled_start_at": "2026-06-15T09:00:00Z",
                "scheduled_end_at": "2026-06-15T11:00:00Z",
                "time_window_label": "morning",
            },
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.data)
        slot = TicketStaffAssignment.objects.get(pk=self.slot_id)
        self.assertEqual(slot.time_window_label, "morning")
        self.assertEqual(
            TicketStaffAssignment.objects.filter(
                ticket=self.ticket, user=self.ahmet
            ).count(),
            1,
        )

    def test_repeated_edits_of_the_same_slot_still_succeed(self):
        for label in ("morning", "afternoon", "evening"):
            response = self.client.patch(
                self._slot_url(self.slot_id),
                {"time_window_label": label},
                format="json",
            )
            self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(
            TicketStaffAssignment.objects.get(pk=self.slot_id)
            .time_window_label,
            "evening",
        )

    def test_re_adding_after_removal_succeeds(self):
        """The refusal is about the row that EXISTS. Remove it and the
        person may be put back on the job."""
        self.assertEqual(
            self.client.delete(self._slot_url(self.slot_id)).status_code, 204
        )
        self.assertEqual(self._add(self.ahmet).status_code, 201)


class TransitionModalBulkAddTests(_OneSlotFixture):
    """`POST /api/tickets/<id>/status/` with `assigned_staff_ids` — the
    second user-driven create path, through the SAME predicate."""

    def setUp(self):
        super().setUp()
        self.authenticate(self.manager)

    def _start_work(self, staff_ids):
        return self.client.post(
            f"/api/tickets/{self.ticket.id}/status/",
            {
                "to_status": TicketStatus.IN_PROGRESS,
                "assigned_staff_ids": staff_ids,
                "scheduled_start_at": timezone.now().isoformat(),
            },
            format="json",
        )

    def test_the_modal_still_staffs_a_ticket_from_empty(self):
        response = self._start_work([self.ahmet.id, self.mehmet.id])
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(
            TicketStaffAssignment.objects.filter(ticket=self.ticket).count(), 2
        )

    def test_naming_someone_already_on_the_ticket_is_refused(self):
        TicketStaffAssignment.objects.create(
            ticket=self.ticket, user=self.ahmet
        )
        response = self._start_work([self.ahmet.id])
        self.assertEqual(
            response.status_code, status.HTTP_400_BAD_REQUEST, response.data
        )
        # Same envelope shape as the sibling answer-rejections on this
        # endpoint (`schedule_forbidden_for_role`): the field carries the
        # sentence, `code` carries the stable identifier.
        self.assertEqual(
            response.data.get("code"), ERR_STAFF_ALREADY_ASSIGNED
        )
        self.assertIn("assigned_staff_ids", response.data)

    def test_a_refused_name_writes_nobody_and_does_not_move_the_ticket(self):
        """One transaction: the refusal must not leave the OTHER person
        assigned, nor the ticket started."""
        TicketStaffAssignment.objects.create(
            ticket=self.ticket, user=self.ahmet
        )
        response = self._start_work([self.mehmet.id, self.ahmet.id])
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertFalse(
            TicketStaffAssignment.objects.filter(
                ticket=self.ticket, user=self.mehmet
            ).exists()
        )
        self.ticket.refresh_from_db()
        self.assertEqual(self.ticket.status, TicketStatus.OPEN)


class BatchPathsCreateNoDuplicateTests(_OneSlotFixture):
    """The two paths that reach the row without a person naming it: they
    keep their idempotent contracts and still create no second slot."""

    def test_bulk_assign_counts_already_assigned_and_creates_nothing(self):
        TicketStaffAssignment.objects.create(
            ticket=self.ticket, user=self.ahmet
        )
        self.authenticate(self.company_admin)
        response = self.client.post(
            "/api/tickets/bulk-assign/",
            {
                "tickets": [self.ticket.id],
                "workers": [self.ahmet.id],
                "mode": "assign",
            },
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["created"], 0)
        self.assertEqual(response.data["already_assigned"], 1)
        self.assertEqual(
            TicketStaffAssignment.objects.filter(
                ticket=self.ticket, user=self.ahmet
            ).count(),
            1,
        )

    def test_approving_a_request_for_someone_already_on_creates_nothing(self):
        TicketStaffAssignment.objects.create(
            ticket=self.ticket, user=self.ahmet
        )
        request_row = StaffAssignmentRequest.objects.create(
            ticket=self.ticket,
            staff=self.ahmet,
            status=AssignmentRequestStatus.PENDING,
        )
        self.authenticate(self.company_admin)
        response = self.client.post(
            f"/api/staff-assignment-requests/{request_row.id}/approve/",
            {},
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.data)
        request_row.refresh_from_db()
        self.assertEqual(
            request_row.status, AssignmentRequestStatus.APPROVED
        )
        self.assertEqual(
            TicketStaffAssignment.objects.filter(
                ticket=self.ticket, user=self.ahmet
            ).count(),
            1,
        )


class PickerOmitsWhoeverAlreadyHoldsASlotTests(_OneSlotFixture):
    """`GET /api/tickets/<id>/assignable-staff/` — the picker's source.
    Absent, not disabled: the dialog needs no explanatory sentence
    because the person is simply not in the list."""

    def setUp(self):
        super().setUp()
        self.authenticate(self.company_admin)

    def _ids(self):
        response = self.client.get(self._assignable_url())
        self.assertEqual(response.status_code, 200)
        return [row["id"] for row in response.data]

    def test_both_are_offered_before_anyone_is_assigned(self):
        self.assertCountEqual(self._ids(), [self.ahmet.id, self.mehmet.id])

    def test_an_assigned_person_is_absent_and_the_rest_remain(self):
        TicketStaffAssignment.objects.create(
            ticket=self.ticket, user=self.ahmet
        )
        ids = self._ids()
        self.assertNotIn(self.ahmet.id, ids)
        self.assertIn(self.mehmet.id, ids)

    def test_a_person_holding_legacy_duplicates_is_listed_once_absent(self):
        """`.exclude()` over a multi-row join must not resurrect them."""
        TicketStaffAssignment.objects.create(
            ticket=self.ticket, user=self.ahmet
        )
        TicketStaffAssignment.objects.create(
            ticket=self.ticket, user=self.ahmet, time_window_label="afternoon"
        )
        self.assertEqual(self._ids(), [self.mehmet.id])

    def test_removing_the_slot_puts_them_back_in_the_picker(self):
        slot = TicketStaffAssignment.objects.create(
            ticket=self.ticket, user=self.ahmet
        )
        self.assertNotIn(self.ahmet.id, self._ids())
        self.client.delete(self._slot_url(slot.id))
        self.assertIn(self.ahmet.id, self._ids())

    def test_an_assignment_on_another_ticket_does_not_hide_them_here(self):
        from tickets.models import Ticket

        other = Ticket.objects.create(
            company=self.company,
            building=self.building,
            customer=self.customer,
            created_by=self.company_admin,
            title="Ticket A2",
            description="x",
        )
        TicketStaffAssignment.objects.create(ticket=other, user=self.ahmet)
        self.assertIn(self.ahmet.id, self._ids())


class LegacyDuplicatesStillReadTests(_OneSlotFixture):
    """The rule is validation-only. Rows that already exist are NOT
    migrated, deleted or repaired, and every surface that reads them
    keeps working."""

    def setUp(self):
        super().setUp()
        # Written at the ORM layer, exactly as a pre-W26 API call left
        # them: same person, same ticket, two rows.
        self.first = TicketStaffAssignment.objects.create(
            ticket=self.ticket,
            user=self.ahmet,
            time_window_label="morning",
        )
        self.second = TicketStaffAssignment.objects.create(
            ticket=self.ticket,
            user=self.ahmet,
            time_window_label="afternoon",
        )
        self.authenticate(self.company_admin)

    def test_the_slot_list_returns_both_rows(self):
        response = self.client.get(self._slots_url())
        self.assertEqual(response.status_code, 200, response.data)
        ids = [row["id"] for row in response.data["results"]]
        self.assertIn(self.first.id, ids)
        self.assertIn(self.second.id, ids)

    def test_the_ticket_detail_still_renders(self):
        response = self.client.get(f"/api/tickets/{self.ticket.id}/")
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(
            [entry["id"] for entry in response.data["assigned_staff"]],
            [self.ahmet.id],
            "the roster still dedups the duplicate rows by user",
        )

    def test_one_duplicate_row_can_still_be_edited(self):
        response = self.client.patch(
            self._slot_url(self.first.id),
            {"time_window_label": "EARLY"},
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.data)
        self.first.refresh_from_db()
        self.second.refresh_from_db()
        self.assertEqual(self.first.time_window_label, "EARLY")
        self.assertEqual(self.second.time_window_label, "afternoon")

    def test_one_duplicate_row_can_still_be_deleted_keeping_the_sibling(self):
        response = self.client.delete(self._slot_url(self.first.id))
        self.assertEqual(response.status_code, 204)
        self.assertFalse(
            TicketStaffAssignment.objects.filter(pk=self.first.id).exists()
        )
        self.assertTrue(
            TicketStaffAssignment.objects.filter(pk=self.second.id).exists()
        )

    def test_adding_a_third_row_is_now_refused(self):
        response = self._add(self.ahmet, time_window_label="evening")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data["code"], ERR_STAFF_ALREADY_ASSIGNED)
        self.assertEqual(
            TicketStaffAssignment.objects.filter(
                ticket=self.ticket, user=self.ahmet
            ).count(),
            2,
        )
