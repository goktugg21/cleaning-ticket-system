"""
Sprint 167 §3 — serializers for the standing hours agreement.

Every relational lookup resolves through a SCOPED queryset, so an
out-of-scope employee, building or hour type reads as `does_not_exist`
— byte-identical to a fictional id (H-1, the Sprint 142.1 defect
class).
"""
from __future__ import annotations

from decimal import Decimal

from rest_framework import serializers

from buildings.models import Building

from .models import ContractHours, HourType
from .scope import (
    eligible_employees_queryset,
    filter_buildings_for_timesheets,
    filter_hour_types_for,
    scope_company_ids_for_timesheets,
)


WEEKDAYS = (
    "monday",
    "tuesday",
    "wednesday",
    "thursday",
    "friday",
    "saturday",
    "sunday",
)


class ContractHoursSerializer(serializers.ModelSerializer):
    employee_name = serializers.SerializerMethodField()
    building_name = serializers.CharField(
        source="building.name", read_only=True, default=None
    )
    hour_type_name = serializers.CharField(
        source="hour_type.name", read_only=True, default=None
    )
    weekly_total = serializers.DecimalField(
        max_digits=6, decimal_places=2, read_only=True
    )
    is_locked = serializers.BooleanField(read_only=True)

    class Meta:
        model = ContractHours
        fields = [
            "id",
            "company",
            "employee",
            "employee_name",
            "building",
            "building_name",
            "hour_type",
            "hour_type_name",
            "valid_from",
            "valid_to",
            *WEEKDAYS,
            "weekly_total",
            "status",
            "is_locked",
            "approved_by",
            "approved_at",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "company",
            "status",
            "approved_by",
            "approved_at",
            "created_at",
            "updated_at",
        ]

    def __init__(self, *args, **kwargs):
        """Bind the relational fields to the ACTOR's scoped querysets —
        the H-1 mechanism, not a convenience."""
        super().__init__(*args, **kwargs)
        request = self.context.get("request")
        user = getattr(request, "user", None)
        if user is None:
            return
        self.fields["employee"].queryset = eligible_employees_queryset(user)
        self.fields["building"].queryset = filter_buildings_for_timesheets(
            user, Building.objects.all()
        )
        self.fields["hour_type"].queryset = filter_hour_types_for(
            user, HourType.objects.all()
        )

    def get_employee_name(self, obj):
        user = obj.employee
        return (user.full_name or user.email) if user else None

    def validate(self, attrs):
        start = attrs.get("valid_from") or getattr(
            self.instance, "valid_from", None
        )
        end = (
            attrs.get("valid_to")
            if "valid_to" in attrs
            else getattr(self.instance, "valid_to", None)
        )
        if start and end and end < start:
            raise serializers.ValidationError(
                {"valid_to": "valid_to must be on or after valid_from."}
            )
        for day in WEEKDAYS:
            value = attrs.get(day)
            if value is not None and value < Decimal("0.00"):
                raise serializers.ValidationError(
                    {day: "Hours may not be negative."}
                )
        return attrs

    def create(self, validated_data):
        # The tenant anchor is DERIVED from the employee, never sent by
        # the client — the same rule `TimeEntry.company` follows, and
        # the reason a client cannot place a row in another tenant.
        from .scope import employee_company_ids

        employee = validated_data["employee"]
        actor = self.context["request"].user
        scope = scope_company_ids_for_timesheets(actor)
        candidates = employee_company_ids(employee)
        if scope is not None:
            candidates = candidates & scope
        if not candidates:
            raise serializers.ValidationError(
                {"employee": "This employee is not in a company you manage."}
            )
        validated_data["company_id"] = sorted(candidates)[0]
        return super().create(validated_data)


class ContractHoursBulkSerializer(serializers.Serializer):
    """The Bulk assignment dialog: several workers x several buildings,
    one valid-from, one weekly pattern.

    Produces one row per PAIR, skipping a pair that already has a row
    with the same `valid_from` rather than raising — a bulk assignment
    re-run must be safe, and the operator's intent is "make sure these
    exist", not "fail if one does".
    """

    employees = serializers.ListField(
        child=serializers.IntegerField(), allow_empty=False
    )
    buildings = serializers.ListField(
        child=serializers.IntegerField(), allow_empty=True
    )
    hour_type = serializers.IntegerField()
    valid_from = serializers.DateField()
    valid_to = serializers.DateField(required=False, allow_null=True)
    monday = serializers.DecimalField(max_digits=4, decimal_places=2, default=Decimal("0.00"))
    tuesday = serializers.DecimalField(max_digits=4, decimal_places=2, default=Decimal("0.00"))
    wednesday = serializers.DecimalField(max_digits=4, decimal_places=2, default=Decimal("0.00"))
    thursday = serializers.DecimalField(max_digits=4, decimal_places=2, default=Decimal("0.00"))
    friday = serializers.DecimalField(max_digits=4, decimal_places=2, default=Decimal("0.00"))
    saturday = serializers.DecimalField(max_digits=4, decimal_places=2, default=Decimal("0.00"))
    sunday = serializers.DecimalField(max_digits=4, decimal_places=2, default=Decimal("0.00"))

    def validate(self, attrs):
        user = self.context["request"].user
        allowed_employees = set(
            eligible_employees_queryset(user).values_list("id", flat=True)
        )
        unknown = [e for e in attrs["employees"] if e not in allowed_employees]
        if unknown:
            # Out of scope reads as nonexistent, never as "exists but
            # forbidden" — the difference is an existence oracle.
            raise serializers.ValidationError(
                {"employees": "One or more employees do not exist."}
            )
        allowed_buildings = set(
            filter_buildings_for_timesheets(
                user, Building.objects.all()
            ).values_list("id", flat=True)
        )
        unknown_b = [b for b in attrs["buildings"] if b not in allowed_buildings]
        if unknown_b:
            raise serializers.ValidationError(
                {"buildings": "One or more buildings do not exist."}
            )
        if not filter_hour_types_for(user, HourType.objects.all()).filter(
            id=attrs["hour_type"]
        ).exists():
            raise serializers.ValidationError(
                {"hour_type": "This hour type does not exist."}
            )
        return attrs

    def create(self, validated_data):
        from .scope import employee_company_ids

        actor = self.context["request"].user
        scope = scope_company_ids_for_timesheets(actor)
        created_by = validated_data.pop("created_by")
        employees = validated_data.pop("employees")
        # An empty buildings list means "no building", which is a
        # legitimate agreement rather than an error.
        buildings = validated_data.pop("buildings") or [None]
        hour_type_id = validated_data.pop("hour_type")

        rows = []
        for employee_id in employees:
            candidates = employee_company_ids_for(employee_id)
            if scope is not None:
                candidates = candidates & scope
            if not candidates:
                continue
            company_id = sorted(candidates)[0]
            for building_id in buildings:
                existing = ContractHours.objects.filter(
                    employee_id=employee_id,
                    building_id=building_id,
                    hour_type_id=hour_type_id,
                    valid_from=validated_data["valid_from"],
                ).first()
                if existing is not None:
                    # Re-running a bulk assignment must be safe.
                    continue
                rows.append(
                    ContractHours(
                        company_id=company_id,
                        employee_id=employee_id,
                        building_id=building_id,
                        hour_type_id=hour_type_id,
                        created_by=created_by,
                        **validated_data,
                    )
                )
        # `save()` per row, not `bulk_create`: the audit rows come from
        # post_save receivers and a bulk insert fires none of them.
        for row in rows:
            row.save()
        return rows


def employee_company_ids_for(employee_id):
    from accounts.models import User

    from .scope import employee_company_ids

    user = User.objects.filter(pk=employee_id).first()
    return employee_company_ids(user) if user else frozenset()
