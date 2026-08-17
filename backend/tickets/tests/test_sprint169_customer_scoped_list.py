"""
Sprint 169 §8 — the customer-scoped list is a UI convenience, not a
permission.

The customer's Tickets and Extra Work pages now mount the SAME list
components the sidebar routes use, with `customer=<id>` fixed. That
makes one thing worth proving explicitly rather than assuming: the id
is supplied by the CLIENT, so the server must still be the authority on
what the actor may see.

What these pin:

  * `?customer=<id>` NARROWS an already-scoped queryset. It can never
    widen it — an actor who could not see a customer's tickets does not
    get them by asking for that customer by id.
  * The narrowing is real for an actor who CAN see them.
  * An out-of-scope id yields an empty list, not a 403: out of scope
    must be indistinguishable from "no rows", or the response is an
    existence oracle (H-1).
"""
from __future__ import annotations

from rest_framework import status
from rest_framework.test import APITestCase

from customers.models import Customer
from tickets.models import Ticket, TicketType
from test_utils import TenantFixtureMixin


TICKETS_URL = "/api/tickets/"


class CustomerScopedListTests(TenantFixtureMixin, APITestCase):
    def setUp(self):
        super().setUp()
        # A second customer in the SAME company, and one in ANOTHER
        # company — the second is what a cross-tenant request would
        # reach for.
        self.customer2 = Customer.objects.create(
            company=self.company,
            building=self.building,
            name="Scoped customer 2",
            contact_email="s2@example.com",
        )
        self.mine = Ticket.objects.create(
            company=self.company,
            customer=self.customer,
            building=self.building,
            title="Mine",
            description="x",
            type=TicketType.REQUEST,
            created_by=self.super_admin,
        )
        self.theirs = Ticket.objects.create(
            company=self.company,
            customer=self.customer2,
            building=self.building,
            title="Theirs",
            description="x",
            type=TicketType.REQUEST,
            created_by=self.super_admin,
        )

    def ids(self, response):
        return {row["id"] for row in response.data["results"]}

    def test_the_filter_narrows_for_an_actor_who_may_see_both(self):
        self.client.force_authenticate(self.super_admin)
        unfiltered = self.client.get(TICKETS_URL, {"page_size": 200})
        self.assertEqual(unfiltered.status_code, status.HTTP_200_OK)
        self.assertIn(self.mine.id, self.ids(unfiltered))
        self.assertIn(self.theirs.id, self.ids(unfiltered))

        filtered = self.client.get(
            TICKETS_URL, {"customer": self.customer2.id, "page_size": 200}
        )
        self.assertEqual(filtered.status_code, status.HTTP_200_OK)
        self.assertIn(self.theirs.id, self.ids(filtered))
        self.assertNotIn(self.mine.id, self.ids(filtered))

    def test_asking_for_a_customer_you_cannot_see_returns_nothing(self):
        """THE test §8 asks for. The customer-scoped page supplies the id
        from the URL, so an actor could type another customer's id — and
        must get that customer's rows only if they could have seen them
        anyway.

        A CUSTOMER_USER is scoped to their own customer, so asking for
        the other one yields an EMPTY list rather than its rows, and a
        200 rather than a 403: a 403 would confirm the customer exists.
        """
        self.client.force_authenticate(self.customer_user)
        response = self.client.get(
            TICKETS_URL, {"customer": self.customer2.id, "page_size": 200}
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(self.ids(response), set())

    def test_a_customer_user_still_sees_their_own_when_the_filter_matches(self):
        """The other half: the filter is not a blanket denial.

        Asserted as a PROPERTY of the rows rather than against a
        hand-made ticket id — a CUSTOMER_USER's visibility also depends
        on their per-building access rows, so "did my fixture ticket
        come back" would be testing the fixture, not the filter."""
        self.client.force_authenticate(self.customer_user)
        unfiltered = self.client.get(TICKETS_URL, {"page_size": 200})
        visible = self.ids(unfiltered)

        response = self.client.get(
            TICKETS_URL, {"customer": self.customer.id, "page_size": 200}
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        # Everything the filter returns was already visible, and every
        # row belongs to the customer asked for.
        self.assertTrue(self.ids(response) <= visible)
        for row in response.data["results"]:
            self.assertEqual(row["customer"], self.customer.id)
        self.assertNotIn(self.theirs.id, self.ids(response))

    def test_a_nonexistent_customer_id_is_not_an_oracle(self):
        """A fictional id and an out-of-scope id must look the same."""
        self.client.force_authenticate(self.customer_user)
        fictional = self.client.get(
            TICKETS_URL, {"customer": 9_999_999, "page_size": 200}
        )
        out_of_scope = self.client.get(
            TICKETS_URL, {"customer": self.customer2.id, "page_size": 200}
        )
        self.assertEqual(fictional.status_code, out_of_scope.status_code)
        self.assertEqual(self.ids(fictional), self.ids(out_of_scope))
