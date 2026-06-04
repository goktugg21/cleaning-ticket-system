"""Sprint 14A — planned-occurrence status rollup endpoint.

GET /api/planned-work/planned-occurrences/stats/

Provider-only (IsProviderManager): STAFF / CUSTOMER_USER are 403 on every
method, mirroring the rest of the planned-work surface. The rollup answers
"this month, how many planned jobs completed / missed / rescheduled?" via
date_from / date_to on planned_date + a status histogram that always
carries all seven PlannedOccurrenceStatus keys (zero-padded for a stable
shape).

Test classes (per the Sprint 14A brief):
  * OccurrenceRollupCountsTests       — by_status counts across all seven
                                        statuses + total.
  * OccurrenceRollupDateRangeTests    — date_from / date_to narrow on the
                                        immutable planned_date ("this
                                        month" window).
  * OccurrenceRollupFilterTests       — building / customer filter narrows
                                        WITHIN scope; a foreign id yields
                                        zero, never 403.
  * OccurrenceRollupScopeTests        — SA all / CA own company / BM
                                        assigned buildings / STAFF 403 /
                                        CUSTOMER_USER 403 + cross-company
                                        isolation.
  * OccurrenceRollupByBuildingTests   — optional per-building breakdown.
"""
from __future__ import annotations

import datetime

from rest_framework import status
from rest_framework.test import APITestCase

from planned_work.models import PlannedOccurrence, PlannedOccurrenceStatus

from ._base import PlannedWorkFixtureMixin


STATS_URL = "/api/planned-work/planned-occurrences/stats/"

_ALL_STATUSES = [
    PlannedOccurrenceStatus.PLANNED,
    PlannedOccurrenceStatus.TICKET_CREATED,
    PlannedOccurrenceStatus.COMPLETED,
    PlannedOccurrenceStatus.MISSED,
    PlannedOccurrenceStatus.RESCHEDULED,
    PlannedOccurrenceStatus.SKIPPED,
    PlannedOccurrenceStatus.CANCELLED,
]


class _OccurrenceFixtureMixin(PlannedWorkFixtureMixin):
    def setUp(self):
        super().setUp()
        self.job = self.make_recurring_job(created_by=self.super_admin)

    def make_occurrence(
        self,
        *,
        status: str,
        planned_date: datetime.date,
        job=None,
        building=None,
        customer=None,
    ) -> PlannedOccurrence:
        # Each occurrence needs its OWN recurring job: the
        # (recurring_job, planned_date) unique constraint allows a job to
        # hold only one occurrence per date, so reusing a single shared
        # job collides the moment two statuses share a planned_date.
        # Realistically a building runs many recurring jobs, so a fresh
        # job per occurrence mirrors production.
        if job is None:
            building = building or self.building
            customer = customer or self.customer
            job = self.make_recurring_job(
                created_by=self.super_admin,
                building=building,
                customer=customer,
            )
        else:
            building = building or job.building
            customer = customer or job.customer
        return PlannedOccurrence.objects.create(
            recurring_job=job,
            company=building.company,
            building=building,
            customer=customer,
            planned_date=planned_date,
            status=status,
            source_window=self.default_window(job),
        )


class OccurrenceRollupCountsTests(_OccurrenceFixtureMixin, APITestCase):
    def setUp(self):
        super().setUp()
        # One occurrence per status, plus an extra PLANNED so PLANNED=2.
        self.day = datetime.date(2026, 6, 10)
        for st in _ALL_STATUSES:
            self.make_occurrence(status=st, planned_date=self.day)
        self.make_occurrence(
            status=PlannedOccurrenceStatus.PLANNED, planned_date=self.day
        )

    def test_rollup_counts_each_status(self):
        self.authenticate(self.super_admin)
        resp = self.client.get(STATS_URL)
        self.assertEqual(resp.status_code, status.HTTP_200_OK, resp.data)
        by_status = resp.data["by_status"]
        self.assertEqual(by_status["PLANNED"], 2)
        self.assertEqual(by_status["TICKET_CREATED"], 1)
        self.assertEqual(by_status["COMPLETED"], 1)
        self.assertEqual(by_status["MISSED"], 1)
        self.assertEqual(by_status["RESCHEDULED"], 1)
        self.assertEqual(by_status["SKIPPED"], 1)
        self.assertEqual(by_status["CANCELLED"], 1)

    def test_rollup_total_and_generated_at_present(self):
        self.authenticate(self.super_admin)
        resp = self.client.get(STATS_URL)
        self.assertEqual(resp.status_code, status.HTTP_200_OK, resp.data)
        self.assertEqual(resp.data["total"], 8)
        self.assertIn("generated_at", resp.data)
        self.assertIsNotNone(resp.data["generated_at"])

    def test_all_seven_status_keys_always_present(self):
        # No occurrences for `other` company's building — but every key must
        # still be present (zero-padded) for a stable response shape.
        self.authenticate(self.super_admin)
        resp = self.client.get(STATS_URL)
        self.assertEqual(
            set(resp.data["by_status"].keys()),
            {s.value for s in _ALL_STATUSES},
        )

    def test_zero_count_statuses_padded_when_no_rows(self):
        PlannedOccurrence.objects.all().delete()
        self.authenticate(self.super_admin)
        resp = self.client.get(STATS_URL)
        self.assertEqual(resp.status_code, status.HTTP_200_OK, resp.data)
        self.assertEqual(resp.data["total"], 0)
        self.assertEqual(
            resp.data["by_status"],
            {s.value: 0 for s in _ALL_STATUSES},
        )


class OccurrenceRollupDateRangeTests(_OccurrenceFixtureMixin, APITestCase):
    def setUp(self):
        super().setUp()
        # May, June, July — one COMPLETED each, on the immutable planned_date.
        self.make_occurrence(
            status=PlannedOccurrenceStatus.COMPLETED,
            planned_date=datetime.date(2026, 5, 31),
        )
        self.make_occurrence(
            status=PlannedOccurrenceStatus.COMPLETED,
            planned_date=datetime.date(2026, 6, 15),
        )
        self.make_occurrence(
            status=PlannedOccurrenceStatus.MISSED,
            planned_date=datetime.date(2026, 6, 20),
        )
        self.make_occurrence(
            status=PlannedOccurrenceStatus.COMPLETED,
            planned_date=datetime.date(2026, 7, 1),
        )

    def test_this_month_window_narrows_inclusive(self):
        self.authenticate(self.super_admin)
        resp = self.client.get(
            STATS_URL,
            {"date_from": "2026-06-01", "date_to": "2026-06-30"},
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK, resp.data)
        # Only the two June rows; May and July are excluded.
        self.assertEqual(resp.data["total"], 2)
        self.assertEqual(resp.data["by_status"]["COMPLETED"], 1)
        self.assertEqual(resp.data["by_status"]["MISSED"], 1)
        self.assertEqual(resp.data["from"], "2026-06-01")
        self.assertEqual(resp.data["to"], "2026-06-30")

    def test_boundary_dates_are_inclusive(self):
        self.authenticate(self.super_admin)
        # 2026-05-31 .. 2026-07-01 inclusive captures all four.
        resp = self.client.get(
            STATS_URL,
            {"date_from": "2026-05-31", "date_to": "2026-07-01"},
        )
        self.assertEqual(resp.data["total"], 4)

    def test_date_from_only_open_upper_bound(self):
        self.authenticate(self.super_admin)
        resp = self.client.get(STATS_URL, {"date_from": "2026-06-01"})
        self.assertEqual(resp.status_code, status.HTTP_200_OK, resp.data)
        # June (2) + July (1); May excluded.
        self.assertEqual(resp.data["total"], 3)

    def test_no_range_counts_all(self):
        self.authenticate(self.super_admin)
        resp = self.client.get(STATS_URL)
        self.assertEqual(resp.data["total"], 4)
        self.assertIsNone(resp.data["from"])
        self.assertIsNone(resp.data["to"])

    def test_reversed_range_rejected(self):
        self.authenticate(self.super_admin)
        resp = self.client.get(
            STATS_URL,
            {"date_from": "2026-06-30", "date_to": "2026-06-01"},
        )
        self.assertEqual(
            resp.status_code, status.HTTP_400_BAD_REQUEST, resp.data
        )

    def test_malformed_date_rejected(self):
        self.authenticate(self.super_admin)
        resp = self.client.get(STATS_URL, {"date_from": "06/2026"})
        self.assertEqual(
            resp.status_code, status.HTTP_400_BAD_REQUEST, resp.data
        )


class OccurrenceRollupFilterTests(_OccurrenceFixtureMixin, APITestCase):
    def setUp(self):
        super().setUp()
        # A second building + customer inside company A.
        from buildings.models import Building
        from customers.models import (
            Customer,
            CustomerBuildingMembership,
        )

        self.building_a2 = Building.objects.create(
            company=self.company, name="Building A2", address="Second 2"
        )
        self.customer_a2 = Customer.objects.create(
            company=self.company,
            building=self.building_a2,
            name="Customer A2",
            contact_email="a2@example.com",
        )
        CustomerBuildingMembership.objects.create(
            customer=self.customer_a2, building=self.building_a2
        )
        self.job_a2 = self.make_recurring_job(
            created_by=self.super_admin,
            building=self.building_a2,
            customer=self.customer_a2,
        )

        self.day = datetime.date(2026, 6, 10)
        # Building A: 2 COMPLETED. Building A2: 1 MISSED.
        self.make_occurrence(
            status=PlannedOccurrenceStatus.COMPLETED, planned_date=self.day
        )
        self.make_occurrence(
            status=PlannedOccurrenceStatus.COMPLETED, planned_date=self.day
        )
        self.make_occurrence(
            status=PlannedOccurrenceStatus.MISSED,
            planned_date=self.day,
            job=self.job_a2,
        )

    def test_building_filter_narrows(self):
        self.authenticate(self.super_admin)
        resp = self.client.get(
            STATS_URL, {"building_id": self.building.id}
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK, resp.data)
        self.assertEqual(resp.data["total"], 2)
        self.assertEqual(resp.data["by_status"]["COMPLETED"], 2)
        self.assertEqual(resp.data["by_status"]["MISSED"], 0)
        self.assertEqual(resp.data["filters"]["building_id"], self.building.id)

    def test_customer_filter_narrows(self):
        self.authenticate(self.super_admin)
        resp = self.client.get(
            STATS_URL, {"customer_id": self.customer_a2.id}
        )
        self.assertEqual(resp.data["total"], 1)
        self.assertEqual(resp.data["by_status"]["MISSED"], 1)

    def test_out_of_scope_building_id_yields_zero_not_403(self):
        # other_building belongs to company B — invisible to a company-A
        # admin. The filter applies WITHIN the scoped qs, so it simply
        # matches nothing; it must NOT 403 and must NOT leak company B rows.
        self.make_occurrence(
            status=PlannedOccurrenceStatus.COMPLETED,
            planned_date=self.day,
            job=self.make_recurring_job(
                created_by=self.super_admin,
                building=self.other_building,
                customer=self.other_customer,
            ),
        )
        self.authenticate(self.company_admin)
        resp = self.client.get(
            STATS_URL, {"building_id": self.other_building.id}
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK, resp.data)
        self.assertEqual(resp.data["total"], 0)

    def test_invalid_building_id_rejected(self):
        self.authenticate(self.super_admin)
        resp = self.client.get(STATS_URL, {"building_id": "abc"})
        self.assertEqual(
            resp.status_code, status.HTTP_400_BAD_REQUEST, resp.data
        )


class OccurrenceRollupScopeTests(_OccurrenceFixtureMixin, APITestCase):
    def setUp(self):
        super().setUp()
        self.day = datetime.date(2026, 6, 10)
        # Company A: 1 COMPLETED on self.building (assigned to self.manager).
        self.make_occurrence(
            status=PlannedOccurrenceStatus.COMPLETED, planned_date=self.day
        )
        # Company B: 1 MISSED.
        self.job_b = self.make_recurring_job(
            created_by=self.super_admin,
            building=self.other_building,
            customer=self.other_customer,
        )
        self.make_occurrence(
            status=PlannedOccurrenceStatus.MISSED,
            planned_date=self.day,
            job=self.job_b,
        )

    def test_super_admin_sees_all_companies(self):
        self.authenticate(self.super_admin)
        resp = self.client.get(STATS_URL)
        self.assertEqual(resp.status_code, status.HTTP_200_OK, resp.data)
        self.assertEqual(resp.data["total"], 2)
        self.assertEqual(resp.data["by_status"]["COMPLETED"], 1)
        self.assertEqual(resp.data["by_status"]["MISSED"], 1)

    def test_company_admin_sees_only_own_company(self):
        self.authenticate(self.company_admin)
        resp = self.client.get(STATS_URL)
        self.assertEqual(resp.status_code, status.HTTP_200_OK, resp.data)
        self.assertEqual(resp.data["total"], 1)
        self.assertEqual(resp.data["by_status"]["COMPLETED"], 1)
        self.assertEqual(resp.data["by_status"]["MISSED"], 0)

    def test_other_company_admin_isolated(self):
        self.authenticate(self.other_company_admin)
        resp = self.client.get(STATS_URL)
        self.assertEqual(resp.status_code, status.HTTP_200_OK, resp.data)
        self.assertEqual(resp.data["total"], 1)
        self.assertEqual(resp.data["by_status"]["MISSED"], 1)
        self.assertEqual(resp.data["by_status"]["COMPLETED"], 0)

    def test_building_manager_sees_only_assigned_buildings(self):
        self.authenticate(self.manager)
        resp = self.client.get(STATS_URL)
        self.assertEqual(resp.status_code, status.HTTP_200_OK, resp.data)
        self.assertEqual(resp.data["total"], 1)
        self.assertEqual(resp.data["by_status"]["COMPLETED"], 1)

    def test_other_building_manager_isolated(self):
        self.authenticate(self.other_manager)
        resp = self.client.get(STATS_URL)
        self.assertEqual(resp.status_code, status.HTTP_200_OK, resp.data)
        self.assertEqual(resp.data["total"], 1)
        self.assertEqual(resp.data["by_status"]["MISSED"], 1)

    def test_staff_forbidden(self):
        self.authenticate(self.staff)
        resp = self.client.get(STATS_URL)
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)

    def test_customer_user_forbidden(self):
        self.authenticate(self.customer_user)
        resp = self.client.get(STATS_URL)
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)

    def test_anonymous_unauthorized(self):
        resp = self.client.get(STATS_URL)
        self.assertIn(
            resp.status_code,
            (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN),
        )


class OccurrenceRollupByBuildingTests(_OccurrenceFixtureMixin, APITestCase):
    def setUp(self):
        super().setUp()
        from buildings.models import Building
        from customers.models import (
            Customer,
            CustomerBuildingMembership,
        )

        self.building_a2 = Building.objects.create(
            company=self.company, name="Building A2", address="Second 2"
        )
        self.customer_a2 = Customer.objects.create(
            company=self.company,
            building=self.building_a2,
            name="Customer A2",
            contact_email="a2@example.com",
        )
        CustomerBuildingMembership.objects.create(
            customer=self.customer_a2, building=self.building_a2
        )
        self.job_a2 = self.make_recurring_job(
            created_by=self.super_admin,
            building=self.building_a2,
            customer=self.customer_a2,
        )
        self.day = datetime.date(2026, 6, 10)
        self.make_occurrence(
            status=PlannedOccurrenceStatus.COMPLETED, planned_date=self.day
        )
        self.make_occurrence(
            status=PlannedOccurrenceStatus.MISSED, planned_date=self.day
        )
        self.make_occurrence(
            status=PlannedOccurrenceStatus.COMPLETED,
            planned_date=self.day,
            job=self.job_a2,
        )

    def test_by_building_breakdown_present_and_padded(self):
        self.authenticate(self.super_admin)
        resp = self.client.get(STATS_URL)
        self.assertEqual(resp.status_code, status.HTTP_200_OK, resp.data)
        self.assertIn("by_building", resp.data)
        by_building = {b["building_id"]: b for b in resp.data["by_building"]}
        self.assertIn(self.building.id, by_building)
        self.assertIn(self.building_a2.id, by_building)
        # Building A: 1 COMPLETED + 1 MISSED.
        a = by_building[self.building.id]
        self.assertEqual(a["building_name"], self.building.name)
        self.assertEqual(a["total"], 2)
        self.assertEqual(a["by_status"]["COMPLETED"], 1)
        self.assertEqual(a["by_status"]["MISSED"], 1)
        # Building A2: 1 COMPLETED.
        a2 = by_building[self.building_a2.id]
        self.assertEqual(a2["total"], 1)
        self.assertEqual(a2["by_status"]["COMPLETED"], 1)
        # Every per-building row still carries all seven status keys.
        self.assertEqual(
            set(a["by_status"].keys()),
            {s.value for s in _ALL_STATUSES},
        )

    def test_by_building_respects_company_scope(self):
        # Company B row must never appear for a company-A admin.
        self.make_occurrence(
            status=PlannedOccurrenceStatus.COMPLETED,
            planned_date=self.day,
            job=self.make_recurring_job(
                created_by=self.super_admin,
                building=self.other_building,
                customer=self.other_customer,
            ),
        )
        self.authenticate(self.company_admin)
        resp = self.client.get(STATS_URL)
        building_ids = {b["building_id"] for b in resp.data["by_building"]}
        self.assertNotIn(self.other_building.id, building_ids)
