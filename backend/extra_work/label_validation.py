"""
Sprint 127.1 — THE one label invariant, extracted so its two callers cannot
drift:

  * `ExtraWorkRequestCreateSerializer` (assignment at create), and
  * the `PATCH /api/extra-work/<id>/labels/` relabel action (assignment /
    correction after create, including ticket-converted rows that never went
    through the create serializer).

A Department / Work Type assigned to an Extra Work MUST belong to that Extra
Work's own customer — otherwise one customer's work is tagged with another
customer's label, silently corrupting the grouped report and the invoice
grouping these fields exist to drive. Two copies of a security-shaped
invariant drift; this is the single source.
"""
from __future__ import annotations

from rest_framework import serializers


def validate_labels_for_customer(customer, *, department=None, work_type=None):
    """Raise a coded, field-keyed `serializers.ValidationError` if a supplied
    `department` / `work_type` does not belong to `customer`.

    A `None` label is skipped — it means "not being set" (absent) or "clear
    to null", neither of which needs a customer check. Both labels are
    validated in one pass so a request that gets both wrong is told about
    both at once. Callable from a serializer `validate()` (the create path)
    or directly from a view (the relabel action); DRF renders the raised
    error as a 400 with the same body either way.
    """
    errors: dict[str, list] = {}
    if department is not None and department.customer_id != customer.id:
        errors["department"] = [
            serializers.ErrorDetail(
                "Department must belong to the same customer as the extra "
                "work.",
                code="department_customer_mismatch",
            )
        ]
    if work_type is not None and work_type.customer_id != customer.id:
        errors["work_type"] = [
            serializers.ErrorDetail(
                "Work type must belong to the same customer as the extra "
                "work.",
                code="work_type_customer_mismatch",
            )
        ]
    if errors:
        raise serializers.ValidationError(errors)


def default_labels_for_customer(customer):
    """Sprint 154 §I.7 — return `(department, work_type)`, the customer's
    "Algemeen" fallback pair, provisioning it if it is somehow absent.

    Lives here, next to the same-customer invariant, because it has the
    same "two callers must not drift" property: the Extra Work create
    serializer fills an omitted label with it, and
    `extra_work.conversion` stamps a converted ticket's Extra Work with
    it. One definition.

    Delegates to `customers.signals.ensure_default_labels` — which is
    idempotent and case-insensitive — so this can never be the thing that
    creates a duplicate the model's uniqueness constraint would reject.
    The import is function-local to keep the `extra_work` <-> `customers`
    module load order tolerant.
    """
    from customers.signals import ensure_default_labels

    return ensure_default_labels(customer)


def issued_invoice_locking_labels(extra_work):
    """Sprint 127.2 — return the live, ISSUED/SENT invoice whose line locks
    this Extra Work's labels, or None if the labels are free to change.

    Owner's rule: once an EW's work sits on an ISSUED invoice, `department`
    and `work_type` are immutable; correcting a mislabel means credit the
    invoice, relabel, re-invoice. This keeps the Department Report and the
    issued invoices reconcilable at all times.

    An EW is locked iff some `InvoiceLine` references it whose invoice is:
      * ISSUED or SENT (a DRAFT does NOT lock — the owner keeps the draft
        window open for corrections; the draft is regenerable and deleting
        it releases the claim),
      * not soft-deleted (`deleted_at IS NULL`), and
      * not reversed (`reversed_by` empty). Crediting/reversing the invoice
        is precisely what unlocks the EW — that is the correction flow.

    Deliberately NOT keyed on `ExtraWorkRequest.is_invoiced`: that claim flag
    is set at DRAFT generation (invoicing/services.py) and released when the
    draft is deleted, so it would freeze labels during the very window the
    owner wants open. This mirrors the `live_claim` subquery shape in
    `invoicing/selectors.py`, narrowed to ISSUED/SENT. A reversal's own
    counter-lines carry `extra_work=NULL`, so a reversal never self-locks.

    The import is function-local ON PURPOSE: `invoicing` imports `extra_work`
    at module scope, so a top-level `from invoicing...` here would be an
    import cycle.
    """
    from invoicing.models import Invoice, InvoiceLine

    line = (
        InvoiceLine.objects.filter(
            extra_work=extra_work,
            invoice__status__in=(Invoice.Status.ISSUED, Invoice.Status.SENT),
            invoice__deleted_at__isnull=True,
            invoice__reversed_by__isnull=True,
        )
        .select_related("invoice")
        .first()
    )
    return line.invoice if line is not None else None
