"""
P-9 B — the Extra work list is four tabs, and the tabs cover the server.

`ExtraWorkTabsCoverTheServerTests` mirrors the frontend's one tab table
(`frontend/src/lib/extraWorkTabs.ts::TAB_OF_PHASE`) as a Python dict and
pins two things:

  * every phase in `EXTRA_WORK_PHASES` maps to exactly one tab or to
    cancelled — a phase the enum gains without a tab is a red test here
    and a compile error there;
  * a fixture with one request per reachable provider phase is listed
    in full, and bucketing the rows by the dict yields tab totals that
    sum to the endpoint's `count` (the P-8 guard, one level up).

`ListRowFactsTests` pins the P-9 additive list fields the tabs print
(the cart lines, the agreed-price estimate, who is on it, the customer's
reason for a no, the finish moment, the invoice reference, the contact,
the billing day), that a customer reader never sees the provider-only
three, and that none of them costs a query per row.
"""
from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from accounts.models import UserRole
from customers.models import Customer
from extra_work.display_phase import (
    EXTRA_WORK_PHASES,
    PHASE_CANCELLED,
    PHASE_DONE,
    PHASE_IN_EXECUTION,
    PHASE_INVOICED,
    PHASE_REJECTED,
    PHASE_SCHEDULED,
    PHASE_WAITING_COMPLETION_APPROVAL,
    PHASE_WAITING_CUSTOMER_APPROVAL,
    PHASE_WAITING_MANAGER_CHECK,
    PHASE_WAITING_PLANNING,
    PHASE_WAITING_PRICE,
    PHASE_WAITING_YOUR_APPROVAL,
)
from extra_work.models import (
    ExtraWorkAssignment,
    ExtraWorkAssignmentRole,
    ExtraWorkCategory,
    ExtraWorkLinePriceSource,
    ExtraWorkPricingUnitType,
    ExtraWorkRequest,
    ExtraWorkRequestIntent,
    ExtraWorkRequestItem,
    ExtraWorkRoutingDecision,
    ExtraWorkStatus,
    ExtraWorkStatusHistory,
    Service,
    ServiceCategory,
)
from invoicing.models import Invoice, InvoiceLine
from test_utils import TenantFixtureMixin
from tickets.models import Ticket, TicketStatus


LIST_URL = "/api/extra-work/"

TAB_TO_PRICE = "to-price"
TAB_WITH_CUSTOMER = "with-customer"
TAB_APPROVED = "approved"
TAB_FINISHED = "finished"
CANCELLED = "cancelled"
TABS = (TAB_TO_PRICE, TAB_WITH_CUSTOMER, TAB_APPROVED, TAB_FINISHED)

#: Mirror of `frontend/src/lib/extraWorkTabs.ts::TAB_OF_PHASE`. Keep the
#: two in step by hand: the frontend's is checked by the compiler, this
#: one by `test_every_phase_maps_to_exactly_one_tab_or_cancelled`.
TAB_OF_PHASE = {
    PHASE_WAITING_PRICE: TAB_TO_PRICE,
    PHASE_WAITING_YOUR_APPROVAL: TAB_WITH_CUSTOMER,
    PHASE_WAITING_CUSTOMER_APPROVAL: TAB_WITH_CUSTOMER,
    PHASE_REJECTED: TAB_WITH_CUSTOMER,
    PHASE_WAITING_PLANNING: TAB_APPROVED,
    PHASE_SCHEDULED: TAB_APPROVED,
    PHASE_IN_EXECUTION: TAB_APPROVED,
    # P-10 B1 — the crew reported done, the manager has not checked yet.
    PHASE_WAITING_MANAGER_CHECK: TAB_APPROVED,
    PHASE_WAITING_COMPLETION_APPROVAL: TAB_APPROVED,
    PHASE_DONE: TAB_FINISHED,
    PHASE_INVOICED: TAB_FINISHED,
    PHASE_CANCELLED: CANCELLED,
}


def bucket_totals(rows):
    """{tab-or-cancelled: n} over a list of serialized rows, plus the
    rows whose phase the dict does not know (must be zero)."""
    totals = {key: 0 for key in TABS + (CANCELLED,)}
    unknown = 0
    for row in rows:
        bucket = TAB_OF_PHASE.get(row["display_phase"])
        if bucket is None:
            unknown += 1
        else:
            totals[bucket] += 1
    return totals, unknown


class _TabFixture(TenantFixtureMixin, APITestCase):
    """One request per phase a PROVIDER list can hold (the customer
    twin `WAITING_YOUR_APPROVAL` is the same row read by a customer)."""

    def setUp(self):
        super().setUp()
        self.worker = self.make_user(
            "p9-worker@example.com", UserRole.STAFF, full_name="Ahmet Worker"
        )
        self.today = timezone.localdate()
        self.by_phase: dict[str, ExtraWorkRequest] = {}
        self._build_one_per_phase()

    def make_ew(self, **kwargs) -> ExtraWorkRequest:
        defaults = dict(
            company=self.company,
            building=self.building,
            customer=self.customer,
            created_by=self.super_admin,
            title="P-9 row",
            description="x",
            category=ExtraWorkCategory.DEEP_CLEANING,
            status=ExtraWorkStatus.REQUESTED,
            routing_decision=ExtraWorkRoutingDecision.PROPOSAL,
            request_intent=ExtraWorkRequestIntent.REQUEST_QUOTE,
            subtotal_amount=Decimal("100.00"),
            vat_amount=Decimal("21.00"),
            total_amount=Decimal("121.00"),
        )
        defaults.update(kwargs)
        return ExtraWorkRequest.objects.create(**defaults)

    def spawn_ticket(self, ew, ticket_status) -> Ticket:
        # `spawn_`: TenantFixtureMixin.setUp owns `self.ticket` (a fixture row).
        return Ticket.objects.create(
            company=ew.company,
            building=ew.building,
            customer=ew.customer,
            created_by=self.super_admin,
            title=f"Ticket for {ew.title}",
            description="x",
            extra_work_request=ew,
            status=ticket_status,
        )

    def history(self, ew, old, new, note=""):
        return ExtraWorkStatusHistory.objects.create(
            extra_work=ew,
            old_status=old,
            new_status=new,
            changed_by=self.super_admin,
            note=note,
        )

    def _build_one_per_phase(self):
        rows = self.by_phase
        rows[PHASE_WAITING_PRICE] = self.make_ew(
            title="price me", created_by=self.customer_user
        )
        # Asked by the customer themselves: a plain customer user's scope
        # is their own requests, and the customer-reader test below reads
        # this row through their eyes.
        rows[PHASE_WAITING_CUSTOMER_APPROVAL] = self.make_ew(
            title="with the customer",
            status=ExtraWorkStatus.PRICING_PROPOSED,
            pricing_proposed_at=timezone.now() - timedelta(days=4),
            created_by=self.customer_user,
        )
        declined = self.make_ew(
            title="declined", status=ExtraWorkStatus.CUSTOMER_REJECTED
        )
        self.history(
            declined,
            ExtraWorkStatus.PRICING_PROPOSED,
            ExtraWorkStatus.CUSTOMER_REJECTED,
            note="[Reject reason] Too expensive\n\nsee the mail",
        )
        rows[PHASE_REJECTED] = declined

        to_plan = self.make_ew(
            title="to plan",
            status=ExtraWorkStatus.CUSTOMER_APPROVED,
            routing_decision=ExtraWorkRoutingDecision.INSTANT,
            request_intent=ExtraWorkRequestIntent.DIRECT_AGREED_PRICE_ORDER,
        )
        self.spawn_ticket(to_plan, TicketStatus.OPEN)
        rows[PHASE_WAITING_PLANNING] = to_plan

        planned = self.make_ew(
            title="planned",
            status=ExtraWorkStatus.CUSTOMER_APPROVED,
            provider_planned_date=self.today + timedelta(days=3),
            budget_hours=Decimal("4.00"),
        )
        self.spawn_ticket(planned, TicketStatus.OPEN)
        ExtraWorkAssignment.objects.create(
            extra_work_request=planned,
            user=self.worker,
            role=ExtraWorkAssignmentRole.WORKER,
            assigned_by=self.super_admin,
        )
        rows[PHASE_SCHEDULED] = planned

        busy = self.make_ew(title="busy", status=ExtraWorkStatus.IN_PROGRESS)
        self.spawn_ticket(busy, TicketStatus.IN_PROGRESS)
        rows[PHASE_IN_EXECUTION] = busy

        manager_check = self.make_ew(
            title="reported done", status=ExtraWorkStatus.IN_PROGRESS
        )
        self.spawn_ticket(manager_check, TicketStatus.WAITING_MANAGER_REVIEW)
        rows[PHASE_WAITING_MANAGER_CHECK] = manager_check

        check = self.make_ew(title="check it", status=ExtraWorkStatus.IN_PROGRESS)
        self.spawn_ticket(check, TicketStatus.WAITING_CUSTOMER_APPROVAL)
        rows[PHASE_WAITING_COMPLETION_APPROVAL] = check

        done = self.make_ew(title="done", status=ExtraWorkStatus.COMPLETED)
        self.history(done, ExtraWorkStatus.IN_PROGRESS, ExtraWorkStatus.COMPLETED)
        rows[PHASE_DONE] = done

        invoiced = self.make_ew(
            title="invoiced",
            status=ExtraWorkStatus.COMPLETED,
            is_invoiced=True,
            invoiced_at=timezone.now(),
        )
        self.invoice = Invoice.objects.create(
            company=self.company,
            customer=self.customer,
            building=None,
            status=Invoice.Status.SENT,
            number="2026-0007",
            created_by=self.super_admin,
            sent_at=timezone.now(),
        )
        InvoiceLine.objects.create(
            invoice=self.invoice, ordering=0, description=invoiced.title, extra_work=invoiced
        )
        rows[PHASE_INVOICED] = invoiced

        rows[PHASE_CANCELLED] = self.make_ew(
            title="called off", status=ExtraWorkStatus.CANCELLED
        )

    def list_as(self, user):
        self.authenticate(user)
        response = self.client.get(LIST_URL, {"page_size": 100})
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        return response


# ---------------------------------------------------------------------------
# The tabs cover the server
# ---------------------------------------------------------------------------
class ExtraWorkTabsCoverTheServerTests(_TabFixture):
    def test_every_phase_maps_to_exactly_one_tab_or_cancelled(self):
        self.assertEqual(set(TAB_OF_PHASE), set(EXTRA_WORK_PHASES))
        for phase, bucket in TAB_OF_PHASE.items():
            self.assertIn(bucket, TABS + (CANCELLED,), phase)
        # The customer twin sits with the provider's reading of the state.
        self.assertEqual(
            TAB_OF_PHASE[PHASE_WAITING_YOUR_APPROVAL],
            TAB_OF_PHASE[PHASE_WAITING_CUSTOMER_APPROVAL],
        )

    def test_provider_rows_bucket_to_tab_totals_that_sum_to_count(self):
        response = self.list_as(self.super_admin)
        rows = {row["id"]: row for row in response.data["results"]}
        self.assertEqual(response.data["count"], len(rows))

        # Every fixture row is listed under the phase it was built for.
        for phase, ew in self.by_phase.items():
            self.assertIn(ew.id, rows, f"{ew.title} missing from the list")
            self.assertEqual(rows[ew.id]["display_phase"], phase, ew.title)

        totals, unknown = bucket_totals(rows.values())
        self.assertEqual(unknown, 0)
        self.assertEqual(sum(totals.values()), response.data["count"])
        self.assertEqual(totals[TAB_TO_PRICE], 1)
        self.assertEqual(totals[TAB_WITH_CUSTOMER], 2)
        self.assertEqual(totals[TAB_APPROVED], 5)
        self.assertEqual(totals[TAB_FINISHED], 2)
        self.assertEqual(totals[CANCELLED], 1)

    def test_company_admin_sees_the_same_cover(self):
        response = self.list_as(self.company_admin)
        totals, unknown = bucket_totals(response.data["results"])
        self.assertEqual(unknown, 0)
        self.assertEqual(sum(totals.values()), response.data["count"])
        self.assertEqual(response.data["count"], len(self.by_phase))

    def test_customer_reader_rows_bucket_too(self):
        """The customer's twin phase lands on With the customer, so a
        customer reading the same rows through the dict is covered."""
        response = self.list_as(self.customer_user)
        rows = {row["id"]: row for row in response.data["results"]}
        with_customer = rows[self.by_phase[PHASE_WAITING_CUSTOMER_APPROVAL].id]
        self.assertEqual(with_customer["display_phase"], PHASE_WAITING_YOUR_APPROVAL)
        totals, unknown = bucket_totals(rows.values())
        self.assertEqual(unknown, 0)
        self.assertEqual(sum(totals.values()), response.data["count"])


# ---------------------------------------------------------------------------
# The facts the tabs print
# ---------------------------------------------------------------------------
class ListRowFactsTests(_TabFixture):
    def setUp(self):
        super().setUp()
        category = ServiceCategory.objects.create(company=self.company, name="Glass")
        self.service = Service.objects.create(
            category=category,
            company=self.company,
            name="Window washing",
            unit_type=ExtraWorkPricingUnitType.HOURS,
            default_unit_price=Decimal("50.00"),
        )
        ew = self.by_phase[PHASE_WAITING_PRICE]
        ExtraWorkRequestItem.objects.create(
            extra_work_request=ew,
            service=self.service,
            quantity=Decimal("2.00"),
            unit_type=ExtraWorkPricingUnitType.HOURS,
            requested_date=self.today,
            snapshot_service_name="Window washing",
            line_price_source=ExtraWorkLinePriceSource.AGREED_CUSTOMER_PRICE,
            snapshot_unit_price=Decimal("30.00"),
            snapshot_vat_pct=Decimal("21.00"),
        )
        ExtraWorkRequestItem.objects.create(
            extra_work_request=ew,
            service=None,
            quantity=Decimal("1.00"),
            unit_type=ExtraWorkPricingUnitType.HOURS,
            requested_date=self.today,
            custom_description="Something else",
            line_price_source=ExtraWorkLinePriceSource.AD_HOC,
        )

    def rows(self, user):
        return {row["id"]: row for row in self.list_as(user).data["results"]}

    def test_lines_estimate_people_reason_finish_invoice_contact(self):
        rows = self.rows(self.super_admin)
        priced = rows[self.by_phase[PHASE_WAITING_PRICE].id]
        self.assertEqual(
            priced["line_summary"],
            {"count": 2, "names": ["Window washing", "Something else"]},
        )
        # Only the agreed line counts: 2 x 30.00; the custom line has no
        # price to estimate from.
        self.assertEqual(priced["contract_estimate_amount"], "60.00")
        # The requester was a customer user, so the contact is them.
        self.assertEqual(priced["contact_name"], "customer-a")
        self.assertEqual(priced["request_intent"], ExtraWorkRequestIntent.REQUEST_QUOTE)

        bare = rows[self.by_phase[PHASE_WAITING_CUSTOMER_APPROVAL].id]
        self.assertEqual(bare["line_summary"], {"count": 0, "names": []})
        self.assertIsNone(bare["contract_estimate_amount"])
        self.assertEqual(bare["contact_name"], "customer-a")
        self.assertIsNone(bare["rejection_note"])

        declined = rows[self.by_phase[PHASE_REJECTED].id]
        self.assertEqual(declined["rejection_note"], "Too expensive")
        # Created by the provider: the customer's contact address.
        self.assertEqual(declined["contact_name"], "customer-a@example.com")

        planned = rows[self.by_phase[PHASE_SCHEDULED].id]
        self.assertEqual(planned["people_names"], ["Ahmet Worker"])
        self.assertEqual(rows[self.by_phase[PHASE_WAITING_PLANNING].id]["people_names"], [])

        done = rows[self.by_phase[PHASE_DONE].id]
        self.assertIsNotNone(done["completed_at"])
        self.assertIsNone(done["invoice_ref"])
        self.assertIsNone(rows[self.by_phase[PHASE_IN_EXECUTION].id]["completed_at"])

        invoiced = rows[self.by_phase[PHASE_INVOICED].id]
        self.assertEqual(invoiced["invoice_ref"]["id"], self.invoice.id)
        self.assertEqual(invoiced["invoice_ref"]["number"], "2026-0007")
        self.assertEqual(invoiced["invoice_ref"]["status"], Invoice.Status.SENT)
        self.assertIsNotNone(invoiced["invoice_ref"]["sent_at"])

    def test_customer_invoice_day_follows_the_customer_setting(self):
        rows = self.rows(self.super_admin)
        any_id = self.by_phase[PHASE_DONE].id
        self.assertIsNone(rows[any_id]["customer_invoice_day"])

        Customer.objects.filter(pk=self.customer.pk).update(invoice_day_of_month=15)
        self.assertEqual(self.rows(self.super_admin)[any_id]["customer_invoice_day"], 15)

        Customer.objects.filter(pk=self.customer.pk).update(
            invoice_day_of_month=None,
            invoice_day_rule=Customer.InvoiceDayRule.LAST_OF_MONTH,
        )
        self.assertEqual(
            self.rows(self.super_admin)[any_id]["customer_invoice_day"], "LAST_OF_MONTH"
        )

    def test_customer_reader_never_sees_the_provider_only_facts(self):
        rows = self.rows(self.customer_user)
        for row in rows.values():
            for hidden in ("people_names", "invoice_ref", "customer_invoice_day"):
                self.assertNotIn(hidden, row)
            for visible in ("line_summary", "rejection_note", "completed_at", "contact_name"):
                self.assertIn(visible, row)

    def test_the_new_facts_do_not_cost_a_query_per_row(self):
        """Growth, not an absolute number (the `ListQueryGrowthTests`
        shape): listing the fixture and listing it again with three
        more rows that carry lines, people and an invoice must cost the
        same number of queries."""

        def count_queries():
            self.authenticate(self.super_admin)
            with CaptureQueriesContext(connection) as ctx:
                response = self.client.get(LIST_URL, {"page_size": 100})
            self.assertEqual(response.status_code, status.HTTP_200_OK)
            return len(ctx.captured_queries), response.data["count"]

        baseline, first_count = count_queries()

        for n in range(3):
            ew = self.make_ew(
                title=f"growth {n}",
                status=ExtraWorkStatus.COMPLETED,
                is_invoiced=True,
                invoiced_at=timezone.now(),
            )
            ExtraWorkRequestItem.objects.create(
                extra_work_request=ew,
                service=self.service,
                quantity=Decimal("1.00"),
                unit_type=ExtraWorkPricingUnitType.HOURS,
                requested_date=self.today,
                snapshot_service_name="Window washing",
                line_price_source=ExtraWorkLinePriceSource.AGREED_CUSTOMER_PRICE,
                snapshot_unit_price=Decimal("30.00"),
            )
            ExtraWorkAssignment.objects.create(
                extra_work_request=ew,
                user=self.worker,
                role=ExtraWorkAssignmentRole.WORKER,
                assigned_by=self.super_admin,
            )
            self.history(ew, ExtraWorkStatus.IN_PROGRESS, ExtraWorkStatus.COMPLETED)
            InvoiceLine.objects.create(
                invoice=self.invoice, ordering=n + 1, description=ew.title, extra_work=ew
            )

        grown, second_count = count_queries()
        self.assertEqual(second_count, first_count + 3)
        self.assertEqual(
            grown,
            baseline,
            "listing three more Extra Work rows must cost the same number "
            "of queries as listing the fixture",
        )
