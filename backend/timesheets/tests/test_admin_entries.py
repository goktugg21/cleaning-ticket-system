"""
Sprint 152.1 — the admin write paths the round exists to close.

Sprint 152 built the entries endpoint to accept an admin filing hours on
an employee's behalf and tested that it does. What it never had was the
UI, so these tests pin the exact shapes the new admin form sends: a CA
naming one of their own STAFF, and a SUPER_ADMIN naming an employee with
an explicit `company` (the one-company-at-a-time model — an SA must say
which tenant they are working in).

Also covers the review finding on the UPDATE path: the CREATE path
verified that an employee belongs to the entry's company, the UPDATE
path did not.
"""
from __future__ import annotations

import datetime as dt
from decimal import Decimal

from timesheets.models import TimeEntry, WeekLock

from .fixtures import ENTRIES_URL, TimesheetsFixture, entry_detail_url


MONDAY = dt.date(2026, 8, 3)  # ISO 2026-W32
TUESDAY = dt.date(2026, 8, 4)


class AdminCreatesForEmployeeTests(TimesheetsFixture):
    """The admin form's create path, per actor."""

    def test_company_admin_creates_for_own_staff(self):
        response = self.api(self.ca_a).post(
            ENTRIES_URL,
            {
                "employee": self.staff_a.id,
                "company": self.company_a.id,
                "date": MONDAY.isoformat(),
                "hour_type": self.normal_a.id,
                "hours": "7.50",
                "building": self.building_a.id,
                "note": "Filed by the office",
            },
            format="json",
        )
        self.assertEqual(response.status_code, 201, response.data)
        entry = TimeEntry.objects.get(pk=response.data["id"])
        self.assertEqual(entry.company_id, self.company_a.id)
        self.assertEqual(entry.employee_id, self.staff_a.id)
        # `created_by` is the ADMIN, not the employee — that difference
        # is the whole point of an on-behalf-of write and is what the
        # AuditLog attributes.
        self.assertEqual(entry.created_by_id, self.ca_a.id)
        self.assertNotEqual(entry.created_by_id, entry.employee_id)
        self.assertEqual(entry.multiplier_snapshot, Decimal("1.00"))
        self.assertEqual(entry.building_id, self.building_a.id)
        self.assertEqual((entry.iso_year, entry.iso_week), (2026, 32))

    def test_super_admin_creates_with_an_explicit_company(self):
        response = self.api(self.sa).post(
            ENTRIES_URL,
            {
                "employee": self.staff_b.id,
                "company": self.company_b.id,
                "date": MONDAY.isoformat(),
                "hour_type": self.normal_b.id,
                "hours": "8.00",
            },
            format="json",
        )
        self.assertEqual(response.status_code, 201, response.data)
        entry = TimeEntry.objects.get(pk=response.data["id"])
        self.assertEqual(entry.company_id, self.company_b.id)
        self.assertEqual(entry.employee_id, self.staff_b.id)
        self.assertEqual(entry.created_by_id, self.sa.id)

    def test_admin_creates_for_a_building_manager_too(self):
        # A BM is an ordinary employee in this module; hours can be
        # filed against them like anyone else.
        response = self.api(self.ca_a).post(
            ENTRIES_URL,
            {
                "employee": self.bm_a.id,
                "company": self.company_a.id,
                "date": MONDAY.isoformat(),
                "hour_type": self.overtime_a.id,
                "hours": "3.00",
            },
            format="json",
        )
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(
            TimeEntry.objects.get(pk=response.data["id"]).multiplier_snapshot,
            Decimal("1.50"),
        )

    def test_admin_create_into_a_closed_week_is_refused(self):
        WeekLock.objects.create(
            company=self.company_a,
            iso_year=2026,
            iso_week=32,
            closed_by=self.ca_a,
        )
        response = self.api(self.ca_a).post(
            ENTRIES_URL,
            {
                "employee": self.staff_a.id,
                "company": self.company_a.id,
                "date": MONDAY.isoformat(),
                "hour_type": self.normal_a.id,
                "hours": "8.00",
            },
            format="json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data["date"][0].code, "week_closed")
        self.assertFalse(TimeEntry.objects.exists())

    def test_admin_edits_and_deletes_an_employees_entry(self):
        entry = self.make_entry(self.staff_a, MONDAY, self.normal_a)
        updated = self.api(self.ca_a).patch(
            entry_detail_url(entry.id),
            {"hours": "6.25", "note": "Corrected"},
            format="json",
        )
        self.assertEqual(updated.status_code, 200, updated.data)
        entry.refresh_from_db()
        self.assertEqual(entry.hours, Decimal("6.25"))
        self.assertEqual(entry.note, "Corrected")

        deleted = self.api(self.ca_a).delete(entry_detail_url(entry.id))
        self.assertEqual(deleted.status_code, 204)
        self.assertFalse(TimeEntry.objects.filter(pk=entry.pk).exists())


class EntryUpdateCrossCompanyEmployeeTests(TimesheetsFixture):
    """Sprint 152.1 review finding — `_resolve_company` returned the
    row's company immediately on UPDATE, so nothing re-checked a NEWLY
    NAMED employee against it.

    A COMPANY_ADMIN was already blocked by the scoped `employee`
    queryset. A SUPER_ADMIN's scope is `None`, so for them the field
    resolved against every user on the platform: they could move an
    entry in company A onto company B's employee. The row keeps company
    A, so that employee can never see it (their scope is B) and A's
    admin sees a name from another provider.
    """

    def setUp(self):
        super().setUp()
        self.entry = self.make_entry(self.staff_a, MONDAY, self.normal_a)

    def test_super_admin_cannot_move_an_entry_onto_a_rival_employee(self):
        response = self.api(self.sa).patch(
            entry_detail_url(self.entry.id),
            {"employee": self.staff_b.id},
            format="json",
        )
        self.assertEqual(response.status_code, 400, response.data)
        self.assertEqual(
            response.data["employee"][0].code,
            "timesheet_employee_not_in_company",
        )
        self.entry.refresh_from_db()
        self.assertEqual(self.entry.employee_id, self.staff_a.id)
        self.assertEqual(self.entry.company_id, self.company_a.id)

    def test_super_admin_may_reassign_within_the_same_company(self):
        response = self.api(self.sa).patch(
            entry_detail_url(self.entry.id),
            {"employee": self.staff_a2.id},
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.data)
        self.entry.refresh_from_db()
        self.assertEqual(self.entry.employee_id, self.staff_a2.id)
        self.assertEqual(self.entry.company_id, self.company_a.id)

    def test_company_admin_is_still_stopped_by_the_scoped_queryset(self):
        # Unchanged behaviour, asserted so the two paths stay distinct:
        # a CA gets `does_not_exist` (the foreign id is invisible), not
        # the membership error.
        response = self.api(self.ca_a).patch(
            entry_detail_url(self.entry.id),
            {"employee": self.staff_b.id},
            format="json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data["employee"][0].code, "does_not_exist")

    def test_an_unrelated_patch_does_not_re_validate_the_employee(self):
        # The check fires only when the employee actually CHANGES, so a
        # plain hours edit is unaffected.
        response = self.api(self.sa).patch(
            entry_detail_url(self.entry.id),
            {"hours": "2.00"},
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.data)

    def test_staff_cannot_reassign_their_entry_to_a_colleague(self):
        response = self.api(self.staff_a).patch(
            entry_detail_url(self.entry.id),
            {"employee": self.staff_a2.id},
            format="json",
        )
        # `does_not_exist`, not a "you may only record your own hours"
        # 403: a non-manager's `employee` queryset is exactly themselves,
        # so a colleague's id is indistinguishable from a fictional one.
        # That is the stronger answer — a 403 would confirm the id names
        # a real person.
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data["employee"][0].code, "does_not_exist")
        self.entry.refresh_from_db()
        self.assertEqual(self.entry.employee_id, self.staff_a.id)
