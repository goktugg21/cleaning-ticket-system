"""
Sprint 167 §3 / §4 — the standing hours agreement.

What these pin: the architectural rule the model exists under (no
import of `contracts`, no FK to one), the validity-window resolution,
the approval transitions including the reopen, that an APPROVED row is
not silently editable, and the scoping floor.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from rest_framework import status

from timesheets.contract_hours import active_contract_hours, in_force_on
from timesheets.models import ContractHours, ContractHoursStatus

from .fixtures import TimesheetsFixture


URL = "/api/timesheets/contract-hours/"


class ContractHoursFixture(TimesheetsFixture):
    def mk(self, **kwargs):
        defaults = dict(
            company=self.company_a,
            employee=self.staff_a,
            building=self.building_a,
            hour_type=self.normal_a,
            valid_from=date(2026, 1, 1),
            monday=Decimal("3.00"),
            tuesday=Decimal("3.00"),
            created_by=self.ca_a,
        )
        defaults.update(kwargs)
        return ContractHours.objects.create(**defaults)


class ModelTests(ContractHoursFixture):
    def test_the_weekly_total_is_derived_not_stored(self):
        row = self.mk(wednesday=Decimal("2.50"))
        self.assertEqual(row.weekly_total, Decimal("8.50"))
        self.assertFalse(
            any(f.name == "weekly_total" for f in ContractHours._meta.get_fields())
        )

    def test_it_has_NO_foreign_key_to_a_contract(self):
        """The architectural rule this model exists under. `timesheets`
        must keep working for a company with no contracts module, so
        the word "contract" here is the operator's, not a relation."""
        related = {
            f.name: f.related_model
            for f in ContractHours._meta.get_fields()
            if getattr(f, "related_model", None) is not None
        }
        for name, model in related.items():
            self.assertNotEqual(
                model._meta.app_label,
                "contracts",
                f"{name} points at the contracts app",
            )

    def test_timesheets_imports_nothing_from_contracts(self):
        import pathlib

        root = pathlib.Path(__file__).resolve().parents[2] / "timesheets"
        for path in root.rglob("*.py"):
            if "tests" in path.parts:
                continue
            text = path.read_text()
            self.assertNotIn("from contracts", text, str(path))
            self.assertNotIn("import contracts", text, str(path))

    def test_valid_to_before_valid_from_is_refused_by_the_database(self):
        from django.db import IntegrityError, transaction

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                self.mk(valid_from=date(2026, 6, 1), valid_to=date(2026, 1, 1))


class ResolutionTests(ContractHoursFixture):
    def test_the_latest_window_at_or_before_the_date_wins(self):
        old = self.mk(valid_from=date(2026, 1, 1), monday=Decimal("3.00"))
        new = self.mk(valid_from=date(2026, 6, 1), monday=Decimal("5.00"))

        self.assertEqual(
            active_contract_hours(
                self.staff_a, self.building_a, self.normal_a, on=date(2026, 5, 31)
            ),
            old,
        )
        self.assertEqual(
            active_contract_hours(
                self.staff_a, self.building_a, self.normal_a, on=date(2026, 6, 1)
            ),
            new,
        )

    def test_a_date_before_any_window_resolves_to_nothing(self):
        """None, not a zero row: "there was no agreement" and "the
        agreement was zero hours" are different facts."""
        self.mk(valid_from=date(2026, 6, 1))
        self.assertIsNone(
            active_contract_hours(
                self.staff_a, self.building_a, self.normal_a, on=date(2026, 1, 1)
            )
        )

    def test_a_closed_window_stops_applying(self):
        self.mk(valid_from=date(2026, 1, 1), valid_to=date(2026, 3, 31))
        self.assertEqual(
            in_force_on(ContractHours.objects.all(), date(2026, 3, 31)).count(), 1
        )
        self.assertEqual(
            in_force_on(ContractHours.objects.all(), date(2026, 4, 1)).count(), 0
        )


class ApprovalTests(ContractHoursFixture):
    def status_url(self, row):
        return f"{URL}{row.pk}/status/"

    def test_the_transitions_that_are_allowed(self):
        row = self.mk()
        client = self.api(self.ca_a)

        for target in ("SAVED", "APPROVED"):
            response = client.post(
                self.status_url(row), {"status": target}, format="json"
            )
            self.assertEqual(response.status_code, status.HTTP_200_OK, target)
            row.refresh_from_db()
            self.assertEqual(row.status, target)

        self.assertEqual(row.approved_by_id, self.ca_a.id)
        self.assertIsNotNone(row.approved_at)

    def test_draft_cannot_jump_straight_to_approved(self):
        row = self.mk()
        response = self.api(self.ca_a).post(
            self.status_url(row), {"status": "APPROVED"}, format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_an_approved_row_can_be_REOPENED_and_the_approval_clears(self):
        """Chosen deliberately: without it one wrong approval is
        permanent and the only escape is a superseding row whose date
        lies about when the agreement changed."""
        row = self.mk()
        client = self.api(self.ca_a)
        client.post(self.status_url(row), {"status": "SAVED"}, format="json")
        client.post(self.status_url(row), {"status": "APPROVED"}, format="json")

        response = client.post(
            self.status_url(row), {"status": "SAVED"}, format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        row.refresh_from_db()
        self.assertEqual(row.status, ContractHoursStatus.SAVED)
        self.assertIsNone(row.approved_by_id)
        self.assertIsNone(row.approved_at)

    def test_an_approved_row_is_NOT_silently_editable(self):
        row = self.mk(status=ContractHoursStatus.APPROVED)
        response = self.api(self.ca_a).patch(
            f"{URL}{row.pk}/", {"monday": "9.00"}, format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            response.data["status"][0].code, "contract_hours_approved_immutable"
        )
        row.refresh_from_db()
        self.assertEqual(row.monday, Decimal("3.00"))

    def test_an_approved_row_cannot_be_deleted_either(self):
        row = self.mk(status=ContractHoursStatus.APPROVED)
        response = self.api(self.ca_a).delete(f"{URL}{row.pk}/")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertTrue(ContractHours.objects.filter(pk=row.pk).exists())

    def test_every_transition_writes_an_audit_row(self):
        from audit.models import AuditAction, AuditLog

        row = self.mk()
        AuditLog.objects.all().delete()
        self.api(self.ca_a).post(
            self.status_url(row), {"status": "SAVED"}, format="json"
        )
        log = AuditLog.objects.get(
            target_model="timesheets.ContractHours", action=AuditAction.UPDATE
        )
        self.assertEqual(log.changes["status"]["before"], "DRAFT")
        self.assertEqual(log.changes["status"]["after"], "SAVED")


class ScopingTests(ContractHoursFixture):
    def test_customer_users_get_nothing(self):
        self.mk()
        self.assertEqual(
            self.api(self.customer_user).get(URL).status_code,
            status.HTTP_403_FORBIDDEN,
        )

    def test_a_company_admin_sees_only_their_own_company(self):
        self.mk()
        self.mk(
            company=self.company_b,
            employee=self.staff_b,
            building=self.building_b,
            hour_type=self.normal_b,
            created_by=self.ca_b,
        )
        rows = self.api(self.ca_a).get(URL).json()["results"]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["employee"], self.staff_a.id)

    def test_staff_may_read_but_not_write(self):
        self.mk()
        self.assertEqual(
            self.api(self.staff_a).get(URL).status_code, status.HTTP_200_OK
        )
        response = self.api(self.staff_a).post(
            URL,
            {
                "employee": self.staff_a.id,
                "building": self.building_a.id,
                "hour_type": self.normal_a.id,
                "valid_from": "2026-01-01",
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_a_foreign_employee_reads_as_nonexistent(self):
        response = self.api(self.ca_a).post(
            URL,
            {
                "employee": self.staff_b.id,
                "building": self.building_a.id,
                "hour_type": self.normal_a.id,
                "valid_from": "2026-01-01",
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data["employee"][0].code, "does_not_exist")


class BulkTests(ContractHoursFixture):
    def test_one_row_per_pair(self):
        response = self.api(self.ca_a).post(
            f"{URL}bulk/",
            {
                "employees": [self.staff_a.id, self.staff_a2.id],
                "buildings": [self.building_a.id],
                "hour_type": self.normal_a.id,
                "valid_from": "2026-01-01",
                "monday": "4.00",
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(len(response.json()), 2)
        self.assertEqual(ContractHours.objects.count(), 2)

    def test_re_running_it_creates_nothing_extra(self):
        """A bulk assignment re-run must be safe: the operator's intent
        is "make sure these exist", not "fail if one does"."""
        payload = {
            "employees": [self.staff_a.id],
            "buildings": [self.building_a.id],
            "hour_type": self.normal_a.id,
            "valid_from": "2026-01-01",
            "monday": "4.00",
        }
        client = self.api(self.ca_a)
        client.post(f"{URL}bulk/", payload, format="json")
        second = client.post(f"{URL}bulk/", payload, format="json")
        self.assertEqual(second.status_code, status.HTTP_201_CREATED)
        self.assertEqual(second.json(), [])
        self.assertEqual(ContractHours.objects.count(), 1)
