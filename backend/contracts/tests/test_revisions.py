"""
Sprint 160 — revision resolution, status derivation and numbering.

The four resolution cases the sprint brief names are each their own
test: one revision, a future revision not yet active, two revisions on
the same day, and a date before the first revision.
"""
from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.utils import timezone

from companies.models import Company
from customers.models import Customer

from contracts.models import (
    Contract,
    ContractLifecycle,
    ContractRevision,
    ContractStatus,
)
from contracts.numbering import allocate_contract_number, format_contract_number
from contracts.revisions import (
    active_revision,
    active_revision_ids,
    is_locked,
    revision_totals,
)

from .fixtures import make_contract


class RevisionResolutionTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.company = Company.objects.create(name="Prov", slug="prov-160-rev")
        cls.customer = Customer.objects.create(
            company=cls.company, name="Customer"
        )
        cls.contract = make_contract(
            company=cls.company,
            customer=cls.customer,
            contract_no="CNT-2026-0001",
            start_date=date(2026, 1, 1),
            lines=[("Schoonmaak", "1000.00", "10.00")],
        )
        cls.initial = cls.contract.revisions.get()

    def test_a_contract_with_one_revision_resolves_to_it(self):
        self.assertEqual(
            active_revision(self.contract, on=date(2026, 6, 1)),
            self.initial,
        )

    def test_a_future_revision_is_not_yet_active(self):
        future = ContractRevision.objects.create(
            contract=self.contract,
            label="Prijsverhoging",
            effective_from=date(2026, 7, 1),
        )
        self.assertEqual(
            active_revision(self.contract, on=date(2026, 6, 30)), self.initial
        )
        # ...and takes over exactly on its effective date.
        self.assertEqual(
            active_revision(self.contract, on=date(2026, 7, 1)), future
        )

    def test_two_revisions_on_the_same_day_break_the_tie_on_id(self):
        """The most recently created row wins — the same tie-break
        `extra_work.pricing.resolve_price` applies, so "the latest
        agreement is the current agreement" means one thing in this
        system, not two."""
        first = ContractRevision.objects.create(
            contract=self.contract,
            label="Versie A",
            effective_from=date(2026, 7, 1),
        )
        second = ContractRevision.objects.create(
            contract=self.contract,
            label="Versie B",
            effective_from=date(2026, 7, 1),
        )
        self.assertGreater(second.id, first.id)
        self.assertEqual(
            active_revision(self.contract, on=date(2026, 7, 1)), second
        )

    def test_a_date_before_the_first_revision_resolves_to_nothing(self):
        """Not to the first revision. The contract had no agreed scope
        before it was agreed, and a forecast for such a date must
        produce nothing rather than borrow the future's prices."""
        self.assertIsNone(active_revision(self.contract, on=date(2025, 12, 31)))

    def test_the_batch_resolver_agrees_with_the_single_one(self):
        """`active_revision_ids` is an optimisation for list pages; if
        it could disagree with `active_revision` the list and the detail
        page would show different money for the same contract."""
        ContractRevision.objects.create(
            contract=self.contract,
            label="Prijsverhoging",
            effective_from=date(2026, 7, 1),
        )
        other = make_contract(
            company=self.company,
            customer=self.customer,
            contract_no="CNT-2026-0002",
            start_date=date(2026, 3, 1),
            lines=[("Glas", "200.00", "2.00")],
        )
        for on in (date(2026, 2, 1), date(2026, 6, 30), date(2026, 7, 1)):
            batch = active_revision_ids(
                [self.contract.id, other.id], on=on
            )
            for contract in (self.contract, other):
                single = active_revision(contract, on=on)
                self.assertEqual(
                    batch.get(contract.id),
                    single.id if single else None,
                    msg=f"disagreement on {on} for {contract.contract_no}",
                )


class RevisionLockingTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.company = Company.objects.create(name="Prov", slug="prov-160-lock")
        cls.customer = Customer.objects.create(
            company=cls.company, name="Customer"
        )
        # `Invoice.created_by` is NOT NULL, so a locking test that bills
        # a period needs somebody to have billed it.
        cls.locker = get_user_model().objects.create_user(
            email="locker-160@example.com",
            password="StrongerTestPassword160!",
            full_name="Locker",
        )

    def _bill_a_period(self, contract, revision, day):
        """The generator's own two writes: an invoice and the claim that
        this contract's period produced it. W11 made that claim the thing
        the lock keys off, so a locking test has to make it."""
        from invoicing.models import Invoice

        from contracts.models import ContractInvoice

        invoice = Invoice.objects.create(
            company=contract.company,
            customer=contract.customer,
            status=Invoice.Status.DRAFT,
            period_year=day.year,
            period_month=day.month,
            created_by=self.locker,
        )
        return ContractInvoice.objects.create(
            contract=contract,
            invoice=invoice,
            revision=revision,
            period_start=day.replace(day=1),
            period_end=day,
            invoice_date=day,
        )

    def test_a_revision_in_force_is_locked_and_a_future_one_is_not(self):
        """W11 — 'in force' is no longer enough on its own; the contract
        must also have billed something. Both halves asserted here."""
        today = timezone.localdate()
        contract = make_contract(
            company=self.company,
            customer=self.customer,
            contract_no="CNT-LOCK-0001",
            start_date=today - timedelta(days=30),
        )
        current = contract.revisions.get()
        future = ContractRevision.objects.create(
            contract=contract,
            label="Volgend jaar",
            effective_from=today + timedelta(days=1),
        )
        # Nothing billed yet: in force, but there is no computed money
        # for an edit to contradict, so it is still open.
        self.assertFalse(is_locked(current))
        self.assertFalse(is_locked(future))

        self._bill_a_period(contract, current, today)
        self.assertTrue(is_locked(current))
        self.assertFalse(
            is_locked(future),
            "a future revision stays open however much has been billed",
        )

    def test_a_revision_locks_on_the_day_it_takes_effect_once_billed(self):
        """W11 — the day alone no longer locks. Locking a revision that
        has produced nothing is what made a contract created today
        impossible to fill in, and left it worth EUR 0.00 for good."""
        today = timezone.localdate()
        contract = make_contract(
            company=self.company,
            customer=self.customer,
            contract_no="CNT-LOCK-0002",
            start_date=today,
        )
        revision = contract.revisions.get()
        self.assertFalse(is_locked(revision))

        self._bill_a_period(contract, revision, today)
        self.assertTrue(is_locked(revision))


class RevisionTotalsTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.company = Company.objects.create(name="Prov", slug="prov-160-tot")
        cls.customer = Customer.objects.create(
            company=cls.company, name="Customer"
        )

    def test_totals_come_from_the_lines(self):
        contract = make_contract(
            company=self.company,
            customer=self.customer,
            contract_no="CNT-TOT-0001",
            lines=[("A", "100.50", "5.25"), ("B", "200.25", "4.75")],
        )
        totals = revision_totals(contract.revisions.get())
        self.assertEqual(totals["amount"], Decimal("300.75"))
        self.assertEqual(totals["hours"], Decimal("10.00"))
        self.assertEqual(totals["line_count"], 2)

    def test_a_revision_with_no_lines_totals_zero_not_null(self):
        contract = make_contract(
            company=self.company,
            customer=self.customer,
            contract_no="CNT-TOT-0002",
            lines=[],
        )
        totals = revision_totals(contract.revisions.get())
        self.assertEqual(totals["amount"], Decimal("0.00"))
        self.assertEqual(totals["hours"], Decimal("0.00"))
        self.assertEqual(totals["line_count"], 0)


class DerivedStatusTests(TestCase):
    """The status an operator sees is derived, and CANNOT contradict
    the dates — because EXPIRED is not storable at all."""

    @classmethod
    def setUpTestData(cls):
        cls.company = Company.objects.create(name="Prov", slug="prov-160-stat")
        cls.customer = Customer.objects.create(
            company=cls.company, name="Customer"
        )

    def mk(self, no, **kwargs):
        return make_contract(
            company=self.company,
            customer=self.customer,
            contract_no=no,
            **kwargs,
        )

    def test_an_active_contract_with_a_past_end_date_reads_expired(self):
        contract = self.mk(
            "CNT-ST-0001",
            start_date=date(2025, 1, 1),
            end_date=date(2025, 12, 31),
            lifecycle=ContractLifecycle.ACTIVE,
        )
        self.assertEqual(
            contract.status(on=date(2026, 6, 1)), ContractStatus.EXPIRED
        )

    def test_an_open_ended_contract_never_expires(self):
        contract = self.mk(
            "CNT-ST-0002",
            start_date=date(2020, 1, 1),
            end_date=None,
            lifecycle=ContractLifecycle.ACTIVE,
        )
        self.assertEqual(
            contract.status(on=date(2099, 1, 1)), ContractStatus.ACTIVE
        )

    def test_draft_and_cancelled_win_over_the_dates(self):
        """An operator statement is not overridden by the calendar: a
        cancelled contract does not become 'expired' when its end date
        passes, and a draft never silently becomes active."""
        draft = self.mk(
            "CNT-ST-0003",
            start_date=date(2025, 1, 1),
            end_date=date(2025, 12, 31),
            lifecycle=ContractLifecycle.DRAFT,
        )
        cancelled = self.mk(
            "CNT-ST-0004",
            start_date=date(2025, 1, 1),
            end_date=date(2025, 12, 31),
            lifecycle=ContractLifecycle.CANCELLED,
        )
        self.assertEqual(
            draft.status(on=date(2026, 6, 1)), ContractStatus.DRAFT
        )
        self.assertEqual(
            cancelled.status(on=date(2026, 6, 1)), ContractStatus.CANCELLED
        )

    def test_expired_cannot_be_stored_at_all(self):
        """The proof that the stored status and the dates can never
        disagree: the database refuses the value that would let them."""
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Contract.objects.create(
                    company=self.company,
                    customer=self.customer,
                    contract_no="CNT-ST-0005",
                    start_date=date(2026, 1, 1),
                    lifecycle="EXPIRED",
                )

    def test_an_end_date_before_the_start_date_is_refused(self):
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Contract.objects.create(
                    company=self.company,
                    customer=self.customer,
                    contract_no="CNT-ST-0006",
                    start_date=date(2026, 6, 1),
                    end_date=date(2026, 1, 1),
                )


class NumberingTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.company_a = Company.objects.create(name="A", slug="prov-160-num-a")
        cls.company_b = Company.objects.create(name="B", slug="prov-160-num-b")

    def test_numbers_are_gapless_per_company_per_year(self):
        with transaction.atomic():
            self.assertEqual(
                allocate_contract_number(self.company_a.id, 2026)[0],
                "CNT-2026-0001",
            )
            self.assertEqual(
                allocate_contract_number(self.company_a.id, 2026)[0],
                "CNT-2026-0002",
            )
            # A different company restarts at 1...
            self.assertEqual(
                allocate_contract_number(self.company_b.id, 2026)[0],
                "CNT-2026-0001",
            )
            # ...and so does a different year.
            self.assertEqual(
                allocate_contract_number(self.company_a.id, 2027)[0],
                "CNT-2027-0001",
            )

    def test_the_format_widens_rather_than_wrapping(self):
        self.assertEqual(format_contract_number(2026, 1), "CNT-2026-0001")
        self.assertEqual(format_contract_number(2026, 9999), "CNT-2026-9999")
        self.assertEqual(format_contract_number(2026, 10000), "CNT-2026-10000")

    def test_two_contracts_of_one_company_cannot_share_a_number(self):
        customer = Customer.objects.create(
            company=self.company_a, name="Customer"
        )
        make_contract(
            company=self.company_a, customer=customer, contract_no="CNT-X-1"
        )
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                make_contract(
                    company=self.company_a,
                    customer=customer,
                    contract_no="CNT-X-1",
                )
