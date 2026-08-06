"""
Sprint 142 — direct tests for
`0024_sprint142_category_company_backfill.backfill_category_company`.

Same shape and same reason as
`test_sprint3_provider_catalog_scope.BackfillHelperTests`: the migration
runs on a fresh test DB that has zero orphan categories, so the function
is a no-op there and its inference / abort branches would never be
executed by the migration run alone. To reach them we temporarily drop
the `NOT NULL` on `extra_work_servicecategory.company_id`, build the
shapes the backfill must handle, call the function, and restore the
constraint.

`TransactionTestCase` (not `TestCase`) because PostgreSQL refuses
`ALTER TABLE ... DROP NOT NULL` inside a transaction with pending
trigger events, and Django's default `TestCase` wraps every test in
exactly such a transaction.

The abort branches matter more than the happy path here: `company` is
the SCOPE boundary, so a wrong guess hides a category from its real
owner AND hands a working cascade-archive button to a different
provider, with nothing left in the data to reveal the mistake.
"""
from __future__ import annotations

from decimal import Decimal

from django.apps import apps as django_apps
from django.db import connection
from django.test import TransactionTestCase

from companies.models import Company
from extra_work.models import (
    ExtraWorkPricingUnitType,
    Service,
    ServiceCategory,
)


class CategoryCompanyBackfillTests(TransactionTestCase):
    @staticmethod
    def _backfill_fn():
        import importlib

        module = importlib.import_module(
            "extra_work.migrations."
            "0024_sprint142_category_company_backfill"
        )
        return module.backfill_category_company

    def setUp(self):
        with connection.cursor() as cursor:
            cursor.execute(
                "ALTER TABLE extra_work_servicecategory ALTER COLUMN "
                "company_id DROP NOT NULL"
            )

    def tearDown(self):
        # Clear anything still null so the NOT NULL restoration succeeds
        # even after an abort-branch test (which raises BEFORE writing).
        # Services first: `Service.category` is PROTECT.
        with connection.cursor() as cursor:
            cursor.execute(
                "DELETE FROM extra_work_service WHERE category_id IN ("
                "  SELECT id FROM extra_work_servicecategory "
                "  WHERE company_id IS NULL"
                ")"
            )
            cursor.execute(
                "DELETE FROM extra_work_servicecategory "
                "WHERE company_id IS NULL"
            )
            cursor.execute(
                "ALTER TABLE extra_work_servicecategory ALTER COLUMN "
                "company_id SET NOT NULL"
            )

    # -- helpers ----------------------------------------------------------
    def _orphan_category(self, name):
        """A ServiceCategory row with `company_id` NULL — the pre-142
        shape. Created with a real company first (the model requires
        one), then NULLed via raw SQL, because
        `ServiceCategory.objects.update(company=None)` trips Django's own
        NOT NULL check on the model re-fetch even with the DB constraint
        dropped."""
        holder = Company.objects.first() or Company.objects.create(
            name="Holder", slug="holder-142"
        )
        cat = ServiceCategory.objects.create(company=holder, name=name)
        with connection.cursor() as cursor:
            cursor.execute(
                "UPDATE extra_work_servicecategory SET company_id = NULL "
                "WHERE id = %s",
                [cat.id],
            )
        cat.refresh_from_db()
        return cat

    def _service(self, company, category, name):
        return Service.objects.create(
            company=company,
            category=category,
            name=name,
            unit_type=ExtraWorkPricingUnitType.HOURS,
            default_unit_price=Decimal("1.00"),
        )

    # -- the happy paths --------------------------------------------------
    def test_inferred_from_the_single_company_of_its_services(self):
        Company.objects.all().delete()
        company_a = Company.objects.create(name="Infer A", slug="i-a-142")
        Company.objects.create(name="Infer B", slug="i-b-142")

        cat = self._orphan_category("Legacy Cat")
        self._service(company_a, cat, "svc-1")
        self._service(company_a, cat, "svc-2")

        self._backfill_fn()(django_apps, None)
        cat.refresh_from_db()
        self.assertEqual(cat.company_id, company_a.id)

    def test_zero_service_category_pinned_to_the_sole_company(self):
        """The single-tenant path — and the shape crmtest is actually
        in. Verified against the live DB before this sprint: 6
        categories, each with services, all under one company."""
        Company.objects.all().delete()
        only = Company.objects.create(name="Only", slug="only-142")

        cat = self._orphan_category("Empty Legacy Cat")
        self._backfill_fn()(django_apps, None)
        cat.refresh_from_db()
        self.assertEqual(cat.company_id, only.id)

    def test_idempotent_on_rerun(self):
        Company.objects.all().delete()
        company = Company.objects.create(name="Idem", slug="idem-142")
        cat = self._orphan_category("Idem Cat")
        self._service(company, cat, "svc-idem")

        backfill = self._backfill_fn()
        backfill(django_apps, None)
        cat.refresh_from_db()
        first = cat.company_id
        # Second run must leave the already-assigned row alone.
        backfill(django_apps, None)
        cat.refresh_from_db()
        self.assertEqual(cat.company_id, first)

    def test_no_pending_rows_is_a_clean_no_op(self):
        Company.objects.all().delete()
        Company.objects.create(name="NoOp", slug="noop-142")
        self._backfill_fn()(django_apps, None)  # must not raise

    # -- the abort branches ----------------------------------------------
    def test_category_spanning_two_companies_aborts(self):
        """The load-bearing abort. Picking a winner here would hand one
        provider's services to the other provider's catalog grouping —
        including Sprint 138's cascade-archive over them."""
        Company.objects.all().delete()
        company_a = Company.objects.create(name="Split A", slug="s-a-142")
        company_b = Company.objects.create(name="Split B", slug="s-b-142")

        cat = self._orphan_category("Shared Legacy Cat")
        self._service(company_a, cat, "svc-a")
        self._service(company_b, cat, "svc-b")

        with self.assertRaises(RuntimeError) as ctx:
            self._backfill_fn()(django_apps, None)
        self.assertIn("Sprint 142 backfill", str(ctx.exception))
        self.assertIn("different", str(ctx.exception))
        cat.refresh_from_db()
        self.assertIsNone(cat.company_id)

    def test_zero_service_category_with_two_companies_aborts(self):
        Company.objects.all().delete()
        Company.objects.create(name="Amb A", slug="amb-a-142")
        Company.objects.create(name="Amb B", slug="amb-b-142")

        cat = self._orphan_category("Signal-free Cat")
        with self.assertRaises(RuntimeError) as ctx:
            self._backfill_fn()(django_apps, None)
        self.assertIn("Sprint 142 backfill", str(ctx.exception))
        self.assertIn("cannot be inferred", str(ctx.exception))
        cat.refresh_from_db()
        self.assertIsNone(cat.company_id)

    def test_normalized_name_collision_aborts_before_writing(self):
        """Pre-142 uniqueness was EXACT-match platform-wide, so
        "Cleaning" and "cleaning " were both legal. The new constraint
        normalizes with `Lower(Trim(...))`, so they collide the moment
        they land in the same company. Caught up front and reported by
        id, rather than surfacing as a bare IntegrityError from the
        constraint added in 0023."""
        Company.objects.all().delete()
        company = Company.objects.create(name="Clash", slug="clash-142")

        first = self._orphan_category("Cleaning")
        second = self._orphan_category("  cleaning ")
        self._service(company, first, "svc-first")
        self._service(company, second, "svc-second")

        with self.assertRaises(RuntimeError) as ctx:
            self._backfill_fn()(django_apps, None)
        self.assertIn("Sprint 142 backfill", str(ctx.exception))
        self.assertIn("collide", str(ctx.exception))
        # Nothing written — the pre-check runs before pass 3.
        first.refresh_from_db()
        second.refresh_from_db()
        self.assertIsNone(first.company_id)
        self.assertIsNone(second.company_id)

    def test_same_normalized_name_in_two_companies_is_fine(self):
        """The mirror image: the collision rule is PER COMPANY, so two
        providers may each end up with a "Cleaning"."""
        Company.objects.all().delete()
        company_a = Company.objects.create(name="Par A", slug="p-a-142")
        company_b = Company.objects.create(name="Par B", slug="p-b-142")

        cat_a = self._orphan_category("Cleaning")
        cat_b = self._orphan_category("cleaning")
        self._service(company_a, cat_a, "svc-a")
        self._service(company_b, cat_b, "svc-b")

        self._backfill_fn()(django_apps, None)
        cat_a.refresh_from_db()
        cat_b.refresh_from_db()
        self.assertEqual(cat_a.company_id, company_a.id)
        self.assertEqual(cat_b.company_id, company_b.id)

    def test_no_companies_at_all_aborts(self):
        cat = self._orphan_category("Orphan With No Company")
        Company.objects.all().delete()
        with self.assertRaises(RuntimeError) as ctx:
            self._backfill_fn()(django_apps, None)
        self.assertIn("no Company rows", str(ctx.exception))
        cat.refresh_from_db()
        self.assertIsNone(cat.company_id)
