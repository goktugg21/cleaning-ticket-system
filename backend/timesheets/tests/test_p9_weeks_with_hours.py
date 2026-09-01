"""
P-9 D3 -- `GET /api/timesheets/weeks/with-hours/`: which weeks of a year
hold saved hours, so an empty week can say where the hours are.

Pins:

  * the scope is the entries list's own: a manager reads the company's
    weeks (`?company=` narrows), a foreign company's hours never appear
    for a COMPANY_ADMIN, STAFF / BUILDING_MANAGER read only their own;
  * a week with no entries is absent (the current empty week included);
  * hours sum across people and entries, as a 2-decimal string;
  * the year bounds the answer and defaults to the current ISO year;
  * a junk year is a 400 with a stable code; a customer-side user is 403.
"""
from __future__ import annotations

import datetime as dt

from .fixtures import TimesheetsFixture


WITH_HOURS_URL = "/api/timesheets/weeks/with-hours/"


class WeeksWithHoursTests(TimesheetsFixture):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        # Company A: two people in W33, one of them again in W35.
        cls.make_entry(cls, cls.staff_a, dt.date(2026, 8, 10), cls.normal_a, "8.00")
        cls.make_entry(cls, cls.staff_a, dt.date(2026, 8, 12), cls.normal_a, "4.50")
        cls.make_entry(cls, cls.staff_a2, dt.date(2026, 8, 11), cls.overtime_a, "8.00")
        cls.make_entry(cls, cls.staff_a, dt.date(2026, 8, 24), cls.normal_a, "3.25")
        # Company B: one person in W34.
        cls.make_entry(cls, cls.staff_b, dt.date(2026, 8, 18), cls.normal_b, "6.00")
        # Last year, company A: proves the year bound.
        cls.make_entry(cls, cls.staff_a, dt.date(2025, 12, 24), cls.normal_a, "2.00")

    def _get(self, user, **params):
        response = self.api(user).get(WITH_HOURS_URL, params)
        self.assertEqual(response.status_code, 200, response.data)
        return response.data

    @staticmethod
    def _weeks(data):
        return [(w["iso_week"], w["hours"], w["entries"]) for w in data["weeks"]]

    def test_company_admin_reads_only_the_company_weeks(self):
        data = self._get(self.ca_a, iso_year=2026)
        self.assertEqual(data["iso_year"], 2026)
        self.assertEqual(
            self._weeks(data), [(33, "20.50", 3), (35, "3.25", 1)]
        )
        for week in data["weeks"]:
            self.assertEqual(week["iso_year"], 2026)

    def test_foreign_company_never_appears(self):
        data = self._get(self.ca_b, iso_year=2026)
        self.assertEqual(self._weeks(data), [(34, "6.00", 1)])

    def test_super_admin_reads_all_unless_narrowed(self):
        every = self._get(self.sa, iso_year=2026)
        self.assertEqual(
            self._weeks(every),
            [(33, "20.50", 3), (34, "6.00", 1), (35, "3.25", 1)],
        )
        narrowed = self._get(self.sa, iso_year=2026, company=self.company_a.id)
        self.assertEqual(
            self._weeks(narrowed), [(33, "20.50", 3), (35, "3.25", 1)]
        )

    def test_staff_reads_own_weeks_only(self):
        data = self._get(self.staff_a, iso_year=2026)
        self.assertEqual(
            self._weeks(data), [(33, "12.50", 2), (35, "3.25", 1)]
        )
        colleague = self._get(self.staff_a2, iso_year=2026)
        self.assertEqual(self._weeks(colleague), [(33, "8.00", 1)])
        # Naming the company does not widen a worker's answer.
        widened = self._get(self.staff_a, iso_year=2026, company=self.company_a.id)
        self.assertEqual(self._weeks(widened), self._weeks(data))

    def test_building_manager_reads_own_weeks_only(self):
        self.assertEqual(self._weeks(self._get(self.bm_a, iso_year=2026)), [])

    def test_empty_weeks_are_absent(self):
        data = self._get(self.ca_a, iso_year=2026)
        weeks = [w["iso_week"] for w in data["weeks"]]
        self.assertNotIn(34, weeks)
        self.assertNotIn(dt.date.today().isocalendar()[1], weeks)
        for week in data["weeks"]:
            self.assertGreater(week["entries"], 0)

    def test_year_bounds_and_defaults(self):
        last_year = self._get(self.ca_a, iso_year=2025)
        self.assertEqual(self._weeks(last_year), [(52, "2.00", 1)])
        default = self._get(self.ca_a)
        self.assertEqual(default["iso_year"], dt.date.today().isocalendar()[0])
        for week in default["weeks"]:
            self.assertEqual(week["iso_year"], default["iso_year"])

    def test_junk_year_is_a_400(self):
        response = self.api(self.ca_a).get(WITH_HOURS_URL, {"iso_year": "abc"})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data["iso_year"][0].code, "iso_year_invalid")
        response = self.api(self.ca_a).get(WITH_HOURS_URL, {"iso_year": "20260"})
        self.assertEqual(response.status_code, 400)

    def test_customer_user_is_forbidden(self):
        response = self.api(self.customer_user).get(WITH_HOURS_URL, {"iso_year": 2026})
        self.assertEqual(response.status_code, 403)
