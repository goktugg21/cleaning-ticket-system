"""
W16 — the extra works register, and the one rule that makes it safe.

The register copies the reference system's
`ContractController::getOrCreateExtraWorksContract`. The tests that
matter most here are the NEGATIVE ones: a register must never raise an
invoice, because the work it mirrors is already billed by the Extra
Work run. Those are `TheRegisterNeverBills`.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from django.db import IntegrityError, transaction

from customers.models import CustomerBuildingMembership
from extra_work.models import ExtraWorkRequest, ExtraWorkStatus
from tickets.models import Ticket, TicketStatus

from contracts.billing import build_forecast
from contracts.extra_work_register import (
    _ticket_map,
    get_or_create_register,
    register_extra_work,
    register_revision,
    register_summary,
    sync_extra_work_register,
)
from contracts.invoice_generation import generate_invoices_for_contract
from contracts.models import Contract, ContractKind, ContractLifecycle

from .fixtures import ContractsFixture


def register_url(customer_id):
    return f"/api/contracts/extra-works/{customer_id}/"


def sync_url(customer_id):
    return f"/api/contracts/extra-works/{customer_id}/sync/"


class RegisterFixture(ContractsFixture):
    """Two pieces of chargeable work for customer A, one finished."""

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        CustomerBuildingMembership.objects.get_or_create(
            customer=cls.customer_a, building=cls.building_a
        )
        cls.ew_done = cls._ew("Ruitenwas na verbouwing", ExtraWorkStatus.COMPLETED)
        cls.ew_open = cls._ew("Extra vloeronderhoud", ExtraWorkStatus.IN_PROGRESS)
        # The finished one has a CLOSED ticket, which is what makes it
        # earned — the register asks `is_billable`, never the status.
        cls.ticket_done = Ticket.objects.create(
            company=cls.company_a,
            building=cls.building_a,
            customer=cls.customer_a,
            created_by=cls.ca_a,
            title="Ruitenwas",
            description="x",
            status=TicketStatus.CLOSED,
            closed_at=date(2026, 6, 30),
            extra_work_request=cls.ew_done,
        )

    @classmethod
    def _ew(cls, title, status, *, total="100.00"):
        return ExtraWorkRequest.objects.create(
            company=cls.company_a,
            building=cls.building_a,
            customer=cls.customer_a,
            created_by=cls.ca_a,
            title=title,
            description="seeded by the W16 register tests",
            status=status,
            subtotal_amount=Decimal(total),
            vat_amount=Decimal("21.00"),
            total_amount=Decimal(total),
        )


class TheRegisterNeverBills(RegisterFixture):
    """THE rule. Everything else in this file is convenience.

    The register mirrors Extra Work rows that reach an invoice through
    `invoicing/selectors.py`, whose unbilled pool means "no live
    InvoiceLine claims this". A register line is not an InvoiceLine, so
    if the contract run billed a register the pool would offer the same
    work again and every customer would be billed twice.
    """

    def test_the_invoice_generator_creates_nothing_for_a_register(self):
        sync_extra_work_register(self.company_a, self.customer_a)
        register = get_or_create_register(self.company_a, self.customer_a)
        # It is ACTIVE and it HAS lines — every ordinary precondition
        # for billing is met, so this is the guard being tested and not
        # an accident of an empty or draft contract.
        self.assertEqual(register.lifecycle, ContractLifecycle.ACTIVE)
        self.assertGreater(register_revision(register).lines.count(), 0)

        result = generate_invoices_for_contract(register, system=True)

        self.assertEqual(result.created, [])

    def test_a_register_has_no_forecast(self):
        sync_extra_work_register(self.company_a, self.customer_a)
        register = get_or_create_register(self.company_a, self.customer_a)

        forecast = build_forecast(register, 2026)

        self.assertEqual(forecast.rows, [])

    def test_an_ordinary_contract_still_bills(self):
        """The guard is narrow: it must not have switched contract
        billing off for everybody."""
        result = generate_invoices_for_contract(
            self.contract_a, system=True, on=date(2026, 3, 15)
        )
        self.assertGreater(len(result.created), 0)


class TheRegisterIsOnePerCustomer(RegisterFixture):
    def test_it_is_created_on_first_ask_and_reused_after(self):
        first = get_or_create_register(self.company_a, self.customer_a)
        second = get_or_create_register(self.company_a, self.customer_a)

        self.assertEqual(first.pk, second.pk)
        self.assertEqual(first.kind, ContractKind.EXTRA_WORK)

    def test_the_database_refuses_a_second_one(self):
        """Not the get_or_create — the CONSTRAINT. Two registers would
        each show half the customer's money and neither would look
        wrong."""
        get_or_create_register(self.company_a, self.customer_a)

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Contract.objects.create(
                    company=self.company_a,
                    customer=self.customer_a,
                    kind=ContractKind.EXTRA_WORK,
                    contract_no="EW-DUPLICATE",
                    start_date=date(2026, 1, 1),
                )

    def test_a_customer_may_still_hold_many_ordinary_contracts(self):
        """The constraint is PARTIAL, and this is why it has to be."""
        self.assertEqual(
            Contract.objects.filter(
                customer=self.customer_a, kind=ContractKind.STANDARD
            ).count(),
            2,
        )


class TheRegisterMirrorsTheWork(RegisterFixture):
    def test_every_chargeable_job_becomes_a_line(self):
        sync_extra_work_register(self.company_a, self.customer_a)
        register = get_or_create_register(self.company_a, self.customer_a)

        names = set(
            register_revision(register).lines.values_list("name", flat=True)
        )
        self.assertEqual(
            names, {"Ruitenwas na verbouwing", "Extra vloeronderhoud"}
        )

    def test_syncing_twice_changes_nothing(self):
        sync_extra_work_register(self.company_a, self.customer_a)
        again = sync_extra_work_register(self.company_a, self.customer_a)

        self.assertEqual(
            again, {"added": 0, "updated": 0, "removed": 0}
        )

    def test_a_repriced_job_rewrites_its_line(self):
        """The line holds no independent number — which is the whole
        difference from the reference system, whose lines are typed by
        hand and drift the moment a price moves."""
        sync_extra_work_register(self.company_a, self.customer_a)
        self.ew_open.total_amount = Decimal("250.00")
        self.ew_open.subtotal_amount = Decimal("250.00")
        self.ew_open.save(
            update_fields=["total_amount", "subtotal_amount", "updated_at"]
        )

        changed = sync_extra_work_register(self.company_a, self.customer_a)

        line = register_revision(
            get_or_create_register(self.company_a, self.customer_a)
        ).lines.get(extra_work=self.ew_open)
        self.assertEqual(changed["updated"], 1)
        self.assertEqual(line.amount, Decimal("250.00"))

    def test_called_off_work_leaves_the_register(self):
        sync_extra_work_register(self.company_a, self.customer_a)
        self.ew_open.status = ExtraWorkStatus.CANCELLED
        self.ew_open.save(update_fields=["status", "updated_at"])

        changed = sync_extra_work_register(self.company_a, self.customer_a)

        self.assertEqual(changed["removed"], 1)

    def test_another_customers_work_is_not_on_it(self):
        """H-1, on the surface most likely to leak it: the register is
        addressed by customer id, so a wrong filter here bills one
        tenant for another's work."""
        sync_extra_work_register(self.company_b, self.customer_b)
        register_b = get_or_create_register(self.company_b, self.customer_b)

        self.assertEqual(register_revision(register_b).lines.count(), 0)


class TheSummaryReconcilesWithTheInvoiceRun(RegisterFixture):
    """`earned - invoiced` must be exactly what the Extra Work run has
    left to bill. Measured on the seeded demo data during the build:
    the register read EUR 990.99 earned and the run offered EUR 660.66,
    and both were right — the third job carried the legacy
    `is_invoiced` flag. A summary that counted only live invoice lines
    would have promised a third more revenue than existed."""

    def test_a_legacy_is_invoiced_flag_counts_as_settled(self):
        self.ew_done.is_invoiced = True
        self.ew_done.save(update_fields=["is_invoiced"])
        sync_extra_work_register(self.company_a, self.customer_a)

        summary = self._summary()

        self.assertEqual(summary["earned_amount"], Decimal("100.00"))
        self.assertEqual(summary["invoiced_amount"], Decimal("100.00"))

    def test_unsettled_earned_work_is_what_is_left_to_bill(self):
        sync_extra_work_register(self.company_a, self.customer_a)

        summary = self._summary()

        self.assertEqual(summary["earned_amount"], Decimal("100.00"))
        self.assertEqual(summary["invoiced_amount"], Decimal("0.00"))

    def test_unfinished_work_is_on_the_register_but_not_earned(self):
        sync_extra_work_register(self.company_a, self.customer_a)

        summary = self._summary()

        self.assertEqual(summary["job_count"], 2)
        self.assertEqual(summary["total_amount"], Decimal("200.00"))
        self.assertEqual(summary["earned_amount"], Decimal("100.00"))

    def _summary(self):
        register = get_or_create_register(self.company_a, self.customer_a)
        ews = register_extra_work(self.company_a.id, self.customer_a.id)
        return register_summary(
            register, register_revision(register), ews, _ticket_map(ews)
        )


class TheRegisterIsNotInTheContractList(RegisterFixture):
    """It is a different kind of object: nobody signed it, and adding
    ad-hoc spend to a figure meaning "recurring fees agreed" would make
    that figure useless. The reference system hides its own the same
    way (`ContractController.php:37`)."""

    def test_the_list_does_not_show_it(self):
        sync_extra_work_register(self.company_a, self.customer_a)
        response = self.api(self.ca_a).get("/api/contracts/")

        kinds = {row["contract_no"] for row in response.data["results"]}
        self.assertNotIn("EW-000001", kinds)

    def test_the_stats_tiles_do_not_count_it(self):
        before = self.api(self.ca_a).get("/api/contracts/stats/").data

        sync_extra_work_register(self.company_a, self.customer_a)
        after = self.api(self.ca_a).get("/api/contracts/stats/").data

        self.assertEqual(before["total"], after["total"])
        self.assertEqual(before["monthly_total"], after["monthly_total"])


class TheRegisterEndpoint(RegisterFixture):
    def test_the_sync_creates_and_the_get_returns_the_register_grouped_by_building(self):
        """W-FIX1 D2 — the GET is a read: before the first sync it answers
        `contract: null` and writes nothing; the explicit sync creates."""
        before = self.api(self.ca_a).get(register_url(self.customer_a.id))
        self.assertEqual(before.status_code, 200)
        self.assertIsNone(before.data["contract"])

        self.api(self.ca_a).post(sync_url(self.customer_a.id))
        response = self.api(self.ca_a).get(register_url(self.customer_a.id))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["contract"]["kind"], "EXTRA_WORK")
        self.assertEqual(response.data["summary"]["job_count"], 2)
        names = [b["name"] for b in response.data["buildings"]]
        self.assertIn(self.building_a.name, names)

    def test_sync_says_what_changed(self):
        response = self.api(self.ca_a).post(sync_url(self.customer_a.id))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["changed"]["added"], 2)

    def test_another_tenants_customer_is_a_404(self):
        """Not a 403 — a 403 confirms the row exists, which is the
        existence oracle H-1 forbids."""
        response = self.api(self.ca_a).get(register_url(self.customer_b.id))

        self.assertEqual(response.status_code, 404)

    def test_a_reader_may_look_but_not_sync(self):
        self.assertEqual(
            self.api(self.staff_a).post(sync_url(self.customer_a.id)).status_code,
            403,
        )
