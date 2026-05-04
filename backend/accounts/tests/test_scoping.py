from django.urls import reverse
from rest_framework.test import APITestCase

from test_utils import TenantFixtureMixin


class AccountScopingTests(TenantFixtureMixin, APITestCase):
    def test_me_returns_correct_scope_per_role(self):
        cases = [
            (self.super_admin, {self.company.id, self.other_company.id}, {self.building.id, self.other_building.id}, {self.customer.id, self.other_customer.id}),
            (self.company_admin, {self.company.id}, {self.building.id}, {self.customer.id}),
            (self.manager, {self.company.id}, {self.building.id}, {self.customer.id}),
            (self.customer_user, {self.company.id}, {self.building.id}, {self.customer.id}),
        ]

        for user, company_ids, building_ids, customer_ids in cases:
            self.authenticate(user)
            response = self.client.get(reverse("auth_me"))
            self.assertEqual(set(response.data["company_ids"]), company_ids)
            self.assertEqual(set(response.data["building_ids"]), building_ids)
            self.assertEqual(set(response.data["customer_ids"]), customer_ids)

    def test_cross_company_company_building_customer_lists_are_not_visible(self):
        self.authenticate(self.company_admin)
        self.assertEqual(self.response_ids(self.client.get("/api/companies/")), {self.company.id})
        self.assertEqual(self.response_ids(self.client.get("/api/buildings/")), {self.building.id})
        self.assertEqual(self.response_ids(self.client.get("/api/customers/")), {self.customer.id})

        self.authenticate(self.customer_user)
        self.assertEqual(self.response_ids(self.client.get("/api/companies/")), {self.company.id})
        self.assertEqual(self.response_ids(self.client.get("/api/buildings/")), {self.building.id})
        self.assertEqual(self.response_ids(self.client.get("/api/customers/")), {self.customer.id})
