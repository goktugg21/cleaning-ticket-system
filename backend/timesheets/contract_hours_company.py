"""
Sprint 183 §4 — which company a ContractHours row belongs to.

THE BUG THIS REPLACES (domain audit F5, verified against the code)
------------------------------------------------------------------
`ContractHoursSerializer.create` resolved the tenant anchor as::

    candidates = employee_company_ids(employee) & scope
    validated_data["company_id"] = sorted(candidates)[0]

Two defects, both real:

1. **It guesses.** For an employee who belongs to two provider companies,
   `sorted(...)[0]` files the agreement against whichever company has the
   LOWER id. Nobody chose that. It is not a tie-break rule anyone wrote
   down; it is what `sorted` happened to return, and it silently puts a
   standing hours agreement in the wrong tenant.

2. **It never re-checks.** `company` is in `read_only_fields` and the
   serializer had no `update()`, so PATCHing a row's `employee` to
   someone from a different company left `company` pointing at the old
   one. The row then belongs to a tenant its own employee is not in.

The bulk path (`ContractHoursBulkSerializer.create`) carried an
independent copy of the same two lines and therefore the same defects.

THE FIX: STOP GUESSING, BECAUSE THE ANSWER IS USUALLY KNOWN
-----------------------------------------------------------
A `ContractHours` row is "this person, at this building, from this date".
`Building.company` is a single non-null FK — so **when the row has a
building, the company is a fact, not an inference**. The old code ignored
the one unambiguous signal on the row and guessed from the ambiguous one.

So:

  * **Building set** -> the building's company. The employee must be in
    that company (otherwise the row asserts a person works somewhere they
    are not employed, which is the error worth reporting).
  * **No building** -> fall back to the employee's companies, narrowed to
    the actor's scope. Exactly one candidate is the answer.
  * **No building AND more than one candidate** -> refuse. This is the
    case that used to be silently mis-filed. The system genuinely cannot
    know, and an error the operator can act on ("pick a building") beats a
    row in the wrong tenant that nobody will notice for months.

The refusal is the deliberate behaviour change. It only fires for a
building-less row belonging to a dual-company employee — the exact case
that was previously resolved by coin-flip.
"""
from __future__ import annotations

from rest_framework import serializers


class ContractHoursCompanyError(serializers.ValidationError):
    """Raised when the row's company cannot be resolved honestly."""


def resolve_company_id(*, employee, building, actor, employee_field="employee"):
    """The company a ContractHours row belongs to.

    `employee` and `building` are model instances (building may be None);
    `actor` is the requesting user, whose scope narrows the candidates so
    a caller can never anchor a row in a tenant they do not manage.

    Raises `ContractHoursCompanyError` rather than guessing. Every caller
    — create, update and bulk — goes through here so the three cannot
    drift apart, which is how the bulk path came to carry its own copy of
    the old defect.
    """
    from .scope import employee_company_ids, scope_company_ids_for_timesheets

    scope = scope_company_ids_for_timesheets(actor)
    candidates = employee_company_ids(employee)
    if scope is not None:
        candidates = candidates & scope

    if not candidates:
        raise ContractHoursCompanyError(
            {employee_field: "This employee is not in a company you manage."}
        )

    if building is not None:
        building_company_id = building.company_id
        if building_company_id not in candidates:
            # The row would claim this person works at a building whose
            # company they are not employed by — or that the actor does
            # not manage. Both are worth refusing rather than silently
            # anchoring somewhere else.
            raise ContractHoursCompanyError(
                {
                    employee_field: (
                        "This employee is not in the company that owns "
                        "the selected building."
                    )
                }
            )
        return building_company_id

    if len(candidates) > 1:
        raise ContractHoursCompanyError(
            {
                employee_field: (
                    "This employee belongs to more than one company, so "
                    "the company for these hours is ambiguous. Select a "
                    "building to settle it."
                )
            }
        )
    return next(iter(candidates))
