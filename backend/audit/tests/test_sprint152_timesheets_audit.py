"""
Sprint 152 — AuditLog coverage for the timesheets module (RBAC H-10).

`HourType`, `TimeEntry` and `WeekLock` are registered for the full CRUD
trio in `audit/signals.py`. The cases that matter beyond "a row is
written":

  * a multiplier EDIT carries the before/after diff — it is the change
    that rewrites every open week's weighted totals, so it has to be
    attributable;
  * the open-week snapshot refresh it triggers writes its own UPDATE
    rows, because it happens through per-row `save()` and not a
    queryset `.update()` (which would fire no signal and silently log
    nothing);
  * a week CLOSE lands as a WeekLock CREATE and a REOPEN as a WeekLock
    DELETE — the reopen deletes the row, so that DELETE log is the only
    surviving record that it happened.
"""
from __future__ import annotations

import datetime as dt
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from audit.models import AuditAction, AuditLog
from buildings.models import Building, BuildingStaffVisibility
from companies.models import Company, CompanyUserMembership
from timesheets.models import HourType, TimeEntry, WeekLock


User = get_user_model()
PASSWORD = "StrongerTestPassword152!"

W32_MONDAY = dt.date(2026, 8, 3)
W33_MONDAY = dt.date(2026, 8, 10)


def _mk(email, role, **extra):
    return User.objects.create_user(
        email=email,
        password=PASSWORD,
        role=role,
        full_name=email.split("@")[0],
        **extra,
    )


class TimesheetsAuditTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.company = Company.objects.create(name="Prov", slug="prov-152-audit")
        cls.ca = _mk("ca-152-audit@example.com", "COMPANY_ADMIN")
        cls.staff = _mk("staff-152-audit@example.com", "STAFF")
        CompanyUserMembership.objects.create(user=cls.ca, company=cls.company)
        cls.building = Building.objects.create(
            company=cls.company, name="B", address="B 1"
        )
        BuildingStaffVisibility.objects.create(
            user=cls.staff, building=cls.building
        )

    def api(self, user):
        client = APIClient()
        client.force_authenticate(user=user)
        return client

    def logs(self, model, action=None, target_id=None):
        qs = AuditLog.objects.filter(target_model=model)
        if action is not None:
            qs = qs.filter(action=action)
        if target_id is not None:
            qs = qs.filter(target_id=target_id)
        return qs

    # -- HourType ---------------------------------------------------------
    def test_hour_type_create_update_delete_are_logged(self):
        client = self.api(self.ca)
        created = client.post(
            "/api/timesheets/hour-types/",
            {"name": "Overwerk", "multiplier": "1.50"},
            format="json",
        )
        self.assertEqual(created.status_code, 201, created.data)
        hour_type_id = created.data["id"]

        create_log = self.logs(
            "timesheets.HourType", AuditAction.CREATE, hour_type_id
        ).get()
        self.assertEqual(create_log.actor_id, self.ca.id)

        client.patch(
            f"/api/timesheets/hour-types/{hour_type_id}/",
            {"multiplier": "2.00"},
            format="json",
        )
        update_log = self.logs(
            "timesheets.HourType", AuditAction.UPDATE, hour_type_id
        ).latest("id")
        self.assertEqual(update_log.actor_id, self.ca.id)
        self.assertEqual(
            update_log.changes["multiplier"],
            {"before": "1.50", "after": "2.00"},
        )

        client.delete(f"/api/timesheets/hour-types/{hour_type_id}/")
        self.assertTrue(
            self.logs("timesheets.HourType", AuditAction.DELETE, hour_type_id).exists()
        )

    # -- TimeEntry --------------------------------------------------------
    def test_time_entry_create_update_delete_are_logged(self):
        hour_type = HourType.objects.create(
            company=self.company, name="Normale uren"
        )
        client = self.api(self.staff)
        created = client.post(
            "/api/timesheets/entries/",
            {
                "date": W32_MONDAY.isoformat(),
                "hour_type": hour_type.id,
                "hours": "8.00",
            },
            format="json",
        )
        self.assertEqual(created.status_code, 201, created.data)
        entry_id = created.data["id"]

        create_log = self.logs("timesheets.TimeEntry", AuditAction.CREATE, entry_id).get()
        self.assertEqual(create_log.actor_id, self.staff.id)

        client.patch(
            f"/api/timesheets/entries/{entry_id}/",
            {"hours": "6.00"},
            format="json",
        )
        update_log = self.logs(
            "timesheets.TimeEntry", AuditAction.UPDATE, entry_id
        ).latest("id")
        self.assertEqual(
            update_log.changes["hours"], {"before": "8.00", "after": "6.00"}
        )

        client.delete(f"/api/timesheets/entries/{entry_id}/")
        self.assertTrue(
            self.logs("timesheets.TimeEntry", AuditAction.DELETE, entry_id).exists()
        )

    def test_admin_writing_on_behalf_records_the_admin_as_actor(self):
        hour_type = HourType.objects.create(
            company=self.company, name="Normale uren"
        )
        created = self.api(self.ca).post(
            "/api/timesheets/entries/",
            {
                "employee": self.staff.id,
                "date": W32_MONDAY.isoformat(),
                "hour_type": hour_type.id,
                "hours": "8.00",
            },
            format="json",
        )
        self.assertEqual(created.status_code, 201, created.data)
        log = self.logs("timesheets.TimeEntry", AuditAction.CREATE, created.data["id"]).get()
        self.assertEqual(log.actor_id, self.ca.id)

    def test_open_week_snapshot_refresh_is_audited(self):
        """The refresh runs per-row `save()` precisely so it lands in the
        AuditLog. A queryset `.update()` would be faster and would write
        nothing here — H-10 is why it is not used.
        """
        hour_type = HourType.objects.create(
            company=self.company, name="Overwerk", multiplier=Decimal("1.50")
        )
        open_entry = TimeEntry.objects.create(
            company=self.company,
            employee=self.staff,
            date=W33_MONDAY,
            hour_type=hour_type,
            hours=Decimal("8.00"),
            multiplier_snapshot=Decimal("1.50"),
            created_by=self.staff,
        )
        AuditLog.objects.all().delete()

        self.api(self.ca).patch(
            f"/api/timesheets/hour-types/{hour_type.id}/",
            {"multiplier": "2.00"},
            format="json",
        )
        refresh_log = self.logs(
            "timesheets.TimeEntry", AuditAction.UPDATE, open_entry.id
        ).get()
        self.assertEqual(
            refresh_log.changes["multiplier_snapshot"],
            {"before": "1.50", "after": "2.00"},
        )
        self.assertEqual(refresh_log.actor_id, self.ca.id)

    def test_closed_week_entries_produce_no_refresh_log(self):
        hour_type = HourType.objects.create(
            company=self.company, name="Overwerk", multiplier=Decimal("1.50")
        )
        closed_entry = TimeEntry.objects.create(
            company=self.company,
            employee=self.staff,
            date=W32_MONDAY,
            hour_type=hour_type,
            hours=Decimal("8.00"),
            multiplier_snapshot=Decimal("1.50"),
            created_by=self.staff,
        )
        WeekLock.objects.create(
            company=self.company,
            iso_year=2026,
            iso_week=32,
            closed_by=self.ca,
        )
        AuditLog.objects.all().delete()

        self.api(self.ca).patch(
            f"/api/timesheets/hour-types/{hour_type.id}/",
            {"multiplier": "2.00"},
            format="json",
        )
        self.assertFalse(
            self.logs("timesheets.TimeEntry", target_id=closed_entry.id).exists()
        )

    # -- WeekLock ---------------------------------------------------------
    def test_week_close_writes_a_create_log(self):
        response = self.api(self.ca).post(
            "/api/timesheets/weeks/close/",
            {"iso_year": 2026, "iso_week": 32},
            format="json",
        )
        self.assertEqual(response.status_code, 201, response.data)
        log = self.logs(
            "timesheets.WeekLock", AuditAction.CREATE, response.data["id"]
        ).get()
        self.assertEqual(log.actor_id, self.ca.id)

    def test_week_reopen_writes_a_delete_log(self):
        """The reopen trail. The row is gone afterwards, so this DELETE
        log is the only surviving evidence the week was ever reopened.
        """
        closed = self.api(self.ca).post(
            "/api/timesheets/weeks/close/",
            {"iso_year": 2026, "iso_week": 32},
            format="json",
        )
        lock_id = closed.data["id"]

        self.api(self.ca).post(
            "/api/timesheets/weeks/reopen/",
            {"iso_year": 2026, "iso_week": 32},
            format="json",
        )
        self.assertFalse(WeekLock.objects.filter(pk=lock_id).exists())
        log = self.logs("timesheets.WeekLock", AuditAction.DELETE, lock_id).get()
        self.assertEqual(log.actor_id, self.ca.id)
