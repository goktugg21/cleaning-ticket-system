from rest_framework import status
from rest_framework.test import APITestCase

from test_utils import TenantFixtureMixin

from ._fixtures import aware, make_ticket_at


URL = "/api/reports/tickets-over-time/"


class TicketsOverTimeTests(TenantFixtureMixin, APITestCase):
    def _make_at(self, when, *, company=None, building=None, customer=None, creator=None):
        return make_ticket_at(
            when,
            company=company or self.company,
            building=building or self.building,
            customer=customer or self.customer,
            created_by=creator or self.customer_user,
            title="t",
            description="t",
        )

    def test_unauthenticated_returns_401(self):
        response = self.client.get(URL)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_customer_user_returns_403(self):
        self.client.force_authenticate(user=self.customer_user)
        response = self.client.get(URL)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_super_admin_default_window_returns_30_day_series(self):
        self.client.force_authenticate(user=self.super_admin)
        response = self.client.get(URL)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["granularity"], "day")
        # Default window: today - 29 days through today, inclusive => 30 buckets.
        self.assertEqual(len(response.data["series"]), 30)

    def test_explicit_range_filters_to_inside_only(self):
        # Three tickets: one inside the range, one before, one after.
        self._make_at(aware(2026, 4, 10))  # inside
        self._make_at(aware(2026, 4, 5))   # before
        self._make_at(aware(2026, 4, 16))  # after
        self.client.force_authenticate(user=self.super_admin)
        response = self.client.get(URL, {"from": "2026-04-08", "to": "2026-04-15"})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["from"], "2026-04-08")
        self.assertEqual(response.data["to"], "2026-04-15")
        self.assertEqual(response.data["total"], 1)
        # Series spans 8..15 inclusive => 8 buckets.
        self.assertEqual(len(response.data["series"]), 8)

    def test_day_granularity_for_short_range(self):
        self.client.force_authenticate(user=self.super_admin)
        # 7 days
        response = self.client.get(URL, {"from": "2026-04-01", "to": "2026-04-07"})
        self.assertEqual(response.data["granularity"], "day")
        self.assertEqual(len(response.data["series"]), 7)

    def test_week_granularity_for_medium_range(self):
        self.client.force_authenticate(user=self.super_admin)
        # 60 days
        response = self.client.get(URL, {"from": "2026-01-01", "to": "2026-03-01"})
        self.assertEqual(response.data["granularity"], "week")
        # period_starts must be Mondays.
        for bucket in response.data["series"]:
            from datetime import date

            d = date.fromisoformat(bucket["period_start"])
            self.assertEqual(d.weekday(), 0)

    def test_month_granularity_for_long_range(self):
        self.client.force_authenticate(user=self.super_admin)
        # 365 days
        response = self.client.get(URL, {"from": "2025-01-01", "to": "2025-12-31"})
        self.assertEqual(response.data["granularity"], "month")
        # 12 months: Jan..Dec 2025
        self.assertEqual(len(response.data["series"]), 12)
        self.assertEqual(response.data["series"][0]["period_start"], "2025-01-01")
        self.assertEqual(response.data["series"][-1]["period_start"], "2025-12-01")

    def test_company_admin_cross_tenant_returns_403(self):
        self.client.force_authenticate(user=self.company_admin)
        response = self.client.get(URL, {"company": self.other_company.id})
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_building_manager_cross_building_returns_403(self):
        self.client.force_authenticate(user=self.manager)
        response = self.client.get(URL, {"building": self.other_building.id})
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_company_admin_own_scope_filters_other_tenants(self):
        # baseline: self.ticket (company A) and self.other_ticket (company B).
        # Add one more ticket inside company A within range and one inside
        # company B within range; the company_admin should only see the A one.
        self._make_at(aware(2026, 4, 10))
        self._make_at(aware(2026, 4, 11), company=self.other_company,
                      building=self.other_building, customer=self.other_customer,
                      creator=self.other_customer_user)
        self.client.force_authenticate(user=self.company_admin)
        response = self.client.get(URL, {"from": "2026-04-09", "to": "2026-04-12"})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["total"], 1)

    def test_invalid_date_format_returns_400(self):
        self.client.force_authenticate(user=self.super_admin)
        response = self.client.get(URL, {"from": "2026/04/01"})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_reversed_range_returns_400(self):
        self.client.force_authenticate(user=self.super_admin)
        response = self.client.get(URL, {"from": "2026-04-15", "to": "2026-04-10"})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_empty_scope_returns_zero_total(self):
        self.client.force_authenticate(user=self.super_admin)
        response = self.client.get(URL, {"from": "2030-01-01", "to": "2030-01-07"})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["total"], 0)
        # Series still spans the requested range with all-zero counts.
        self.assertEqual(len(response.data["series"]), 7)
        self.assertTrue(all(b["count"] == 0 for b in response.data["series"]))
