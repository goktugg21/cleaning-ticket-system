"""
Sprint 127 — read/write serializers for the per-customer Extra Work label
lists (`Department` + `WorkType`).

Both share one base: the two models are identical in shape (see
`customers.models._CustomerLabelList`) and neither carries any behaviour
beyond the label itself.

`customer` is deliberately NOT a serializer field — the owning customer is
fixed by the URL (`/api/customers/<customer_id>/departments/`) and stamped
by the view on save, exactly like the documents endpoints. `name` is trimmed
and required; the case-insensitive per-customer uniqueness is pre-checked
here for a friendly 400 (the customer arrives via serializer context) and
enforced for real by the model's `UniqueConstraint(Lower(Trim(name)),
customer)` — the view re-catches the `IntegrityError` for the race the
pre-check cannot see. Mirrors `ManagedUnitSerializer`.
"""
from __future__ import annotations

from rest_framework import serializers

from .models import Department, WorkType


class _CustomerLabelSerializer(serializers.ModelSerializer):
    # Concrete subclasses override with a model-specific code so the
    # friendly pre-check here and the view's IntegrityError backstop emit
    # the SAME code for a duplicate (matches ManagedUnit's single-code
    # convention across both layers).
    conflict_code = "label_name_not_unique"

    # trim_whitespace=False so `validate_name` owns the stripping: a
    # whitespace-only name must reach the validator intact rather than being
    # silently trimmed to blank first (matches ManagedUnitSerializer.label).
    name = serializers.CharField(max_length=128, trim_whitespace=False)

    class Meta:
        model = None  # concrete subclasses set this
        fields = ["id", "name", "description", "is_active", "created_at"]
        read_only_fields = ["id", "created_at"]

    def validate_name(self, value):
        stripped = (value or "").strip()
        if not stripped:
            raise serializers.ValidationError(
                serializers.ErrorDetail(
                    "name must not be blank.",
                    code="label_name_required",
                )
            )
        return stripped

    def validate(self, attrs):
        # Friendly case-insensitive uniqueness pre-check. The customer comes
        # from the view via context (it is fixed by the URL, never the
        # payload); when absent the DB constraint is the sole backstop. The
        # per-customer list is tiny (twelve departments at most), so the
        # Python-side compare mirrors ManagedUnitSerializer without a cost.
        customer = self.context.get("customer")
        name = attrs.get("name", getattr(self.instance, "name", None))
        if customer is not None and name:
            normalized = name.strip().lower()
            existing = self.Meta.model.objects.filter(customer=customer)
            if self.instance is not None:
                existing = existing.exclude(pk=self.instance.pk)
            if any(row.name.strip().lower() == normalized for row in existing):
                raise serializers.ValidationError(
                    {
                        "name": [
                            serializers.ErrorDetail(
                                f"A label named {name!r} already exists for "
                                "this customer.",
                                code=self.conflict_code,
                            )
                        ]
                    }
                )
        return attrs


class DepartmentSerializer(_CustomerLabelSerializer):
    conflict_code = "department_name_conflict"

    class Meta(_CustomerLabelSerializer.Meta):
        model = Department


class WorkTypeSerializer(_CustomerLabelSerializer):
    conflict_code = "work_type_name_conflict"

    class Meta(_CustomerLabelSerializer.Meta):
        model = WorkType
