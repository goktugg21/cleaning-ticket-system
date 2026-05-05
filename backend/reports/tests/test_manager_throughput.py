from rest_framework import status
from rest_framework.test import APITestCase

from accounts.models import UserRole
from buildings.models import BuildingManagerAssignment
from test_utils import TenantFixtureMixin
from tickets.models import Ticket

from ._fixtures import aware, assign_to, resolve_ticket_at


URL = "/api/reports/manager-throughput/"


class ManagerThroughputTests(TenantFixtureMixin, APITestCase):
    def _make_resolved(self, when, *, assignee, company=None, building=None,
                       customer=None, creator=None):
        ticket = Ticket.objects.create(
            company=company or self.company,
            building=building or self.building,
            customer=customer or self.customer,
            created_by=creator or self.customer_user,
            title="t",
            description="t",
        )
        assign_to(ticket, assignee)
        resolve_ticket_at(ticket, when)
        return ticket

    def test_unauthenticated_returns_401(self):
        response = self.client.get(URL)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_customer_user_returns_403(self):
        self.client.force_authenticate(user=self.customer_user)
        response = self.client.get(URL)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_super_admin_lists_managers_with_resolved_counts(self):
        self._make_resolved(aware(2026, 4, 10), assignee=self.manager)
        self._make_resolved(aware(2026, 4, 11), assignee=self.manager)
        self.client.force_authenticate(user=self.super_admin)
        response = self.client.get(URL, {"from": "2026-04-09", "to": "2026-04-12"})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        managers_by_id = {m["user_id"]: m for m in response.data["managers"]}
        self.assertIn(self.manager.id, managers_by_id)
        self.assertEqual(managers_by_id[self.manager.id]["resolved_count"], 2)

    def test_resolved_at_outside_range_excluded(self):
        # Inside.
        self._make_resolved(aware(2026, 4, 10), assignee=self.manager)
        # Before.
        self._make_resolved(aware(2026, 4, 1), assignee=self.manager)
        # After.
        self._make_resolved(aware(2026, 4, 20), assignee=self.manager)
        self.client.force_authenticate(user=self.super_admin)
        response = self.client.get(URL, {"from": "2026-04-08", "to": "2026-04-15"})
        managers_by_id = {m["user_id"]: m for m in response.data["managers"]}
        self.assertEqual(managers_by_id[self.manager.id]["resolved_count"], 1)

    def test_manager_with_assignment_but_zero_resolutions_appears_with_zero(self):
        # No resolutions at all in the range. self.manager has an assignment
        # in scope so should still appear.
        self.client.force_authenticate(user=self.super_admin)
        response = self.client.get(URL, {"from": "2026-04-08", "to": "2026-04-15"})
        managers_by_id = {m["user_id"]: m for m in response.data["managers"]}
        self.assertIn(self.manager.id, managers_by_id)
        self.assertEqual(managers_by_id[self.manager.id]["resolved_count"], 0)

    def test_manager_outside_scope_excluded(self):
        # self.other_manager has BuildingManagerAssignment on self.other_building
        # (company B). When the company_admin (company A) hits the endpoint,
        # other_manager must NOT appear.
        self.client.force_authenticate(user=self.company_admin)
        response = self.client.get(URL, {"from": "2026-04-08", "to": "2026-04-15"})
        managers_by_id = {m["user_id"]: m for m in response.data["managers"]}
        self.assertNotIn(self.other_manager.id, managers_by_id)
        self.assertIn(self.manager.id, managers_by_id)

    def test_company_admin_cross_tenant_returns_403(self):
        self.client.force_authenticate(user=self.company_admin)
        response = self.client.get(URL, {"company": self.other_company.id})
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_building_manager_cross_building_returns_403(self):
        self.client.force_authenticate(user=self.manager)
        response = self.client.get(URL, {"building": self.other_building.id})
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_sort_order_resolved_desc_then_name_asc(self):
        # Add a third manager assigned to building A so we have multiple
        # managers in scope to sort.
        from django.contrib.auth import get_user_model

        third = get_user_model().objects.create_user(
            email="charlie-third@example.com",
            password=self.password,
            role=UserRole.BUILDING_MANAGER,
            full_name="Charlie Third",
        )
        BuildingManagerAssignment.objects.create(user=third, building=self.building)
        # self.manager (full_name "manager-a"): 2 resolutions
        # third  (full_name "Charlie Third"): 5 resolutions
        for _ in range(2):
            self._make_resolved(aware(2026, 4, 10), assignee=self.manager)
        for _ in range(5):
            self._make_resolved(aware(2026, 4, 10), assignee=third)
        self.client.force_authenticate(user=self.super_admin)
        response = self.client.get(URL, {"from": "2026-04-08", "to": "2026-04-15"})
        managers = response.data["managers"]
        # third has 5, manager has 2. Sort: resolved_count DESC.
        self.assertEqual(managers[0]["user_id"], third.id)
        self.assertEqual(managers[0]["resolved_count"], 5)
        # manager-a@example.com is "manager-a"; third is "Charlie Third".
        # Both with non-zero counts come first sorted by count, then by name.

    def test_company_admin_includes_themselves_with_resolutions(self):
        # COMPANY_ADMIN is a "manager" too per the spec. Resolve a ticket
        # with company_admin as the assignee and verify they appear.
        self._make_resolved(aware(2026, 4, 10), assignee=self.company_admin)
        self.client.force_authenticate(user=self.company_admin)
        response = self.client.get(URL, {"from": "2026-04-08", "to": "2026-04-15"})
        managers_by_id = {m["user_id"]: m for m in response.data["managers"]}
        self.assertIn(self.company_admin.id, managers_by_id)
        self.assertEqual(
            managers_by_id[self.company_admin.id]["resolved_count"], 1
        )

    def test_invalid_date_returns_400(self):
        self.client.force_authenticate(user=self.super_admin)
        response = self.client.get(URL, {"from": "garbage"})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_empty_scope_returns_empty_managers(self):
        self.client.force_authenticate(user=self.super_admin)
        # Future range: no resolutions there. Managers still listed if they
        # have an assignment in scope (with resolved_count=0). To get an
        # empty managers array, hit a brand-new company with no buildings.
        from companies.models import Company

        empty = Company.objects.create(name="Empty", slug="empty")
        response = self.client.get(URL, {"company": empty.id})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["managers"], [])
