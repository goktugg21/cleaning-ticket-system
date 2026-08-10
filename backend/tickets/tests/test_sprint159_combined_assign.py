"""
Sprint 159 §2 — the ticket endpoint takes managers AND workers in one
request, exactly like its extra-work sibling.

Two ticket-specific things are pinned on top of the shared properties:

  * a WORKER lands as a `TicketStaffAssignment` (a dated operational
    SLOT, unscheduled here) and a MANAGER as a
    `TicketManagerAssignment` — one body, two different models, and
    neither leaks into the other;
  * one slot per (ticket, person), never a second, even when the same
    body is posted twice.
"""
from rest_framework import status
from rest_framework.test import APITestCase

from accounts.models import UserRole
from buildings.models import BuildingManagerAssignment, BuildingStaffVisibility
from test_utils import TenantFixtureMixin
from tickets.models import TicketManagerAssignment, TicketStaffAssignment


BULK_URL = "/api/tickets/bulk-assign/"


class TicketCombinedAssignTests(TenantFixtureMixin, APITestCase):
    def setUp(self):
        super().setUp()
        self.worker = self.make_user("t159-worker@example.com", UserRole.STAFF)
        BuildingStaffVisibility.objects.create(
            user=self.worker, building=self.building
        )
        self.worker_two = self.make_user("t159-worker2@example.com", UserRole.STAFF)
        BuildingStaffVisibility.objects.create(
            user=self.worker_two, building=self.building
        )
        self.site_manager = self.make_user(
            "t159-manager@example.com", UserRole.BUILDING_MANAGER
        )
        BuildingManagerAssignment.objects.create(
            user=self.site_manager, building=self.building
        )

    def _combined(self, workers, managers, mode="assign"):
        return {
            "tickets": [self.ticket.id],
            "workers": [u.id for u in workers],
            "managers": [u.id for u in managers],
            "mode": mode,
        }

    def test_one_body_creates_a_slot_and_a_manager_row(self):
        self.authenticate(self.company_admin)
        response = self.client.post(
            BULK_URL,
            self._combined([self.worker, self.worker_two], [self.site_manager]),
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertEqual(response.data["created"], 3)
        self.assertEqual(
            set(
                TicketStaffAssignment.objects.filter(
                    ticket=self.ticket
                ).values_list("user_id", flat=True)
            ),
            {self.worker.id, self.worker_two.id},
        )
        self.assertEqual(
            set(
                TicketManagerAssignment.objects.filter(
                    ticket=self.ticket
                ).values_list("user_id", flat=True)
            ),
            {self.site_manager.id},
        )

    def test_an_ineligible_manager_rejects_the_workers_with_it(self):
        """A STAFF member named as a MANAGER makes the manager group
        unresolvable; the workers in the same body must not land."""
        self.authenticate(self.company_admin)
        response = self.client.post(
            BULK_URL, self._combined([self.worker], [self.worker_two]), format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(TicketStaffAssignment.objects.count(), 0)
        self.assertEqual(TicketManagerAssignment.objects.count(), 0)

    def test_a_foreign_id_and_a_fictional_id_answer_identically(self):
        """H-1 — equality of the rendered body, not merely two 400s."""
        self.authenticate(self.company_admin)
        outsider = self.make_user("t159-outsider@example.com", UserRole.STAFF)
        BuildingStaffVisibility.objects.create(
            user=outsider, building=self.other_building
        )
        foreign = self.client.post(
            BULK_URL, self._combined([outsider], [self.site_manager]), format="json"
        )
        fictional = self.client.post(
            BULK_URL,
            {
                "tickets": [self.ticket.id],
                "workers": [999_999],
                "managers": [self.site_manager.id],
            },
            format="json",
        )
        self.assertEqual(foreign.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(fictional.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(foreign.data, fictional.data)
        self.assertEqual(TicketStaffAssignment.objects.count(), 0)

    def test_posting_the_same_body_twice_makes_no_second_slot(self):
        self.authenticate(self.company_admin)
        body = self._combined([self.worker], [self.site_manager])
        self.client.post(BULK_URL, body, format="json")
        second = self.client.post(BULK_URL, body, format="json")
        self.assertEqual(second.status_code, status.HTTP_200_OK)
        self.assertEqual(second.data["created"], 0)
        self.assertEqual(second.data["already_assigned"], 2)
        self.assertEqual(TicketStaffAssignment.objects.count(), 1)
        self.assertEqual(TicketManagerAssignment.objects.count(), 1)

    def test_the_combined_shape_unassigns_both_roles(self):
        self.authenticate(self.company_admin)
        self.client.post(
            BULK_URL, self._combined([self.worker], [self.site_manager]), format="json"
        )
        response = self.client.post(
            BULK_URL,
            self._combined([self.worker], [self.site_manager], mode="unassign"),
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["removed"], 2)
        self.assertEqual(TicketStaffAssignment.objects.count(), 0)
        self.assertEqual(TicketManagerAssignment.objects.count(), 0)

    def test_the_single_role_body_still_works(self):
        self.authenticate(self.company_admin)
        response = self.client.post(
            BULK_URL,
            {
                "tickets": [self.ticket.id],
                "users": [self.worker.id],
                "role": "WORKER",
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertEqual(TicketStaffAssignment.objects.count(), 1)

    def test_a_body_naming_nobody_is_rejected(self):
        self.authenticate(self.company_admin)
        response = self.client.post(
            BULK_URL,
            {"tickets": [self.ticket.id], "workers": [], "managers": []},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(TicketStaffAssignment.objects.count(), 0)
