"""W12 — the worker's own week fills, and only the worker's.

Two facts under test, and they are the same fact seen from both sides:

  * a STAFF member may run the standing-agreement fill for their OWN
    week (W10's promise reached the admin wizard and stopped there);
  * running it writes nothing for anybody else, whatever the request
    body says.

Plus the read half: a standing agreement is a wage-adjacent personnel
record, so a non-manager listing them sees only their own.
"""
from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from timesheets.models import ContractHours, TimeEntry

from .fixtures import TimesheetsFixture


FILL_URL = "/api/timesheets/entries/fill-week/"
CONTRACT_HOURS_URL = "/api/timesheets/contract-hours/"

# A settled week, so `date.today()` never drifts the fixture.
ISO_YEAR, ISO_WEEK = 2026, 20
WEEK_MONDAY = date.fromisocalendar(ISO_YEAR, ISO_WEEK, 1)


class WorkerSelfFillTests(TimesheetsFixture):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.agreement_staff = ContractHours.objects.create(
            company=cls.company_a,
            employee=cls.staff_a,
            building=cls.building_a,
            hour_type=cls.normal_a,
            valid_from=date(2026, 1, 1),
            monday=Decimal("8.00"),
            tuesday=Decimal("8.00"),
            auto_fill=True,
            created_by=cls.ca_a,
        )
        cls.agreement_colleague = ContractHours.objects.create(
            company=cls.company_a,
            employee=cls.staff_a2,
            building=cls.building_a,
            hour_type=cls.normal_a,
            valid_from=date(2026, 1, 1),
            monday=Decimal("6.00"),
            auto_fill=True,
            created_by=cls.ca_a,
        )

    def _fill(self, user, **extra):
        return self.api(user).post(
            FILL_URL,
            {"iso_year": ISO_YEAR, "iso_week": ISO_WEEK, **extra},
            format="json",
        )

    def test_staff_fills_own_week(self):
        response = self._fill(self.staff_a)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["created"], 1)
        mine = TimeEntry.objects.filter(
            employee=self.staff_a, iso_year=ISO_YEAR, iso_week=ISO_WEEK
        )
        self.assertEqual(mine.count(), 2)
        self.assertEqual(
            sorted(str(e.date) for e in mine),
            [str(WEEK_MONDAY), str(WEEK_MONDAY + timedelta(days=1))],
        )

    def test_staff_fill_writes_nothing_for_a_colleague(self):
        self._fill(self.staff_a)
        self.assertFalse(
            TimeEntry.objects.filter(employee=self.staff_a2).exists()
        )

    def test_staff_cannot_fill_for_someone_else(self):
        """A named `employee` is ignored, not obeyed."""
        response = self._fill(self.staff_a, employee=self.staff_a2.id)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["employee"], self.staff_a.id)
        self.assertFalse(
            TimeEntry.objects.filter(employee=self.staff_a2).exists()
        )

    def test_staff_fill_is_idempotent(self):
        self._fill(self.staff_a)
        second = self._fill(self.staff_a)
        self.assertEqual(second.data["created"], 0)
        self.assertEqual(second.data["skipped_existing"], 1)
        self.assertEqual(
            TimeEntry.objects.filter(employee=self.staff_a).count(), 2
        )

    def test_manager_still_fills_the_whole_company(self):
        response = self._fill(self.ca_a, company=self.company_a.id)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["created"], 2)
        self.assertTrue(TimeEntry.objects.filter(employee=self.staff_a).exists())
        self.assertTrue(TimeEntry.objects.filter(employee=self.staff_a2).exists())

    def test_manager_may_still_narrow_to_one_employee(self):
        response = self._fill(
            self.ca_a, company=self.company_a.id, employee=self.staff_a2.id
        )
        self.assertEqual(response.data["created"], 1)
        self.assertFalse(TimeEntry.objects.filter(employee=self.staff_a).exists())

    def test_customer_user_is_forbidden(self):
        response = self._fill(self.customer_user)
        self.assertEqual(response.status_code, 403)

    def test_other_company_staff_fills_nothing(self):
        response = self._fill(self.staff_b)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["created"], 0)
        self.assertFalse(
            TimeEntry.objects.filter(company=self.company_a).exists()
        )


class ContractHoursReadIsSelfScopedTests(TimesheetsFixture):
    """A standing agreement is personnel data. The list endpoint admits
    every provider-side role and used to hand a STAFF member the whole
    company's."""

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        for employee in (cls.staff_a, cls.staff_a2, cls.bm_a):
            ContractHours.objects.create(
                company=cls.company_a,
                employee=employee,
                building=cls.building_a,
                hour_type=cls.normal_a,
                valid_from=date(2026, 1, 1),
                monday=Decimal("8.00"),
                created_by=cls.ca_a,
            )

    def test_staff_sees_only_their_own(self):
        response = self.api(self.staff_a).get(CONTRACT_HOURS_URL)
        self.assertEqual(response.status_code, 200)
        rows = response.data["results"]
        self.assertEqual([row["employee"] for row in rows], [self.staff_a.id])

    def test_building_manager_sees_only_their_own(self):
        response = self.api(self.bm_a).get(CONTRACT_HOURS_URL)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            [row["employee"] for row in response.data["results"]],
            [self.bm_a.id],
        )

    def test_company_admin_still_sees_the_company(self):
        response = self.api(self.ca_a).get(CONTRACT_HOURS_URL)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data["results"]), 3)

    def test_customer_user_is_forbidden(self):
        response = self.api(self.customer_user).get(CONTRACT_HOURS_URL)
        self.assertEqual(response.status_code, 403)
