"""
Sprint 170 §1 — the Work Plan's `?scope=company`.

The Work Plan was built on `/api/tickets/my-slots/` and its nav entry
was gated to STAFF and BUILDING_MANAGER, so a SUPER_ADMIN could not
reach it at all. Opening the gate alone would not have been enough: an
admin holds no assignment rows of their own, so the page would have
rendered a permanently empty week — a nav entry leading to an empty
page is the same defect as one leading to a 403.

So the endpoint answers `?scope=company` with the TEAM's slots. What
these pin is that the widening is a SCOPE, not a hole:

  * without the param nothing changes — still only the caller's rows;
  * with it, a provider admin gets the team's, expressed through
    `scope_tickets_for` so it can never show a ticket they could not
    already open;
  * a STAFF user passing the param gets exactly what they got before.
    The param is not a way to escalate.
"""
from __future__ import annotations

from rest_framework import status
from rest_framework.test import APITestCase

from accounts.models import UserRole
from tickets.models import (
    Ticket,
    TicketStaffAssignment,
    TicketType,
)
from test_utils import TenantFixtureMixin


URL = "/api/tickets/my-slots/"


class AgendaScopeTests(TenantFixtureMixin, APITestCase):
    def setUp(self):
        super().setUp()
        # The shared fixture has no STAFF user, and slots are only ever
        # held by STAFF — the staff-assign endpoint refuses any other
        # role — so this module makes its own two.
        self.worker = self.make_user("worker-170@example.com", UserRole.STAFF)
        self.other_worker = self.make_user(
            "worker2-170@example.com", UserRole.STAFF
        )
        self.ticket = Ticket.objects.create(
            company=self.company,
            customer=self.customer,
            building=self.building,
            title="Slot ticket",
            description="x",
            type=TicketType.REQUEST,
            created_by=self.super_admin,
        )
        # A slot held by the STAFF user, and none held by the admin —
        # which is the situation that made the page empty for an admin.
        self.staff_slot = TicketStaffAssignment.objects.create(
            ticket=self.ticket,
            user=self.worker,
            assigned_by=self.super_admin,
        )

    def ids(self, response):
        return {row["id"] for row in response.data["results"]}

    def test_without_the_param_an_admin_still_sees_only_their_own(self):
        """The default is unchanged, which is what makes this additive."""
        self.client.force_authenticate(self.super_admin)
        response = self.client.get(URL)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(self.ids(response), set())

    def test_with_the_param_an_admin_sees_the_teams_slots(self):
        self.client.force_authenticate(self.super_admin)
        response = self.client.get(URL, {"scope": "company"})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn(self.staff_slot.id, self.ids(response))

    def test_a_staff_user_cannot_widen_with_the_param(self):
        """The param is not an escalation: a STAFF caller gets their own
        rows whether or not they ask for the company scope."""
        other = Ticket.objects.create(
            company=self.company,
            customer=self.customer,
            building=self.building,
            title="Somebody else's",
            description="x",
            type=TicketType.REQUEST,
            created_by=self.super_admin,
        )
        theirs = TicketStaffAssignment.objects.create(
            ticket=other,
            user=self.other_worker,
            assigned_by=self.super_admin,
        )
        self.client.force_authenticate(self.worker)
        widened = self.client.get(URL, {"scope": "company"})
        plain = self.client.get(URL)
        self.assertEqual(widened.status_code, status.HTTP_200_OK)
        self.assertEqual(self.ids(widened), self.ids(plain))
        self.assertNotIn(theirs.id, self.ids(widened))

    def test_a_customer_user_gets_nothing_either_way(self):
        self.client.force_authenticate(self.customer_user)
        for params in ({}, {"scope": "company"}):
            with self.subTest(params=params):
                response = self.client.get(URL, params)
                self.assertEqual(response.status_code, status.HTTP_200_OK)
                self.assertEqual(self.ids(response), set())
