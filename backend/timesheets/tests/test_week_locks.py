"""
Sprint 152 — week locks: closing blocks every write in the week,
including date-moves in AND out; reopening restores writes; empty weeks
may be closed; the role matrix; cross-company isolation.
"""
from __future__ import annotations

import datetime as dt

from timesheets.models import TimeEntry, WeekLock

from .fixtures import (
    ENTRIES_URL,
    TimesheetsFixture,
    WEEK_CLOSE_URL,
    WEEK_REOPEN_URL,
    WEEK_STATUS_URL,
    WEEKS_URL,
    entry_detail_url,
)


W32_MONDAY = dt.date(2026, 8, 3)   # ISO 2026-W32
W33_MONDAY = dt.date(2026, 8, 10)  # ISO 2026-W33


class WeekCloseTests(TimesheetsFixture):
    def test_absence_of_a_row_means_open(self):
        response = self.api(self.staff_a).get(
            WEEK_STATUS_URL, {"iso_year": 2026, "iso_week": 32}
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.data["is_closed"])
        self.assertIsNone(response.data["lock"])
        self.assertEqual(WeekLock.objects.count(), 0)

    def test_company_admin_closes_a_week(self):
        response = self.api(self.ca_a).post(
            WEEK_CLOSE_URL, {"iso_year": 2026, "iso_week": 32}, format="json"
        )
        self.assertEqual(response.status_code, 201, response.data)
        lock = WeekLock.objects.get()
        self.assertEqual(lock.company_id, self.company_a.id)
        self.assertEqual(lock.closed_by_id, self.ca_a.id)

    def test_closing_an_empty_week_is_allowed(self):
        self.assertEqual(TimeEntry.objects.count(), 0)
        response = self.api(self.ca_a).post(
            WEEK_CLOSE_URL, {"iso_year": 2026, "iso_week": 12}, format="json"
        )
        self.assertEqual(response.status_code, 201)

    def test_closing_twice_is_a_400(self):
        client = self.api(self.ca_a)
        client.post(
            WEEK_CLOSE_URL, {"iso_year": 2026, "iso_week": 32}, format="json"
        )
        second = client.post(
            WEEK_CLOSE_URL, {"iso_year": 2026, "iso_week": 32}, format="json"
        )
        self.assertEqual(second.status_code, 400)
        self.assertEqual(second.data["code"], "week_already_closed")

    def test_reopen_deletes_the_row(self):
        client = self.api(self.ca_a)
        client.post(
            WEEK_CLOSE_URL, {"iso_year": 2026, "iso_week": 32}, format="json"
        )
        response = client.post(
            WEEK_REOPEN_URL, {"iso_year": 2026, "iso_week": 32}, format="json"
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.data["is_closed"])
        self.assertEqual(WeekLock.objects.count(), 0)

    def test_reopening_an_open_week_is_a_400(self):
        response = self.api(self.ca_a).post(
            WEEK_REOPEN_URL, {"iso_year": 2026, "iso_week": 32}, format="json"
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data["code"], "week_not_closed")

    def test_invalid_week_numbers_rejected(self):
        client = self.api(self.ca_a)
        for payload in (
            {"iso_year": 2026, "iso_week": 0},
            {"iso_year": 2026, "iso_week": 54},
            {"iso_year": 2026},
            {},
        ):
            response = client.post(WEEK_CLOSE_URL, payload, format="json")
            self.assertEqual(response.status_code, 400, payload)


class WeekLockRoleMatrixTests(TimesheetsFixture):
    def test_staff_and_bm_cannot_close_or_reopen(self):
        for user in (self.staff_a, self.bm_a):
            client = self.api(user)
            self.assertEqual(
                client.post(
                    WEEK_CLOSE_URL,
                    {"iso_year": 2026, "iso_week": 32},
                    format="json",
                ).status_code,
                403,
            )
            self.assertEqual(
                client.post(
                    WEEK_REOPEN_URL,
                    {"iso_year": 2026, "iso_week": 32},
                    format="json",
                ).status_code,
                403,
            )

    def test_staff_may_read_the_lock_status_of_their_own_week(self):
        WeekLock.objects.create(
            company=self.company_a,
            iso_year=2026,
            iso_week=32,
            closed_by=self.ca_a,
        )
        response = self.api(self.staff_a).get(
            WEEK_STATUS_URL, {"iso_year": 2026, "iso_week": 32}
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data["is_closed"])

    def test_customer_user_is_forbidden_everywhere(self):
        client = self.api(self.customer_user)
        self.assertEqual(client.get(WEEKS_URL).status_code, 403)
        self.assertEqual(
            client.get(
                WEEK_STATUS_URL, {"iso_year": 2026, "iso_week": 32}
            ).status_code,
            403,
        )
        self.assertEqual(
            client.post(
                WEEK_CLOSE_URL,
                {"iso_year": 2026, "iso_week": 32},
                format="json",
            ).status_code,
            403,
        )
        self.assertEqual(
            client.post(
                WEEK_REOPEN_URL,
                {"iso_year": 2026, "iso_week": 32},
                format="json",
            ).status_code,
            403,
        )

    def test_admin_cannot_close_a_rival_companys_week(self):
        response = self.api(self.ca_a).post(
            WEEK_CLOSE_URL,
            {"iso_year": 2026, "iso_week": 32, "company": self.company_b.id},
            format="json",
        )
        self.assertEqual(response.status_code, 403)
        self.assertFalse(
            WeekLock.objects.filter(company=self.company_b).exists()
        )

    def test_week_list_is_scoped(self):
        WeekLock.objects.create(
            company=self.company_b,
            iso_year=2026,
            iso_week=32,
            closed_by=self.ca_b,
        )
        response = self.api(self.ca_a).get(WEEKS_URL)
        self.assertEqual(response.data["results"], [])

    def test_closing_one_company_leaves_the_other_open(self):
        self.api(self.ca_a).post(
            WEEK_CLOSE_URL, {"iso_year": 2026, "iso_week": 32}, format="json"
        )
        response = self.api(self.staff_b).get(
            WEEK_STATUS_URL, {"iso_year": 2026, "iso_week": 32}
        )
        self.assertFalse(response.data["is_closed"])


class ClosedWeekBlocksWritesTests(TimesheetsFixture):
    def setUp(self):
        super().setUp()
        self.entry_w32 = self.make_entry(
            self.staff_a, W32_MONDAY, self.normal_a
        )
        self.entry_w33 = self.make_entry(
            self.staff_a, W33_MONDAY, self.normal_a
        )
        WeekLock.objects.create(
            company=self.company_a,
            iso_year=2026,
            iso_week=32,
            closed_by=self.ca_a,
        )

    def _create_in_w32(self, user):
        return self.api(user).post(
            ENTRIES_URL,
            {
                "date": W32_MONDAY.isoformat(),
                "hour_type": self.normal_a.id,
                "hours": "8.00",
            },
            format="json",
        )

    def test_create_in_a_closed_week_is_rejected(self):
        response = self._create_in_w32(self.staff_a)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data["date"][0].code, "week_closed")

    def test_an_admin_is_blocked_too(self):
        response = self.api(self.ca_a).post(
            ENTRIES_URL,
            {
                "employee": self.staff_a.id,
                "date": W32_MONDAY.isoformat(),
                "hour_type": self.normal_a.id,
                "hours": "8.00",
            },
            format="json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data["date"][0].code, "week_closed")

    def test_update_of_an_entry_in_a_closed_week_is_rejected(self):
        response = self.api(self.staff_a).patch(
            entry_detail_url(self.entry_w32.id),
            {"hours": "1.00"},
            format="json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data["date"][0].code, "week_closed")

    def test_delete_of_an_entry_in_a_closed_week_is_rejected(self):
        response = self.api(self.staff_a).delete(
            entry_detail_url(self.entry_w32.id)
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data["date"][0].code, "week_closed")
        self.assertTrue(
            TimeEntry.objects.filter(pk=self.entry_w32.pk).exists()
        )

    def test_date_move_INTO_a_closed_week_is_rejected(self):
        response = self.api(self.staff_a).patch(
            entry_detail_url(self.entry_w33.id),
            {"date": W32_MONDAY.isoformat()},
            format="json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data["date"][0].code, "week_closed")
        self.entry_w33.refresh_from_db()
        self.assertEqual(self.entry_w33.date, W33_MONDAY)

    def test_date_move_OUT_OF_a_closed_week_is_rejected(self):
        response = self.api(self.staff_a).patch(
            entry_detail_url(self.entry_w32.id),
            {"date": W33_MONDAY.isoformat()},
            format="json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data["date"][0].code, "week_closed")
        self.entry_w32.refresh_from_db()
        self.assertEqual(self.entry_w32.date, W32_MONDAY)

    def test_the_open_week_beside_it_is_unaffected(self):
        response = self.api(self.staff_a).patch(
            entry_detail_url(self.entry_w33.id),
            {"hours": "5.00"},
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.data)

    def test_is_locked_flag_is_reported_on_the_entry(self):
        response = self.api(self.ca_a).get(entry_detail_url(self.entry_w32.id))
        self.assertTrue(response.data["is_locked"])
        open_response = self.api(self.ca_a).get(
            entry_detail_url(self.entry_w33.id)
        )
        self.assertFalse(open_response.data["is_locked"])

    def test_reopen_restores_writes(self):
        self.api(self.ca_a).post(
            WEEK_REOPEN_URL, {"iso_year": 2026, "iso_week": 32}, format="json"
        )
        created = self._create_in_w32(self.staff_a)
        self.assertEqual(created.status_code, 201, created.data)

        updated = self.api(self.staff_a).patch(
            entry_detail_url(self.entry_w32.id),
            {"hours": "3.00"},
            format="json",
        )
        self.assertEqual(updated.status_code, 200)

        deleted = self.api(self.staff_a).delete(
            entry_detail_url(self.entry_w32.id)
        )
        self.assertEqual(deleted.status_code, 204)
