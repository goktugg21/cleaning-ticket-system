"""
Sprint 28 Batch 4 — Contact (customer phone-book entry) serializer.

Contacts are distinct from Users: they have no login, no role enum, no
scope rows and no permission overrides (spec
docs/product/meeting-2026-05-15-system-requirements.md §1). The
serializer therefore deliberately exposes ONLY the communication fields
on the model and the read-only audit timestamps. The
`fields = [...]` list is explicit so an accidental future addition of
auth-shaped columns to the model is NOT silently serialized through this
endpoint.
"""
from rest_framework import serializers

from .models import Contact, CustomerBuildingMembership


class ContactSerializer(serializers.ModelSerializer):
    """Read/write serializer for `customers.Contact`.

    Validation:

      * `customer` is read-only — the URL kwarg owns the binding so a
        PATCH/POST body cannot smuggle a different customer.
      * `building` is optional. When provided, it MUST be linked to the
        contact's customer via `CustomerBuildingMembership`. A
        cross-customer / cross-company building attempt fails with
        `{"building": "Building is not a member of this customer."}`
        (400). The cross-company case (e.g. SUPER_ADMIN supplying a
        building in another tenant) is rejected by the same check
        because customer↔building membership is scoped per-customer.
    """

    customer = serializers.PrimaryKeyRelatedField(read_only=True)

    class Meta:
        model = Contact
        fields = [
            "id",
            "customer",
            "building",
            "full_name",
            "email",
            "phone",
            "role_label",
            "notes",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "customer", "created_at", "updated_at"]

    def validate(self, attrs):
        # `building` is optional. If a PATCH does not include it, leave
        # the existing value alone — only validate when the field is
        # present in the incoming payload.
        building = attrs.get("building", serializers.empty)
        if building is serializers.empty:
            return attrs
        if building is None:
            return attrs

        # The contact's customer comes from the URL on create
        # (view-supplied via .save(customer=...)) and from
        # `self.instance.customer` on update.
        customer = None
        if self.instance is not None:
            customer = self.instance.customer
        else:
            customer = self.context.get("customer")

        if customer is None:
            # Defensive: the view always supplies the customer. If we
            # got here without one, fall through to the model layer.
            return attrs

        if not CustomerBuildingMembership.objects.filter(
            customer=customer, building=building
        ).exists():
            raise serializers.ValidationError(
                {"building": "Building is not a member of this customer."}
            )
        return attrs
