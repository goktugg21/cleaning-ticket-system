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
