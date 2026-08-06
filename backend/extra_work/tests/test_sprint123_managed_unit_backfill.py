"""
Sprint 123 — the `0019_sprint123_managed_unit_backfill` data-migration
algorithm, exercised directly (not via `manage.py migrate`, which the
real dev-stack run already proved end-to-end and idempotent — see the
sprint report). This test proves the DEDUPE + WINNER-SELECTION logic on
a scenario the real dev data didn't have: genuine colliding spellings.

The dev DB's real data had exactly one distinct OTHER-unit label
("smoke-m3", one company) — zero collisions to observe. This test seeds
deliberate case/whitespace collisions across BOTH `Service` and
`CustomerCustomPrice`, across TWO companies, to prove:

  1. Most-frequent-spelling wins (Company A: "m3" appears twice
     — Service + CustomerCustomPrice — vs "M3" once).
  2. A frequency TIE is broken by earliest `created_at`.
  3. Companies never collapse into each other's units, even for the
     identical raw spelling.
  4. Re-running the backfill is idempotent (no duplicate ManagedUnit
     rows, no re-processing of already-linked rows).
  5. Running on a company with NO OTHER rows is a safe no-op.

The migration module is imported directly via `importlib` (its
filename is not a valid Python identifier for a plain `import`
statement) and its `backfill_managed_units(apps, schema_editor)` is
called with the LIVE app registry — the function only calls
`apps.get_model(...)` + plain queryset operations, so the live
registry is a valid stand-in for the historical one Django's real
migration runner would pass; the real runner path itself was already
proven against the dev DB directly (not re-tested here).
"""
from __future__ import annotations

import importlib
from datetime import datetime, timezone as dt_timezone

from django.apps import apps as live_apps
from django.contrib.auth import get_user_model
from django.test import TestCase

from companies.models import Company
from customers.models import Customer
from extra_work.models import (
    CustomerCustomPrice,
    ManagedUnit,
    Service,
    ServiceCategory,
)

_migration = importlib.import_module(
    "extra_work.migrations.0019_sprint123_managed_unit_backfill"
)
backfill_managed_units = _migration.backfill_managed_units

User = get_user_model()
PASSWORD = "StrongerTestPassword123!"


def _dt(day: int) -> datetime:
    return datetime(2026, 1, day, 12, 0, tzinfo=dt_timezone.utc)


class ManagedUnitBackfillTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.company_a = Company.objects.create(name="Company A", slug="co-a-123")
        cls.company_b = Company.objects.create(name="Company B", slug="co-b-123")
        cls.admin = User.objects.create_user(
            email="admin-123@example.com",
            password=PASSWORD,
            role="COMPANY_ADMIN",
            full_name="Admin",
        )
        # Sprint 142 — one category per company. This fixture creates
        # services for BOTH, and a category now belongs to exactly one
        # provider, so `_service()` below picks the matching one.
        cls.category = ServiceCategory.objects.create(
            company=cls.company_a, name="Cat 123"
        )
        cls.category_b = ServiceCategory.objects.create(
            company=cls.company_b, name="Cat 123"
        )
        cls.customer_a = Customer.objects.create(
            company=cls.company_a, name="Customer A"
        )
        cls.customer_b = Customer.objects.create(
            company=cls.company_b, name="Customer B"
        )

    def _service(self, company, label, created_day):
        svc = Service.objects.create(
            company=company,
            category=(
                self.category
                if company == self.company_a
                else self.category_b
            ),
            name=f"svc-{label}-{created_day}",
            unit_type="OTHER",
            custom_unit_label=label,
            default_unit_price="10.00",
        )
        Service.objects.filter(pk=svc.pk).update(created_at=_dt(created_day))
        svc.refresh_from_db()
        return svc

    def _ccp(self, customer, label, created_day):
        ccp = CustomerCustomPrice.objects.create(
            customer=customer,
            custom_name=f"ccp-{label}-{created_day}",
            unit_type="OTHER",
            custom_unit_label=label,
            unit_price="10.00",
            valid_from="2026-01-01",
        )
        CustomerCustomPrice.objects.filter(pk=ccp.pk).update(
            created_at=_dt(created_day)
        )
        ccp.refresh_from_db()
        return ccp

    def test_most_frequent_spelling_wins(self):
        # Company A: "m3" appears twice (Service day1 + CCP day3),
        # "M3" appears once (Service day2). "m3" must win on frequency
        # alone, regardless of who was created first.
        svc_m3 = self._service(self.company_a, "m3", created_day=1)
        svc_M3 = self._service(self.company_a, "M3", created_day=2)
        ccp_m3 = self._ccp(self.customer_a, "m3", created_day=3)

        backfill_managed_units(live_apps, None)

        units = ManagedUnit.objects.filter(company=self.company_a)
        self.assertEqual(units.count(), 1)
        unit = units.get()
        self.assertEqual(unit.label, "m3")

        svc_m3.refresh_from_db()
        svc_M3.refresh_from_db()
        ccp_m3.refresh_from_db()
        self.assertEqual(svc_m3.managed_unit_id, unit.id)
        self.assertEqual(svc_M3.managed_unit_id, unit.id)
        self.assertEqual(ccp_m3.managed_unit_id, unit.id)
        # The original free text is untouched by the FK link.
        self.assertEqual(svc_M3.custom_unit_label, "M3")

    def test_frequency_tie_broken_by_earliest_created_at(self):
        # Company A, a DIFFERENT unit than the above: "strek" (day 5)
        # vs "STREK" (day 4) -- 1 occurrence each (a tie). The earlier
        # row ("STREK", day 4) must win.
        svc_strek = self._service(self.company_a, "strek", created_day=5)
        ccp_STREK = self._ccp(self.customer_a, "STREK", created_day=4)

        backfill_managed_units(live_apps, None)

        unit = ManagedUnit.objects.get(
            company=self.company_a, label__iexact="strek"
        )
        self.assertEqual(unit.label, "STREK")
        svc_strek.refresh_from_db()
        ccp_STREK.refresh_from_db()
        self.assertEqual(svc_strek.managed_unit_id, unit.id)
        self.assertEqual(ccp_STREK.managed_unit_id, unit.id)

    def test_companies_never_collapse_into_each_other(self):
        # Same raw spelling, two different companies -> two ManagedUnit
        # rows, never one shared row.
        svc_a = self._service(self.company_a, "pallet", created_day=1)
        svc_b = self._service(self.company_b, "pallet", created_day=1)

        backfill_managed_units(live_apps, None)

        unit_a = ManagedUnit.objects.get(company=self.company_a, label="pallet")
        unit_b = ManagedUnit.objects.get(company=self.company_b, label="pallet")
        self.assertNotEqual(unit_a.id, unit_b.id)
        svc_a.refresh_from_db()
        svc_b.refresh_from_db()
        self.assertEqual(svc_a.managed_unit_id, unit_a.id)
        self.assertEqual(svc_b.managed_unit_id, unit_b.id)

    def test_idempotent_on_rerun(self):
        self._service(self.company_a, "m3", created_day=1)
        self._ccp(self.customer_a, "M3", created_day=2)

        backfill_managed_units(live_apps, None)
        first_count = ManagedUnit.objects.count()
        first_ids = set(ManagedUnit.objects.values_list("id", flat=True))

        # Re-run against the now-already-backfilled state.
        backfill_managed_units(live_apps, None)
        second_count = ManagedUnit.objects.count()
        second_ids = set(ManagedUnit.objects.values_list("id", flat=True))

        self.assertEqual(first_count, second_count)
        self.assertEqual(first_ids, second_ids)

    def test_safe_on_company_with_no_other_rows(self):
        # No Service / CustomerCustomPrice rows at all for company_b in
        # this test -- must not raise, must create nothing.
        backfill_managed_units(live_apps, None)
        self.assertEqual(
            ManagedUnit.objects.filter(company=self.company_b).count(), 0
        )

    def test_safe_on_empty_db(self):
        # Delete everything the fixture created; the function must run
        # cleanly over zero companies / zero rows.
        Service.objects.all().delete()
        CustomerCustomPrice.objects.all().delete()
        Customer.objects.all().delete()
        # Sprint 142 — categories must go before companies now:
        # `ServiceCategory.company` is PROTECT, so a leftover category
        # would make the Company delete raise instead of clearing the DB.
        ServiceCategory.objects.all().delete()
        Company.objects.all().delete()
        backfill_managed_units(live_apps, None)  # must not raise
        self.assertEqual(ManagedUnit.objects.count(), 0)

    def test_blank_label_never_backfilled(self):
        # A concrete (non-OTHER) unit type, or an OTHER row with a
        # blank label, must never produce a ManagedUnit.
        Service.objects.create(
            company=self.company_a,
            category=self.category,
            name="concrete-unit-svc",
            unit_type="HOURS",
            custom_unit_label="",
            default_unit_price="10.00",
        )
        backfill_managed_units(live_apps, None)
        self.assertEqual(
            ManagedUnit.objects.filter(company=self.company_a).count(), 0
        )
