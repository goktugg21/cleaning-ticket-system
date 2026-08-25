"""W26.3 — PARTS DIVIDE THE PEOPLE ALREADY ON THE JOB.

W26 said "one person, one slot" and meant ANY slot on the ticket. That
was too broad: it made the part-level assign unusable, because filing
someone under a part of a job they were on counted as a duplicate of
being on the job. The owner's model, which this file pins:

  a) JOB level — a person holds AT MOST ONE base slot (`sub_task=NULL`)
     per ticket. A second one is 400 `staff_already_assigned`.
     (Unchanged by W26.3; pinned in `test_w26_one_person_one_slot.py`,
     and restated here for the one case that moved.)
  b) PART level — a person MAY hold several part slots, one per DISTINCT
     part. Same person + same part twice is 400
     `staff_already_assigned`; same person on two different parts is the
     NORMAL case and is allowed.
  c) ORDER — parts divide people who are already on the job. A part slot
     for someone with no base slot here is 400 `staff_not_on_job`, its
     own stable code.

Two consequences that are not restatements of (a)-(c) and are the real
reason this file exists, because each is a path that reaches a state the
rules forbid WITHOUT ever passing the chokepoint:

  * REMOVING A BASE SLOT cascades to that person's part slots. Left
    alone it strands part slots that (c) says cannot exist, on a person
    the assignment card no longer draws a row for at all.
  * DELETING A PART must not let `on_delete=SET_NULL` turn its part
    slots into SECOND BASE SLOTS. Under (c) every part slot sits beside
    a base slot, so the FK's own behaviour would mint a duplicate for
    every one of them.

Time lives on the BASE slot; part slots carry no schedule of their own.
"""
from __future__ import annotations

from rest_framework import status
from rest_framework.test import APITestCase

from accounts.models import StaffProfile, UserRole
from buildings.models import BuildingStaffVisibility
from test_utils import TenantFixtureMixin
from tickets.models import SubTask, TicketStaffAssignment
from tickets.views_staff_assignments import (
    ERR_STAFF_ALREADY_ASSIGNED,
    ERR_STAFF_NOT_ON_JOB,
)


class _PartsFixture(TenantFixtureMixin, APITestCase):
    """One ticket, two eligible STAFF, two named parts."""

    def setUp(self):
        super().setUp()
        self.ahmet = self._make_staff("w263-ahmet@example.com")
        self.mehmet = self._make_staff("w263-mehmet@example.com")
        self.windows = SubTask.objects.create(
            ticket=self.ticket, title="Windows 3rd floor"
        )
        self.kitchen = SubTask.objects.create(
            ticket=self.ticket, title="Kitchen"
        )
        self.authenticate(self.company_admin)

    def _make_staff(self, email):
        staff = self.make_user(email, UserRole.STAFF)
        StaffProfile.objects.create(user=staff)
        BuildingStaffVisibility.objects.create(
            user=staff, building=self.building
        )
        return staff

    def _slots_url(self):
        return f"/api/tickets/{self.ticket.id}/staff-assignments/"

    def _slot_url(self, slot_id):
        return f"/api/tickets/{self.ticket.id}/staff-assignments/{slot_id}/"

    def _part_url(self, part):
        return f"/api/tickets/{self.ticket.id}/sub-tasks/{part.id}/"

    def _add(self, staff, **slot):
        return self.client.post(
            self._slots_url(), {"user_id": staff.id, **slot}, format="json"
        )

    def _put_on_job(self, staff):
        response = self._add(staff)
        self.assertEqual(response.status_code, 201, response.data)
        return response.data["id"]

    def _base_slots(self, staff):
        return TicketStaffAssignment.objects.filter(
            ticket=self.ticket, user=staff, sub_task__isnull=True
        )

    def _part_slots(self, staff):
        return TicketStaffAssignment.objects.filter(
            ticket=self.ticket, user=staff, sub_task__isnull=False
        )


class TheJobLevelStillTakesEachPersonOnceTests(_PartsFixture):
    """(a) — unchanged, and it must STAY unchanged now that the
    predicate takes a level argument: the easy way to get (b) wrong is
    to widen the base case with it."""

    def test_duplicate_base_slot_is_rejected(self):
        self._put_on_job(self.ahmet)
        response = self._add(self.ahmet)
        self.assertEqual(
            response.status_code, status.HTTP_400_BAD_REQUEST, response.data
        )
        self.assertEqual(response.data["code"], ERR_STAFF_ALREADY_ASSIGNED)
        self.assertEqual(self._base_slots(self.ahmet).count(), 1)

    def test_a_person_on_two_parts_still_cannot_take_a_second_base_slot(self):
        """The one that would break if (b) were implemented by simply
        dropping the duplicate check for anyone who holds a part slot."""
        self._put_on_job(self.ahmet)
        self.assertEqual(
            self._add(self.ahmet, sub_task=self.windows.id).status_code, 201
        )
        self.assertEqual(
            self._add(self.ahmet, sub_task=self.kitchen.id).status_code, 201
        )
        response = self._add(self.ahmet)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data["code"], ERR_STAFF_ALREADY_ASSIGNED)
        self.assertEqual(self._base_slots(self.ahmet).count(), 1)


class OnePersonMayHoldSeveralPartsTests(_PartsFixture):
    """(b) — the case W26 refused and the owner wants."""

    def test_the_same_person_on_two_different_parts_is_accepted(self):
        self._put_on_job(self.ahmet)
        first = self._add(self.ahmet, sub_task=self.windows.id)
        second = self._add(self.ahmet, sub_task=self.kitchen.id)
        self.assertEqual(first.status_code, 201, first.data)
        self.assertEqual(second.status_code, 201, second.data)
        self.assertEqual(first.data["sub_task"], self.windows.id)
        self.assertEqual(second.data["sub_task"], self.kitchen.id)
        # One person, ONE base slot, TWO parts — the shape the
        # assignment card draws as a single row with two chips.
        self.assertEqual(self._base_slots(self.ahmet).count(), 1)
        self.assertEqual(self._part_slots(self.ahmet).count(), 2)

    def test_the_same_person_on_the_same_part_twice_is_rejected(self):
        self._put_on_job(self.ahmet)
        self.assertEqual(
            self._add(self.ahmet, sub_task=self.windows.id).status_code, 201
        )
        response = self._add(self.ahmet, sub_task=self.windows.id)
        self.assertEqual(
            response.status_code, status.HTTP_400_BAD_REQUEST, response.data
        )
        self.assertEqual(response.data["code"], ERR_STAFF_ALREADY_ASSIGNED)
        self.assertEqual(
            self._part_slots(self.ahmet).filter(sub_task=self.windows).count(),
            1,
        )

    def test_two_people_may_share_one_part(self):
        self._put_on_job(self.ahmet)
        self._put_on_job(self.mehmet)
        self.assertEqual(
            self._add(self.ahmet, sub_task=self.windows.id).status_code, 201
        )
        self.assertEqual(
            self._add(self.mehmet, sub_task=self.windows.id).status_code, 201
        )
        self.assertEqual(
            TicketStaffAssignment.objects.filter(
                ticket=self.ticket, sub_task=self.windows
            ).count(),
            2,
        )


class PartsOnlyDividePeopleAlreadyOnTheJobTests(_PartsFixture):
    """(c) — ORDER, and its own stable code."""

    def test_a_part_slot_without_a_base_slot_is_rejected(self):
        response = self._add(self.ahmet, sub_task=self.windows.id)
        self.assertEqual(
            response.status_code, status.HTTP_400_BAD_REQUEST, response.data
        )
        self.assertEqual(response.data["code"], ERR_STAFF_NOT_ON_JOB)
        self.assertFalse(
            TicketStaffAssignment.objects.filter(ticket=self.ticket).exists()
        )

    def test_not_on_job_is_reported_ahead_of_a_same_part_duplicate(self):
        """Both are wrong when a legacy part slot exists without a base
        one. "Not on this job" is the fact that explains the other, and
        putting them on the job is the step that fixes it — so it is the
        code the operator gets."""
        TicketStaffAssignment.objects.create(
            ticket=self.ticket, user=self.ahmet, sub_task=self.windows
        )
        response = self._add(self.ahmet, sub_task=self.windows.id)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data["code"], ERR_STAFF_NOT_ON_JOB)

    def test_the_job_picker_offers_only_people_not_yet_on_the_job(self):
        self._put_on_job(self.ahmet)
        response = self.client.get(
            f"/api/tickets/{self.ticket.id}/assignable-staff/"
        )
        self.assertEqual(response.status_code, 200, response.data)
        ids = [row["id"] for row in response.data]
        self.assertNotIn(self.ahmet.id, ids)
        self.assertIn(self.mehmet.id, ids)

    def test_holding_part_slots_does_not_remove_someone_from_the_picker(self):
        """The picker excludes BASE-slot holders. A person with only a
        legacy part slot is not on the job, so they must still be
        offerable — otherwise (c) would be unsatisfiable for them."""
        TicketStaffAssignment.objects.create(
            ticket=self.ticket, user=self.ahmet, sub_task=self.windows
        )
        response = self.client.get(
            f"/api/tickets/{self.ticket.id}/assignable-staff/"
        )
        self.assertIn(self.ahmet.id, [row["id"] for row in response.data])


class RemovingSomeoneFromTheJobTakesTheirPartsTests(_PartsFixture):
    """The base-removal behaviour. Recon found DELETE removed only the
    addressed row, which under (c) strands part slots on a person the
    card can no longer draw."""

    def setUp(self):
        super().setUp()
        self.base_id = self._put_on_job(self.ahmet)
        self.windows_slot = self._add(
            self.ahmet, sub_task=self.windows.id
        ).data["id"]
        self.kitchen_slot = self._add(
            self.ahmet, sub_task=self.kitchen.id
        ).data["id"]
        self.other_base = self._put_on_job(self.mehmet)

    def test_removing_the_base_slot_removes_their_part_slots_too(self):
        response = self.client.delete(self._slot_url(self.base_id))
        self.assertEqual(response.status_code, 204)
        self.assertFalse(
            TicketStaffAssignment.objects.filter(
                ticket=self.ticket, user=self.ahmet
            ).exists(),
            "the person is off the job, so nothing of theirs is left "
            "filed under its parts",
        )

    def test_removing_a_base_slot_leaves_other_people_alone(self):
        self.assertEqual(
            self.client.delete(self._slot_url(self.base_id)).status_code, 204
        )
        self.assertTrue(
            TicketStaffAssignment.objects.filter(pk=self.other_base).exists()
        )

    def test_removing_one_part_slot_leaves_the_person_on_the_job(self):
        response = self.client.delete(self._slot_url(self.windows_slot))
        self.assertEqual(response.status_code, 204)
        self.assertEqual(self._base_slots(self.ahmet).count(), 1)
        self.assertEqual(
            [slot.sub_task_id for slot in self._part_slots(self.ahmet)],
            [self.kitchen.id],
        )

    def test_they_can_be_put_back_on_the_job_after_removal(self):
        self.assertEqual(
            self.client.delete(self._slot_url(self.base_id)).status_code, 204
        )
        self.assertEqual(self._add(self.ahmet).status_code, 201)


class DeletingAPartDoesNotMintASecondBaseSlotTests(_PartsFixture):
    """`TicketStaffAssignment.sub_task` is `on_delete=SET_NULL`. Under
    (c) that would turn EVERY part slot into a duplicate base slot."""

    def test_deleting_a_part_leaves_exactly_one_base_slot_per_person(self):
        self._put_on_job(self.ahmet)
        self.assertEqual(
            self._add(self.ahmet, sub_task=self.windows.id).status_code, 201
        )
        self.assertEqual(
            self.client.delete(self._part_url(self.windows)).status_code, 204
        )
        self.assertEqual(
            self._base_slots(self.ahmet).count(),
            1,
            "SET_NULL must not promote the part slot to a second base slot",
        )
        self.assertEqual(self._part_slots(self.ahmet).count(), 0)

    def test_a_legacy_part_slot_with_no_base_slot_still_falls_back(self):
        """Old behaviour preserved where it cannot cause a duplicate:
        the owner is not on the job, so SET_NULL returning the row to the
        loose pool is still the right answer and its completion evidence
        survives."""
        legacy = TicketStaffAssignment.objects.create(
            ticket=self.ticket, user=self.ahmet, sub_task=self.windows
        )
        self.assertEqual(
            self.client.delete(self._part_url(self.windows)).status_code, 204
        )
        legacy.refresh_from_db()
        self.assertIsNone(legacy.sub_task_id)


class CustomerRedactionOfPartsIsUnchangedTests(_PartsFixture):
    """The proof named in the brief: `sub_tasks` is provider-internal in
    its entirety, and nothing above widened what a customer sees."""

    def test_a_customer_user_gets_no_parts_and_the_key_still_exists(self):
        self._put_on_job(self.ahmet)
        self.assertEqual(
            self._add(self.ahmet, sub_task=self.windows.id).status_code, 201
        )
        self.authenticate(self.customer_user)
        response = self.client.get(f"/api/tickets/{self.ticket.id}/")
        self.assertEqual(response.status_code, 200, response.data)
        self.assertIn("sub_tasks", response.data)
        self.assertEqual(response.data["sub_tasks"], [])

    def test_a_provider_role_still_sees_the_parts_and_their_people(self):
        self._put_on_job(self.ahmet)
        self.assertEqual(
            self._add(self.ahmet, sub_task=self.windows.id).status_code, 201
        )
        response = self.client.get(f"/api/tickets/{self.ticket.id}/")
        titles = [part["title"] for part in response.data["sub_tasks"]]
        self.assertIn("Windows 3rd floor", titles)


class RefilingASlotGoesThroughTheSameRulesTests(_PartsFixture):
    """`sub_task` is a manager-writable PATCH field, so a slot can be
    MOVED between levels. Under W26 that could not collide — one person
    held one slot. Under W26.3 it reaches the same states a create does,
    so it goes through the same chokepoint."""

    def setUp(self):
        super().setUp()
        self.base_id = self._put_on_job(self.ahmet)
        self.windows_slot = self._add(
            self.ahmet, sub_task=self.windows.id
        ).data["id"]

    def _patch(self, slot_id, sub_task):
        return self.client.patch(
            self._slot_url(slot_id), {"sub_task": sub_task}, format="json"
        )

    def test_moving_a_part_slot_onto_a_part_they_already_hold_is_refused(self):
        second = self._add(self.ahmet, sub_task=self.kitchen.id).data["id"]
        response = self._patch(second, self.windows.id)
        self.assertEqual(
            response.status_code, status.HTTP_400_BAD_REQUEST, response.data
        )
        self.assertEqual(response.data["code"], ERR_STAFF_ALREADY_ASSIGNED)

    def test_moving_a_part_slot_back_to_the_job_is_refused(self):
        """It would become a SECOND base slot for someone who has one."""
        response = self._patch(self.windows_slot, None)
        self.assertEqual(
            response.status_code, status.HTTP_400_BAD_REQUEST, response.data
        )
        self.assertEqual(response.data["code"], ERR_STAFF_ALREADY_ASSIGNED)
        self.assertEqual(self._base_slots(self.ahmet).count(), 1)

    def test_moving_the_only_base_slot_into_a_part_is_refused(self):
        """(c) must not be satisfied by the very row being consumed."""
        response = self._patch(self.base_id, self.kitchen.id)
        self.assertEqual(
            response.status_code, status.HTTP_400_BAD_REQUEST, response.data
        )
        self.assertEqual(response.data["code"], ERR_STAFF_NOT_ON_JOB)
        self.assertEqual(self._base_slots(self.ahmet).count(), 1)

    def test_moving_a_part_slot_to_a_free_part_is_allowed(self):
        response = self._patch(self.windows_slot, self.kitchen.id)
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["sub_task"], self.kitchen.id)

    def test_a_patch_that_does_not_move_the_slot_still_edits_it(self):
        """The guard fires on a CHANGE of level, not on any PATCH that
        happens to carry the field."""
        response = self.client.patch(
            self._slot_url(self.windows_slot),
            {"sub_task": self.windows.id, "assignment_note": "bring a ladder"},
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["assignment_note"], "bring a ladder")

    def test_editing_the_time_on_a_base_slot_is_untouched(self):
        response = self.client.patch(
            self._slot_url(self.base_id),
            {"time_window_label": "morning"},
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["time_window_label"], "morning")
