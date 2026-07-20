"""
Invoicing — Phase 2a read models (selectors).

The unbilled-EW pool under OPTION 1 (the invoice is the single source of
truth for "invoiced"):

  A billable ExtraWorkRequest is UNBILLED iff it is earned + in the asked
  billing month AND it is not already settled — where "already settled"
  means EITHER:
    * `is_invoiced=True` (the fast-exclusion flag; also covers the legacy
      M4 bulk-run rows, which are treated as ALREADY SETTLED and must NEVER
      resurface into the pool), OR
    * it is claimed by a LIVE (non-soft-deleted) InvoiceLine.

Releasing a draft (Phase 2c) soft-deletes the invoice AND clears
`is_invoiced`, so the EW reappears here (both exclusion legs flip off).

We REUSE the earned / billing-month logic verbatim from
`extra_work.billing` (build_ticket_map / is_earned / billing_month) and the
tenant scope from `extra_work.scoping.scope_extra_work_for` — this selector
adds only the Option-1 "not yet claimed" test on top of the same filter the
M4 mark-invoiced run used.
"""
from __future__ import annotations

from django.db.models import Exists, OuterRef

from extra_work.billing import billing_month, build_ticket_map, is_earned
from extra_work.scoping import scope_extra_work_for

from .models import InvoiceLine


def unbilled_extra_work(actor, company_id, customer_id, year, month, building_id=None):
    """
    Return the list of ExtraWorkRequest rows for (company, customer) that
    are billable in (year, month) and NOT yet claimed (Option 1).

    Every ExtraWorkRequest is tied to exactly one building (the FK is
    NON-nullable / PROTECT), so there is no buildingless / company-wide EW:
    per-building generation is clean and a customer-level invoice is just
    all the customer's buildings' EW combined. (Revisit only if EW ever
    becomes buildingless.)
    """
    live_claim = InvoiceLine.objects.filter(
        extra_work_id=OuterRef("pk"),
        invoice__deleted_at__isnull=True,
    )
    qs = (
        scope_extra_work_for(actor)
        .filter(
            company_id=company_id,
            customer_id=customer_id,
            deleted_at__isnull=True,
            # Option-1 fast exclusion: is_invoiced rows (incl. the legacy
            # M4 bulk-run settled rows) never resurface into the pool.
            is_invoiced=False,
        )
        .annotate(_live_claim=Exists(live_claim))
        .filter(_live_claim=False)
    )
    if building_id is not None:
        qs = qs.filter(building_id=building_id)

    ew_list = list(qs)
    # Earned + correct month — reuse the M4/reports logic exactly.
    ticket_map = build_ticket_map([e.id for e in ew_list])
    return [
        e
        for e in ew_list
        if is_earned(ticket_map.get(e.id))
        and billing_month(e, ticket_map.get(e.id)) == (year, month)
    ]
