"""
Sprint 185 E §1 — meldingen per category per building.

The report the owner asked for in these words, and the tests are written
against what he would check first:

  * the counts are right, bucketed by building and by category;
  * an UNCATEGORISED melding is a row, not a gap — otherwise the report's
    total disagrees with the number of meldingen in the period, which is
    the first thing anyone checks;
  * it costs the same number of queries whatever the period holds;
  * it is provider-side only;
  * it is scoped, and the page's own company/building narrowing composes
    with that scope rather than replacing it.
"""
from __future__ import annotations

from datetime import date, timedelta

from django.utils import timezone
from rest_framework.test import APITestCase

from test_utils import TenantFixtureMixin
from tickets.models import Ticket, WorkCategory

URL = "/api/reports/meldingen-by-category/"


class MeldingenByCategoryTests(TenantFixtureMixin, APITestCase):
    def setUp(self):
        super().setUp()
        self.sanitair = WorkCategory.objects.create(
            company=self.company, name="Sanitair"
        )
        self.glas = WorkCategory.objects.create(
            company=self.company, name="Glasbewassing"
        )
        # The fixture's own ticket, categorised.
        self.ticket.category = self.sanitair
        self.ticket.save(update_fields=["category"])

    def _melding(self, category=None, building=None):
        return Ticket.objects.create(
            company=self.company,
            building=building or self.building,
            customer=self.customer,
            created_by=self.customer_user,
            title="Melding",
            description="x",
            category=category,
        )

    def _params(self):
        today = timezone.localdate()
        return {
            "from": (today - timedelta(days=7)).isoformat(),
            "to": today.isoformat(),
        }

    def as_(self, user):
        self.client.force_authenticate(user=user)
        return self.client

    def test_it_counts_meldingen_per_category_per_building(self):
        self._melding(category=self.sanitair)
        self._melding(category=self.glas)

        response = self.as_(self.company_admin).get(URL, self._params())
        self.assertEqual(response.status_code, 200, response.data)

        buckets = {b["building"]: b for b in response.data["buildings"]}
        bucket = buckets[self.building.id]
        counts = {
            row["category_name"]: row["count"] for row in bucket["categories"]
        }
        self.assertEqual(counts["Sanitair"], 2)
        self.assertEqual(counts["Glasbewassing"], 1)
        self.assertEqual(bucket["total"], 3)
        self.assertEqual(response.data["total"], 3)

    def test_an_uncategorised_melding_is_a_row_not_a_gap(self):
        """The report's total must equal the number of meldingen in the
        period, or the first thing an operator checks is already wrong."""
        self._melding(category=None)

        response = self.as_(self.company_admin).get(URL, self._params())
        bucket = response.data["buildings"][0]
        rows = {row["category_name"]: row["count"] for row in bucket["categories"]}
        self.assertIn(None, rows)
        self.assertEqual(rows[None], 1)
        self.assertEqual(response.data["total"], 2)
        self.assertEqual(response.data["uncategorised"], 1)

    def test_it_costs_the_same_number_of_queries_whatever_the_period_holds(self):
        """Two aggregates, flat. A report that got slower as a tenant got
        busier would stop being opened."""
        self.as_(self.company_admin).get(URL, self._params())  # warm auth
        with self.assertNumQueries(2):
            from reports.category_report import build_meldingen_by_category

            today = timezone.localdate()
            build_meldingen_by_category(
                self.company_admin, today - timedelta(days=7), today
            )

        for _ in range(10):
            self._melding(category=self.glas)

        with self.assertNumQueries(2):
            from reports.category_report import build_meldingen_by_category

            today = timezone.localdate()
            build_meldingen_by_category(
                self.company_admin, today - timedelta(days=7), today
            )

    def test_a_staff_user_is_denied(self):
        from accounts.models import UserRole

        staff = self.make_user("staff-cat@example.com", UserRole.STAFF)
        response = self.as_(staff).get(URL, self._params())
        self.assertEqual(response.status_code, 403)

    def test_a_customer_user_is_denied(self):
        response = self.as_(self.customer_user).get(URL, self._params())
        self.assertEqual(response.status_code, 403)

    def test_another_tenants_meldingen_are_not_counted(self):
        """H-1: the other company's melding exists and is categorised; it
        must not appear in this company admin's answer."""
        other_category = WorkCategory.objects.create(
            company=self.other_company, name="Foreign"
        )
        self.other_ticket.category = other_category
        self.other_ticket.save(update_fields=["category"])

        response = self.as_(self.company_admin).get(URL, self._params())
        names = {
            row["category_name"]
            for bucket in response.data["buildings"]
            for row in bucket["categories"]
        }
        self.assertNotIn("Foreign", names)

    def test_the_csv_export_renders(self):
        self._melding(category=self.glas)
        response = self.as_(self.company_admin).get(
            f"{URL}export.csv", self._params()
        )
        self.assertEqual(response.status_code, 200)
        body = b"".join(response.streaming_content).decode() if getattr(
            response, "streaming", False
        ) else response.content.decode()
        self.assertIn("Glasbewassing", body)
