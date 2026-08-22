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
    """§6c — Ahmet Yildiz, twice on ticket 355, both rows identical."""

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
        self.assertEqual(second.data["code"], "duplicate_flat_assignment")
        self.assertEqual(
            TicketStaffAssignment.objects.filter(
                ticket=self.ticket, user=self.staff
            ).count(),
            1,
        )

    def test_a_dated_slot_for_the_same_person_is_still_allowed(self):
        """The dropped uniqueness exists for the AM/PM split. It stays."""
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
        self.assertEqual(dated.status_code, status.HTTP_201_CREATED)
        self.assertEqual(
            TicketStaffAssignment.objects.filter(
                ticket=self.ticket, user=self.staff
            ).count(),
            2,
        )
