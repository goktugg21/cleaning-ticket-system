"""
FE-4 (Addendum D §D.12 item 7) — multi-customer membership stays as it
is (no model change). The customer chooser's ONE input is
`/auth/me/`'s `customer_ids`: the frontend shows a picker only when it
holds more than one id (`MyDocumentsPage`), never for a single
membership. This pins the wire fact that rule reads.
"""
from __future__ import annotations

from rest_framework import status as http
from rest_framework.test import APITestCase

from customers.models import Customer, CustomerUserMembership
from test_utils import TenantFixtureMixin


class MembershipChooserTests(TenantFixtureMixin, APITestCase):
    def _me(self):
        self.client.force_authenticate(self.customer_user)
        response = self.client.get("/api/auth/me/")
        self.assertEqual(response.status_code, http.HTTP_200_OK, response.data)
        return response.data

    def test_a_single_membership_user_never_gets_a_chooser(self):
        self.assertEqual(self._me()["customer_ids"], [self.customer.id])

    def test_a_multi_membership_user_gets_every_customer_to_choose_from(self):
        second = Customer.objects.create(
            company=self.company, name="Customer A2", building=self.building
        )
        CustomerUserMembership.objects.create(
            user=self.customer_user, customer=second
        )
        ids = self._me()["customer_ids"]
        self.assertEqual(sorted(ids), sorted([self.customer.id, second.id]))
        self.assertGreater(len(ids), 1)
