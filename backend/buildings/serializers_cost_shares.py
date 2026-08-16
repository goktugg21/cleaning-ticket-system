"""
Sprint 185 E §2 — the cost-share write shape.

A WHOLE-SET replace, not a row CRUD, and that is the design decision
worth stating: the invariant is that a building's shares sum to exactly
100, which is a condition over the SET. Adding one row at a time can
never satisfy it — going from two share-holders to three has to pass
through a state that does not sum to 100 — so a per-row endpoint would
have to accept invalid states and trust somebody to finish the job. The
operator states the whole division; it is valid or it is refused.

Clearing the shares is expressed as an empty set, and it is a legitimate
edit: a building that stops being shared goes back to behaving exactly as
it did before this sprint, with the customer whose Extra Work it is
carrying the whole bill.
"""
from __future__ import annotations

from decimal import Decimal

from rest_framework import serializers

from customers.models import Customer

from .models import BuildingCostShare

ERR_SHARES_MUST_SUM_TO_100 = "cost_shares_must_sum_to_100"
ERR_SHARE_CUSTOMER_NOT_LINKED = "cost_share_customer_not_linked"
ERR_SHARE_DUPLICATE_CUSTOMER = "cost_share_duplicate_customer"

_HUNDRED = Decimal("100.00")


class BuildingCostShareSerializer(serializers.ModelSerializer):
    """One row, for reading back."""

    customer_name = serializers.CharField(source="customer.name", read_only=True)

    class Meta:
        model = BuildingCostShare
        fields = [
            "id",
            "building",
            "customer",
            "customer_name",
            "share_pct",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields


class _CostShareInputSerializer(serializers.Serializer):
    customer = serializers.PrimaryKeyRelatedField(queryset=Customer.objects.all())
    share_pct = serializers.DecimalField(
        max_digits=5,
        decimal_places=2,
        min_value=Decimal("0.01"),
        max_value=_HUNDRED,
    )


class BuildingCostSharesWriteSerializer(serializers.Serializer):
    """The whole division of one building, replacing whatever was there.

    Validation, in the order a reader needs it:

      * every customer must actually be LINKED to the building
        (`CustomerBuildingMembership`). Billing a share to a customer who
        does not operate there is not a division of the cost, it is an
        invoice to a stranger;
      * no customer twice — the same customer with 30 and 20 is two rows
        that the unique constraint would refuse anyway, but the operator
        deserves to be told which name is the problem rather than shown a
        database error;
      * the shares sum to exactly 100. An empty set is allowed and means
        "not shared".
    """

    shares = _CostShareInputSerializer(many=True)

    def __init__(self, *args, building=None, **kwargs):
        self.building = building
        super().__init__(*args, **kwargs)

    def validate_shares(self, value):
        from customers.models import CustomerBuildingMembership

        if not value:
            # The empty set is how a building stops being shared.
            return value

        customer_ids = [row["customer"].id for row in value]
        if len(set(customer_ids)) != len(customer_ids):
            raise serializers.ValidationError(
                {
                    "detail": "A customer can hold only one share of a "
                    "building.",
                    "code": ERR_SHARE_DUPLICATE_CUSTOMER,
                }
            )

        linked = set(
            CustomerBuildingMembership.objects.filter(
                building_id=self.building.id, customer_id__in=customer_ids
            ).values_list("customer_id", flat=True)
        )
        missing = [row for row in value if row["customer"].id not in linked]
        if missing:
            names = ", ".join(sorted(row["customer"].name for row in missing))
            raise serializers.ValidationError(
                {
                    "detail": (
                        f"{names} is not linked to this building. Link the "
                        "customer to the building first, then divide the "
                        "cost."
                    ),
                    "code": ERR_SHARE_CUSTOMER_NOT_LINKED,
                }
            )

        total = sum(
            (Decimal(row["share_pct"]) for row in value), Decimal("0.00")
        )
        if total != _HUNDRED:
            raise serializers.ValidationError(
                {
                    "detail": (
                        f"The shares add up to {total}%, not 100%. A "
                        "building's cost is divided in full or not at all."
                    ),
                    "code": ERR_SHARES_MUST_SUM_TO_100,
                }
            )
        return value
