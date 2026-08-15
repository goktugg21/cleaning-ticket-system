"""
Sprint 182 §3 — who an invoice is addressed to, and how finely it splits.

ONE place answers both questions, because they used to be answered by one
dropdown that conflated them and by call sites that each re-derived a bit
of it.

The two questions
-----------------
**Target** — is this invoice addressed to the BUILDING or to the CUSTOMER
organisation? This is what populates `Invoice.building` (NULL for a
customer-level invoice, set for a per-building one).

**Split** — does the target's work land on ONE invoice, or is it split by
department and work type? This is a refinement *within* a building target;
it is not a third addressee.

Precedence: the Extra Work wins
-------------------------------
`ExtraWorkRequest.billed_to` is the more specific statement — somebody
looked at this particular job and said who pays for it — so when it is set
it beats the customer's default. When it is NULL the row follows the
customer.

A consequence worth stating plainly, because it looks like a bug the first
time you see it: a customer set to "per building" with one Extra Work
marked "bill the customer" produces BOTH kinds of invoice in the same run.
That is correct. `resolve_billing_target` is per-EW for exactly this
reason.

Integration note (Sprint 182, four agents in parallel)
-----------------------------------------------------
Agent A is making `ExtraWorkRequest.billed_to` NULLABLE, NULL meaning
"follow the customer". On THIS branch the column is still NOT NULL with a
`BUILDING` default, so every existing row reads BUILDING and would
override its customer. `_ew_billed_to` therefore treats the field as an
override only when it is genuinely set, and the whole module is written to
the post-A semantics. See `EW_BILLED_TO_IS_NULLABLE` below for the switch
and the report for why this must be merged together with A.
"""
from __future__ import annotations

from customers.models import Customer


# Sprint 182 §3 — is `ExtraWorkRequest.billed_to` nullable yet?
#
# Resolved from the model field itself rather than hardcoded, so this
# module behaves correctly BEFORE and AFTER Agent A's migration without
# anyone having to remember to flip a constant:
#
#   * Before A lands: the column is NOT NULL with a BUILDING default, so
#     every row carries a value nobody chose. Treating those as deliberate
#     overrides would silently route every customer's work per-building.
#     While the field cannot be null, we ignore it entirely and follow the
#     customer's setting — which is exactly today's behaviour.
#   * After A lands: NULL means "follow the customer" and a non-NULL value
#     is a real decision, so it wins.
#
# The check is a one-time model introspection, not a per-call query.
def _ew_billed_to_is_nullable() -> bool:
    from extra_work.models import ExtraWorkRequest

    return ExtraWorkRequest._meta.get_field("billed_to").null


def _ew_billed_to(ew):
    """The EW's OWN billing target, or None when it has not stated one.

    Returns a `Customer.InvoiceBillingTarget` value or None. Anything
    unrecognised reads as None (follow the customer) rather than raising —
    an unknown string is not a decision.
    """
    if not _ew_billed_to_is_nullable():
        # Pre-Agent-A schema: the value is a non-null default nobody
        # chose. Not an override. See the module docstring.
        return None
    raw = getattr(ew, "billed_to", None)
    if not raw:
        return None
    value = str(raw).upper()
    if value in {
        Customer.InvoiceBillingTarget.BUILDING,
        Customer.InvoiceBillingTarget.CUSTOMER,
    }:
        return value
    return None


def resolve_billing_target(ew, customer, *, default=None) -> str:
    """Who THIS Extra Work's invoice is addressed to.

    ONE rule, applied to every row: the EW's own `billed_to` wins when
    set; otherwise the row follows `default`, which is the customer's
    `invoice_billing_target` unless the caller supplies another.

    `default` exists because the `generate` endpoint still accepts an
    explicit granularity override. That override supplies the default for
    rows with no opinion of their own — it does NOT overrule a row that
    states one, because "this job is billed to the customer" is a fact
    about the job, not a preference about the run.

    Returns a `Customer.InvoiceBillingTarget` value — never None, because
    every row has to land on some invoice.
    """
    own = _ew_billed_to(ew)
    if own is not None:
        return own
    if default is not None:
        return default
    return customer_billing_target(customer)


def customer_billing_target(customer) -> str:
    """The customer's default target, defensive about a missing customer.

    A customer we cannot resolve falls back to CUSTOMER-level, which is
    also the model default: one invoice addressed to the organisation is
    the least surprising thing to produce when the setting is unknown, and
    it never invents a building attribution nobody asked for.
    """
    if customer is None:
        return Customer.InvoiceBillingTarget.CUSTOMER
    return (
        customer.invoice_billing_target
        or Customer.InvoiceBillingTarget.CUSTOMER
    )


def customer_split(customer) -> str:
    """How finely the customer's invoices split. NONE when unresolvable."""
    if customer is None:
        return Customer.InvoiceSplit.NONE
    return customer.invoice_split or Customer.InvoiceSplit.NONE


# ---------------------------------------------------------------------------
# The legacy `InvoiceGranularity` vocabulary
# ---------------------------------------------------------------------------
#
# `Invoice.granularity` records, per invoice, which granularity produced
# it, and `state_machine._resync_invoice_group_labels` keys off the
# PER_BUILDING_DEPARTMENT_WORK_TYPE value to decide whether an invoice ever
# claimed a department/work-type grouping. That is a real behavioural
# dependency on the old vocabulary, so the split does NOT retire it — it
# derives it. One direction only: the (target, split) pair is the input,
# the granularity string is the output.

_PAIR_TO_GRANULARITY = {
    (
        Customer.InvoiceBillingTarget.CUSTOMER,
        Customer.InvoiceSplit.NONE,
    ): Customer.InvoiceGranularity.CUSTOMER,
    (
        Customer.InvoiceBillingTarget.BUILDING,
        Customer.InvoiceSplit.NONE,
    ): Customer.InvoiceGranularity.PER_BUILDING,
    (
        Customer.InvoiceBillingTarget.BUILDING,
        Customer.InvoiceSplit.DEPARTMENT_WORK_TYPE,
    ): Customer.InvoiceGranularity.PER_BUILDING_DEPARTMENT_WORK_TYPE,
}


def granularity_for(target, split) -> str:
    """The legacy granularity string for a (target, split) pair.

    (CUSTOMER, DEPARTMENT_WORK_TYPE) has no legacy equivalent — the old
    vocabulary could only split under a building target. It resolves to
    CUSTOMER, i.e. the split is ignored for a customer-addressed invoice,
    which is what the old three-value list did too (there was no way to
    ask for it). The UI does not offer that combination; this is the
    server refusing to invent behaviour for it rather than crashing.
    """
    return _PAIR_TO_GRANULARITY.get(
        (target, split), Customer.InvoiceGranularity.CUSTOMER
    )


def pair_for_granularity(granularity):
    """The (target, split) pair a legacy granularity string means.

    The inverse of `granularity_for`, used by the data migration and by
    any caller still handed a granularity string (the `generate` endpoint
    accepts one as an explicit override). An unrecognised string reads as
    (CUSTOMER, NONE) — the same fallback `generate_draft_invoices` has
    always applied to an unrecognised granularity.
    """
    if granularity == Customer.InvoiceGranularity.PER_BUILDING:
        return (
            Customer.InvoiceBillingTarget.BUILDING,
            Customer.InvoiceSplit.NONE,
        )
    if (
        granularity
        == Customer.InvoiceGranularity.PER_BUILDING_DEPARTMENT_WORK_TYPE
    ):
        return (
            Customer.InvoiceBillingTarget.BUILDING,
            Customer.InvoiceSplit.DEPARTMENT_WORK_TYPE,
        )
    return (
        Customer.InvoiceBillingTarget.CUSTOMER,
        Customer.InvoiceSplit.NONE,
    )


def sync_legacy_granularity(customer) -> bool:
    """Keep the deprecated `invoice_granularity_default` in step.

    Returns True when the value changed. Callers that are already saving
    the customer fold `"invoice_granularity_default"` into their
    `update_fields`; this helper deliberately does NOT save, so it cannot
    surprise a caller with a second write.

    The field stays written because `Invoice.granularity` and the
    `/due/` payload both still speak the old vocabulary. It is never read
    to DECIDE anything — `generate_draft_invoices` reads the pair.
    """
    derived = granularity_for(
        customer_billing_target(customer), customer_split(customer)
    )
    if customer.invoice_granularity_default != derived:
        customer.invoice_granularity_default = derived
        return True
    return False
