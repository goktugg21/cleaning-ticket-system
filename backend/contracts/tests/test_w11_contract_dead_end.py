"""
W11 — the two dead ends the owner has reported for six waves, pinned.

Both complaints ("Create Revision does nothing", "a Project cannot be
added") are ONE root cause, and it is not in either of those two
features: both write correctly. It is the lock rule.

`is_locked` closed a revision the moment its effective date ARRIVED. The
rule is right for a revision that has billed something — that is what
was agreed, and money was computed against it. It was applied to a
revision that had billed NOTHING, and that is where the app ate itself:

  * A contract created today gets its first revision effective from its
    own start date. Start a contract today -- the ordinary case -- and
    that revision is born locked, so the contract can never be given a
    single line and is permanently worth EUR 0.00.

  * The only revision the detail page will edit is the one in force
    TODAY. Author one for next month and it is correctly unlocked, but
    it is not the one in force, so nothing on the page changes: the
    write succeeded and the screen looks identical.

The rule now asks whether the contract has ever been INVOICED, which is
the thing the lock actually protects. Before the first invoice there is
no computed money to contradict; after it, every past-dated revision is
closed exactly as before.
"""
from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from django.utils import timezone

from contracts.models import (
    Contract,
    ContractInvoice,
    ContractLifecycle,
    ContractLine,
    ContractRevision,
)
from contracts.revisions import is_locked

from .fixtures import ContractsFixture


class ContractDeadEndTests(ContractsFixture):
    """The contract an operator actually creates: one that starts today."""

    def _contract_starting_today(self):
        today = timezone.localdate()
        contract = Contract.objects.create(
            company=self.company_a,
            customer=self.customer_a,
            contract_no="2026-0900",
            start_date=today,
        )
        revision = ContractRevision.objects.create(
            contract=contract, label="Initial", effective_from=today
        )
        return contract, revision

    def _claim_period(self, contract, revision, day):
        """A real invoice plus the claim row -- the generator's own two
        writes, so the test locks on the same fact production does."""
        from invoicing.models import Invoice

        invoice = Invoice.objects.create(
            company=self.company_a,
            customer=self.customer_a,
            status=Invoice.Status.DRAFT,
            period_year=day.year,
            period_month=day.month,
            created_by=self.ca_a,
        )
        return ContractInvoice.objects.create(
            contract=contract,
            invoice=invoice,
            revision=revision,
            period_start=day.replace(day=1),
            period_end=day,
            invoice_date=day,
        )

    def test_initial_revision_of_a_contract_starting_today_is_editable(self):
        """The bug, from the operator's side: a contract signed today has
        to be fillable today."""
        contract, revision = self._contract_starting_today()
        self.assertFalse(
            is_locked(revision),
            "a revision of a contract that has never been invoiced has no "
            "computed money to protect, so it must stay open",
        )

    def test_revision_locks_once_the_contract_has_been_invoiced(self):
        """And the protection the rule exists for is still there."""
        contract, revision = self._contract_starting_today()
        ContractLine.objects.create(
            revision=revision, name="Daily clean", amount=Decimal("100.00")
        )
        today = timezone.localdate()
        self._claim_period(contract, revision, today)
        self.assertTrue(
            is_locked(revision),
            "once a period has been invoiced the agreement behind it is "
            "closed, and the correction path is a new revision",
        )

    def test_future_revision_stays_open_even_after_invoicing(self):
        """Authoring next month's prices must survive this month's run."""
        contract, revision = self._contract_starting_today()
        today = timezone.localdate()
        future = ContractRevision.objects.create(
            contract=contract,
            label="Next",
            effective_from=today + timedelta(days=30),
        )
        self._claim_period(contract, revision, today)
        self.assertTrue(is_locked(revision))
        self.assertFalse(
            is_locked(future),
            "a revision whose date has not arrived is the whole point of "
            "being able to author one ahead of time",
        )


class ContractBillingReachesTheDailyRunTests(ContractsFixture):
    """W11 — the second half: a contract's monthly fee reaches an invoice
    without anybody typing a management command.

    The generator has been correct and tested since Sprint 164. What it
    never had was a caller, which is why every contract's billing tab
    read EUR 0.00 and the module looked broken rather than unwired.
    """

    def test_the_daily_run_creates_the_contract_invoice(self):
        from invoicing.tasks import run_daily_invoice_run

        today = timezone.localdate()
        first = today.replace(day=1)
        contract = Contract.objects.create(
            company=self.company_a,
            customer=self.customer_a,
            contract_no="2026-0910",
            start_date=first,
            billing_day=1,
            # A DRAFT contract does not bill, by design.
            lifecycle=ContractLifecycle.ACTIVE,
        )
        revision = ContractRevision.objects.create(
            contract=contract, label="Initial", effective_from=first
        )
        ContractLine.objects.create(
            revision=revision,
            name="Monthly cleaning",
            amount=Decimal("1500.00"),
        )

        result = run_daily_invoice_run(today=first.isoformat())

        # The run bills every ACTIVE contract it finds, so the fixture's
        # own contracts are in this number too. What this test pins is
        # that THIS contract's fee reached an invoice, and that it did so
        # from the daily run rather than from a typed command.
        self.assertGreaterEqual(result["contract_invoices_created"], 1)
        claim = ContractInvoice.objects.get(contract=contract)
        self.assertEqual(claim.period_start, first)
        self.assertIsNone(
            claim.invoice.created_by,
            "a scheduled run records the system, not a borrowed person",
        )

    def test_running_twice_creates_one_invoice(self):
        """The claim row is the idempotency key, and Postgres is the
        arbiter -- a beat tick overlapping its predecessor is normal."""
        from invoicing.tasks import run_daily_invoice_run

        today = timezone.localdate()
        first = today.replace(day=1)
        contract = Contract.objects.create(
            company=self.company_a,
            customer=self.customer_a,
            contract_no="2026-0911",
            start_date=first,
            billing_day=1,
            # A DRAFT contract does not bill, by design.
            lifecycle=ContractLifecycle.ACTIVE,
        )
        revision = ContractRevision.objects.create(
            contract=contract, label="Initial", effective_from=first
        )
        ContractLine.objects.create(
            revision=revision, name="Monthly", amount=Decimal("900.00")
        )

        run_daily_invoice_run(today=first.isoformat())
        before = ContractInvoice.objects.filter(contract=contract).count()
        run_daily_invoice_run(today=first.isoformat())

        self.assertEqual(before, 1)
        self.assertEqual(
            ContractInvoice.objects.filter(contract=contract).count(),
            1,
            "a second pass must find the period already claimed",
        )
