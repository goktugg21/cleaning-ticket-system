"""
Sprint 167 §3 — serializers for the standing hours agreement.

Every relational lookup resolves through a SCOPED queryset, so an
out-of-scope employee, building or hour type reads as `does_not_exist`
— byte-identical to a fictional id (H-1, the Sprint 142.1 defect
class).
"""
from __future__ import annotations

from decimal import Decimal

from django.db import transaction
from rest_framework import serializers

from buildings.models import Building

from .models import ContractHours, HourType, WorkType
from .scope import (
    eligible_employees_queryset,
    filter_buildings_for_timesheets,
    filter_hour_types_for,
    filter_work_types_for,
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
    work_type_name = serializers.CharField(
        source="work_type.name", read_only=True, default=None
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
            "work_type",
            "work_type_name",
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
        # Sprint 168 §3 — the sibling catalog, scoped the same way. A
        # foreign work type must read as nonexistent, not as forbidden.
        self.fields["work_type"].queryset = filter_work_types_for(
            user, WorkType.objects.all()
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


class ContractHoursRowSerializer(serializers.Serializer):
    """One explicit row the bulk grid produced.

    Sprint 168 §1 — the dialog does not send a cross-product any more.
    The operator picks workers and buildings, the grid OPENS one row per
    pair, and then they edit it: a different hour type here, an extra
    row added there with `+ Add type`. What comes back is therefore a
    LIST of rows that were actually on screen, not the inputs that
    generated them. Sending the cross-product would silently discard
    every per-row edit.
    """

    employee = serializers.IntegerField()
    building = serializers.IntegerField(required=False, allow_null=True)
    hour_type = serializers.IntegerField()
    work_type = serializers.IntegerField(required=False, allow_null=True)
    monday = serializers.DecimalField(max_digits=4, decimal_places=2, default=Decimal("0.00"))
    tuesday = serializers.DecimalField(max_digits=4, decimal_places=2, default=Decimal("0.00"))
    wednesday = serializers.DecimalField(max_digits=4, decimal_places=2, default=Decimal("0.00"))
    thursday = serializers.DecimalField(max_digits=4, decimal_places=2, default=Decimal("0.00"))
    friday = serializers.DecimalField(max_digits=4, decimal_places=2, default=Decimal("0.00"))
    saturday = serializers.DecimalField(max_digits=4, decimal_places=2, default=Decimal("0.00"))
    sunday = serializers.DecimalField(max_digits=4, decimal_places=2, default=Decimal("0.00"))


class ContractHoursBulkSerializer(serializers.Serializer):
    """The Bulk assignment dialog.

    TWO accepted shapes, and the richer one wins when both are present:

      `rows`  the grid's own rows, each with its own hour type, work
              type and weekly pattern. This is what the dialog sends.
      the cross-product fields (`employees` x `buildings` + one
              `hour_type` + one pattern), kept because it is a sane API
              on its own and Sprint 167's tests pin it.

    Either way the write is ONE transaction: an operator who filled in
    twelve rows and got eight saved would have no way to tell which
    four are missing. A pair that already has a row with the same
    `valid_from` is SKIPPED rather than raising — a bulk assignment
    re-run must be safe, and the intent is "make sure these exist", not
    "fail if one does". Skipping is not failing, so it does not roll the
    transaction back.
    """

    rows = ContractHoursRowSerializer(many=True, required=False)

    employees = serializers.ListField(
        child=serializers.IntegerField(), allow_empty=False, required=False
    )
    buildings = serializers.ListField(
        child=serializers.IntegerField(), allow_empty=True, required=False
    )
    hour_type = serializers.IntegerField(required=False)
    work_type = serializers.IntegerField(required=False, allow_null=True)
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
        rows = attrs.get("rows") or []
        if not rows and not attrs.get("employees"):
            raise serializers.ValidationError(
                {"rows": "Send either rows or employees."}
            )
        if not rows and not attrs.get("hour_type"):
            raise serializers.ValidationError(
                {"hour_type": "An hour type is required."}
            )

        # Every id that appears in EITHER shape is checked against the
        # actor's own scope, in one pass — an id the actor may not see
        # must read as nonexistent, never as "exists but forbidden".
        employee_ids = set(attrs.get("employees") or [])
        building_ids = {b for b in (attrs.get("buildings") or []) if b}
        hour_type_ids = {attrs["hour_type"]} if attrs.get("hour_type") else set()
        work_type_ids = {attrs["work_type"]} if attrs.get("work_type") else set()
        for row in rows:
            employee_ids.add(row["employee"])
            if row.get("building"):
                building_ids.add(row["building"])
            hour_type_ids.add(row["hour_type"])
            if row.get("work_type"):
                work_type_ids.add(row["work_type"])

        allowed_employees = set(
            eligible_employees_queryset(user).values_list("id", flat=True)
        )
        if employee_ids - allowed_employees:
            raise serializers.ValidationError(
                {"employees": "One or more employees do not exist."}
            )
        allowed_buildings = set(
            filter_buildings_for_timesheets(
                user, Building.objects.all()
            ).values_list("id", flat=True)
        )
        if building_ids - allowed_buildings:
            raise serializers.ValidationError(
                {"buildings": "One or more buildings do not exist."}
            )
        allowed_hour_types = set(
            filter_hour_types_for(user, HourType.objects.all()).values_list(
                "id", flat=True
            )
        )
        if hour_type_ids - allowed_hour_types:
            raise serializers.ValidationError(
                {"hour_type": "This hour type does not exist."}
            )
        allowed_work_types = set(
            filter_work_types_for(user, WorkType.objects.all()).values_list(
                "id", flat=True
            )
        )
        if work_type_ids - allowed_work_types:
            raise serializers.ValidationError(
                {"work_type": "This work type does not exist."}
            )
        return attrs

    def create(self, validated_data):
        actor = self.context["request"].user
        scope = scope_company_ids_for_timesheets(actor)
        created_by = validated_data.pop("created_by")
        explicit_rows = validated_data.pop("rows", None) or []
        employees = validated_data.pop("employees", None) or []
        # An empty buildings list means "no building", which is a
        # legitimate agreement rather than an error.
        buildings = validated_data.pop("buildings", None) or [None]
        hour_type_id = validated_data.pop("hour_type", None)
        work_type_id = validated_data.pop("work_type", None)
        valid_from = validated_data["valid_from"]
        valid_to = validated_data.get("valid_to")

        # Normalise BOTH shapes into one list of intended rows, so the
        # write path below exists once. The cross-product is just a
        # shorthand for a list of rows sharing a pattern.
        intended = []
        if explicit_rows:
            for row in explicit_rows:
                intended.append(
                    {
                        "employee_id": row["employee"],
                        "building_id": row.get("building") or None,
                        "hour_type_id": row["hour_type"],
                        "work_type_id": row.get("work_type") or None,
                        "days": {day: row.get(day, Decimal("0.00")) for day in WEEKDAYS},
                    }
                )
        else:
            pattern = {day: validated_data.get(day, Decimal("0.00")) for day in WEEKDAYS}
            for employee_id in employees:
                for building_id in buildings:
                    intended.append(
                        {
                            "employee_id": employee_id,
                            "building_id": building_id,
                            "hour_type_id": hour_type_id,
                            "work_type_id": work_type_id,
                            "days": dict(pattern),
                        }
                    )

        created = []
        # ONE transaction for the whole assignment: an operator who
        # filled in twelve rows and got eight saved would have no way to
        # tell which four are missing.
        with transaction.atomic():
            for row in intended:
                candidates = employee_company_ids_for(row["employee_id"])
                if scope is not None:
                    candidates = candidates & scope
                if not candidates:
                    continue
                company_id = sorted(candidates)[0]
                exists = ContractHours.objects.filter(
                    employee_id=row["employee_id"],
                    building_id=row["building_id"],
                    hour_type_id=row["hour_type_id"],
                    valid_from=valid_from,
                ).exists()
                if exists:
                    # Re-running a bulk assignment must be safe. A skip
                    # is not a failure and does not roll anything back.
                    continue
                instance = ContractHours(
                    company_id=company_id,
                    employee_id=row["employee_id"],
                    building_id=row["building_id"],
                    hour_type_id=row["hour_type_id"],
                    work_type_id=row["work_type_id"],
                    valid_from=valid_from,
                    valid_to=valid_to,
                    created_by=created_by,
                    **row["days"],
                )
                # `save()` per row, not `bulk_create`: the audit rows
                # come from post_save receivers and a bulk insert fires
                # none of them.
                instance.save()
                created.append(instance)
        return created


def employee_company_ids_for(employee_id):
    from accounts.models import User

    from .scope import employee_company_ids

    user = User.objects.filter(pk=employee_id).first()
    return employee_company_ids(user) if user else frozenset()
