"""
Sprint 168 §3 — work-type catalog serializers.

The `HourType` serializer discipline, unchanged where it applies:

  * `company` is given a SCOPED queryset, so a foreign id is
    indistinguishable from a fictional one (H-1) — a 400 "not a valid
    choice", never a 403 that confirms the row exists.
  * Uniqueness is enforced by the DATABASE constraint, not by a
    check-then-act read here. This serializer only turns that specific
    IntegrityError into a field error.
"""
from __future__ import annotations

from rest_framework import serializers

from companies.models import Company

from .models import WorkType
from .scope import scope_company_ids_for_timesheets


ERR_WORK_TYPE_NAME_NOT_UNIQUE = "work_type_name_not_unique"
ERR_WORK_TYPE_NAME_REQUIRED = "work_type_name_required"

# The four the reference offers. Vendor-neutral names in the operator's
# primary language (nl), because `name` is a single operator-typed
# column — the same decision `standard_hour_types` documents. A company
# is free to rename or delete every one of them.
SLOT_FIXED = "fixed_work"
SLOT_EXTRA = "extra_work"
SLOT_MACHINE = "machine"
SLOT_OTHER = "other"

# (slot, nl name, en name, sort_order). Sprint 170 §5 — the owner's
# instruction covers EVERY standard set, not only contract types. This
# one shipped in Sprint 168 with names and no slot, so an English
# operator saw four Dutch words.
#
# Both names identify the slot on the way back in, which is what makes a
# rename in either language re-attach — the `HourType` rule from Sprint
# 152.3, applied here rather than reinvented.
STANDARD_WORK_TYPE_SLOTS = (
    (SLOT_FIXED, "Vast werk", "Fixed work", 10),
    (SLOT_EXTRA, "Meerwerk", "Extra work", 20),
    (SLOT_MACHINE, "Machinewerk", "Machine work", 30),
    (SLOT_OTHER, "Overig", "Other", 40),
)

STANDARD_WORK_TYPE_CHOICES = tuple(
    (slot, en) for slot, _nl, en, _order in STANDARD_WORK_TYPE_SLOTS
)


def slot_for_name(name: str | None) -> str:
    """The standard slot a name belongs to, or `""` for a custom name.

    THE single derivation, called from `WorkType.save()`.
    """
    normalised = normalise_work_type_name(name)
    if not normalised:
        return ""
    for slot, nl_name, en_name, _order in STANDARD_WORK_TYPE_SLOTS:
        if normalised in {
            normalise_work_type_name(nl_name),
            normalise_work_type_name(en_name),
        }:
            return slot
    return ""


def standard_work_types(language: str | None):
    """The `(slot, name, sort_order)` tuples to create, in the actor's
    language. Anything that is not exactly `"en"` falls back to Dutch."""
    use_english = (language or "").lower() == "en"
    return tuple(
        (slot, en_name if use_english else nl_name, order)
        for slot, nl_name, en_name, order in STANDARD_WORK_TYPE_SLOTS
    )


def slot_aliases():
    """Every name that identifies a slot, normalised, one frozenset per
    entry — the standard set's skip test, so pressing the button under
    an English profile on a Dutch-seeded company creates nothing."""
    return tuple(
        frozenset(
            {normalise_work_type_name(nl_name), normalise_work_type_name(en_name)}
        )
        for _slot, nl_name, en_name, _order in STANDARD_WORK_TYPE_SLOTS
    )


def normalise_work_type_name(name: str | None) -> str:
    """The Python side of `Lower(Trim(name))`.

    The comparison must agree with the constraint, or the skip test and
    the database disagree about what "the same name" is — which is how a
    seeded company ends up with duplicates the constraint happily allows.
    """
    return (name or "").strip().lower()


class WorkTypeSerializer(serializers.ModelSerializer):
    company_name = serializers.CharField(source="company.name", read_only=True)
    # Read-only and ANNOTATED — never a per-row query. A catalog page
    # renders the whole list, so a per-row count would be N queries for
    # a number the list aggregate already has.
    usage_count = serializers.IntegerField(
        source="annotated_usage_count", read_only=True, default=0
    )

    class Meta:
        model = WorkType
        fields = [
            "id",
            "company",
            "company_name",
            "name",
            "standard_slot",
            "is_active",
            "sort_order",
            "usage_count",
            "created_at",
            "updated_at",
        ]
        # `standard_slot` is DERIVED in save() and never client-set.
        read_only_fields = [
            "id",
            "company_name",
            "standard_slot",
            "usage_count",
            "created_at",
            "updated_at",
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        request = self.context.get("request")
        if request is None:
            return
        # `None` means "no scope filter" (SUPER_ADMIN), NOT "no
        # companies" — `id__in=None` would raise, and treating it as an
        # empty set would silently hide every company from the one role
        # that may see them all.
        company_ids = scope_company_ids_for_timesheets(request.user)
        self.fields["company"].queryset = (
            Company.objects.all()
            if company_ids is None
            else Company.objects.filter(id__in=company_ids)
        )

    def validate_name(self, value):
        cleaned = (value or "").strip()
        if not cleaned:
            raise serializers.ValidationError(ERR_WORK_TYPE_NAME_REQUIRED)
        return cleaned


class WorkTypeStandardSetSerializer(serializers.Serializer):
    """`company` is optional: a COMPANY_ADMIN has exactly one and does
    not send it. `resolve_target_company` decides, so the "which
    company" rule lives in one place for every timesheets write.
    """

    company = serializers.PrimaryKeyRelatedField(
        queryset=Company.objects.none(), required=False, allow_null=True
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        request = self.context.get("request")
        if request is None:
            return
        scope = scope_company_ids_for_timesheets(request.user)
        self.fields["company"].queryset = (
            Company.objects.all()
            if scope is None
            else Company.objects.filter(id__in=scope)
        )
