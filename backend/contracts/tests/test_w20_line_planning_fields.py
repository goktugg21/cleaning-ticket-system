"""
W20 — the three planning fields on a contract line.

`frequency_per_year` (a COUNT of performances per year, never money),
`norm` (the operator's spec note) and `department` (the customer's own
label list). The test that matters most here is the tenant-scoping one:
a department of ANOTHER customer must be rejected on write — within the
same provider company and across companies alike. That is the P0 class
CLAUDE.md's H-1/H-2 invariants describe, so it is pinned before the
convenience assertions.
"""
from __future__ import annotations

from datetime import date

from customers.models import Customer, Department

from contracts.models import ContractLine
from contracts.serializers import ERR_DEPARTMENT_CROSS_CUSTOMER

from .fixtures import (
    ContractsFixture,
    line_detail_url,
    make_contract,
    revision_lines_url,
)


class LinePlanningFieldsTests(ContractsFixture):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        # An OPEN revision to write lines against: the shared fixture's
        # contracts are all in force (effective 2026-01-01, locked).
        cls.contract_open = make_contract(
            company=cls.company_a,
            customer=cls.customer_a,
            contract_type=cls.type_a,
            contract_no="CNT-2026-9001",
            buildings=[cls.building_a],
            revision_effective_from=date(2099, 1, 1),
        )
        cls.open_revision = cls.contract_open.revisions.get()

        # A SECOND customer of the SAME company — the subtler half of
        # cross-customer: same tenant, wrong customer.
        cls.customer_a2 = Customer.objects.create(
            company=cls.company_a, name="Customer A2"
        )

        cls.dept_a = Department.objects.create(
            customer=cls.customer_a, name="Kantoren"
        )
        cls.dept_a2 = Department.objects.create(
            customer=cls.customer_a2, name="Praktijken"
        )
        cls.dept_b = Department.objects.create(
            customer=cls.customer_b, name="Fabriek"
        )

    def _post_line(self, user, **overrides):
        payload = {"name": "Vloeronderhoud", **overrides}
        return self.api(user).post(
            revision_lines_url(self.open_revision.id), payload, format="json"
        )

    # -- the tenant-scoping rejection (the reason this file exists) ----

    def test_department_of_another_customer_same_company_is_rejected(self):
        response = self._post_line(self.ca_a, department=self.dept_a2.id)
        self.assertEqual(response.status_code, 400)
        self.assertIn("department", response.data)
        self.assertEqual(
            response.data["department"][0].code,
            ERR_DEPARTMENT_CROSS_CUSTOMER,
        )
        self.assertFalse(
            ContractLine.objects.filter(department=self.dept_a2).exists()
        )

    def test_department_of_another_tenants_customer_is_rejected(self):
        response = self._post_line(self.ca_a, department=self.dept_b.id)
        self.assertEqual(response.status_code, 400)
        self.assertFalse(
            ContractLine.objects.filter(department=self.dept_b).exists()
        )

    def test_update_cannot_move_a_line_to_another_customers_department(self):
        created = self._post_line(self.ca_a, department=self.dept_a.id)
        self.assertEqual(created.status_code, 201)
        response = self.api(self.ca_a).patch(
            line_detail_url(created.data["id"]),
            {"department": self.dept_a2.id},
            format="json",
        )
        self.assertEqual(response.status_code, 400)
        line = ContractLine.objects.get(id=created.data["id"])
        self.assertEqual(line.department_id, self.dept_a.id)

    # -- the three fields, written and read back --------------------------

    def test_the_three_fields_round_trip(self):
        response = self._post_line(
            self.ca_a,
            frequency_per_year=26,
            norm="180 m2/uur",
            department=self.dept_a.id,
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data["frequency_per_year"], 26)
        self.assertEqual(response.data["norm"], "180 m2/uur")
        self.assertEqual(response.data["department"], self.dept_a.id)
        self.assertEqual(response.data["department_name"], "Kantoren")

    def test_all_three_default_to_absent(self):
        # Additive: a line written the way every existing caller writes
        # one carries NULL / "" / NULL, and reads back that way.
        response = self._post_line(self.ca_a)
        self.assertEqual(response.status_code, 201)
        self.assertIsNone(response.data["frequency_per_year"])
        self.assertEqual(response.data["norm"], "")
        self.assertIsNone(response.data["department"])
        self.assertIsNone(response.data["department_name"])

    def test_deleting_the_department_keeps_the_line(self):
        # SET_NULL: retiring a label must never take agreed scope with it.
        created = self._post_line(self.ca_a, department=self.dept_a.id)
        self.assertEqual(created.status_code, 201)
        self.dept_a.delete()
        line = ContractLine.objects.get(id=created.data["id"])
        self.assertIsNone(line.department_id)
