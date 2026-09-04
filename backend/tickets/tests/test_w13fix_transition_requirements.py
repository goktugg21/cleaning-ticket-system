"""W13-FIX §1 + §6c — what a step needs, and who may be added twice.

The gate these cover is the one the owner's father asked for: a move
that ASKS before it happens, and refuses until it is answered. The
modal reads the same rule through
`GET /tickets/<id>/transition-requirements/`, so a test that the
endpoint and the enforcement agree is a test that the screen and the
server cannot drift apart.
"""
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from test_utils import TenantFixtureMixin
from tickets.models import TicketStaffAssignment, TicketStatus
from tickets.transition_requirements import ERR_TRANSITION_REQUIREMENTS
from tickets.views_staff_assignments import ERR_STAFF_ALREADY_ASSIGNED


class TransitionRequirementsGateTests(TenantFixtureMixin, APITestCase):
    def test_start_the_work_is_refused_without_who_and_when(self):
        self.authenticate(self.manager)
        response = self.client.post(
            f"/api/tickets/{self.ticket.id}/status/",
            {"to_status": TicketStatus.IN_PROGRESS},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data["code"], ERR_TRANSITION_REQUIREMENTS)
        self.ticket.refresh_from_db()
        self.assertEqual(self.ticket.status, TicketStatus.OPEN)

    def test_acknowledge_is_refused_without_a_date(self):
        """ACKNOWLEDGED's own docstring says "seen and SCHEDULED"."""
        self.authenticate(self.manager)
        response = self.client.post(
            f"/api/tickets/{self.ticket.id}/status/",
            {"to_status": TicketStatus.ACKNOWLEDGED},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data["code"], ERR_TRANSITION_REQUIREMENTS)

    def test_the_move_succeeds_once_the_ticket_carries_both(self):
        self.make_workable()
        self.authenticate(self.manager)
        response = self.client.post(
            f"/api/tickets/{self.ticket.id}/status/",
            {"to_status": TicketStatus.IN_PROGRESS},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_the_modal_may_answer_in_the_same_press(self):
        """The whole point of the optional payload fields: the operator
        answers the modal and the move happens, in ONE call."""
        self.authenticate(self.manager)
        when = timezone.now().isoformat()
        response = self.client.post(
            f"/api/tickets/{self.ticket.id}/status/",
            {
                "to_status": TicketStatus.ACKNOWLEDGED,
                "scheduled_start_at": when,
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.ticket.refresh_from_db()
        self.assertEqual(self.ticket.status, TicketStatus.ACKNOWLEDGED)
        self.assertIsNotNone(self.ticket.scheduled_start_at)

    def test_nothing_is_written_when_the_move_is_refused(self):
        """The answers and the transition share one transaction, so a
        refused move must not leave the date behind."""
        self.authenticate(self.manager)
        response = self.client.post(
            f"/api/tickets/{self.ticket.id}/status/",
            # A date, but still nobody doing it -> IN_PROGRESS refused.
            {
                "to_status": TicketStatus.IN_PROGRESS,
                "scheduled_start_at": timezone.now().isoformat(),
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.ticket.refresh_from_db()
        self.assertIsNone(self.ticket.scheduled_start_at)
        self.assertEqual(self.ticket.status, TicketStatus.OPEN)


class TransitionAnswersAreNotASideDoorTests(TenantFixtureMixin, APITestCase):
    """H-11 — a workflow move is not a permission override.

    The optional `scheduled_start_at` / `assigned_staff_ids` on the
    status endpoint are a CONVENIENCE, not a second set of rules. If
    they skipped the checks that `POST /schedule/` and
    `POST /staff-assignments/` apply, then `POST /status/` would let a
    role do what those endpoints refuse it.
    """

    def test_customer_user_cannot_schedule_through_the_status_endpoint(self):
        self.authenticate(self.customer_user)
        response = self.client.post(
            f"/api/tickets/{self.ticket.id}/status/",
            {
                "to_status": TicketStatus.ACKNOWLEDGED,
                "scheduled_start_at": timezone.now().isoformat(),
            },
            format="json",
        )
        self.assertIn(
            response.status_code,
            (status.HTTP_400_BAD_REQUEST, status.HTTP_403_FORBIDDEN),
        )
        self.ticket.refresh_from_db()
        self.assertIsNone(self.ticket.scheduled_start_at)

    def test_out_of_scope_manager_cannot_schedule_another_tenants_ticket(self):
        """The other tenant's ticket 404s on scope before anything is
        written -- the H-1 boundary is not softened by this path."""
        self.authenticate(self.manager)
        response = self.client.post(
            f"/api/tickets/{self.other_ticket.id}/status/",
            {
                "to_status": TicketStatus.ACKNOWLEDGED,
                "scheduled_start_at": timezone.now().isoformat(),
            },
            format="json",
        )
        self.assertIn(
            response.status_code,
            (status.HTTP_403_FORBIDDEN, status.HTTP_404_NOT_FOUND),
        )
        self.other_ticket.refresh_from_db()
        self.assertIsNone(self.other_ticket.scheduled_start_at)


class TransitionRequirementsEndpointTests(TenantFixtureMixin, APITestCase):
    def test_endpoint_reports_what_the_step_is_missing(self):
        self.authenticate(self.manager)
        response = self.client.get(
            f"/api/tickets/{self.ticket.id}/transition-requirements/",
            {"to_status": TicketStatus.IN_PROGRESS},
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(sorted(response.data["unmet"]), ["assignee", "schedule"])

    def test_endpoint_reports_nothing_missing_once_satisfied(self):
        self.make_workable()
        self.authenticate(self.manager)
        response = self.client.get(
            f"/api/tickets/{self.ticket.id}/transition-requirements/",
            {"to_status": TicketStatus.IN_PROGRESS},
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["unmet"], [])

    def test_to_status_is_required(self):
        self.authenticate(self.manager)
        response = self.client.get(
            f"/api/tickets/{self.ticket.id}/transition-requirements/"
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data["code"], "to_status_required")

    def test_unknown_status_is_refused_not_answered_empty(self):
        self.authenticate(self.manager)
        response = self.client.get(
            f"/api/tickets/{self.ticket.id}/transition-requirements/",
            {"to_status": "NOT_A_STATUS"},
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data["code"], "unknown_status")


class DuplicateFlatAssignmentTests(TenantFixtureMixin, APITestCase):
    """§6c — Ahmet Yildiz, twice on ticket 355, both rows identical.

    W26 SUPERSEDED §6c's rule while keeping its subject. §6c refused only
    an INDISTINGUISHABLE second row (`duplicate_flat_assignment`) and let
    a second row through when it carried a start time or a different
    window label. The owner's decision since is ONE PERSON, ONE SLOT: any
    second slot for someone already on the ticket is refused
    `staff_already_assigned`, and a second window is an EDIT of their
    existing slot. The two tests that pinned the permissive half now pin
    the refusal; the full W26 surface lives in
    `test_w26_one_person_one_slot.py`.
    """

    def setUp(self):
        super().setUp()
        self.staff = self.make_staff_for_building(self.building)

    def make_staff_for_building(self, building):
        from accounts.models import StaffProfile, User, UserRole
        from buildings.models import BuildingStaffVisibility

        staff = User.objects.create_user(
            email="w13fix-staff@example.com",
            password="Test12345!",
            full_name="W13 Fix Staff",
            role=UserRole.STAFF,
        )
        StaffProfile.objects.create(user=staff)
        BuildingStaffVisibility.objects.create(
            user=staff,
            building=building,
            visibility_level=BuildingStaffVisibility.VisibilityLevel.BUILDING_READ,
        )
        return staff

    def test_second_flat_add_of_the_same_person_is_refused(self):
        self.authenticate(self.company_admin)
        url = f"/api/tickets/{self.ticket.id}/staff-assignments/"
        first = self.client.post(url, {"user_id": self.staff.id}, format="json")
        self.assertEqual(first.status_code, status.HTTP_201_CREATED)

        second = self.client.post(url, {"user_id": self.staff.id}, format="json")
        self.assertEqual(second.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(second.data["code"], ERR_STAFF_ALREADY_ASSIGNED)
        self.assertEqual(
            TicketStaffAssignment.objects.filter(
                ticket=self.ticket, user=self.staff
            ).count(),
            1,
        )

    def test_a_differently_labelled_flat_slot_is_now_refused_too(self):
        """W26 — §6c allowed this ("morning" then "afternoon" say
        different things). One person, one slot: the afternoon is a
        change to the same slot, not a second one."""
        self.authenticate(self.company_admin)
        url = f"/api/tickets/{self.ticket.id}/staff-assignments/"
        first = self.client.post(
            url,
            {"user_id": self.staff.id, "time_window_label": "morning"},
            format="json",
        )
        self.assertEqual(first.status_code, status.HTTP_201_CREATED)
        second = self.client.post(
            url,
            {"user_id": self.staff.id, "time_window_label": "afternoon"},
            format="json",
        )
        self.assertEqual(second.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(second.data["code"], ERR_STAFF_ALREADY_ASSIGNED)
        self.assertEqual(
            TicketStaffAssignment.objects.filter(
                ticket=self.ticket, user=self.staff
            ).count(),
            1,
        )

    def test_the_same_label_twice_is_still_refused(self):
        self.authenticate(self.company_admin)
        url = f"/api/tickets/{self.ticket.id}/staff-assignments/"
        self.client.post(
            url,
            {"user_id": self.staff.id, "time_window_label": "morning"},
            format="json",
        )
        again = self.client.post(
            url,
            {"user_id": self.staff.id, "time_window_label": "morning"},
            format="json",
        )
        self.assertEqual(again.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(again.data["code"], ERR_STAFF_ALREADY_ASSIGNED)

    def test_a_dated_slot_for_the_same_person_is_now_refused_too(self):
        """W26 — §6c kept the AM/PM split as a second ROW. The owner's
        decision replaces it: the person holds one slot and the dated
        window is a PATCH on it, so this create is refused and the
        original row is untouched."""
        self.authenticate(self.company_admin)
        url = f"/api/tickets/{self.ticket.id}/staff-assignments/"
        self.client.post(url, {"user_id": self.staff.id}, format="json")
        dated = self.client.post(
            url,
            {
                "user_id": self.staff.id,
                "scheduled_start_at": timezone.now().isoformat(),
            },
            format="json",
        )
        self.assertEqual(dated.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(dated.data["code"], ERR_STAFF_ALREADY_ASSIGNED)
        self.assertEqual(
            TicketStaffAssignment.objects.filter(
                ticket=self.ticket, user=self.staff
            ).count(),
            1,
        )
