"""
Sprint 182 — the month-end job (§1), the preview (§2), and the split of
billing target from invoice grouping (§3).

The three claims these tests exist to prove, because each is a claim the
report makes and a reader should not have to take on trust:

  §1  Running the job twice does not double-create. Not "we set a flag" —
      the CLAIM on the Extra Work is what stops it, so the test runs the
      job twice for real and counts invoices.
  §2  The preview and the generator are ONE calculation. The test asserts
      the preview's plan and the generated invoices agree row for row,
      and that the preview stores nothing and never carries a number.
  §3  Target and split are separate, the Extra Work overrides the
      customer, and the migration is faithful for all three legacy
      values.
"""
from __future__ import annotations

import io
from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from unittest import mock

from django.contrib.auth import get_user_model
from django.core import mail
from rest_framework import status
from rest_framework.test import APIClient

from customers.models import Customer
from extra_work.models import ExtraWorkRequest
from invoicing.billing_target import (
    granularity_for,
    pair_for_granularity,
    resolve_billing_target,
    sync_legacy_granularity,
)
from invoicing.models import Invoice
from invoicing.preview import plan_invoices
from invoicing.schedule import (
    billing_day_reached,
    effective_billing_day,
    is_billing_day,
)
from invoicing import services as invoicing_services
from invoicing.services import generate_draft_invoices
from invoicing.tasks import run_daily_invoice_run, run_invoice_run_for_customer

from ._helpers import InvoicingFixture


PERIOD = (2026, 5)


# ---------------------------------------------------------------------------
# §3 — the resolver, as a pure function
# ---------------------------------------------------------------------------
class BillingTargetResolverTests(InvoicingFixture):
    """Pure-function tests over stub rows.

    Stubs rather than real `ExtraWorkRequest` rows ON PURPOSE. Agent A is
    making `billed_to` nullable this same sprint; on this branch the
    column is still NOT NULL, so the NULL case CANNOT be built in the
    database here. A stub exercises the logic that will run once A's
    migration lands, which is the only way to test it from this branch.
    The DB-backed behaviour is covered separately below.
    """

    def _customer(self, target, split=Customer.InvoiceSplit.NONE):
        return SimpleNamespace(
            invoice_billing_target=target, invoice_split=split
        )

    def super_admin_for_patch(self):
        """A SUPER_ADMIN for the customer-PATCH back-compat tests.

        The shared fixture's actors are COMPANY_ADMINs; the customer
        write gate is OSIUS-admin, and a SUPER_ADMIN satisfies it
        without depending on which company a membership points at.
        """
        from accounts.models import UserRole

        User = get_user_model()
        return User.objects.create_user(
            email="sa-182-patch@example.com",
            password="StrongerTestPassword123!",
            role=UserRole.SUPER_ADMIN,
            full_name="SA 182",
            is_staff=True,
            is_superuser=True,
        )

    def test_ew_with_no_opinion_follows_the_customer(self):
        for target in (
            Customer.InvoiceBillingTarget.BUILDING,
            Customer.InvoiceBillingTarget.CUSTOMER,
        ):
            with self.subTest(target=target):
                ew = SimpleNamespace(billed_to=None)
                self.assertEqual(
                    resolve_billing_target(ew, self._customer(target)),
                    target,
                )

    def test_customer_default_when_customer_is_missing(self):
        # Never None: every row has to land on some invoice, and a
        # customer-level invoice is the choice that invents nothing.
        self.assertEqual(
            resolve_billing_target(SimpleNamespace(billed_to=None), None),
            Customer.InvoiceBillingTarget.CUSTOMER,
        )

    def test_explicit_default_overrides_the_customer_setting(self):
        # The `generate` endpoint's granularity override supplies the
        # default for rows with no opinion.
        ew = SimpleNamespace(billed_to=None)
        self.assertEqual(
            resolve_billing_target(
                ew,
                self._customer(Customer.InvoiceBillingTarget.CUSTOMER),
                default=Customer.InvoiceBillingTarget.BUILDING,
            ),
            Customer.InvoiceBillingTarget.BUILDING,
        )

    def test_granularity_round_trip(self):
        for granularity in (
            Customer.InvoiceGranularity.CUSTOMER,
            Customer.InvoiceGranularity.PER_BUILDING,
            Customer.InvoiceGranularity.PER_BUILDING_DEPARTMENT_WORK_TYPE,
        ):
            with self.subTest(granularity=granularity):
                target, split = pair_for_granularity(granularity)
                self.assertEqual(granularity_for(target, split), granularity)

    def test_unrecognised_granularity_falls_back_to_customer_none(self):
        # The long-standing behaviour of `generate_draft_invoices` for an
        # unrecognised string, preserved through the split.
        self.assertEqual(
            pair_for_granularity("SOMETHING_ELSE"),
            (
                Customer.InvoiceBillingTarget.CUSTOMER,
                Customer.InvoiceSplit.NONE,
            ),
        )

    def test_customer_target_with_split_has_no_legacy_equivalent(self):
        # The old vocabulary could only split under a building target.
        # The server resolves the impossible pair rather than crashing.
        self.assertEqual(
            granularity_for(
                Customer.InvoiceBillingTarget.CUSTOMER,
                Customer.InvoiceSplit.DEPARTMENT_WORK_TYPE,
            ),
            Customer.InvoiceGranularity.CUSTOMER,
        )

    def test_legacy_only_patch_is_translated_into_the_pair(self):
        # BACK-COMPAT. An older client (or an integration written against
        # the pre-split API) still PATCHes `invoice_granularity_default`.
        # Making that field read-only would have made those writes a
        # SILENT no-op — the quiet kind of break. The serializer
        # translates instead, so the legacy write still lands and the
        # pair stays the single source of truth.
        client = APIClient()
        client.force_authenticate(user=self.super_admin_for_patch())
        response = client.patch(
            f"/api/customers/{self.customer.id}/",
            {
                "invoice_granularity_default": (
                    Customer.InvoiceGranularity.PER_BUILDING
                )
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.customer.refresh_from_db()
        self.assertEqual(
            self.customer.invoice_billing_target,
            Customer.InvoiceBillingTarget.BUILDING,
        )
        self.assertEqual(
            self.customer.invoice_split, Customer.InvoiceSplit.NONE
        )
        # ...and the legacy column still reads back what was written.
        self.assertEqual(
            self.customer.invoice_granularity_default,
            Customer.InvoiceGranularity.PER_BUILDING,
        )

    def test_pair_wins_when_both_are_sent(self):
        client = APIClient()
        client.force_authenticate(user=self.super_admin_for_patch())
        response = client.patch(
            f"/api/customers/{self.customer.id}/",
            {
                "invoice_billing_target": (
                    Customer.InvoiceBillingTarget.CUSTOMER
                ),
                "invoice_split": Customer.InvoiceSplit.NONE,
                # Contradicts the pair; the pair is what the operator saw.
                "invoice_granularity_default": (
                    Customer.InvoiceGranularity.PER_BUILDING
                ),
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.customer.refresh_from_db()
        self.assertEqual(
            self.customer.invoice_billing_target,
            Customer.InvoiceBillingTarget.CUSTOMER,
        )
        self.assertEqual(
            self.customer.invoice_granularity_default,
            Customer.InvoiceGranularity.CUSTOMER,
        )

    def test_customer_endpoint_renders_the_new_fields(self):
        # A filter test issues a query but never serialises a row, so it
        # cannot catch a missing `fields` entry — which took the whole
        # Extra Work page down in Sprint 173. This one READS the payload.
        client = APIClient()
        client.force_authenticate(user=self.super_admin_for_patch())
        response = client.get(f"/api/customers/{self.customer.id}/")
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        for key in (
            "invoice_billing_target",
            "invoice_split",
            "invoice_granularity_default",
        ):
            self.assertIn(key, response.data)
        self.assertEqual(
            response.data["invoice_billing_target"],
            self.customer.invoice_billing_target,
        )

    def test_due_payload_renders_the_new_fields(self):
        # Same rule for the /due/ panel, which reports the pair beside
        # the derived legacy value.
        self.customer.invoice_day_of_month = 15
        self.customer.save(update_fields=["invoice_day_of_month"])
        client = APIClient()
        client.force_authenticate(user=self.admin)
        response = client.get("/api/invoices/due/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        row = next(
            r for r in response.data if r["customer"] == self.customer.id
        )
        for key in (
            "invoice_billing_target",
            "invoice_split",
            "invoice_granularity_default",
        ):
            self.assertIn(key, row)

    def test_sync_legacy_granularity_derives_and_reports_change(self):
        self.customer.invoice_billing_target = (
            Customer.InvoiceBillingTarget.BUILDING
        )
        self.customer.invoice_split = Customer.InvoiceSplit.DEPARTMENT_WORK_TYPE
        self.assertTrue(sync_legacy_granularity(self.customer))
        self.assertEqual(
            self.customer.invoice_granularity_default,
            Customer.InvoiceGranularity.PER_BUILDING_DEPARTMENT_WORK_TYPE,
        )
        # Idempotent: a second call changes nothing and says so.
        self.assertFalse(sync_legacy_granularity(self.customer))

    def test_billed_to_is_ignored_while_the_column_is_not_nullable(self):
        # THE INTEGRATION GUARD. Every row on this branch carries a
        # non-null BUILDING default nobody chose. Treating those as
        # deliberate overrides would silently route every customer-level
        # customer's work per-building the moment this merged without
        # Agent A. Once A makes the column nullable this test's premise
        # disappears and the assertion below flips to the real override
        # behaviour — which is why it asserts on the schema, not a
        # constant.
        nullable = ExtraWorkRequest._meta.get_field("billed_to").null
        ew = self.make_ew()
        resolved = resolve_billing_target(
            ew,
            self._customer(Customer.InvoiceBillingTarget.CUSTOMER),
        )
        if nullable:
            # Post-Agent-A: a real value wins.
            self.assertEqual(resolved, str(ew.billed_to).upper())
        else:
            # Pre-Agent-A: the default is not a decision.
            self.assertEqual(
                resolved, Customer.InvoiceBillingTarget.CUSTOMER
            )


# ---------------------------------------------------------------------------
# §3 — grouping through the real generator
# ---------------------------------------------------------------------------
class BillingTargetGroupingTests(InvoicingFixture):
    def _set(self, target, split=Customer.InvoiceSplit.NONE):
        self.customer.invoice_billing_target = target
        self.customer.invoice_split = split
        sync_legacy_granularity(self.customer)
        self.customer.save(
            update_fields=[
                "invoice_billing_target",
                "invoice_split",
                "invoice_granularity_default",
            ]
        )

    def test_customer_target_produces_one_invoice_across_buildings(self):
        self.make_ew(building=self.building)
        self.make_ew(building=self.building2)
        self._set(Customer.InvoiceBillingTarget.CUSTOMER)

        created = generate_draft_invoices(
            self.admin, self.company.id, self.customer.id, *PERIOD
        )
        self.assertEqual(len(created), 1)
        self.assertIsNone(created[0].building_id)
        self.assertEqual(created[0].lines.count(), 2)
        self.assertEqual(
            created[0].granularity, Customer.InvoiceGranularity.CUSTOMER
        )

    def test_building_target_produces_one_invoice_per_building(self):
        self.make_ew(building=self.building)
        self.make_ew(building=self.building2)
        self._set(Customer.InvoiceBillingTarget.BUILDING)

        created = generate_draft_invoices(
            self.admin, self.company.id, self.customer.id, *PERIOD
        )
        self.assertEqual(len(created), 2)
        self.assertEqual(
            sorted(inv.building_id for inv in created),
            sorted([self.building.id, self.building2.id]),
        )
        for inv in created:
            self.assertEqual(
                inv.granularity, Customer.InvoiceGranularity.PER_BUILDING
            )

    def test_building_target_with_split_groups_by_department_and_work_type(self):
        self.make_ew(building=self.building, department=self.dept_a,
                     work_type=self.wt_a)
        self.make_ew(building=self.building, department=self.dept_b,
                     work_type=self.wt_a)
        self._set(
            Customer.InvoiceBillingTarget.BUILDING,
            Customer.InvoiceSplit.DEPARTMENT_WORK_TYPE,
        )

        created = generate_draft_invoices(
            self.admin, self.company.id, self.customer.id, *PERIOD
        )
        self.assertEqual(len(created), 2)
        self.assertEqual(
            sorted(inv.department_id for inv in created),
            sorted([self.dept_a.id, self.dept_b.id]),
        )
        for inv in created:
            self.assertEqual(
                inv.granularity,
                Customer.InvoiceGranularity.PER_BUILDING_DEPARTMENT_WORK_TYPE,
            )

    def test_split_is_not_applied_to_a_customer_addressed_invoice(self):
        # The split cuts WITHIN a building. The old vocabulary had no way
        # to ask for a split customer-level invoice and this sprint does
        # not invent one.
        self.make_ew(building=self.building, department=self.dept_a)
        self.make_ew(building=self.building2, department=self.dept_b)
        self._set(
            Customer.InvoiceBillingTarget.CUSTOMER,
            Customer.InvoiceSplit.DEPARTMENT_WORK_TYPE,
        )

        created = generate_draft_invoices(
            self.admin, self.company.id, self.customer.id, *PERIOD
        )
        self.assertEqual(len(created), 1)
        self.assertIsNone(created[0].building_id)

    def test_zero_amount_extra_work_is_invoiced_as_zero_not_skipped(self):
        # §1's rule. Work that was done and came to nothing still belongs
        # on the invoice; leaving it off makes the invoice disagree with
        # what the customer was told happened.
        self.make_ew(
            subtotal=Decimal("0.00"),
            vat=Decimal("0.00"),
            total=Decimal("0.00"),
        )
        self._set(Customer.InvoiceBillingTarget.CUSTOMER)

        created = generate_draft_invoices(
            self.admin, self.company.id, self.customer.id, *PERIOD
        )
        self.assertEqual(len(created), 1)
        self.assertEqual(created[0].lines.count(), 1)
        self.assertEqual(created[0].total_amount, Decimal("0.00"))


# ---------------------------------------------------------------------------
# §2 — the preview
# ---------------------------------------------------------------------------
class InvoicePreviewTests(InvoicingFixture):
    def setUp(self):
        super().setUp()
        self.client = APIClient()

    def _get(self, user, **params):
        self.client.force_authenticate(user=user)
        return self.client.get("/api/invoices/preview/", params)

    def test_preview_matches_what_generation_creates(self):
        # THE SINGLE-CALCULATION PROOF. Same customer, same period: the
        # plan the preview renders and the invoices generation produces
        # must agree on count, addressee and money.
        self.make_ew(building=self.building, total=Decimal("121.00"))
        self.make_ew(building=self.building2, total=Decimal("242.00"))
        self.customer.invoice_billing_target = (
            Customer.InvoiceBillingTarget.BUILDING
        )
        self.customer.save(update_fields=["invoice_billing_target"])

        planned = plan_invoices(
            self.admin, self.company.id, self.customer.id, *PERIOD,
            through=False,
        )
        created = generate_draft_invoices(
            self.admin, self.company.id, self.customer.id, *PERIOD
        )

        self.assertEqual(len(planned), len(created))
        self.assertEqual(
            [p.building_id for p in planned],
            [inv.building_id for inv in created],
        )
        self.assertEqual(
            [p.total for p in planned],
            [inv.total_amount for inv in created],
        )

    def test_preview_stores_nothing(self):
        self.make_ew()
        before = Invoice.objects.count()
        self._get(self.admin, customer=self.customer.id, year=2026, month=5)
        self._get(self.admin, customer=self.customer.id, year=2026, month=5)
        self.assertEqual(Invoice.objects.count(), before)
        # ...and the Extra Work is still unbilled: a preview must never
        # claim, or the month-end job would find nothing to invoice.
        self.assertFalse(
            ExtraWorkRequest.objects.filter(is_invoiced=True).exists()
        )

    def test_preview_never_carries_an_invoice_number(self):
        # Numbering happens at Send and must stay gapless.
        self.make_ew()
        response = self._get(
            self.admin, customer=self.customer.id, year=2026, month=5
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data["invoices"])
        for planned in response.data["invoices"]:
            self.assertNotIn("number", planned)
            self.assertNotIn("id", planned)

    def test_preview_is_stamped_with_the_moment_it_was_computed(self):
        self.make_ew()
        response = self._get(
            self.admin, customer=self.customer.id, year=2026, month=5
        )
        self.assertIn("computed_at", response.data)
        self.assertTrue(response.data["computed_at"])

    def test_preview_renders_its_rows(self):
        # A filter test issues a query but never serialises a row. This
        # one reads the payload the UI draws.
        self.make_ew(total=Decimal("121.00"))
        response = self._get(
            self.admin, customer=self.customer.id, year=2026, month=5
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        invoice = response.data["invoices"][0]
        for key in (
            "building",
            "building_name",
            "granularity",
            "subtotal_amount",
            "vat_amount",
            "total_amount",
            "line_count",
            "lines",
        ):
            self.assertIn(key, invoice)
        line = invoice["lines"][0]
        for key in ("extra_work", "description", "line_total"):
            self.assertIn(key, line)

    def test_preview_pdf_is_stamped_and_carries_no_number(self):
        # §2's document rules, checked against the extracted text rather
        # than "a PDF came back": the stamp is the whole point of the
        # download existing.
        self.make_ew(total=Decimal("121.00"))
        self.client.force_authenticate(user=self.admin)
        response = self.client.get(
            "/api/invoices/preview/",
            {
                "customer": self.customer.id,
                "year": 2026,
                "month": 5,
                "download": "pdf",
            },
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response["Content-Type"], "application/pdf")

        from pypdf import PdfReader

        text = "".join(
            page.extract_text() or ""
            for page in PdfReader(io.BytesIO(response.content)).pages
        )
        self.assertIn("PREVIEW", text)
        # Says what it is, in the customer's language, above the numbers.
        self.assertIn("geen factuur", text)
        # A preview must never carry a number. "CONCEPT" is the real
        # invoice PDF's numberless marker; this document is not that
        # either, and neither string may appear as a number slot.
        self.assertNotIn("Factuurnummer", text)

    def test_preview_pdf_still_stores_nothing(self):
        self.make_ew()
        before = Invoice.objects.count()
        self.client.force_authenticate(user=self.admin)
        self.client.get(
            "/api/invoices/preview/",
            {"customer": self.customer.id, "download": "pdf",
             "year": 2026, "month": 5},
        )
        self.assertEqual(Invoice.objects.count(), before)
        self.assertFalse(
            ExtraWorkRequest.objects.filter(is_invoiced=True).exists()
        )

    def test_preview_pdf_renders_with_nothing_to_bill(self):
        # The empty case is the one a PDF renderer usually crashes on.
        self.client.force_authenticate(user=self.admin)
        response = self.client.get(
            "/api/invoices/preview/",
            {"customer": self.customer.id, "download": "pdf",
             "year": 2026, "month": 5},
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.content)

    def test_preview_is_provider_only(self):
        self.make_ew()
        response = self._get(
            self.customer_user, customer=self.customer.id, year=2026, month=5
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_preview_of_another_tenants_customer_is_404(self):
        response = self._get(
            self.admin_b, customer=self.customer.id, year=2026, month=5
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_preview_requires_a_customer(self):
        response = self._get(self.admin)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_preview_rejects_an_impossible_month(self):
        response = self._get(
            self.admin, customer=self.customer.id, year=2026, month=13
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)


# ---------------------------------------------------------------------------
# §1 — the billing-day rule
# ---------------------------------------------------------------------------
class BillingScheduleTests(InvoicingFixture):
    def _customer(self, *, day=None, rule=""):
        self.customer.invoice_day_of_month = day
        self.customer.invoice_day_rule = rule
        return self.customer

    def test_specific_day_is_the_billing_day_only_on_that_day(self):
        customer = self._customer(day=5)
        self.assertTrue(is_billing_day(customer, date(2026, 5, 5)))
        self.assertFalse(is_billing_day(customer, date(2026, 5, 6)))
        self.assertFalse(is_billing_day(customer, date(2026, 5, 4)))

    def test_panel_and_job_ask_different_questions(self):
        # The panel keeps showing a customer as due after their day has
        # passed; the job must not keep firing. Both read from the same
        # module so they cannot drift, but they are NOT the same test.
        customer = self._customer(day=5)
        later = date(2026, 5, 20)
        self.assertTrue(billing_day_reached(customer, later))
        self.assertFalse(is_billing_day(customer, later))

    def test_first_of_month(self):
        customer = self._customer(rule=Customer.InvoiceDayRule.FIRST_OF_MONTH)
        self.assertEqual(
            effective_billing_day(customer, year=2026, month=5), 1
        )
        self.assertTrue(is_billing_day(customer, date(2026, 5, 1)))
        self.assertFalse(is_billing_day(customer, date(2026, 5, 2)))

    def test_last_of_month_resolves_against_the_real_calendar(self):
        customer = self._customer(rule=Customer.InvoiceDayRule.LAST_OF_MONTH)
        # 31-day month, 30-day month, and February in a leap year — the
        # case "the 31st" is really asking about.
        self.assertEqual(
            effective_billing_day(customer, year=2026, month=5), 31
        )
        self.assertEqual(
            effective_billing_day(customer, year=2026, month=4), 30
        )
        self.assertEqual(
            effective_billing_day(customer, year=2028, month=2), 29
        )
        self.assertTrue(is_billing_day(customer, date(2026, 4, 30)))
        self.assertFalse(is_billing_day(customer, date(2026, 4, 29)))

    def test_unscheduled_customer_is_never_due(self):
        customer = self._customer()
        self.assertIsNone(
            effective_billing_day(customer, year=2026, month=5)
        )
        self.assertFalse(is_billing_day(customer, date(2026, 5, 1)))


# ---------------------------------------------------------------------------
# §1 — the job
# ---------------------------------------------------------------------------
class MonthEndJobTests(InvoicingFixture):
    def _schedule(self, day):
        self.customer.invoice_day_of_month = day
        self.customer.invoice_billing_target = (
            Customer.InvoiceBillingTarget.CUSTOMER
        )
        self.customer.save(
            update_fields=[
                "invoice_day_of_month",
                "invoice_billing_target",
            ]
        )

    def test_job_creates_drafts_on_the_billing_day(self):
        self.make_ew()
        self._schedule(15)

        result = run_daily_invoice_run(today="2026-05-15")

        self.assertEqual(result["customers_invoiced"], 1)
        self.assertEqual(result["invoices_created"], 1)
        self.assertEqual(result["failed"], 0)
        self.assertEqual(Invoice.objects.count(), 1)

    def test_job_does_nothing_on_a_day_that_is_not_the_billing_day(self):
        self.make_ew()
        self._schedule(15)

        result = run_daily_invoice_run(today="2026-05-14")

        self.assertEqual(result["invoices_created"], 0)
        self.assertEqual(Invoice.objects.count(), 0)

    def test_running_twice_does_not_double_create(self):
        # THE IDEMPOTENCY PROOF. Not a flag — the CLAIM on the Extra Work
        # is what stops the second pass, so this runs the real job twice.
        self.make_ew()
        self._schedule(15)

        first = run_daily_invoice_run(today="2026-05-15")
        second = run_daily_invoice_run(today="2026-05-15")

        self.assertEqual(first["invoices_created"], 1)
        self.assertEqual(second["invoices_created"], 0)
        self.assertEqual(Invoice.objects.count(), 1)

    def test_the_claim_is_what_stops_it(self):
        # Prove the mechanism, not just the outcome: after the run the
        # Extra Work is marked invoiced AND linked to a line, and both
        # are what `unbilled_extra_work` excludes on.
        ew = self.make_ew()
        self._schedule(15)
        run_daily_invoice_run(today="2026-05-15")

        ew.refresh_from_db()
        self.assertTrue(ew.is_invoiced)
        self.assertIsNotNone(ew.invoiced_at)
        self.assertEqual(ew.invoice_lines.count(), 1)

    def test_unscheduled_customer_is_never_invoiced_by_the_job(self):
        self.make_ew()
        self.customer.invoice_day_of_month = None
        self.customer.invoice_day_rule = ""
        self.customer.save(
            update_fields=["invoice_day_of_month", "invoice_day_rule"]
        )

        for day in range(1, 29):
            run_daily_invoice_run(today=f"2026-05-{day:02d}")
        self.assertEqual(Invoice.objects.count(), 0)

    def test_job_notifies_the_admin(self):
        self.make_ew()
        self._schedule(15)
        mail.outbox = []

        run_daily_invoice_run(today="2026-05-15")

        self.assertTrue(mail.outbox)
        self.assertIn(self.admin.email, mail.outbox[0].to)

    def test_job_does_not_notify_when_nothing_was_created(self):
        # A daily job that mails "0 invoices" every day is a job whose
        # mail gets filtered, and then the real one gets filtered too.
        self._schedule(15)
        mail.outbox = []
        run_daily_invoice_run(today="2026-05-15")
        self.assertEqual(mail.outbox, [])

    def _schedule_second_tenant(self):
        self.make_ew(
            company=self.company_b,
            building=self.building_b,
            customer=self.customer_b,
            created_by=self.admin_b,
        )
        self.customer_b.invoice_day_of_month = 15
        self.customer_b.save(update_fields=["invoice_day_of_month"])

    def test_run_covers_every_due_customer_across_tenants(self):
        self.make_ew()
        self._schedule(15)
        self._schedule_second_tenant()

        result = run_daily_invoice_run(today="2026-05-15")
        self.assertEqual(result["failed"], 0)
        self.assertEqual(result["customers_invoiced"], 2)

    def test_one_customers_failure_does_not_stop_the_run(self):
        # The run must report what it could not do rather than dying at
        # the first problem and leaving the remaining customers silently
        # unbilled — a whole month of billing lost to one bad row.
        #
        # The failure is INJECTED. An earlier version of this test simply
        # ran two healthy customers and asserted failed == 0, which
        # proved nothing about the except branch it was named for.
        self.make_ew()
        self._schedule(15)
        self._schedule_second_tenant()

        real_generate = invoicing_services.generate_draft_invoices
        failing_customer_id = self.customer.id

        def _explode(actor, company_id, customer_id, *args, **kwargs):
            if customer_id == failing_customer_id:
                raise RuntimeError("injected failure")
            return real_generate(actor, company_id, customer_id, *args, **kwargs)

        with mock.patch.object(
            invoicing_services, "generate_draft_invoices", _explode
        ):
            result = run_daily_invoice_run(today="2026-05-15")

        self.assertEqual(result["failed"], 1)
        # The healthy tenant was still invoiced.
        self.assertEqual(result["customers_invoiced"], 1)
        self.assertEqual(
            Invoice.objects.filter(customer=self.customer_b).count(), 1
        )
        self.assertEqual(
            Invoice.objects.filter(customer=self.customer).count(), 0
        )

    def test_per_customer_entry_point_is_drivable_directly(self):
        # The management/test entry point exists so a missed day can be
        # re-run without faking a beat tick.
        self.make_ew()
        self._schedule(15)
        created = run_invoice_run_for_customer(
            self.customer, year=2026, month=5, actor=self.admin
        )
        self.assertEqual(len(created), 1)
