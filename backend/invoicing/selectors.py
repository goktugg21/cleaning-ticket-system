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
    * it is claimed by a LIVE InvoiceLine — where "live" means the claiming
      invoice is neither soft-deleted NOR itself REVERSED. (Phase 2b: a
      SENT original stays on the books after a reversal — we do NOT soft-
      delete it — so its line still points at the EW; but the reversal is
      the counter-entry and the work is released, so a reversed original's
      claim no longer counts.)

Release paths, both of which flip BOTH exclusion legs off:
  * delete draft (Phase 2a): soft-delete the invoice + clear `is_invoiced`.
  * reverse a SENT invoice (Phase 2b): the original is reversed (its claim
    stops counting) + `reverse_invoice` clears `is_invoiced`.

We REUSE the earned / billing-month logic verbatim from
`extra_work.billing` (build_ticket_map / is_earned / billing_month) and the
tenant scope from `extra_work.scoping.scope_extra_work_for` — this selector
adds only the Option-1 "not yet claimed" test on top of the same filter the
M4 mark-invoiced run used.
"""
from __future__ import annotations

from django.db.models import Exists, OuterRef

from accounts.models import UserRole
from accounts.scoping import scope_customers_for
from buildings.models import BuildingManagerAssignment
from companies.models import CompanyUserMembership
from extra_work.billing import billing_month, build_ticket_map, is_earned
from extra_work.scoping import scope_extra_work_for

from .models import Invoice, InvoiceLine


def _is_anonymous(user) -> bool:
    return user is None or not getattr(user, "is_authenticated", False)


def scope_invoices_for(user):
    """
    Return the queryset of (non-soft-deleted) Invoices visible to `user`,
    tenant-scoped by COMPANY (mirrors the provider branches of
    scope_extra_work_for, but at company granularity so both customer-level
    (building=NULL) and per-building invoices are covered uniformly):

      * SUPER_ADMIN      -> every invoice.
      * COMPANY_ADMIN    -> invoices of the companies they belong to.
      * BUILDING_MANAGER -> invoices of the companies they manage a building
        in (company-level, so a customer-level invoice with building=NULL is
        still reachable).
      * everyone else (STAFF / CUSTOMER_USER / anon) -> none. Customer
        visibility is Phase 5; the fetch endpoint additionally gates on
        _is_provider_operator, so non-operators 403 before scope matters.

    A soft-deleted invoice (a released draft) is never fetchable; a reversed
    original stays SENT and IS fetchable.
    """
    if _is_anonymous(user):
        return Invoice.objects.none()
    base = Invoice.objects.filter(deleted_at__isnull=True)
    if user.role == UserRole.SUPER_ADMIN:
        return base
    if user.role == UserRole.COMPANY_ADMIN:
        company_ids = CompanyUserMembership.objects.filter(
            user=user
        ).values_list("company_id", flat=True)
        return base.filter(company_id__in=company_ids)
    if user.role == UserRole.BUILDING_MANAGER:
        company_ids = BuildingManagerAssignment.objects.filter(
            user=user
        ).values_list("building__company_id", flat=True)
        return base.filter(company_id__in=company_ids)
    return Invoice.objects.none()


def scope_customer_invoices_for(user):
    """
    Phase 5 — the CUSTOMER read scope (SEPARATE from the provider
    `scope_invoices_for`; this one does NOT widen provider visibility).

    Returns the queryset of invoices a CUSTOMER_USER may see in the customer
    portal. MEMBERSHIP-LEVEL ownership (owner decision): a customer sees an
    invoice iff they are a MEMBER of that invoice's customer — resolved via
    `accounts.scoping.scope_customers_for` (the same CustomerUserMembership
    axis used everywhere else), NOT per-building access. An invoice is a
    financial document of the customer as a legal entity, so this covers the
    customer-level invoice (building=NULL) AND every per-building invoice of
    that customer uniformly.

    Three HARD INVARIANTS baked in here:
      1. status == SENT only — a customer NEVER sees a DRAFT or an ISSUED
         invoice (a reversal is created ISSUED, so a credit note surfaces to
         the customer only if/when it is SENT — acceptable for v1).
      2. their own customer(s) only — `customer_id` must be in the caller's
         membership scope (no cross-tenant, no other customers of the same
         provider they aren't a member of).
      3. never a soft-deleted invoice (`deleted_at IS NULL`).

    NON-customer roles (SUPER_ADMIN / COMPANY_ADMIN / BUILDING_MANAGER /
    STAFF / anon) get `.none()` — this helper is the CUSTOMER path ONLY; the
    provider path stays `scope_invoices_for`.
    """
    if _is_anonymous(user):
        return Invoice.objects.none()
    if user.role != UserRole.CUSTOMER_USER:
        return Invoice.objects.none()
    # scope_customers_for resolves the caller's CustomerUserMembership set
    # (active customers only) — reuse it verbatim as the ownership axis.
    customer_ids = scope_customers_for(user).values_list("id", flat=True)
    return Invoice.objects.filter(
        deleted_at__isnull=True,
        status=Invoice.Status.SENT,
        customer_id__in=customer_ids,
    )


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
        # Phase 2b: a REVERSED original no longer holds its claim — its work
        # is released back to the pool by the reversal counter-entry.
        invoice__reversed_by__isnull=True,
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
