"""Sprint W4-Q §2 — the wire shape of the per-company thresholds.

The screen has to answer three questions about every knob and the
payload is built so it can, without the frontend re-deriving anything:

  effective  the number actually in force for this company right now
  override   what this company stored, or null when it stored nothing
  default    the platform fallback, so "back to default" can say what it
             is going back TO

`override` and `effective` are separate fields on purpose. Collapsing
them would make "this company set 24" and "this company set nothing and
the platform default happens to be 24" render identically, and the whole
point of the screen is that an operator can tell those apart. It is the
same distinction the money rule makes between unpriced and free, and 0
is a legal value here for the same reason: `manager_review_business_
hours = 0` means "warn me the moment it lands in review", and it must
never be read as "unset".
"""
from rest_framework import serializers

from .models import SlaWarningThreshold
from .thresholds import THRESHOLD_FIELDS, defaults, merge

#: Business meaning of each knob, in the field order the screen renders.
#: `unit` is what the number means and is what the UI turns into the
#: "business hours, Mon-Fri 09:00-17:00" sentence — a bare "24" is not a
#: threshold anybody can reason about.
_FIELD_UNITS = {name: unit for name, _setting, unit in THRESHOLD_FIELDS}


class SlaWarningThresholdWriteSerializer(serializers.ModelSerializer):
    """PUT body. Every field optional; an explicit null CLEARS the
    override and returns that knob to the platform default."""

    class Meta:
        model = SlaWarningThreshold
        fields = [name for name, _s, _u in THRESHOLD_FIELDS]
        extra_kwargs = {
            name: {"required": False, "allow_null": True}
            for name, _s, _u in THRESHOLD_FIELDS
        }

    def validate(self, attrs):
        """The escalation figure must not sit BELOW the first threshold.

        Not a style rule: the hop is `if crossed >= escalate_target`, so
        an escalation smaller than the first threshold fires in the same
        tick as the first notice and the one-hop design silently becomes
        "tell everybody at once". The approval-cutoff pair runs the other
        way — it counts DOWN to a date, so its escalation window is the
        smaller number.

        Validated against the EFFECTIVE values, not the submitted ones:
        a company that overrides only the escalation figure is still
        compared against the default it is inheriting for the other half,
        because that is the pair the sweep will actually run.
        """
        instance = getattr(self, "instance", None)
        effective = merge(instance)
        for name in attrs:
            value = attrs[name]
            effective[name] = int(value) if value is not None else None
        base = defaults()
        for name, value in list(effective.items()):
            if value is None:
                effective[name] = base[name]

        if (
            effective["approval_cutoff_escalate_days"]
            > effective["approval_cutoff_days"]
        ):
            raise serializers.ValidationError(
                {
                    "approval_cutoff_escalate_days": (
                        "The escalation window must be inside the warning "
                        "window: it counts down to the billing date, so it "
                        "cannot be larger than the day the warning starts."
                    )
                }
            )
        for first, second in (
            (
                "manager_review_business_hours",
                "manager_review_escalate_business_hours",
            ),
            (
                "not_started_business_hours",
                "not_started_escalate_business_hours",
            ),
        ):
            if effective[second] < effective[first]:
                raise serializers.ValidationError(
                    {
                        second: (
                            "The escalation threshold must be at least the "
                            "first threshold, or the one escalation hop "
                            "fires in the same sweep as the first warning."
                        )
                    }
                )
        return attrs


def serialize_company_thresholds(*, company, row):
    """The read payload for ONE company. `row` may be None."""
    base = defaults()
    effective = merge(row, base)
    return {
        "company": company.id,
        "company_name": company.name,
        "updated_at": row.updated_at.isoformat() if row is not None else None,
        "updated_by_name": (
            (row.updated_by.full_name or row.updated_by.email)
            if row is not None and row.updated_by_id
            else None
        ),
        # True when this company has stored at least one number of its
        # own. The screen uses it for the "running on platform defaults"
        # badge; it is NOT derivable from `effective` alone, because an
        # override that equals the default is still an override.
        "is_customized": row is not None
        and any(
            getattr(row, name) is not None for name, _s, _u in THRESHOLD_FIELDS
        ),
        "thresholds": [
            {
                "field": name,
                "unit": _FIELD_UNITS[name],
                "effective": effective[name],
                "override": (
                    getattr(row, name) if row is not None else None
                ),
                "default": base[name],
            }
            for name, _s, _u in THRESHOLD_FIELDS
        ],
    }
