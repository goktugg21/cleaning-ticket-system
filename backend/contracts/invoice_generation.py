"""
Sprint 164 §8 — turning a DUE forecast row into a real invoice.

`contracts/billing.py` is a pure function that says what WOULD be
invoiced. This module is the only place that acts on it, and it is
deliberately the only module in `contracts` that imports `invoicing`.

The dependency runs ONE WAY. `invoicing` gained no column, no field and
no behaviour: the claim that a period has been invoiced lives in
`contracts.ContractInvoice`, in the app that grew the need. Nothing an
existing invoicing caller does changes, and a test pins that.

--------------------------------------------------------------------
What it makes, and what it deliberately does not
--------------------------------------------------------------------

DRAFT invoices, and nothing else. No issue, no send, and **no number** —
numbering is assigned at SEND, gapless per company per year
(`invoicing/numbering.py`, and `sot-addendum-b-invoicing.md` §B.2), and
a generator that reached into that sequence would be allocating numbers
for documents nobody has approved. A DRAFT with `number=NULL` is exactly
what the schema is shaped for: the `(company, number)` unique constraint
tolerates any quantity of NULLs.

One `InvoiceLine` per `ContractLine` of the revision **in force on that
period's date** — not the revision in force today. That is the whole
point of revisions: a period bills what was agreed then. A contract
whose price rose in July bills June at June's price when the run
catches up in August.

--------------------------------------------------------------------
Idempotency
--------------------------------------------------------------------

The claim is a ROW, and the database refuses the second one:
`ContractInvoice` carries `UniqueConstraint(contract, period_start)`.
The generator does not read-then-decide; it attempts the insert inside a
savepoint and treats `IntegrityError` as "another run already has this
period". Two concurrent runs therefore produce one invoice, because the
arbiter is Postgres rather than a Python `if`.

That shape is chosen against a specific prior defect: `ensure_default_
labels` shipped a check-then-create that two requests could both pass.
A generator is far likelier to run twice at once than that ever was —
a cron overlapping its previous tick is the normal failure — so the
weaker shape is not available here.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Optional

from django.db import IntegrityError, transaction
from django.utils import timezone

from .billing import build_forecast, money
from .models import Contract, ContractInvoice, ContractLifecycle
from .revisions import active_revision


logger = logging.getLogger(__name__)


@dataclass
class GenerationResult:
    """What one run did. Returned rather than logged-and-forgotten so a
    management command, a test and a future task can all report the same
    numbers."""

    created: list
    skipped_existing: int = 0
    skipped_not_due: int = 0
    skipped_no_revision: int = 0

    @property
    def created_count(self) -> int:
        return len(self.created)


def _scheduled_rows(contract, year: int, on: date):
    """EVERY scheduled row for one year, including the first invoice the
    preview hides.

    `build_forecast` is a preview: Sprint 160 §5 has it exclude the
    already-raised first invoice, which is right on screen and wrong
    here — a generator that skipped the first period would never bill
    it. Rather than add a generator flag to a pure display function,
    the first period is rebuilt from the same primitives it uses.
    """
    from datetime import timedelta

    from .billing import (
        ForecastRow,
        _amount_for_period,
        _invoice_date_for,
        _months_per_period,
        _prorate,
        period_end_for_index,
        period_index,
        period_start_for_index,
    )

    forecast = build_forecast(contract, year, on=on)
    rows = list(forecast.rows)
    if not forecast.excluded_first_invoice:
        return rows

    months = _months_per_period(contract)
    index = period_index(contract.start_date, months)
    p_start = period_start_for_index(index, months)
    p_end = period_end_for_index(index, months)
    covered_start = max(p_start, contract.start_date)
    covered_end = min(p_end, contract.end_date) if contract.end_date else p_end
    period_days = (p_end - p_start).days + 1
    covered_days = max(0, (covered_end - covered_start).days + 1)
    if covered_days <= 0:
        return rows

    invoice_date = _invoice_date_for(contract, p_start, p_end, is_first=True)
    if invoice_date.year != year:
        return rows

    revisions = list(
        contract.revisions.order_by("-effective_from", "-id").prefetch_related(
            "lines"
        )
    )
    base = _amount_for_period(contract, covered_start, revisions)
    amount = (
        _prorate(base, covered_days, period_days)
        if contract.start_proration
        else money(base)
    )
    rows.insert(
        0,
        ForecastRow(
            invoice_date=invoice_date,
            due_date=invoice_date + timedelta(days=contract.payment_terms_days),
            period_start=covered_start,
            period_end=covered_end,
            amount=amount,
            is_prorated=contract.start_proration and covered_days < period_days,
            covered_days=covered_days,
            period_days=period_days,
        ),
    )
    return rows


def _due_rows(contract, on: date):
    """Every period whose invoice date has ARRIVED and which is not
    already claimed.

    The forecast is computed per YEAR, so catching up after a gap means
    walking the years between the contract's start and today — a handful
    of iterations bounded by the contract's own dates, not a scan.
    """
    first_year = contract.start_date.year
    last_year = min(
        on.year, contract.end_date.year if contract.end_date else on.year
    )
    seen = set()
    for year in range(first_year, last_year + 1):
        for row in _scheduled_rows(contract, year, on):
            if row.invoice_date > on:
                continue
            if row.period_start in seen:
                continue
            seen.add(row.period_start)
            yield row


def generate_invoices_for_contract(
    contract, *, actor, on: Optional[date] = None
) -> GenerationResult:
    """Create DRAFT invoices for every due, not-yet-invoiced period.

    `actor` is REQUIRED and has no default. `Invoice.created_by` is NOT
    NULL, so every invoice records who made it — and a scheduled run is
    not exempt from that question, it just has to answer it in
    configuration instead of from a request. The management command
    takes the user explicitly for the same reason.

    (Found the hard way: the first version of this passed `actor=None`
    and wrapped the write in a broad `except IntegrityError`, which
    swallowed the NOT NULL violation and reported "nothing was due".)

    Returns a `GenerationResult`. Never raises for the ordinary
    "already generated" case — that is the expected outcome of a second
    run and is counted, not reported as a failure.
    """
    if actor is None:
        raise ValueError(
            "generate_invoices_for_contract requires an actor: "
            "Invoice.created_by is NOT NULL."
        )
    from invoicing.models import Invoice, InvoiceLine
    from invoicing.services import recompute_invoice_totals

    today = on or timezone.localdate()
    result = GenerationResult(created=[])

    # A DRAFT or CANCELLED contract does not bill. The status is derived
    # (`Contract.status`), so this reads the same answer the UI shows
    # rather than a second interpretation of the dates.
    if contract.lifecycle != ContractLifecycle.ACTIVE:
        return result

    for row in _due_rows(contract, today):
        revision = active_revision(contract, on=row.period_start)
        if revision is None:
            # No agreed scope covered that period. Nothing to bill, and
            # inventing a zero invoice would be worse than none.
            result.skipped_no_revision += 1
            continue

        lines = list(revision.lines.all())
        if not lines:
            result.skipped_no_revision += 1
            continue

        try:
            # One savepoint per period: a duplicate refused here must not
            # poison the surrounding transaction, and the next period
            # must still get its chance.
            with transaction.atomic():
                invoice = Invoice.objects.create(
                    company=contract.company,
                    customer=contract.customer,
                    status=Invoice.Status.DRAFT,
                    period_year=row.period_start.year,
                    period_month=row.period_start.month,
                    created_by=actor,
                )
                for index, line in enumerate(lines):
                    amount = money(line.amount)
                    vat = money(amount * line.vat_pct / Decimal("100"))
                    InvoiceLine.objects.create(
                        invoice=invoice,
                        ordering=index,
                        description=line.name,
                        # NULL — this line came from a contract, not
                        # from an extra-work row. The column is nullable
                        # precisely for a hand-added free-text line, and
                        # a contract line is that shape.
                        extra_work=None,
                        quantity=Decimal("1.00"),
                        unit_price=amount,
                        vat_pct=line.vat_pct,
                        line_subtotal=amount,
                        line_vat=vat,
                        line_total=money(amount + vat),
                        period_year=row.period_start.year,
                        period_month=row.period_start.month,
                    )
                recompute_invoice_totals(invoice)
                # The CLAIM. Its unique constraint is what makes a second
                # run — or a concurrent one — a no-op rather than a
                # duplicate.
                ContractInvoice.objects.create(
                    contract=contract,
                    invoice=invoice,
                    revision=revision,
                    period_start=row.period_start,
                    period_end=row.period_end,
                    invoice_date=row.invoice_date,
                )
            result.created.append(invoice)
        except IntegrityError as exc:
            # ONLY the duplicate-claim case is expected. Anything else
            # is a real defect and must surface: a broad catch here is
            # what hid a NOT NULL violation on the first attempt at this
            # module and turned it into a silent "nothing was due".
            if "uniq_contract_invoice_per_period" not in str(exc):
                raise
            # Another run got this period first.
            result.skipped_existing += 1
            logger.info(
                "contracts: period %s of contract #%s was already "
                "invoiced; skipping",
                row.period_start,
                contract.pk,
            )

    return result


def generate_invoices(
    *, actor, company=None, on: Optional[date] = None
) -> GenerationResult:
    """Run the generator across every ACTIVE contract, optionally of one
    company. The callable a management command, a test, or a future
    scheduled task all share.
    """
    today = on or timezone.localdate()
    combined = GenerationResult(created=[])
    contracts = Contract.objects.filter(lifecycle=ContractLifecycle.ACTIVE)
    if company is not None:
        contracts = contracts.filter(company=company)
    for contract in contracts.select_related("company", "customer"):
        one = generate_invoices_for_contract(contract, actor=actor, on=today)
        combined.created.extend(one.created)
        combined.skipped_existing += one.skipped_existing
        combined.skipped_not_due += one.skipped_not_due
        combined.skipped_no_revision += one.skipped_no_revision
    return combined
