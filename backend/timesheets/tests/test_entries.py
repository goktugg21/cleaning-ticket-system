"""
Sprint 152 — time entries: the role matrix, the own-entries-only floor
for STAFF / BUILDING_MANAGER, cross-company isolation, the derived
fields (company, ISO week, snapshot), and the validation rules.
"""
from __future__ import annotations

import datetime as dt
from decimal import Decimal

from timesheets.models import TimeEntry

from .fixtures import ENTRIES_URL, TimesheetsFixture, entry_detail_url


MONDAY = dt.date(2026, 8, 3)  # ISO 2026-W32
TUESDAY = dt.date(2026, 8, 4)


class EntryCreateTests(TimesheetsFixture):
    def test_staff_creates_own_entry_and_every_derived_field_is_set(self):
        response = self.api(self.staff_a).post(
            ENTRIES_URL,
            {
                "date": MONDAY.isoformat(),
                "hour_type": self.overtime_a.id,
                "hours": "6.00",
                "building": self.building_a.id,
                "note": "Extra shift",
            },
            format="json",
        )
        self.assertEqual(response.status_code, 201, response.data)
        entry = TimeEntry.objects.get(pk=response.data["id"])
        self.assertEqual(entry.employee_id, self.staff_a.id)
        self.assertEqual(entry.created_by_id, self.staff_a.id)
        self.assertEqual(entry.company_id, self.company_a.id)
        self.assertEqual((entry.iso_year, entry.iso_week), (2026, 32))
        self.assertEqual(entry.multiplier_snapshot, Decimal("1.50"))
        self.assertEqual(response.data["weighted_hours"], "9.00")

    def test_client_cannot_set_derived_fields(self):
        response = self.api(self.staff_a).post(
            ENTRIES_URL,
            {
                "date": MONDAY.isoformat(),
                "hour_type": self.normal_a.id,
                "hours": "8.00",
                "iso_year": 1999,
                "iso_week": 1,
                "multiplier_snapshot": "9.99",
                "created_by": self.ca_a.id,
            },
            format="json",
        )
        self.assertEqual(response.status_code, 201)
        entry = TimeEntry.objects.get(pk=response.data["id"])
        self.assertEqual((entry.iso_year, entry.iso_week), (2026, 32))
        self.assertEqual(entry.multiplier_snapshot, Decimal("1.00"))
        self.assertEqual(entry.created_by_id, self.staff_a.id)

    def test_future_dates_are_allowed(self):
        response = self.api(self.staff_a).post(
            ENTRIES_URL,
            {
                "date": (dt.date.today() + dt.timedelta(days=90)).isoformat(),
                "hour_type": self.normal_a.id,
                "hours": "8.00",
            },
            format="json",
        )
        self.assertEqual(response.status_code, 201, response.data)

    def test_multiple_entries_per_day_are_allowed(self):
        client = self.api(self.staff_a)
        for hour_type in (self.normal_a, self.overtime_a):
            response = client.post(
                ENTRIES_URL,
                {
                    "date": MONDAY.isoformat(),
                    "hour_type": hour_type.id,
                    "hours": "4.00",
                },
                format="json",
            )
            self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(
            TimeEntry.objects.filter(
                employee=self.staff_a, date=MONDAY
            ).count(),
            2,
        )

    def test_admin_records_hours_on_behalf_of_an_employee(self):
        response = self.api(self.ca_a).post(
            ENTRIES_URL,
            {
                "employee": self.staff_a.id,
                "date": MONDAY.isoformat(),
                "hour_type": self.normal_a.id,
                "hours": "8.00",
            },
            format="json",
        )
        self.assertEqual(response.status_code, 201, response.data)
        entry = TimeEntry.objects.get(pk=response.data["id"])
        self.assertEqual(entry.employee_id, self.staff_a.id)
        self.assertEqual(entry.created_by_id, self.ca_a.id)

    def test_hours_bounds(self):
        client = self.api(self.staff_a)
        for hours in ("0.00", "0.10", "24.50"):
            response = client.post(
                ENTRIES_URL,
                {
                    "date": MONDAY.isoformat(),
                    "hour_type": self.normal_a.id,
                    "hours": hours,
                },
                format="json",
            )
            self.assertEqual(response.status_code, 400, hours)
            self.assertEqual(
                response.data["hours"][0].code, "timesheet_hours_invalid"
            )

    def test_hours_bounds_accept_the_edges(self):
        client = self.api(self.staff_a)
        for hours in ("0.25", "24.00"):
            response = client.post(
                ENTRIES_URL,
                {
                    "date": MONDAY.isoformat(),
                    "hour_type": self.normal_a.id,
                    "hours": hours,
                },
                format="json",
            )
            self.assertEqual(response.status_code, 201, hours)

    def test_archived_type_rejected_for_a_new_entry(self):
        self.overtime_a.is_active = False
        self.overtime_a.save(update_fields=["is_active"])
        response = self.api(self.staff_a).post(
            ENTRIES_URL,
            {
                "date": MONDAY.isoformat(),
                "hour_type": self.overtime_a.id,
                "hours": "8.00",
            },
            format="json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.data["hour_type"][0].code, "hour_type_archived"
        )

    def test_archived_type_kept_on_an_existing_entry(self):
        entry = self.make_entry(self.staff_a, MONDAY, self.overtime_a)
        self.overtime_a.is_active = False
        self.overtime_a.save(update_fields=["is_active"])
        response = self.api(self.staff_a).patch(
            entry_detail_url(entry.id), {"hours": "7.00"}, format="json"
        )
        self.assertEqual(response.status_code, 200, response.data)
        entry.refresh_from_db()
        self.assertEqual(entry.hours, Decimal("7.00"))
        self.assertEqual(entry.hour_type_id, self.overtime_a.id)

    def test_building_must_belong_to_the_entry_company(self):
        response = self.api(self.staff_a).post(
            ENTRIES_URL,
            {
                "date": MONDAY.isoformat(),
                "hour_type": self.normal_a.id,
                "hours": "8.00",
                "building": self.building_b.id,
            },
            format="json",
        )
        # The scoped field queryset makes a foreign building read as
        # nonexistent, which is the no-oracle answer.
        self.assertEqual(response.status_code, 400)
        self.assertIn("building", response.data)

    def test_foreign_hour_type_reads_as_nonexistent(self):
        response = self.api(self.staff_a).post(
            ENTRIES_URL,
            {
                "date": MONDAY.isoformat(),
                "hour_type": self.normal_b.id,
                "hours": "8.00",
            },
            format="json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.data["hour_type"][0].code, "does_not_exist"
        )

    def test_hours_cannot_be_filed_against_a_customer_user(self):
        response = self.api(self.ca_a).post(
            ENTRIES_URL,
            {
                "employee": self.customer_user.id,
                "date": MONDAY.isoformat(),
                "hour_type": self.normal_a.id,
                "hours": "8.00",
            },
            format="json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data["employee"][0].code, "does_not_exist")

    def test_hours_cannot_be_filed_against_a_super_admin(self):
        response = self.api(self.sa).post(
            ENTRIES_URL,
            {
                "employee": self.sa.id,
                "company": self.company_a.id,
                "date": MONDAY.isoformat(),
                "hour_type": self.normal_a.id,
                "hours": "8.00",
            },
            format="json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data["employee"][0].code, "does_not_exist")


class EntryPrivacyTests(TimesheetsFixture):
    """STAFF and BUILDING_MANAGER see their OWN entries and nothing
    else — not another employee's rows, and not their names.
    """

    def setUp(self):
        super().setUp()
        self.own = self.make_entry(self.staff_a, MONDAY, self.normal_a)
        self.colleague = self.make_entry(
            self.staff_a2, MONDAY, self.normal_a, hours="7.50"
        )

    def test_staff_lists_only_own_entries(self):
        response = self.api(self.staff_a).get(ENTRIES_URL)
        self.assertEqual(response.status_code, 200)
        ids = {row["id"] for row in response.data["results"]}
        self.assertEqual(ids, {self.own.id})

    def test_staff_cannot_read_a_colleagues_entry(self):
        response = self.api(self.staff_a).get(
            entry_detail_url(self.colleague.id)
        )
        self.assertEqual(response.status_code, 404)

    def test_staff_cannot_edit_or_delete_a_colleagues_entry(self):
        client = self.api(self.staff_a)
        self.assertEqual(
            client.patch(
                entry_detail_url(self.colleague.id),
                {"hours": "1.00"},
                format="json",
            ).status_code,
            404,
        )
        self.assertEqual(
            client.delete(entry_detail_url(self.colleague.id)).status_code, 404
        )

    def test_colleague_name_never_appears_in_a_staff_response(self):
        response = self.api(self.staff_a).get(ENTRIES_URL)
        self.assertNotIn(self.staff_a2.full_name, str(response.data))
        self.assertNotIn(self.staff_a2.email, str(response.data))

    def test_employee_filter_cannot_widen_for_staff(self):
        response = self.api(self.staff_a).get(
            ENTRIES_URL, {"employee": self.staff_a2.id}
        )
        self.assertEqual(response.data["results"], [])

    def test_staff_cannot_create_an_entry_for_someone_else(self):
        response = self.api(self.staff_a).post(
            ENTRIES_URL,
            {
                "employee": self.staff_a2.id,
                "date": TUESDAY.isoformat(),
                "hour_type": self.normal_a.id,
                "hours": "8.00",
            },
            format="json",
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(
            response.data["code"], "timesheet_employee_forbidden"
        )

    def test_building_manager_is_an_ordinary_employee_here(self):
        bm_entry = self.make_entry(self.bm_a, MONDAY, self.normal_a)
        response = self.api(self.bm_a).get(ENTRIES_URL)
        ids = {row["id"] for row in response.data["results"]}
        self.assertEqual(ids, {bm_entry.id})

    def test_company_admin_sees_every_employee_in_own_company(self):
        response = self.api(self.ca_a).get(ENTRIES_URL)
        ids = {row["id"] for row in response.data["results"]}
        self.assertEqual(ids, {self.own.id, self.colleague.id})


class EntryTenantIsolationTests(TimesheetsFixture):
    def setUp(self):
        super().setUp()
        self.entry_a = self.make_entry(self.staff_a, MONDAY, self.normal_a)
        self.entry_b = self.make_entry(self.staff_b, MONDAY, self.normal_b)

    def test_company_admin_never_sees_the_other_tenant(self):
        response = self.api(self.ca_a).get(ENTRIES_URL)
        ids = {row["id"] for row in response.data["results"]}
        self.assertEqual(ids, {self.entry_a.id})

    def test_foreign_entry_detail_is_404(self):
        self.assertEqual(
            self.api(self.ca_a).get(
                entry_detail_url(self.entry_b.id)
            ).status_code,
            404,
        )

    def test_company_filter_cannot_widen(self):
        response = self.api(self.ca_a).get(
            ENTRIES_URL, {"company": self.company_b.id}
        )
        self.assertEqual(response.data["results"], [])

    def test_customer_user_is_forbidden_on_every_method(self):
        client = self.api(self.customer_user)
        self.assertEqual(client.get(ENTRIES_URL).status_code, 403)
        self.assertEqual(
            client.post(ENTRIES_URL, {}, format="json").status_code, 403
        )
        self.assertEqual(
            client.get(entry_detail_url(self.entry_a.id)).status_code, 403
        )
        self.assertEqual(
            client.patch(
                entry_detail_url(self.entry_a.id),
                {"hours": "1.00"},
                format="json",
            ).status_code,
            403,
        )
        self.assertEqual(
            client.delete(entry_detail_url(self.entry_a.id)).status_code, 403
        )

    def test_super_admin_sees_both_and_can_write_in_either(self):
        response = self.api(self.sa).get(ENTRIES_URL)
        ids = {row["id"] for row in response.data["results"]}
        self.assertEqual(ids, {self.entry_a.id, self.entry_b.id})

        created = self.api(self.sa).post(
            ENTRIES_URL,
            {
                "employee": self.staff_b.id,
                "date": TUESDAY.isoformat(),
                "hour_type": self.normal_b.id,
                "hours": "8.00",
            },
            format="json",
        )
        self.assertEqual(created.status_code, 201, created.data)
        self.assertEqual(created.data["company"], self.company_b.id)

    def test_admin_cannot_file_hours_for_a_rival_companys_employee(self):
        response = self.api(self.ca_a).post(
            ENTRIES_URL,
            {
                "employee": self.staff_b.id,
                "date": MONDAY.isoformat(),
                "hour_type": self.normal_a.id,
                "hours": "8.00",
            },
            format="json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data["employee"][0].code, "does_not_exist")


class EntryUpdateTests(TimesheetsFixture):
    def setUp(self):
        super().setUp()
        self.entry = self.make_entry(self.staff_a, MONDAY, self.normal_a)

    def test_date_edit_recomputes_the_iso_week(self):
        response = self.api(self.staff_a).patch(
            entry_detail_url(self.entry.id),
            {"date": "2026-08-10"},  # ISO 2026-W33
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.data)
        self.entry.refresh_from_db()
        self.assertEqual((self.entry.iso_year, self.entry.iso_week), (2026, 33))

    def test_iso_year_can_differ_from_the_calendar_year(self):
        # 2027-01-01 is a Friday in ISO week 53 of 2026.
        response = self.api(self.staff_a).patch(
            entry_detail_url(self.entry.id),
            {"date": "2027-01-01"},
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.data)
        self.entry.refresh_from_db()
        self.assertEqual((self.entry.iso_year, self.entry.iso_week), (2026, 53))

    def test_hour_type_change_re_snapshots(self):
        response = self.api(self.staff_a).patch(
            entry_detail_url(self.entry.id),
            {"hour_type": self.overtime_a.id},
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.data)
        self.entry.refresh_from_db()
        self.assertEqual(self.entry.multiplier_snapshot, Decimal("1.50"))

    def test_company_cannot_be_moved(self):
        response = self.api(self.sa).patch(
            entry_detail_url(self.entry.id),
            {"company": self.company_b.id},
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        self.entry.refresh_from_db()
        self.assertEqual(self.entry.company_id, self.company_a.id)

    def test_staff_deletes_own_entry(self):
        response = self.api(self.staff_a).delete(
            entry_detail_url(self.entry.id)
        )
        self.assertEqual(response.status_code, 204)
        self.assertFalse(TimeEntry.objects.filter(pk=self.entry.pk).exists())
