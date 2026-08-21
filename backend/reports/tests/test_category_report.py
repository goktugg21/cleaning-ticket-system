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
from tickets.models import Ticket, TicketCategory

URL = "/api/reports/meldingen-by-category/"


class MeldingenByCategoryTests(TenantFixtureMixin, APITestCase):
    def setUp(self):
        super().setUp()
        # W13 — the catalog behind this report is now the owner's
        # seeded list, so the fixture uses two of its rows instead of
        # inventing trade names. The report's shape did not change; what
        # the rows are called did.
        self.sanitair = TicketCategory.objects.get(
            company=self.company, slug="storing"
        )
        self.glas = TicketCategory.objects.get(
            company=self.company, slug="klacht"
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
        self.assertEqual(counts["Storing"], 2)
        self.assertEqual(counts["Klacht"], 1)
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
        """THREE aggregates, flat. A report that got slower as a tenant
        got busier would stop being opened.

        W13 raised the pin from 2 to 3: the groups roll-up
        ("how many tickets in 2026, and in what groups") is its own
        aggregate rather than a Python sum of the per-building rows, for
        the same reason the per-building totals are — two numbers shown
        beside each other must not be able to disagree, and the first
        thing anyone checks is whether they do.

        What the pin protects is unchanged and is the point: the cost is
        CONSTANT in the size of the period. Three queries for one melding
        and three for ten thousand. The loop below is what proves it."""
        self.as_(self.company_admin).get(URL, self._params())  # warm auth
        with self.assertNumQueries(3):
            from reports.category_report import build_meldingen_by_category

            today = timezone.localdate()
            build_meldingen_by_category(
                self.company_admin, today - timedelta(days=7), today
            )

        for _ in range(10):
            self._melding(category=self.glas)

        # Ten times the data, the SAME three queries. This is the half
        # of the test that matters.
        with self.assertNumQueries(3):
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
        other_category = TicketCategory.objects.create(
            company=self.other_company,
            slug="foreign",
            label_nl="Foreign",
            label_en="Foreign",
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
        self.assertIn("Klacht", body)
