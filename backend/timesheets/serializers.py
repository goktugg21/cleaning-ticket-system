"""
Sprint 152 — serializers for the timesheets module.

Two rules drive nearly every choice in this file:

  1. **No existence oracles.** Every relational field (`employee`,
     `hour_type`, `building`, `company`) is given a SCOPED queryset in
     `get_fields`, so an id belonging to another tenant produces DRF's
     ordinary `does_not_exist` 400 — byte-identical to the answer for an
     id that never existed. The uniqueness pre-check on `HourType.name`
     uses the same `_scoped_siblings` shape `extra_work` adopted in
     Sprint 142.1, so a rival company's hour-type names are unobservable
     from the outside: a foreign company id yields an EMPTY sibling set,
     the pre-check goes quiet, and the request falls through to the 403
     it should always have had.
  2. **The snapshot is the truth.** `multiplier_snapshot` is written by
     the view on every create and update; it is read-only on the wire
     and no client can set it.
"""
from __future__ import annotations

from decimal import Decimal

from rest_framework import serializers

from buildings.models import Building
from companies.models import Company

from .models import (
    HOURS_MAX,
    HOURS_MIN,
    MULTIPLIER_MAX,
    MULTIPLIER_MIN,
    HourType,
    TimeEntry,
    WeekLock,
)
from .scope import (
    eligible_employees_queryset,
    employee_company_ids,
    filter_buildings_for_timesheets,
    filter_hour_types_for,
    is_timesheet_manager,
    is_eligible_employee,
    scope_company_ids_for_timesheets,
)
from .weeks import enforce_week_open, is_week_closed


# Stable error codes raised from this module.
ERR_HOUR_TYPE_NAME_NOT_UNIQUE = "hour_type_name_not_unique"
ERR_HOUR_TYPE_NAME_REQUIRED = "hour_type_name_required"
ERR_HOUR_TYPE_MULTIPLIER_INVALID = "hour_type_multiplier_invalid"
ERR_HOURS_INVALID = "timesheet_hours_invalid"
ERR_HOUR_TYPE_ARCHIVED = "hour_type_archived"
ERR_HOUR_TYPE_COMPANY_MISMATCH = "hour_type_company_mismatch"
ERR_BUILDING_COMPANY_MISMATCH = "timesheet_building_company_mismatch"
ERR_EMPLOYEE_INVALID = "timesheet_employee_invalid"
ERR_EMPLOYEE_NOT_IN_COMPANY = "timesheet_employee_not_in_company"
ERR_COMPANY_REQUIRED = "timesheet_company_required"


def _request_user(serializer):
    request = serializer.context.get("request") if serializer.context else None
    return getattr(request, "user", None) if request else None


def _scoped_siblings(serializer, queryset, scope_filter):
    """Sprint 152 — apply the actor's timesheet scope to a uniqueness
    pre-check's sibling queryset.

    A verbatim re-statement of the argument in
    `extra_work.serializers_catalog._scoped_siblings`, in this app's own
    terms rather than imported from it (module independence — see
    `scope.py`). The mechanism it defends against:

        POST {"company": <rival id>, "name": "Overwerk"}
          -> 400 "already exists for this company"   if the rival has it
          -> 403 timesheet_cross_company_forbidden   if it does not

    Two different answers, so the status code alone reports whether
    another provider carries that hour type. Scoping the sibling
    queryset collapses both foreign cases onto the 403, which is what
    "no oracle" means — not merely "both are errors".

    Wired in from day one here rather than added by a follow-up sprint:
    the pattern already exists, and re-introducing the defect in a new
    module just to fix it again would be the "written once, omitted
    elsewhere" failure Sprint 142.1 was spent on.

    With no `request` in context the scope helper sees no user and
    returns an empty set: the pre-check goes quiet and the DB constraint
    plus the view's `IntegrityError` handler remain the backstop. That
    fails toward "no friendly message", never toward "leaks a name".
    """
    return scope_filter(_request_user(serializer), queryset)


class HourTypeSerializer(serializers.ModelSerializer):
    """Read/write serializer for the per-company hour-type catalog.

    `company` is a writable PK on CREATE only and read-only on UPDATE —
    the `ServiceCategory` / `ManagedUnit` rule, for the same reason:
    re-pinning a type to another provider would strand every `TimeEntry`
    already filed under it in a company its own admins cannot see.

    `entry_count` is what the UI uses to decide whether to OFFER Delete,
    instead of offering it always and letting the operator discover
    which rows 400 (`TimeEntry.hour_type` is PROTECT). It comes from an
    annotation on the view's queryset — one aggregate for the whole
    page; the `getattr` fallback only fires for the single un-annotated
    object of a CREATE/UPDATE response, so it cannot become an N+1.
    """

    # Deliberately UNSCOPED, unlike every relational field on
    # `TimeEntrySerializer`: the thing that had to be scoped is the
    # uniqueness PRE-CHECK (`_scoped_siblings`), because that is what
    # would otherwise answer differently depending on whether a rival
    # owns the name. With the pre-check silent for a foreign company,
    # both foreign cases reach `resolve_target_company` and get the same
    # 403 — one answer, no oracle. Same field shape as
    # `ServiceCategorySerializer.company`.
    company = serializers.PrimaryKeyRelatedField(
        queryset=Company.objects.all(),
        required=False,
        allow_null=True,
        default=None,
    )
    company_name = serializers.CharField(source="company.name", read_only=True)
    name = serializers.CharField(max_length=128, trim_whitespace=False)
    # Declared explicitly so `validate_multiplier`'s STABLE code is what
    # a client sees. A ModelSerializer would otherwise copy the model's
    # Min/MaxValueValidator onto the field, and a field-level validator
    # runs BEFORE `validate_<field>` — so the response would carry DRF's
    # generic `min_value` / `max_value` and the stable code would be
    # unreachable. The bounds themselves are unchanged (same module
    # constants); the model validators stay as the ORM-level floor.
    multiplier = serializers.DecimalField(
        max_digits=4, decimal_places=2, required=False
    )
    entry_count = serializers.SerializerMethodField()

    class Meta:
        model = HourType
        fields = [
            "id",
            "company",
            "company_name",
            "name",
            "multiplier",
            "is_active",
            "sort_order",
            "entry_count",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "company_name",
            "entry_count",
            "created_at",
            "updated_at",
        ]

    def get_fields(self):
        fields = super().get_fields()
        if self.instance is not None:
            # UPDATE path — pin `company`; see the class docstring.
            fields["company"].read_only = True
        return fields

    def get_entry_count(self, obj) -> int:
        annotated = getattr(obj, "annotated_entry_count", None)
        if annotated is not None:
            return int(annotated)
        return obj.time_entries.count()

    def validate_name(self, value):
        stripped = (value or "").strip()
        if not stripped:
            raise serializers.ValidationError(
                serializers.ErrorDetail(
                    "name must not be blank.",
                    code=ERR_HOUR_TYPE_NAME_REQUIRED,
                )
            )
        return stripped

    def validate_multiplier(self, value):
        if value is None:
            return value
        if value < MULTIPLIER_MIN or value > MULTIPLIER_MAX:
            raise serializers.ValidationError(
                serializers.ErrorDetail(
                    f"multiplier must be between {MULTIPLIER_MIN} and "
                    f"{MULTIPLIER_MAX}.",
                    code=ERR_HOUR_TYPE_MULTIPLIER_INVALID,
                )
            )
        return value

    def validate(self, attrs):
        """Friendly-400 pre-check for the per-company,
        case/whitespace-insensitive name uniqueness.

        Needed because the constraint is an EXPRESSION constraint
        (`Lower(Trim("name")), company`) and DRF cannot derive a
        `UniqueValidator` from one — without this a duplicate would
        reach Postgres and surface as a 500.

        Same limitation the catalog serializers carry: on a
        COMPANY_ADMIN's CREATE that omits `company`, the target is not
        resolved until `perform_create`, so the pre-check is skipped and
        the view's `IntegrityError` handler is the sole backstop.
        """
        name = attrs.get("name", getattr(self.instance, "name", None))
        company = attrs.get("company")
        if company is None and self.instance is not None:
            company = self.instance.company
        if name and company is not None:
            normalized = name.strip().lower()
            existing = _scoped_siblings(
                self,
                HourType.objects.filter(company=company),
                filter_hour_types_for,
            )
            if self.instance is not None:
                existing = existing.exclude(pk=self.instance.pk)
            if any(h.name.strip().lower() == normalized for h in existing):
                raise serializers.ValidationError(
                    {
                        "name": [
                            serializers.ErrorDetail(
                                f"An hour type named {name!r} already "
                                "exists for this company.",
                                code=ERR_HOUR_TYPE_NAME_NOT_UNIQUE,
                            )
                        ]
                    }
                )
        return attrs


class TimeEntrySerializer(serializers.ModelSerializer):
    """Read/write serializer for a single hours row.

    Everything derived is read-only on the wire: `company` is resolved
    from the employee's membership, `iso_year` / `iso_week` from the
    date, `multiplier_snapshot` from the hour type, `created_by` from
    the actor. A client can set none of them.

    `company` IS accepted as an optional write field, but only as a
    DISAMBIGUATOR — it must be one of the companies the employee already
    belongs to. It exists for the SUPER_ADMIN's one-company-at-a-time
    model (Sprint 149) and for the rare employee who works for two
    provider companies; it can never file hours into a company the
    employee is not part of.
    """

    company = serializers.PrimaryKeyRelatedField(
        queryset=Company.objects.none(),
        required=False,
        allow_null=True,
        default=None,
    )
    company_name = serializers.CharField(source="company.name", read_only=True)
    employee = serializers.PrimaryKeyRelatedField(
        queryset=Company.objects.none(),  # replaced in get_fields
        required=False,
    )
    employee_name = serializers.SerializerMethodField()
    hour_type_name = serializers.CharField(
        source="hour_type.name", read_only=True
    )
    hour_type_multiplier = serializers.DecimalField(
        source="hour_type.multiplier",
        max_digits=4,
        decimal_places=2,
        read_only=True,
    )
    building = serializers.PrimaryKeyRelatedField(
        queryset=Building.objects.none(),
        required=False,
        allow_null=True,
    )
    building_name = serializers.CharField(
        source="building.name", read_only=True, default=None
    )
    hour_type = serializers.PrimaryKeyRelatedField(
        queryset=HourType.objects.none(),
    )
    # Declared explicitly for the same reason as
    # `HourTypeSerializer.multiplier`: so `validate_hours`'s stable code
    # reaches the client instead of DRF's generic `min_value`.
    hours = serializers.DecimalField(max_digits=4, decimal_places=2)
    weighted_hours = serializers.SerializerMethodField()
    is_locked = serializers.SerializerMethodField()

    class Meta:
        model = TimeEntry
        fields = [
            "id",
            "company",
            "company_name",
            "employee",
            "employee_name",
            "date",
            "iso_year",
            "iso_week",
            "hour_type",
            "hour_type_name",
            "hour_type_multiplier",
            "hours",
            "multiplier_snapshot",
            "weighted_hours",
            "building",
            "building_name",
            "note",
            "is_locked",
            "created_by",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "company_name",
            "employee_name",
            "iso_year",
            "iso_week",
            "hour_type_name",
            "hour_type_multiplier",
            "multiplier_snapshot",
            "weighted_hours",
            "building_name",
            "is_locked",
            "created_by",
            "created_at",
            "updated_at",
        ]

    def get_fields(self):
        """Install SCOPED querysets on every relational field.

        This is the H-1 floor for the write path: without it, DRF would
        resolve `hour_type` / `building` / `employee` against the whole
        table and report "this exists but you may not use it" — the
        existence oracle `scope.py` exists to prevent. With it, a
        foreign id is indistinguishable from a fictional one.
        """
        fields = super().get_fields()
        user = _request_user(self)
        scope = scope_company_ids_for_timesheets(user)

        company_qs = Company.objects.all()
        if scope is not None:
            company_qs = company_qs.filter(id__in=scope)
        fields["company"].queryset = company_qs
        fields["employee"].queryset = eligible_employees_queryset(user)
        fields["hour_type"].queryset = filter_hour_types_for(
            user, HourType.objects.select_related("company")
        )
        fields["building"].queryset = filter_buildings_for_timesheets(
            user, Building.objects.select_related("company")
        )
        if self.instance is not None:
            # The tenant anchor never moves after create. Re-filing an
            # existing entry under another company would silently move
            # it across a week lock and out of every report it was
            # already counted in.
            fields["company"].read_only = True
        return fields

    def get_employee_name(self, obj) -> str:
        employee = getattr(obj, "employee", None)
        if employee is None:
            return ""
        return getattr(employee, "full_name", "") or getattr(
            employee, "email", ""
        )

    def get_weighted_hours(self, obj) -> str:
        return str(obj.weighted_hours)

    def get_is_locked(self, obj) -> bool:
        """Whether this entry's week is closed — what the UI reads to
        disable its own edit affordances. The server refuses the write
        regardless (`weeks.enforce_week_open`); this only stops the UI
        offering an action that would 400.
        """
        return is_week_closed(obj.company_id, obj.iso_year, obj.iso_week)

    def validate_hours(self, value):
        if value is None or value < HOURS_MIN or value > HOURS_MAX:
            raise serializers.ValidationError(
                serializers.ErrorDetail(
                    f"hours must be between {HOURS_MIN} and {HOURS_MAX}.",
                    code=ERR_HOURS_INVALID,
                )
            )
        return value

    def validate(self, attrs):
        """Resolve the tenant anchor, then check every cross-object rule
        against it.

        Order is deliberate: the company must be known before
        `hour_type`, `building` or the week lock can be judged, and the
        employee's memberships are what determine it.
        """
        instance = self.instance
        actor = _request_user(self)

        # `employee` OMITTED means "me". That default is resolved HERE,
        # before anything else, because the company, the hour type's
        # ownership and the week lock are all judged against the
        # employee — resolving it in the view afterwards would validate
        # one person's request and save another's. The view separately
        # 403s a non-manager who names SOMEONE ELSE; this only fills in
        # a blank.
        employee = (
            attrs.get("employee")
            or getattr(instance, "employee", None)
            or actor
        )
        attrs["employee"] = employee
        if not is_eligible_employee(employee):
            raise serializers.ValidationError(
                {
                    "employee": [
                        serializers.ErrorDetail(
                            "Hours can only be recorded for an active "
                            "provider-side employee.",
                            code=ERR_EMPLOYEE_INVALID,
                        )
                    ]
                }
            )

        company = self._resolve_company(attrs, instance, actor, employee)
        attrs["company"] = company

        hour_type = attrs.get("hour_type") or getattr(
            instance, "hour_type", None
        )
        if hour_type is not None:
            if hour_type.company_id != company.id:
                raise serializers.ValidationError(
                    {
                        "hour_type": [
                            serializers.ErrorDetail(
                                "This hour type belongs to a different "
                                "provider company.",
                                code=ERR_HOUR_TYPE_COMPANY_MISMATCH,
                            )
                        ]
                    }
                )
            # An ARCHIVED type is not offerable for a NEW entry, nor for
            # one being MOVED onto it — but an existing entry that
            # already carries it keeps working, which is the whole point
            # of archiving instead of deleting. So the check fires only
            # when `hour_type` is actually being written.
            if "hour_type" in attrs and not hour_type.is_active:
                raise serializers.ValidationError(
                    {
                        "hour_type": [
                            serializers.ErrorDetail(
                                "This hour type is archived and cannot be "
                                "used for new entries.",
                                code=ERR_HOUR_TYPE_ARCHIVED,
                            )
                        ]
                    }
                )

        building = attrs.get("building", getattr(instance, "building", None))
        if building is not None and building.company_id != company.id:
            raise serializers.ValidationError(
                {
                    "building": [
                        serializers.ErrorDetail(
                            "This building belongs to a different provider "
                            "company.",
                            code=ERR_BUILDING_COMPANY_MISMATCH,
                        )
                    ]
                }
            )

        # Week lock, enforced on BOTH sides of a date edit. Checking only
        # the new date would let an entry be dragged OUT of a closed week
        # — which changes that week's totals just as surely as adding one
        # to it, and is the likelier direction for a mistake to take.
        old_date = getattr(instance, "date", None)
        new_date = attrs.get("date", old_date)
        if old_date is not None:
            enforce_week_open(company.id, old_date)
        if new_date is not None and new_date != old_date:
            enforce_week_open(company.id, new_date)

        return attrs

    def _resolve_company(self, attrs, instance, actor, employee):
        """Pick the tenant anchor for this entry.

        On UPDATE the row's existing company is authoritative and
        immutable — but the EMPLOYEE is not, so it is re-checked against
        that company. On CREATE the company is the employee's own
        membership company, intersected with what the actor may reach: a
        supplied `company` narrows within that set, it never widens it.
        """
        if instance is not None:
            # Sprint 152.1 (review finding) — this used to return
            # immediately, so nothing verified that a NEWLY NAMED
            # employee belongs to the row's company. A COMPANY_ADMIN is
            # stopped earlier by the scoped `employee` queryset, but a
            # SUPER_ADMIN's scope is `None`: they could PATCH an entry in
            # company A onto company B's employee. The row would keep
            # company A, so that employee could never see their own entry
            # (their scope is B) and A's admin would see a name from
            # another provider in their list. Nothing rejected it and no
            # test covered it — the CREATE path had this check, the
            # UPDATE path did not.
            if employee is not None and employee.pk != instance.employee_id:
                if instance.company_id not in employee_company_ids(employee):
                    raise serializers.ValidationError(
                        {
                            "employee": [
                                serializers.ErrorDetail(
                                    "This employee is not a member of the "
                                    "provider company this entry belongs "
                                    "to.",
                                    code=ERR_EMPLOYEE_NOT_IN_COMPANY,
                                )
                            ]
                        }
                    )
            return instance.company

        candidates = employee_company_ids(employee)
        actor_scope = scope_company_ids_for_timesheets(actor)
        if actor_scope is not None:
            candidates = frozenset(candidates & actor_scope)

        supplied = attrs.get("company")
        if supplied is not None:
            if supplied.id not in candidates:
                raise serializers.ValidationError(
                    {
                        "employee": [
                            serializers.ErrorDetail(
                                "This employee is not a member of the "
                                "selected provider company.",
                                code=ERR_EMPLOYEE_NOT_IN_COMPANY,
                            )
                        ]
                    }
                )
            return supplied

        if not candidates:
            raise serializers.ValidationError(
                {
                    "employee": [
                        serializers.ErrorDetail(
                            "This employee is not a member of any provider "
                            "company you can record hours for.",
                            code=ERR_EMPLOYEE_NOT_IN_COMPANY,
                        )
                    ]
                }
            )
        if len(candidates) > 1:
            raise serializers.ValidationError(
                {
                    "company": [
                        serializers.ErrorDetail(
                            "`company` is required when the employee "
                            "belongs to more than one provider company.",
                            code=ERR_COMPANY_REQUIRED,
                        )
                    ]
                }
            )
        return Company.objects.get(id=next(iter(candidates)))


class WeekLockSerializer(serializers.ModelSerializer):
    """Read serializer for a closed week. Every field is derived from
    the close action itself — the client sends `iso_year` / `iso_week`
    (and, for a SUPER_ADMIN, `company`) to the close endpoint, not to
    this serializer.
    """

    company_name = serializers.CharField(source="company.name", read_only=True)
    closed_by_name = serializers.SerializerMethodField()

    class Meta:
        model = WeekLock
        fields = [
            "id",
            "company",
            "company_name",
            "iso_year",
            "iso_week",
            "closed_at",
            "closed_by",
            "closed_by_name",
        ]
        read_only_fields = fields

    def get_closed_by_name(self, obj) -> str:
        closed_by = getattr(obj, "closed_by", None)
        if closed_by is None:
            return ""
        return getattr(closed_by, "full_name", "") or getattr(
            closed_by, "email", ""
        )


class HourTypeStandardSetSerializer(serializers.Serializer):
    """Input for POST /api/timesheets/hour-types/standard-set/.

    Only `company` — the standard set itself is fixed (see
    `standard_set.STANDARD_SLOTS`). Optional, and resolved the same
    way every other create in this app resolves it.
    """

    # Unscoped for the same reason as `HourTypeSerializer.company`: the
    # 403 from `resolve_target_company` is the single answer for every
    # foreign company, and this action has no name pre-check to leak
    # through in the first place.
    company = serializers.PrimaryKeyRelatedField(
        queryset=Company.objects.all(),
        required=False,
        allow_null=True,
        default=None,
    )


def snapshot_multiplier(hour_type) -> Decimal:
    """The ONE place `multiplier_snapshot` is derived from an hour type.

    Trivial by design — the value is a straight copy. It is a named
    function so every write path (create, update, and the open-week
    refresh after a multiplier edit) is visibly the same operation, and
    so a future change to what "the snapshot" means has one site.
    """
    return hour_type.multiplier
