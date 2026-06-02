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

Sprint 12B — multi-building (`building_ids` write / `linked_building_ids`
read), the `contact_type` taxonomy + `is_primary` flag, the read-only
`user` bridge FK, and a `promotion_status` projection. A plain
create/edit through this serializer NEVER creates a User or a membership:
`user` is read-only and is set only by the promote/link flow
(`customers.promotion`).
"""
from django.utils import timezone
from rest_framework import serializers

from .models import Contact, ContactBuildingLink, CustomerBuildingMembership


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
      * `building_ids` (Sprint 12B) is the WRITE-only multi-building
        input: an optional list of building ids that replaces the
        contact's `ContactBuildingLink` set. Each id must be linked to
        the contact's customer via `CustomerBuildingMembership`.
      * `linked_building_ids` (Sprint 12B) is the READ projection of the
        contact's current `ContactBuildingLink` set.
      * `user` is read-only — the promote/link flow sets it, never a
        plain edit.
    """

    customer = serializers.PrimaryKeyRelatedField(read_only=True)
    user = serializers.PrimaryKeyRelatedField(read_only=True)
    # Sprint 12B — WRITE-only multi-building input; the READ projection
    # is `linked_building_ids` below.
    building_ids = serializers.ListField(
        child=serializers.IntegerField(),
        required=False,
        write_only=True,
    )
    linked_building_ids = serializers.SerializerMethodField()
    promotion_status = serializers.SerializerMethodField()

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
            "contact_type",
            "is_primary",
            "user",
            "building_ids",
            "linked_building_ids",
            "promotion_status",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "customer", "user", "created_at", "updated_at"]

    def get_linked_building_ids(self, obj):
        ids = list(obj.building_links.values_list("building_id", flat=True))
        # Sprint 14G — a BUILDING_MANAGER reader must never see building
        # associations outside the buildings they manage. The view puts
        # the manager's allowed building-id set in the serializer context
        # (`bm_allowed_building_ids`); when it is None (SUPER_ADMIN /
        # COMPANY_ADMIN — who see everything) the projection is unfiltered.
        allowed = self.context.get("bm_allowed_building_ids")
        if allowed is not None:
            ids = [bid for bid in ids if bid in allowed]
        return ids

    def to_representation(self, instance):
        data = super().to_representation(instance)
        # Sprint 14G — also redact the legacy single-building `building`
        # FK for a BUILDING_MANAGER when it points at a building they do
        # not manage (the contact is only visible to them because of a
        # DIFFERENT, managed link). Same leak class as
        # `linked_building_ids`; closing both keeps the contract
        # consistent. SUPER_ADMIN / COMPANY_ADMIN (allowed is None) are
        # untouched.
        allowed = self.context.get("bm_allowed_building_ids")
        if (
            allowed is not None
            and data.get("building") is not None
            and data["building"] not in allowed
        ):
            data["building"] = None
        return data

    def get_promotion_status(self, obj):
        if obj.user_id:
            return "linked"
        # Lazy import to avoid an accounts↔customers import cycle at
        # module load time.
        from accounts.invitations import Invitation

        has_pending = Invitation.objects.filter(
            contact=obj,
            accepted_at__isnull=True,
            revoked_at__isnull=True,
            expires_at__gt=timezone.now(),
        ).exists()
        return "invited" if has_pending else "none"

    def _resolve_customer(self):
        if self.instance is not None:
            return self.instance.customer
        return self.context.get("customer")

    def validate(self, attrs):
        customer = self._resolve_customer()

        # Legacy single-building check — unchanged from Sprint 28 Batch 4.
        # `building` is optional. If a PATCH does not include it, leave
        # the existing value alone — only validate when present.
        building = attrs.get("building", serializers.empty)
        if building not in (serializers.empty, None) and customer is not None:
            if not CustomerBuildingMembership.objects.filter(
                customer=customer, building=building
            ).exists():
                raise serializers.ValidationError(
                    {"building": "Building is not a member of this customer."}
                )

        # Sprint 12B — multi-building input. Validate EACH id against the
        # contact's customer's CustomerBuildingMembership set, reusing the
        # legacy message style.
        building_ids = attrs.get("building_ids", serializers.empty)
        if building_ids is not serializers.empty and customer is not None:
            for bid in building_ids:
                if not CustomerBuildingMembership.objects.filter(
                    customer=customer, building_id=bid
                ).exists():
                    raise serializers.ValidationError(
                        {"building_ids": "Building is not a member of this customer."}
                    )
        return attrs

    def _reconcile_links(self, contact, target_building_ids):
        """Replace the contact's ContactBuildingLink set to EXACTLY
        `target_building_ids` (create missing, delete extras)."""
        target = set(target_building_ids)
        existing = set(
            contact.building_links.values_list("building_id", flat=True)
        )
        to_delete = existing - target
        to_create = target - existing
        if to_delete:
            contact.building_links.filter(building_id__in=to_delete).delete()
        for bid in to_create:
            ContactBuildingLink.objects.create(contact=contact, building_id=bid)

    def create(self, validated_data):
        building_ids = validated_data.pop("building_ids", None)
        contact = super().create(validated_data)

        if building_ids is not None:
            self._reconcile_links(contact, building_ids)

        # Keep the legacy single-building anchor visible in the
        # multi-building read projection: ensure a link exists for it.
        if contact.building_id is not None:
            ContactBuildingLink.objects.get_or_create(
                contact=contact, building_id=contact.building_id
            )
        return contact

    def update(self, instance, validated_data):
        building_ids_present = "building_ids" in validated_data
        building_ids = validated_data.pop("building_ids", None)
        contact = super().update(instance, validated_data)

        if building_ids_present:
            # Replace-set the links to exactly the provided ids.
            self._reconcile_links(contact, building_ids or [])
        elif contact.building_id is not None:
            # building_ids absent: leave links untouched, but if a new
            # legacy `building` was set, ensure a link exists for it
            # (additive — do not delete other links).
            ContactBuildingLink.objects.get_or_create(
                contact=contact, building_id=contact.building_id
            )
        return contact
