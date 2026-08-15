"""
Sprint 182 §2 — "if this were cut now, your invoice would be this".

THE SINGLE CALCULATION
----------------------
`plan_invoices` is the one function that answers "what would be billed".
Everything that needs that answer calls it:

  * the PREVIEW endpoint (`InvoiceViewSet.preview`) renders its result;
  * `services.generate_draft_invoices` groups by the same rules through
    the same `billing_target` resolver;
  * the month-end job (`tasks.run_daily_invoice_run`) reaches generation
    through that service, so it inherits the same answer.

This matters more than it sounds. This system has already been bitten by
exactly the failure it prevents: the dashboard money tile and the invoice
generator each computed "billable" their own way and drifted apart. A
preview that disagrees with the invoice it is previewing is worse than no
preview — the operator trusts it, sends something else, and finds out
from the customer.

So the preview does NOT reimplement grouping. It plans; generation
executes the same plan.

NOTHING IS STORED
-----------------
Recomputed on every open. There is nothing to expire, nothing to clean
up, and — the real reason — no second source of drafts the month-end job
would have to reconcile against. A stored preview is a draft in all but
name, and two kinds of draft is how you end up invoicing twice.

The consequence to keep in mind: a preview is a photograph, not a
promise. Between opening it and running the job, work can complete, be
relabelled, or be reversed, and the invoice will differ. That is correct
and unavoidable; it is why the PDF is stamped with the moment it was
computed.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

from customers.models import Customer

from .billing_target import (
    customer_billing_target,
    customer_split,
    pair_for_granularity,
    resolve_billing_target,
)
from .selectors import unbilled_extra_work_through

_TWO_PLACES = Decimal("0.01")


@dataclass
class PlannedInvoice:
    """One invoice that WOULD be created, with the rows it would carry.

    Deliberately not an unsaved `Invoice` instance. An unsaved model is
    one careless `.save()` away from becoming a real draft, and this
    object is handed to a serializer and a PDF renderer — both places
    where "just persist it" is a tempting one-liner. A plain dataclass
    cannot be saved by accident.
    """

    building_id: int | None
    department_id: int | None
    work_type_id: int | None
    granularity: str
    extra_works: list = field(default_factory=list)

    @property
    def building_name(self) -> str | None:
        """The addressee building's name, or None for a customer-level plan.

        Read off the rows already in memory rather than queried: every EW
        in a building-addressed plan shares that building by
        construction. Lives here so the JSON serializer and the preview
        PDF label the same plan identically.
        """
        if self.building_id is None:
            return None
        for ew in self.extra_works:
            if ew.building_id == self.building_id:
                return ew.building.name
        return None

    @property
    def subtotal(self) -> Decimal:
        return self._sum(0)

    @property
    def vat(self) -> Decimal:
        return self._sum(1)

    @property
    def total(self) -> Decimal:
        return self._sum(2)

    def _sum(self, index: int) -> Decimal:
        # Imported here rather than at module scope: `services` imports
        # this module's siblings and the amounts helper lives with the
        # generation code that owns the money shape.
        from .services import _earned_amounts

        return sum(
            (_earned_amounts(ew)[index] or Decimal("0.00")
             for ew in self.extra_works),
            Decimal("0.00"),
        ).quantize(_TWO_PLACES)


def plan_invoices(
    actor,
    company_id,
    customer_id,
    year,
    month,
    *,
    granularity=None,
    through=True,
):
    """The invoices that WOULD be created, without creating anything.

    Returns a list of `PlannedInvoice`, ordered exactly the way
    `generate_draft_invoices` creates them: the customer-addressed
    invoice first (when there is one), then the building-addressed ones
    by building id, then by department and work type within a building.
    Matching the order is not cosmetic — an operator comparing the
    preview against the result should not have to sort them by eye.

    `through=True` (the preview default) includes work billable in this
    period OR ANY EARLIER one, via `unbilled_extra_work_through` — the
    same rule the `/due/` panel uses, so the preview shows what is
    actually outstanding rather than silently dropping last month's
    unbilled work once the calendar rolls over.

    `through=False` matches `generate_draft_invoices`' exact-period
    query. The month-end job's own preview-vs-result comparison uses it.

    A ZERO-AMOUNT Extra Work is planned like any other: it appears as a
    row written as zero, not skipped and not hidden. Work that was done
    and came to nothing still belongs on the invoice — leaving it off
    makes the invoice disagree with what the customer was told happened.
    """
    from .selectors import unbilled_extra_work

    customer = Customer.objects.filter(
        id=customer_id, company_id=company_id
    ).first()

    if granularity is None:
        default_target = customer_billing_target(customer)
        split = customer_split(customer)
    else:
        default_target, split = pair_for_granularity(granularity)

    query = unbilled_extra_work_through if through else unbilled_extra_work
    unbilled = query(actor, company_id, customer_id, year, month)
    if not unbilled:
        return []

    customer_addressed = []
    building_addressed = []
    for ew in unbilled:
        target = resolve_billing_target(ew, customer, default=default_target)
        if target == Customer.InvoiceBillingTarget.CUSTOMER:
            customer_addressed.append(ew)
        else:
            building_addressed.append(ew)

    planned: list[PlannedInvoice] = []
    if customer_addressed:
        planned.append(
            PlannedInvoice(
                building_id=None,
                department_id=None,
                work_type_id=None,
                granularity=Customer.InvoiceGranularity.CUSTOMER,
                extra_works=customer_addressed,
            )
        )

    if split == Customer.InvoiceSplit.NONE:
        by_building: dict[int, list] = {}
        for ew in building_addressed:
            by_building.setdefault(ew.building_id, []).append(ew)
        for building_id in sorted(by_building):
            planned.append(
                PlannedInvoice(
                    building_id=building_id,
                    department_id=None,
                    work_type_id=None,
                    granularity=Customer.InvoiceGranularity.PER_BUILDING,
                    extra_works=by_building[building_id],
                )
            )
    else:
        by_group: dict[tuple[int, int | None, int | None], list] = {}
        for ew in building_addressed:
            key = (ew.building_id, ew.department_id, ew.work_type_id)
            by_group.setdefault(key, []).append(ew)

        # Same ordering rule as generation: building, then department,
        # then work type, with None sorting FIRST inside its building (the
        # untagged group reads as the base group ahead of its labelled
        # siblings). -1 stands in for None because None cannot be compared
        # to an int in Python 3; real ids start at 1 so it never collides.
        def _group_sort_key(key):
            b_id, d_id, w_id = key
            return (
                b_id,
                d_id if d_id is not None else -1,
                w_id if w_id is not None else -1,
            )

        for key in sorted(by_group, key=_group_sort_key):
            building_id, department_id, work_type_id = key
            planned.append(
                PlannedInvoice(
                    building_id=building_id,
                    department_id=department_id,
                    work_type_id=work_type_id,
                    granularity=(
                        Customer.InvoiceGranularity
                        .PER_BUILDING_DEPARTMENT_WORK_TYPE
                    ),
                    extra_works=by_group[key],
                )
            )
    return planned
