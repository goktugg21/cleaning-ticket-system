"""
Sprint 28 Batch 6 — backfill / legacy-row behaviour tests.

The 0003 migration creates exactly one `ExtraWorkRequestItem` row per
existing `ExtraWorkRequest` with `service=NULL`, `quantity=1`,
`unit_type=OTHER`, `requested_date = preferred_date or
requested_at.date()`, `customer_note=""`. It also forces
`routing_decision="PROPOSAL"` on every backfilled request.

Because the test DB already has every migration applied (Django's test
runner re-runs migrations on creation, including the data migration),
a full historical-replay `MigrationTestCase` would require unwinding
to 0002, building rows at that schema, then re-applying 0003. That
shape is fragile in practice (the Customer schema also changed in
parallel), so the fallback approach below is used instead:

  * Assert the new model accepts NULL `service` (legacy-row shape).
  * Assert the field defaults match the backfill rules (so any future
    edit to the model defaults causes a meaningful failure here).
  * Reach into the on-disk migration object and assert the data
    migration is wired up, with the right reverse_noop pairing.

This is intentionally lighter than a full migration replay, but it
captures the exact rules the migration must encode without being
hostage to schema-replay flakiness.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from importlib import import_module

from django.db import migrations
from django.test import TestCase

from buildings.models import Building
from companies.models import Company
from customers.models import Customer, CustomerBuildingMembership
from django.contrib.auth import get_user_model

from extra_work.models import (
    ExtraWorkCategory,
    ExtraWorkPricingUnitType,
    ExtraWorkRequest,
    ExtraWorkRequestItem,
    ExtraWorkRoutingDecision,
)


User = get_user_model()
PASSWORD = "StrongerTestPassword123!"


class LegacyRowShapeTests(TestCase):
    """
    Model-level: the new ExtraWorkRequestItem accepts the exact field
    shape the data migration creates on backfill. If any of these
    assertions break, the migration backfill must be revisited in
    lockstep.
    """

    def setUp(self):
        self.company = Company.objects.create(
            name="Backfill Co", slug="backfill-co"
        )
        self.building = Building.objects.create(
            company=self.company, name="B"
        )
        self.customer = Customer.objects.create(
            company=self.company, name="Cust", building=self.building
        )
        CustomerBuildingMembership.objects.create(
            customer=self.customer, building=self.building
        )
        self.user = User.objects.create_user(
            email="backfill@example.com",
            password=PASSWORD,
            full_name="b",
        )
        self.request = ExtraWorkRequest.objects.create(
            company=self.company,
            building=self.building,
            customer=self.customer,
            created_by=self.user,
            title="Legacy",
            description="legacy desc",
            category=ExtraWorkCategory.DEEP_CLEANING,
        )

    def test_legacy_line_accepts_null_service(self):
        # The migration backfill creates rows with service=None.
        line = ExtraWorkRequestItem.objects.create(
            extra_work_request=self.request,
            service=None,
            quantity=Decimal("1"),
            unit_type=ExtraWorkPricingUnitType.OTHER,
            requested_date=date(2026, 6, 1),
            customer_note="",
        )
        line.refresh_from_db()
        self.assertIsNone(line.service)
        self.assertEqual(line.quantity, Decimal("1.00"))
        self.assertEqual(line.unit_type, ExtraWorkPricingUnitType.OTHER)
        self.assertEqual(line.customer_note, "")

    def test_routing_decision_defaults_to_proposal(self):
        # The migration explicitly sets PROPOSAL on every backfilled
        # request; the model default must match so the rule survives
        # any future field-default edit.
        self.assertEqual(
            self.request.routing_decision,
            ExtraWorkRoutingDecision.PROPOSAL,
        )

    def test_routing_decision_field_default_is_proposal(self):
        # Belt-and-braces: read the field default off the model class
        # so a refactor of `ExtraWorkRequest._meta` triggers a clear
        # failure here rather than a silent backfill-rule drift.
        field = ExtraWorkRequest._meta.get_field("routing_decision")
        self.assertEqual(field.default, ExtraWorkRoutingDecision.PROPOSAL)


class MigrationFileShapeTests(TestCase):
    """
    The 0003 migration must wire up the data-migration RunPython
    operation with the documented reverse-noop pairing. If anyone
    drops the RunPython operation or replaces reverse_noop with a
    destructive code path, this test fails fast.
    """

    def test_migration_includes_runpython_with_reverse_noop(self):
        module = import_module(
            "extra_work.migrations.0003_request_items_and_routing"
        )
        run_python_ops = [
            op
            for op in module.Migration.operations
            if isinstance(op, migrations.RunPython)
        ]
        self.assertEqual(
            len(run_python_ops),
            1,
            "Expected exactly one RunPython op (the backfill).",
        )
        op = run_python_ops[0]
        self.assertEqual(op.code.__name__, "backfill_line_items_and_routing")
        self.assertEqual(op.reverse_code.__name__, "reverse_noop")

    def test_migration_creates_one_line_per_existing_request(self):
        # Direct invocation: run the migration's forwards function
        # against the live `apps` registry, with a fresh request
        # built at the post-0003 schema. The function must add
        # exactly one line item with the documented field shape.
        module = import_module(
            "extra_work.migrations.0003_request_items_and_routing"
        )

        company = Company.objects.create(
            name="Backfill Co 2", slug="backfill-co-2"
        )
        building = Building.objects.create(company=company, name="B2")
        customer = Customer.objects.create(
            company=company, name="Cust 2", building=building
        )
        CustomerBuildingMembership.objects.create(
            customer=customer, building=building
        )
        user = User.objects.create_user(
            email="backfill-2@example.com",
            password=PASSWORD,
            full_name="b",
        )
        legacy_request = ExtraWorkRequest.objects.create(
            company=company,
            building=building,
            customer=customer,
            created_by=user,
            title="Pre-Batch-6",
            description="legacy desc",
            category=ExtraWorkCategory.DEEP_CLEANING,
            preferred_date=date(2026, 7, 4),
            routing_decision=ExtraWorkRoutingDecision.INSTANT,
        )
        # Strip the auto-created shape so the backfill has work to do
        # (the model's manager doesn't auto-create items; the helper
        # below just ensures we start from zero lines for this row).
        legacy_request.line_items.all().delete()

        from django.apps import apps as live_apps

        module.backfill_line_items_and_routing(live_apps, None)

        legacy_request.refresh_from_db()
        # Routing forced to PROPOSAL by the backfill, regardless of
        # the pre-existing value.
        self.assertEqual(
            legacy_request.routing_decision,
            ExtraWorkRoutingDecision.PROPOSAL,
        )
        lines = list(legacy_request.line_items.all())
        self.assertEqual(len(lines), 1)
        line = lines[0]
        self.assertIsNone(line.service)
        self.assertEqual(line.quantity, Decimal("1.00"))
        self.assertEqual(line.unit_type, ExtraWorkPricingUnitType.OTHER)
        # preferred_date=2026-07-04 → requested_date copies it.
        self.assertEqual(line.requested_date, date(2026, 7, 4))
        self.assertEqual(line.customer_note, "")

    def test_backfill_idempotent(self):
        # Running the backfill twice must not create a second line
        # item per request — the duplicate-guard in the migration
        # makes the operation safe to reapply.
        module = import_module(
            "extra_work.migrations.0003_request_items_and_routing"
        )
        company = Company.objects.create(
            name="Backfill Co 3", slug="backfill-co-3"
        )
        building = Building.objects.create(company=company, name="B3")
        customer = Customer.objects.create(
            company=company, name="Cust 3", building=building
        )
        CustomerBuildingMembership.objects.create(
            customer=customer, building=building
        )
        user = User.objects.create_user(
            email="backfill-3@example.com",
            password=PASSWORD,
            full_name="b",
        )
        legacy_request = ExtraWorkRequest.objects.create(
            company=company,
            building=building,
            customer=customer,
            created_by=user,
            title="Pre-Batch-6 (idempotent)",
            description="legacy desc",
            category=ExtraWorkCategory.DEEP_CLEANING,
        )
        legacy_request.line_items.all().delete()

        from django.apps import apps as live_apps

        module.backfill_line_items_and_routing(live_apps, None)
        module.backfill_line_items_and_routing(live_apps, None)

        self.assertEqual(legacy_request.line_items.count(), 1)
