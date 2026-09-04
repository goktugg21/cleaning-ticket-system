"""W4-R — reading and writing a per-person hourly rate.

App-scoped file name, per CLAUDE.md's naming rule, rather than a class
added to a shared `serializers.py` this app does not have.

## Every lookup resolves through scope

`company` and `employee` are `PrimaryKeyRelatedField`s over SCOPED
querysets, not over `.objects.all()` with a check afterwards. An
out-of-scope id then reads as NONEXISTENT (DRF's `does_not_exist` 400)
rather than as "exists but forbidden" — the two answers differ, and the
difference is an existence oracle against another tenant's staff list.
That is the Sprint 142.1 defect class and `timesheets/scope.py` opens
with the same rule in the same words.

## The employee must actually work for the company

Two scoped fields both passing does not mean the PAIR is valid: a
SUPER_ADMIN may reach every company and every employee, so nothing in
the field layer stops company A being given employee B's rate. The
cross-check is in `validate()`, against
`timesheets.scope.employee_company_ids` — the same three-way definition
of "in a company" the employee picker and the timesheet write path use,
so a person who may hold hours in a company is exactly a person who may
hold a rate there.

## A wage of zero is a 400, not a stored zero

The model validator says `>= 0.01` and this repeats it with a sentence
an operator can act on. Zero is a legal price and is not a legal wage
(`reports/models.py` argues it); a form that accepted 0 would put a
number in the database that `labour_cost` then has to decide how to
disbelieve.
"""
from __future__ import annotations

from decimal import Decimal

from rest_framework import serializers
from rest_framework.validators import UniqueTogetherValidator

from .labour_rate_scope import rate_companies_queryset, rate_employees_queryset
from .models import MIN_HOURLY_RATE, EmployeeHourlyRate


class EmployeeHourlyRateSerializer(serializers.ModelSerializer):
    """One dated rate row, read and written."""

    # Declared explicitly, WITHOUT `min_value`. ModelSerializer would
    # otherwise map the model's `MinValueValidator` onto the field and
    # answer a zero with DRF's stock "Ensure this value is greater than
    # or equal to 0.01" — true, and no help at all to an operator who
    # meant "this work is free". `validate_hourly_rate` below says what
    # to do instead, and can only say it if it is the thing that fires.
    hourly_rate = serializers.DecimalField(max_digits=8, decimal_places=2)
    company = serializers.PrimaryKeyRelatedField(queryset=rate_companies_queryset(None))
    employee = serializers.PrimaryKeyRelatedField(
        queryset=rate_employees_queryset(None)
    )
    employee_name = serializers.SerializerMethodField()
    employee_email = serializers.EmailField(source="employee.email", read_only=True)
    company_name = serializers.CharField(source="company.name", read_only=True)
    created_by_name = serializers.SerializerMethodField()

    class Meta:
        model = EmployeeHourlyRate
        fields = [
            "id",
            "company",
            "company_name",
            "employee",
            "employee_name",
            "employee_email",
            "hourly_rate",
            "valid_from",
            "note",
            "created_by",
            "created_by_name",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_by", "created_at", "updated_at"]
        # DECLARED, not left to ModelSerializer's introspection, and the
        # only reason is the message. The model's UniqueConstraint makes
        # DRF generate this validator automatically with its stock "The
        # fields company, employee, valid_from must make a unique set" —
        # true, and no help to an operator who has just tried to record a
        # raise on a date this person already has a rate for. The
        # validator itself is kept rather than replaced by a check in
        # `validate()`: it queries inside the same request as the insert,
        # so a race answers 400 rather than reaching the database
        # constraint and answering 500.
        validators = [
            UniqueTogetherValidator(
                queryset=EmployeeHourlyRate.objects.all(),
                fields=("company", "employee", "valid_from"),
                message=(
                    "This person already has a rate starting on that date. "
                    "Edit that row to correct it, or pick a different start "
                    "date to change the rate from."
                ),
            )
        ]

    def __init__(self, *args, **kwargs):
        """Bind the two relation querysets to the ACTUAL actor.

        The class-level `queryset=` above is a placeholder that resolves
        to nothing (`rate_employees_queryset(None)` is `User.objects.none()`)
        precisely so a forgotten context cannot fail OPEN: a serializer
        built without a request accepts no id at all, rather than every
        id in the database.
        """
        super().__init__(*args, **kwargs)
        request = self.context.get("request")
        user = getattr(request, "user", None)
        self.fields["company"].queryset = rate_companies_queryset(user)
        self.fields["employee"].queryset = rate_employees_queryset(user)

    def get_employee_name(self, obj) -> str:
        # `full_name` can be blank on an account created by import; the
        # email is what an operator would recognise next, and this is a
        # provider-management-only surface.
        return obj.employee.full_name or obj.employee.email

    def get_created_by_name(self, obj) -> str:
        return obj.created_by.full_name or obj.created_by.email

    def validate_hourly_rate(self, value: Decimal) -> Decimal:
        if value is None or value < MIN_HOURLY_RATE:
            raise serializers.ValidationError(
                f"An hourly rate must be at least {MIN_HOURLY_RATE}. Zero is a "
                "legal price but not a legal wage; leave the rate unset "
                "instead, and the cost figures will say they are unknown."
            )
        return value

    def validate(self, attrs: dict) -> dict:
        from timesheets.scope import employee_company_ids, is_eligible_employee

        # On PATCH, either side may be absent from `attrs`; the pair
        # still has to hold, so the instance supplies whichever half was
        # not sent.
        company = attrs.get("company") or getattr(self.instance, "company", None)
        employee = attrs.get("employee") or getattr(self.instance, "employee", None)

        if employee is not None and not is_eligible_employee(employee):
            raise serializers.ValidationError(
                {
                    "employee": (
                        "This user is not a provider employee, so no hours "
                        "and no rate can be recorded for them."
                    )
                }
            )

        if company is not None and employee is not None:
            if company.id not in employee_company_ids(employee):
                raise serializers.ValidationError(
                    {
                        "employee": (
                            "This person is not an employee of that company. "
                            "A rate is per company: someone who works for two "
                            "providers holds one rate in each."
                        )
                    }
                )

        return attrs
