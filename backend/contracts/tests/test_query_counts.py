"""
Sprint 160 — the contract list costs a CONSTANT number of queries.

The thing being prevented is the obvious implementation of a list page
whose money comes from a derived active revision: resolve the revision
per row, aggregate its lines per row, fetch its buildings per row.
That looks fine on the four contracts in a seed database and issues
30-odd queries per page on a real tenant.

So the assertion is not "few queries" — a number chosen today drifts
the moment a field is added. It is that a TEN-row page costs EXACTLY
what a TWO-row page costs. That property survives refactors and fails
loudly the moment anything per-row creeps back in.
"""
from __future__ import annotations

from datetime import date

from django.test import TestCase
from rest_framework.test import APIClient

from buildings.models import Building
from companies.models import Company, CompanyUserMembership
from customers.models import Customer

from .fixtures import CONTRACTS_URL, STATS_URL, mk_user, make_contract


class ContractListQueryCountTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.company = Company.objects.create(name="Prov", slug="prov-160-q")
        cls.admin = mk_user("ca-q-160@example.com", "COMPANY_ADMIN")
        CompanyUserMembership.objects.create(
            user=cls.admin, company=cls.company
        )
        cls.customer = Customer.objects.create(
            company=cls.company, name="Customer"
        )
        cls.buildings = [
            Building.objects.create(
                company=cls.company, name=f"Building {index}"
            )
            for index in range(4)
        ]

    def seed(self, count, offset=0):
        """`count` contracts, each with several buildings and several
        projects, so a per-row implementation has something to fan out
        over. A fixture with one line per contract would let an N+1 hide.
        """
        for index in range(count):
            make_contract(
                company=self.company,
                customer=self.customer,
                contract_no=f"CNT-2026-{offset + index:04d}",
                start_date=date(2026, 1, 1),
                buildings=self.buildings[: (index % 3) + 1],
                lines=[
                    (f"Project {n}", f"{100 + n}.00", f"{n + 1}.00")
                    for n in range((index % 3) + 1)
                ],
            )

    def client_for_admin(self):
        client = APIClient()
        client.force_authenticate(user=self.admin)
        return client

    def test_a_ten_row_page_costs_what_a_two_row_page_costs(self):
        client = self.client_for_admin()
        self.seed(2)
        with CaptureQueries(self) as two_rows:
            response = client.get(CONTRACTS_URL, {"page_size": 2})
        self.assertEqual(len(response.json()["results"]), 2)

        # The 2-row measurement becomes the budget the 10-row page must
        # meet. `assertNumQueries` with a MEASURED number rather than a
        # typed-in one: the assertion is the equality, and it cannot go
        # stale when an unrelated change adds a legitimate query.
        self.seed(8, offset=100)
        with self.assertNumQueries(two_rows.count):
            response = client.get(CONTRACTS_URL, {"page_size": 10})
        self.assertEqual(len(response.json()["results"]), 10)

    def test_the_stats_endpoint_is_constant_too(self):
        client = self.client_for_admin()
        self.seed(2)
        with CaptureQueries(self) as few:
            self.assertEqual(client.get(STATS_URL).status_code, 200)
        self.seed(20, offset=200)
        with CaptureQueries(self) as many:
            self.assertEqual(client.get(STATS_URL).status_code, 200)
        self.assertEqual(few.count, many.count)


class CaptureQueries:
    """Count the queries a block issues, without asserting a literal.

    `assertNumQueries` needs a number up front; what this module tests
    is that TWO measurements agree, which is a different shape. Django's
    `CaptureQueriesContext` does exactly this, and is used directly
    rather than reimplemented.
    """

    def __init__(self, test_case):
        from django.db import connection
        from django.test.utils import CaptureQueriesContext

        self._ctx = CaptureQueriesContext(connection)
        self._test_case = test_case

    def __enter__(self):
        self._ctx.__enter__()
        return self

    def __exit__(self, *exc_info):
        result = self._ctx.__exit__(*exc_info)
        self.count = len(self._ctx.captured_queries)
        return result
