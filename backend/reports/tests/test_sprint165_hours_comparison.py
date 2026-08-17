"""
Sprint 165 §5 — contracted hours against worked hours.

What these pin, beyond "it adds up": the module-independence rule the
report exists to respect, the union semantics (a missing side is zero,
never a dropped row), the scoping floor, and that the read costs a
constant number of queries.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from rest_framework import status
from rest_framework.test import APITestCase

from accounts.models import UserRole
from buildings.models import Building, BuildingStaffVisibility
from companies.models import Company, CompanyUserMembership
from customers.models import Customer
from contracts.models import BillingPeriod
from contracts.tests.fixtures import make_contract
from timesheets.models import HourType, TimeEntry


URL = "/api/reports/hours-comparison/"


def mk_user(email, role):
    from django.contrib.auth import get_user_model

    return get_user_model().objects.create_user(
        email=email, password="StrongerTestPassword165!", role=role,
        full_name=email.split("@")[0],
    )


class HoursComparisonTests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.company = Company.objects.create(name="Prov", slug="prov-165")
        cls.other = Company.objects.create(name="Other", slug="other-165")
        cls.customer = Customer.objects.create(
            company=cls.company, name="Customer"
        )
        cls.building = Building.objects.create(
            company=cls.company, name="Hoofdkantoor"
        )
        cls.building_b = Building.objects.create(
            company=cls.company, name="Depot"
        )

        cls.sa = mk_user("sa-165@example.com", UserRole.SUPER_ADMIN)
        cls.ca = mk_user("ca-165@example.com", UserRole.COMPANY_ADMIN)
        CompanyUserMembership.objects.create(user=cls.ca, company=cls.company)
        cls.staff = mk_user("staff-165@example.com", UserRole.STAFF)
        BuildingStaffVisibility.objects.create(
            user=cls.staff, building=cls.building
        )
        cls.customer_user = mk_user("cu-165@example.com", UserRole.CUSTOMER_USER)

        cls.hour_type = HourType.objects.create(
            company=cls.company, name="Normale uren"
        )

        # 40 contracted hours a month at the head office.
        cls.contract = make_contract(
            company=cls.company,
            customer=cls.customer,
            contract_no="CNT-2026-7001",
            buildings=[cls.building],
            lines=[("Schoonmaak", "1000.00", "40.00")],
            start_date=date(2026, 1, 1),
        )

    def worked(self, employee, building, day, hours):
        return TimeEntry.objects.create(
            company=self.company,
            employee=employee,
            building=building,
            date=day,
            hour_type=self.hour_type,
            hours=Decimal(hours),
            multiplier_snapshot=Decimal("1.00"),
            created_by=employee,
        )

    def get(self, user, **params):
        self.client.force_authenticate(user=user)
        return self.client.get(URL, {"year": 2026, "month": 3, **params})

    # ---- the comparison itself ---------------------------------------

    def test_it_reports_contracted_worked_and_the_difference(self):
        self.worked(self.staff, self.building, date(2026, 3, 4), "13.00")

        response = self.get(self.ca)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        row = next(
            r for r in response.json()["rows"]
            if r["building"] == self.building.id
        )
        self.assertEqual(Decimal(row["contracted_hours"]), Decimal("40.00"))
        self.assertEqual(Decimal(row["worked_hours"]), Decimal("13.00"))
        # Worked MINUS contracted, so the sign says under or over.
        self.assertEqual(Decimal(row["difference"]), Decimal("-27.00"))

    def test_over_worked_reads_positive(self):
        self.worked(self.staff, self.building, date(2026, 3, 4), "45.00")
        row = next(
            r for r in self.get(self.ca).json()["rows"]
            if r["building"] == self.building.id
        )
        self.assertEqual(Decimal(row["difference"]), Decimal("5.00"))

    def test_a_quarterly_contract_is_normalised_to_the_month(self):
        """Both sides have to be on the same basis, and the month is the
        only one they share."""
        make_contract(
            company=self.company,
            customer=self.customer,
            contract_no="CNT-2026-7002",
            buildings=[self.building_b],
            lines=[("Kwartaal", "3000.00", "120.00")],
            start_date=date(2026, 1, 1),
            billing_period=BillingPeriod.QUARTERLY,
        )
        row = next(
            r for r in self.get(self.ca).json()["rows"]
            if r["building"] == self.building_b.id
        )
        self.assertEqual(Decimal(row["contracted_hours"]), Decimal("40.00"))

    # ---- the union: a missing side is ZERO, not a dropped row --------

    def test_a_building_with_no_worked_hours_still_appears(self):
        """The row an operator most needs: contracted, and nobody came."""
        rows = self.get(self.ca).json()["rows"]
        row = next(r for r in rows if r["building"] == self.building.id)
        self.assertEqual(Decimal(row["contracted_hours"]), Decimal("40.00"))
        self.assertEqual(Decimal(row["worked_hours"]), Decimal("0.00"))

    def test_a_building_with_no_contract_still_appears(self):
        self.worked(self.staff, self.building_b, date(2026, 3, 5), "6.00")
        rows = self.get(self.ca).json()["rows"]
        row = next(r for r in rows if r["building"] == self.building_b.id)
        self.assertEqual(Decimal(row["contracted_hours"]), Decimal("0.00"))
        self.assertEqual(Decimal(row["worked_hours"]), Decimal("6.00"))

    def test_hours_outside_the_month_are_not_counted(self):
        self.worked(self.staff, self.building, date(2026, 2, 27), "8.00")
        self.worked(self.staff, self.building, date(2026, 4, 1), "8.00")
        row = next(
            r for r in self.get(self.ca).json()["rows"]
            if r["building"] == self.building.id
        )
        self.assertEqual(Decimal(row["worked_hours"]), Decimal("0.00"))

    # ---- the employee breakdown is the WORKED side only --------------

    def test_the_employee_breakdown_is_worked_hours(self):
        other = mk_user("staff2-165@example.com", UserRole.STAFF)
        BuildingStaffVisibility.objects.create(
            user=other, building=self.building
        )
        self.worked(self.staff, self.building, date(2026, 3, 4), "8.00")
        self.worked(other, self.building, date(2026, 3, 5), "5.00")

        row = next(
            r for r in self.get(self.ca).json()["rows"]
            if r["building"] == self.building.id
        )
        by_id = {e["employee_id"]: e for e in row["employees"]}
        self.assertEqual(
            Decimal(by_id[self.staff.id]["worked_hours"]), Decimal("8.00")
        )
        self.assertEqual(
            Decimal(by_id[other.id]["worked_hours"]), Decimal("5.00")
        )
        # No contracted figure per employee: a contract has no employee
        # dimension, and inventing an allocation would be a number
        # nobody agreed.
        self.assertNotIn("contracted_hours", by_id[self.staff.id])

    # ---- scoping -----------------------------------------------------

    def test_customer_roles_get_nothing(self):
        self.client.force_authenticate(user=self.customer_user)
        self.assertEqual(
            self.client.get(URL).status_code, status.HTTP_403_FORBIDDEN
        )

    def test_staff_gets_nothing(self):
        self.client.force_authenticate(user=self.staff)
        self.assertEqual(
            self.client.get(URL).status_code, status.HTTP_403_FORBIDDEN
        )

    def test_anonymous_is_rejected(self):
        self.client.force_authenticate(user=None)
        self.assertIn(
            self.client.get(URL).status_code,
            (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN),
        )

    def test_a_company_admin_sees_only_their_own_company(self):
        other_customer = Customer.objects.create(
            company=self.other, name="Other customer"
        )
        other_building = Building.objects.create(
            company=self.other, name="Foreign"
        )
        make_contract(
            company=self.other,
            customer=other_customer,
            contract_no="CNT-2026-7003",
            buildings=[other_building],
            lines=[("Foreign", "500.00", "99.00")],
            start_date=date(2026, 1, 1),
        )

        rows = self.get(self.ca).json()["rows"]
        self.assertNotIn(
            other_building.id, {r["building"] for r in rows}
        )

    def test_the_company_param_narrows_and_cannot_widen(self):
        rows = self.get(self.ca, company=self.other.id).json()["rows"]
        self.assertEqual(rows, [])

    # ---- cost --------------------------------------------------------

    def test_the_read_costs_a_constant_number_of_queries(self):
        """More buildings and more contracts must not mean more queries."""
        from django.db import connection
        from django.test.utils import CaptureQueriesContext

        self.worked(self.staff, self.building, date(2026, 3, 4), "8.00")
        self.client.force_authenticate(user=self.ca)
        with CaptureQueriesContext(connection) as few:
            self.client.get(URL, {"year": 2026, "month": 3})
        baseline = len(few.captured_queries)

        for index in range(5):
            building = Building.objects.create(
                company=self.company, name=f"Extra {index}"
            )
            make_contract(
                company=self.company,
                customer=self.customer,
                contract_no=f"CNT-2026-71{index:02d}",
                buildings=[building],
                lines=[("Werk", "100.00", "10.00")],
                start_date=date(2026, 1, 1),
            )
            self.worked(self.staff, building, date(2026, 3, 6), "2.00")

        with self.assertNumQueries(baseline):
            response = self.client.get(URL, {"year": 2026, "month": 3})
        self.assertEqual(len(response.json()["rows"]), 6)

    # ---- the architectural rule this report exists to respect --------

    def test_neither_module_imports_the_other(self):
        """The reason the comparison lives in `reports` at all. Asserted
        against the SOURCE, because an accidental import would otherwise
        only show up as a circular-import crash months later."""
        import pathlib

        root = pathlib.Path(__file__).resolve().parents[2]
        for app, forbidden in (("timesheets", "contracts"), ("contracts", "timesheets")):
            for path in (root / app).rglob("*.py"):
                if "tests" in path.parts:
                    continue
                text = path.read_text()
                self.assertNotIn(
                    f"from {forbidden}",
                    text,
                    f"{path} imports {forbidden}",
                )
                self.assertNotIn(
                    f"import {forbidden}\n",
                    text,
                    f"{path} imports {forbidden}",
                )
