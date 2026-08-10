"""
Sprint 158 §1 — tickets get the same bulk assign surface extra work has,
with the same building-derived eligibility rule.

Reused, not reinvented: the eligibility comes from
`buildings.assignment_eligibility`, the same helper the extra-work
endpoint calls, so the two cannot drift on who counts as a manager.

The ticket-specific thing worth pinning is that
`TicketStaffAssignment` is NOT a plain link — since Sprint 14E each row
is a dated operational SLOT and the same staff member may hold several on
one ticket. A bulk assign therefore makes ONE unscheduled slot per pair
and refuses to make a second, because "assign these people to these
tickets" means one slot each, not another slot every time the button is
pressed.
"""
from rest_framework import status
from rest_framework.test import APITestCase

from accounts.models import UserRole
from buildings.models import BuildingManagerAssignment, BuildingStaffVisibility
from test_utils import TenantFixtureMixin
from tickets.models import TicketManagerAssignment, TicketStaffAssignment


BULK_URL = "/api/tickets/bulk-assign/"


def candidates_url(ticket_id, role):
    return f"/api/tickets/{ticket_id}/assignments/candidates/?role={role}"


class TicketBulkAssignTests(TenantFixtureMixin, APITestCase):
    def setUp(self):
        super().setUp()
        self.worker = self.make_user("t-worker@example.com", UserRole.STAFF)
        BuildingStaffVisibility.objects.create(
            user=self.worker, building=self.building
        )
        self.site_manager = self.make_user(
            "t-manager@example.com", UserRole.BUILDING_MANAGER
        )
        BuildingManagerAssignment.objects.create(
            user=self.site_manager, building=self.building
        )

    def _post(self, users, role, mode="assign", tickets=None):
        return self.client.post(
            BULK_URL,
            {
                "tickets": [t.id for t in (tickets or [self.ticket])],
                "users": [u.id for u in users],
                "role": role,
                "mode": mode,
            },
            format="json",
        )

    def test_assigns_a_worker_as_a_slot(self):
        self.authenticate(self.company_admin)
        response = self._post([self.worker], "WORKER")
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertEqual(response.data["created"], 1)
        self.assertTrue(
            TicketStaffAssignment.objects.filter(
                ticket=self.ticket, user=self.worker
            ).exists()
        )

    def test_assigning_twice_does_not_make_a_second_slot(self):
        """A staff member CAN hold several slots on one ticket, but this
        endpoint is not how a second one is made — see the module
        docstring."""
        self.authenticate(self.company_admin)
        self._post([self.worker], "WORKER")
        again = self._post([self.worker], "WORKER")
        self.assertEqual(again.data["already_assigned"], 1)
        self.assertEqual(
            TicketStaffAssignment.objects.filter(
                ticket=self.ticket, user=self.worker
            ).count(),
            1,
        )

    def test_assigns_a_manager(self):
        self.authenticate(self.company_admin)
        response = self._post([self.site_manager], "MANAGER")
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertTrue(
            TicketManagerAssignment.objects.filter(
                ticket=self.ticket, user=self.site_manager
            ).exists()
        )

    def test_a_worker_cannot_be_assigned_as_a_manager(self):
        self.authenticate(self.company_admin)
        response = self._post([self.worker], "MANAGER")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(TicketManagerAssignment.objects.count(), 0)

    def test_unassign_removes_every_slot_that_person_holds(self):
        """"Unassign this person" means all of their slots, not the
        oldest one."""
        self.authenticate(self.company_admin)
        self._post([self.worker], "WORKER")
        TicketStaffAssignment.objects.create(
            ticket=self.ticket, user=self.worker
        )
        response = self._post([self.worker], "WORKER", mode="unassign")
        self.assertEqual(response.data["removed"], 2)
        self.assertEqual(
            TicketStaffAssignment.objects.filter(
                ticket=self.ticket, user=self.worker
            ).count(),
            0,
        )

    def test_one_bad_id_rolls_the_whole_batch_back(self):
        self.authenticate(self.company_admin)
        response = self.client.post(
            BULK_URL,
            {
                "tickets": [self.ticket.id],
                "users": [self.worker.id, 999_999],
                "role": "WORKER",
                "mode": "assign",
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(TicketStaffAssignment.objects.count(), 0)

    def test_ineligible_reads_like_fictional(self):
        """H-1, on this endpoint too."""
        self.authenticate(self.company_admin)
        ineligible = self._post([self.site_manager], "WORKER")
        fictional = self.client.post(
            BULK_URL,
            {
                "tickets": [self.ticket.id],
                "users": [999_999],
                "role": "WORKER",
                "mode": "assign",
            },
            format="json",
        )
        self.assertEqual(ineligible.status_code, fictional.status_code)
        self.assertEqual(str(ineligible.data), str(fictional.data))

    def test_a_foreign_ticket_is_rejected(self):
        self.authenticate(self.company_admin)
        response = self._post([self.worker], "WORKER", tickets=[self.other_ticket])
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_customer_user_cannot_call_it(self):
        self.authenticate(self.customer_user)
        response = self._post([self.worker], "WORKER")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_staff_cannot_call_it(self):
        self.authenticate(self.worker)
        response = self._post([self.worker], "WORKER")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_every_offered_candidate_is_accepted(self):
        """Picker and validator agree by construction, here too."""
        self.authenticate(self.super_admin)
        for role in ("WORKER", "MANAGER"):
            offered = self.client.get(candidates_url(self.ticket.id, role)).data
            self.assertGreater(len(offered), 0, f"no {role} candidates")
            response = self.client.post(
                BULK_URL,
                {
                    "tickets": [self.ticket.id],
                    "users": [row["id"] for row in offered],
                    "role": role,
                    "mode": "assign",
                },
                format="json",
            )
            self.assertEqual(
                response.status_code,
                status.HTTP_200_OK,
                f"the picker offered a {role} the endpoint refused: "
                f"{response.data}",
            )
