"""
Sprint 168 §1 / §3 — the work-type catalog, and the bulk shape the
assignment dialog actually sends.

What these pin, and why each one is here rather than left to the type
checker:

  * `WorkType` is a per-company catalog with the same uniqueness rule
    `HourType` has, created WITH the table. A duplicate name differing
    only by case or whitespace is the exact thing that rule exists to
    refuse.
  * The FK on `ContractHours` is NULLABLE. Every row written before the
    column existed has no work type, and a NOT NULL with a default
    would have invented one for them.
  * The bulk endpoint accepts the GRID's rows, each with its own hour
    type and pattern. Sprint 167 accepted only a cross-product, which
    would have silently discarded every per-row edit the operator made
    — the defect §1 was written to fix.
  * The window filter (`in_force_between`) is an OVERLAP, not a point.
    A row starting mid-week belongs to that week, and the point test
    dropped it — which is why the approval screen showed nothing.
  * Standard-set is idempotent, and out-of-scope ids read as
    nonexistent (H-1), never as forbidden.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from rest_framework import status

from timesheets.contract_hours import in_force_between
from timesheets.models import ContractHours, WorkType

from .fixtures import TimesheetsFixture


URL = "/api/timesheets/work-types/"
STANDARD_SET_URL = "/api/timesheets/work-types/standard-set/"
BULK_URL = "/api/timesheets/contract-hours/bulk/"


class WorkTypeFixture(TimesheetsFixture):
    def mk(self, **kwargs):
        defaults = dict(company=self.company_a, name="Vast werk")
        defaults.update(kwargs)
        return WorkType.objects.create(**defaults)


class CatalogTests(WorkTypeFixture):
    def test_the_name_is_unique_per_company_case_and_space_insensitively(self):
        from django.db import IntegrityError, transaction

        self.mk(name="Vast werk")
        for clashing in ("vast werk", "  VAST WERK  ", "Vast Werk"):
            with self.subTest(name=clashing):
                with self.assertRaises(IntegrityError):
                    with transaction.atomic():
                        WorkType.objects.create(
                            company=self.company_a, name=clashing
                        )

    def test_the_same_name_in_another_company_is_fine(self):
        """Per-company, not global: two tenants naming a work type the
        same thing are not in conflict."""
        self.mk(name="Vast werk")
        other = WorkType.objects.create(company=self.company_b, name="Vast werk")
        self.assertEqual(other.company_id, self.company_b.id)

    def test_it_is_a_separate_axis_from_the_hour_type(self):
        """Two catalogs on purpose: HourType carries a multiplier and
        answers "how is this hour weighted"; WorkType carries none and
        answers "what kind of work". A multiplier here would be a
        weight nobody asked for."""
        self.assertFalse(
            any(f.name == "multiplier" for f in WorkType._meta.get_fields())
        )

    def test_the_contract_hours_work_type_is_nullable(self):
        row = ContractHours.objects.create(
            company=self.company_a,
            employee=self.staff_a,
            building=self.building_a,
            hour_type=self.normal_a,
            valid_from=date(2026, 1, 1),
            created_by=self.ca_a,
        )
        self.assertIsNone(row.work_type_id)


class StandardSetTests(WorkTypeFixture):
    def test_it_creates_the_four_and_then_creates_nothing(self):
        client = self.api(self.ca_a)
        first = client.post(
            STANDARD_SET_URL, {"company": self.company_a.id}, format="json"
        )
        self.assertEqual(first.status_code, status.HTTP_201_CREATED)
        self.assertEqual(len(first.data["created"]), 4)
        self.assertEqual(first.data["skipped"], [])

        second = client.post(
            STANDARD_SET_URL, {"company": self.company_a.id}, format="json"
        )
        self.assertEqual(second.status_code, status.HTTP_200_OK)
        self.assertEqual(second.data["created"], [])
        self.assertEqual(len(second.data["skipped"]), 4)
        self.assertEqual(
            WorkType.objects.filter(company=self.company_a).count(), 4
        )

    def test_an_existing_name_is_skipped_case_insensitively(self):
        """The skip test must agree with the DB constraint, or the seed
        raises instead of skipping."""
        self.mk(name="  vast WERK ")
        client = self.api(self.ca_a)
        response = client.post(
            STANDARD_SET_URL, {"company": self.company_a.id}, format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertIn("Vast werk", response.data["skipped"])
        self.assertEqual(
            WorkType.objects.filter(company=self.company_a).count(), 4
        )

    def test_writing_the_set_into_another_companys_catalog_is_refused(self):
        client = self.api(self.ca_a)
        response = client.post(
            STANDARD_SET_URL, {"company": self.company_b.id}, format="json"
        )
        self.assertIn(
            response.status_code,
            (status.HTTP_400_BAD_REQUEST, status.HTTP_403_FORBIDDEN),
        )
        self.assertEqual(
            WorkType.objects.filter(company=self.company_b).count(), 0
        )


class ScopingTests(WorkTypeFixture):
    def test_a_company_admin_sees_only_their_own_catalog(self):
        self.mk(name="Mine")
        WorkType.objects.create(company=self.company_b, name="Theirs")
        client = self.api(self.ca_a)
        response = client.get(URL)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        names = {row["name"] for row in response.data["results"]}
        self.assertEqual(names, {"Mine"})

    def test_a_customer_user_gets_nothing(self):
        """Personnel-adjacent, exactly like TimeEntry: no customer-side
        role reads this, ever."""
        self.mk()
        client = self.api(self.customer_user)
        response = client.get(URL)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)


class BulkRowsTests(WorkTypeFixture):
    """The shape the assignment dialog sends: explicit rows."""

    def test_it_writes_one_row_per_sent_row_keeping_per_row_edits(self):
        work_type = self.mk()
        client = self.api(self.ca_a)
        payload = {
            "valid_from": "2026-03-04",
            "rows": [
                {
                    "employee": self.staff_a.id,
                    "building": self.building_a.id,
                    "hour_type": self.normal_a.id,
                    "work_type": work_type.id,
                    "monday": "4.00",
                    "tuesday": "4.00",
                },
                {
                    # A DIFFERENT pattern for the same pair — the whole
                    # point of sending rows rather than a cross-product.
                    "employee": self.staff_a.id,
                    "building": None,
                    "hour_type": self.normal_a.id,
                    "monday": "1.50",
                },
            ],
        }
        response = client.post(BULK_URL, payload, format="json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        rows = ContractHours.objects.filter(employee=self.staff_a).order_by("id")
        self.assertEqual(rows.count(), 2)
        self.assertEqual(rows[0].monday, Decimal("4.00"))
        self.assertEqual(rows[0].work_type_id, work_type.id)
        self.assertEqual(rows[1].monday, Decimal("1.50"))
        self.assertIsNone(rows[1].building_id)
        self.assertIsNone(rows[1].work_type_id)

    def test_re_running_it_creates_nothing_the_second_time(self):
        client = self.api(self.ca_a)
        payload = {
            "valid_from": "2026-03-04",
            "rows": [
                {
                    "employee": self.staff_a.id,
                    "building": self.building_a.id,
                    "hour_type": self.normal_a.id,
                    "monday": "4.00",
                }
            ],
        }
        client.post(BULK_URL, payload, format="json")
        client.post(BULK_URL, payload, format="json")
        self.assertEqual(
            ContractHours.objects.filter(employee=self.staff_a).count(), 1
        )

    def test_a_foreign_work_type_reads_as_nonexistent(self):
        """H-1: out of scope must be indistinguishable from fictional —
        a 400 "does not exist", never a 403 that confirms it does."""
        theirs = WorkType.objects.create(company=self.company_b, name="Theirs")
        client = self.api(self.ca_a)
        response = client.post(
            BULK_URL,
            {
                "valid_from": "2026-03-04",
                "rows": [
                    {
                        "employee": self.staff_a.id,
                        "building": self.building_a.id,
                        "hour_type": self.normal_a.id,
                        "work_type": theirs.id,
                        "monday": "4.00",
                    }
                ],
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(ContractHours.objects.count(), 0)

    def test_the_cross_product_shape_still_works(self):
        """Sprint 167's shape is a sane API on its own and its tests
        pin it — the new shape is added beside it, not instead."""
        client = self.api(self.ca_a)
        response = client.post(
            BULK_URL,
            {
                "employees": [self.staff_a.id],
                "buildings": [self.building_a.id],
                "hour_type": self.normal_a.id,
                "valid_from": "2026-03-04",
                "monday": "2.00",
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(ContractHours.objects.count(), 1)


class WindowFilterTests(WorkTypeFixture):
    """`in_force_between` — the fix for the approval screen showing
    nothing."""

    def mk_hours(self, valid_from, valid_to=None):
        return ContractHours.objects.create(
            company=self.company_a,
            employee=self.staff_a,
            building=self.building_a,
            hour_type=self.normal_a,
            valid_from=valid_from,
            valid_to=valid_to,
            created_by=self.ca_a,
        )

    def test_a_row_starting_mid_week_is_in_that_week(self):
        """The defect exactly: rows created on the Wednesday were
        invisible on the approval screen for the week containing that
        Wednesday, because the screen asked about the Monday."""
        row = self.mk_hours(date(2026, 3, 4))  # a Wednesday
        found = in_force_between(
            ContractHours.objects.all(), date(2026, 3, 2), date(2026, 3, 8)
        )
        self.assertIn(row, found)

    def test_a_row_that_ended_before_the_week_is_not(self):
        self.mk_hours(date(2026, 1, 1), valid_to=date(2026, 2, 1))
        found = in_force_between(
            ContractHours.objects.all(), date(2026, 3, 2), date(2026, 3, 8)
        )
        self.assertEqual(found.count(), 0)

    def test_a_row_starting_after_the_week_is_not(self):
        self.mk_hours(date(2026, 4, 1))
        found = in_force_between(
            ContractHours.objects.all(), date(2026, 3, 2), date(2026, 3, 8)
        )
        self.assertEqual(found.count(), 0)

    def test_an_open_ended_row_that_started_earlier_is(self):
        row = self.mk_hours(date(2026, 1, 1))
        found = in_force_between(
            ContractHours.objects.all(), date(2026, 3, 2), date(2026, 3, 8)
        )
        self.assertIn(row, found)

    def test_the_endpoint_applies_the_window(self):
        self.mk_hours(date(2026, 3, 4))
        client = self.api(self.ca_a)
        response = client.get(
            "/api/timesheets/contract-hours/",
            {
                "valid_between_start": "2026-03-02",
                "valid_between_end": "2026-03-08",
            },
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data["results"]), 1)
