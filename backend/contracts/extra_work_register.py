"""
W16 — the EXTRA WORKS REGISTER, one per customer.

    The owner: "make the contracts page exactly the same as my
    father's system. Establish those connections."

The reference system's
`ContractController::getOrCreateExtraWorksContract($customerId)` gives
every customer an auto-created contract that carries one line per piece
of ad-hoc work, so a customer's chargeable spend has a page, grouped by
building, with a total. That idea is copied here in full.

--------------------------------------------------------------------
Three things his does not do, and why ours must
--------------------------------------------------------------------

**1. His lines are hand-typed. Ours are PROJECTED.**

`addExtraWorkLine` takes `description` + `amount_year` from a form and
stores them. `ContractLine` in his schema has no `extra_work_id` and no
other link to a job — a repo-wide grep finds no ExtraWork controller or
service that touches `ContractLine` at all. So his register is a second
set of books that an operator keeps in step by hand, and the moment the
job's price changes it is wrong and nothing says so.

Ours holds `ContractLine.extra_work`, and `sync_extra_work_register`
rebuilds every amount from `reports.dimensions._amounts_for_state` —
the named server-side mirror of `rowAmounts()`. The register cannot
drift from the invoice because it does not hold an independent number.

**2. His register is not connected to billing. Neither is ours — and
that is deliberate, not an omission.**

It would be easy to read "all billing flows through contracts" and wire
the register into `contracts/invoice_generation.py`. That would double-
bill every customer. Our Extra Work already reaches an invoice through
`invoicing/selectors.py`, whose unbilled pool is defined as "no live
`InvoiceLine` claims this row"; a register line is not an `InvoiceLine`
and would not claim anything, so the pool would offer the same work a
second time.

So the register is a MIRROR. `invoice_generation` refuses a register
and `billing.build_forecast` returns an empty forecast for one, both
with tests. See `ContractKind`.

**3. His totals are stored and recomputed on demand
(`Contract::recalculateTotals`, `POST /contracts/{id}/recalculate`).
Ours are derived on read.**

A stored total is a copy, and a copy drifts the moment anything writes
a line without calling the recompute — which is exactly what his
`addExtraWorkLine` does: it creates the line and returns, never calling
`recalculateTotals`, so his contract header is stale until somebody
presses a button. `contracts/revisions.py::annotate_revision_totals`
sums the lines in the query that reads them, so ours cannot be stale.
`recalculate_register` exists anyway, because a PROJECTION genuinely
can go out of date when the underlying job changes — but what it
refreshes is the LINE SET, not a cached sum.

--------------------------------------------------------------------
Which work is on the register
--------------------------------------------------------------------

Every chargeable Extra Work for the customer that was not called off —
`extra_work.billing.NON_BILLABLE_STATUSES` is the test, the same one
`is_billable` applies before an invoice. Work still in progress is ON
the register, priced at its quote, because "what has this customer
committed to" is the question the page answers; `earned_amount` in the
summary is the narrower "what may be invoiced" figure, and it asks
`is_billable` rather than restating it.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Optional

from django.db import transaction
from django.utils import timezone

from extra_work.billing import NON_BILLABLE_STATUSES, is_billable
from extra_work.models import ExtraWorkRequest
from reports.dimensions import _amounts_for_state, _classify_extra_work
from tickets.models import Ticket

from .models import (
    Contract,
    ContractKind,
    ContractLifecycle,
    ContractLine,
    ContractRevision,
)


#: The label the register's single revision carries. A register is not
#: versioned — it mirrors live work — so it has exactly one revision and
#: this names it rather than leaving a blank in the UI.
REGISTER_REVISION_LABEL = "Extra work"

ERR_REGISTER_NOT_INVOICEABLE = "contract_register_not_invoiceable"


def _register_contract_no(customer) -> str:
    """`EW-<customer id>`, mirroring his `EW-000123`.

    Deliberately NOT drawn from `ContractNumberSequence`: that sequence
    is gapless per company per year and belongs to documents somebody
    signed. A register is machinery, and burning a real contract number
    on one every time a customer is created would put gaps in the
    series that matters.
    """
    return f"EW-{customer.id:06d}"


def _ticket_map(ews):
    """`{extra_work_id: ticket}` for the spawned tickets, in ONE query.

    `_classify_extra_work` and `is_billable` both need the ticket, and
    fetching it per row is the N+1 the query-count tests exist to
    catch.
    """
    ticket_by_ew = {}
    for ticket in Ticket.objects.filter(
        extra_work_request__in=[ew.id for ew in ews],
        deleted_at__isnull=True,
    ).order_by("id"):
        ticket_by_ew.setdefault(ticket.extra_work_request_id, ticket)
    return ticket_by_ew


def register_extra_work(company_id, customer_id):
    """The Extra Work rows the register mirrors, oldest first."""
    return list(
        ExtraWorkRequest.objects.filter(
            company_id=company_id,
            customer_id=customer_id,
            deleted_at__isnull=True,
        )
        .exclude(status__in=NON_BILLABLE_STATUSES)
        .select_related("building")
        .order_by("id")
    )


@transaction.atomic
def get_or_create_register(company, customer, *, actor=None) -> Contract:
    """The customer's register, created on first ask.

    `get_or_create` on `(company, customer, kind)` — the uniqueness is
    the point, because two registers for one customer would each show
    half the money. A partial unique index enforces it in the database
    as well, so a race cannot make the second one.
    """
    contract, created = Contract.objects.get_or_create(
        company=company,
        customer=customer,
        kind=ContractKind.EXTRA_WORK,
        defaults={
            "contract_no": _register_contract_no(customer),
            # ACTIVE, not DRAFT: the register is not a proposal anybody
            # approves, it is a view of work already agreed one job at
            # a time. A DRAFT register would invite somebody to press
            # "activate" on a thing that has no such state.
            "lifecycle": ContractLifecycle.ACTIVE,
            "start_date": timezone.localdate().replace(month=1, day=1),
            "end_date": None,
            "description": (
                "Chargeable work for this customer. One line per job, "
                "priced by the same rule the invoice uses."
            ),
        },
    )
    if created:
        ContractRevision.objects.create(
            contract=contract,
            label=REGISTER_REVISION_LABEL,
            effective_from=contract.start_date,
            created_by=actor,
        )
    return contract


def register_revision(contract) -> ContractRevision:
    """The register's one revision, made if a legacy row lacks it."""
    revision = contract.revisions.order_by("effective_from", "id").first()
    if revision is None:
        revision = ContractRevision.objects.create(
            contract=contract,
            label=REGISTER_REVISION_LABEL,
            effective_from=contract.start_date,
        )
    return revision


@transaction.atomic
def sync_extra_work_register(company, customer, *, actor=None) -> dict:
    """Rebuild the register's lines from the customer's live work.

    Idempotent by construction: the line set is keyed on
    `ContractLine.extra_work`, so running this twice produces the same
    rows. Work that has since been called off loses its line; work
    whose price changed has its amount rewritten from the one rule.

    Returns `{"added": n, "updated": n, "removed": n}` so the caller
    can say what changed in a sentence rather than "done".
    """
    contract = get_or_create_register(company, customer, actor=actor)
    revision = register_revision(contract)

    ews = register_extra_work(company.id, customer.id)
    tickets = _ticket_map(ews)

    existing = {
        line.extra_work_id: line
        for line in revision.lines.filter(extra_work__isnull=False)
    }
    seen = set()
    added = updated = 0

    for index, ew in enumerate(ews):
        ticket = tickets.get(ew.id)
        state = _classify_extra_work(ew, ticket)
        subtotal, vat, total = _amounts_for_state(ew, state)
        name = (ew.title or "").strip() or f"Extra work #{ew.id}"
        fields = {
            "name": name,
            "building": ew.building,
            "sort_order": index,
            "hours": Decimal("0.00"),
            "amount": total or Decimal("0.00"),
            "vat_pct": _blended_vat_pct(subtotal, vat),
        }
        line = existing.get(ew.id)
        if line is None:
            ContractLine.objects.create(
                revision=revision, extra_work=ew, **fields
            )
            added += 1
        else:
            changed = [
                key
                for key, value in fields.items()
                if getattr(line, key) != value
            ]
            if changed:
                for key, value in fields.items():
                    setattr(line, key, value)
                line.save(update_fields=[*fields.keys(), "updated_at"])
                updated += 1
        seen.add(ew.id)

    stale = [ew_id for ew_id in existing if ew_id not in seen]
    removed = 0
    if stale:
        removed, _ = revision.lines.filter(extra_work_id__in=stale).delete()

    return {"added": added, "updated": updated, "removed": removed}


def _blended_vat_pct(subtotal, vat) -> Decimal:
    """A display-only blended VAT %, exactly as
    `invoicing.services._derive_vat_pct` computes it for the invoice
    line built from the same figures. Cosmetic: `amount` is the
    authoritative number on a register line."""
    subtotal = subtotal or Decimal("0.00")
    vat = vat or Decimal("0.00")
    if subtotal and subtotal != Decimal("0"):
        return (vat / subtotal * Decimal("100")).quantize(Decimal("0.01"))
    return Decimal("21.00")


def register_summary(contract, revision, ews, tickets) -> dict:
    """The numbers the register's header shows. THREE, not one.

    One figure would be a lie whichever one it was, and finding that
    out is what the build measured. On the seeded B Amsterdam customer
    the register totals EUR 990.99 of earned work while the invoice run
    offers EUR 660.66 — and BOTH are right. The third earned job
    (EUR 330.33) carries `is_invoiced=True`: it has been billed already,
    so it is correctly absent from the unbilled pool and correctly
    present on the register. A header showing only "earned" would have
    read as "still to bill" and been wrong by a third.

    So the register answers the three questions separately:

      * `total_amount`   — every job on the register, committed and
        finished alike. "What has this customer taken on."
      * `earned_amount`  — the finished, chargeable part, invoiced or
        not. Asks `extra_work.billing.is_billable`, the same predicate
        the invoice run applies, rather than restating it.
      * `invoiced_amount` — the part already SETTLED. The difference
        `earned - invoiced` is therefore exactly what the Extra Work run
        still has to bill, and it can be read off the page instead of
        guessed.

    ## "Settled" is two things, and using only one of them was a bug

    The first version of this counted a job as invoiced when a live
    `InvoiceLine` claimed it. Measured against the seeded data it read
    EUR 0.00 invoiced while the run could only find EUR 660.66 of the
    EUR 990.99 to bill — a page that would have promised a third more
    revenue than existed.

    `invoicing.selectors` excludes a job from the unbilled pool on
    EITHER of two tests, and the register has to ask both or it cannot
    reconcile:

      * the legacy `is_invoiced` boolean, which the bulk runs and the
        seed set without ever writing an `InvoiceLine`; and
      * a LIVE invoice line — not soft-deleted, not reversed, and
        belonging to THIS customer, because on a shared building one
        share-holder's invoice must not settle another's part.

    Both are read here, in that order, mirroring
    `_scoped_unbilled_ew_with_tickets`.
    """
    from invoicing.models import InvoiceLine

    lines = list(revision.lines.select_related("building"))
    by_ew = {line.extra_work_id: line for line in lines}

    claimed_ids = set(
        InvoiceLine.objects.filter(
            extra_work_id__in=[ew.id for ew in ews],
            invoice__deleted_at__isnull=True,
            invoice__reversed_by__isnull=True,
            invoice__customer_id=contract.customer_id,
        ).values_list("extra_work_id", flat=True)
    )

    earned = Decimal("0.00")
    invoiced = Decimal("0.00")
    for ew in ews:
        line = by_ew.get(ew.id)
        if line is None:
            continue
        if is_billable(ew, tickets.get(ew.id)):
            earned += line.amount
            if ew.is_invoiced or ew.id in claimed_ids:
                invoiced += line.amount

    total = sum((line.amount for line in lines), Decimal("0.00"))
    buildings = {line.building_id for line in lines if line.building_id}
    return {
        "job_count": len(lines),
        "building_count": len(buildings),
        "total_amount": total,
        "earned_amount": earned,
        "invoiced_amount": invoiced,
    }
