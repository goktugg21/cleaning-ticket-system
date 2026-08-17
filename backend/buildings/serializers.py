from rest_framework import serializers

from .models import Building


# Sprint 154 §I.5 — how many linked customer names the list column
# carries. The column shows the first two plus a "+N" chip, so three is
# one more than it needs; the extra one costs nothing and leaves room
# for the column to widen without a serializer change.
CUSTOMER_NAME_PREVIEW_LIMIT = 3


class BuildingSerializer(serializers.ModelSerializer):
    """Sprint 154 §I.5 — the list row grew four counts and a bounded
    preview of the linked customer names.

    All five READ THE QUERYSET ANNOTATION first. `BuildingViewSet
    .get_queryset()` annotates the counts with `Count(..., distinct=True)`;
    the `.count()` fallbacks below exist only for the single-object paths
    that re-serialise a bare `Building` outside that queryset (`reactivate`,
    and the create/update responses). A `.count()` per row on a 25-row page
    would be 100 extra queries — the exact N+1 the `assertNumQueries` guard
    in `buildings/tests/test_sprint154_buildings_area.py` exists to catch.
    """

    customer_count = serializers.SerializerMethodField()
    manager_count = serializers.SerializerMethodField()
    staff_count = serializers.SerializerMethodField()
    contact_count = serializers.SerializerMethodField()
    # Bounded preview for the list's Customers column: the first few
    # names plus the true total, so the client never has to fetch the
    # whole membership set to render a cell.
    customer_names = serializers.SerializerMethodField()
    # Sprint 178 §1 — the type's NAME travels with the row so the list and
    # the detail can render it without a second request. `select_related`
    # in the viewset keeps it free; the fallback is for the single-object
    # paths that serialise a bare Building.
    building_type_name = serializers.SerializerMethodField()

    class Meta:
        model = Building
        fields = [
            "id",
            "company",
            "name",
            # Sprint 178 §1 — writable (the building form offers it) and
            # its resolved name alongside, read-only.
            "building_type",
            "building_type_name",
            "address",
            "city",
            "country",
            "postal_code",
            "is_active",
            # Sprint 154 §I.5 — annotated counts + the bounded name preview.
            "customer_count",
            "manager_count",
            "staff_count",
            "contact_count",
            "customer_names",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "is_active",
            "customer_count",
            "manager_count",
            "staff_count",
            "contact_count",
            "customer_names",
            "created_at",
            "updated_at",
        ]

    # `getattr(obj, name, None)` with an `is None` test, never a
    # truthiness test: an annotated 0 is a legitimate answer and must not
    # fall through to a query.
    @staticmethod
    def _annotated_or_count(obj, attr, related_manager_name):
        annotated = getattr(obj, attr, None)
        if annotated is not None:
            return annotated
        return getattr(obj, related_manager_name).count()

    def get_customer_count(self, obj: Building) -> int:
        return self._annotated_or_count(
            obj, "_customer_count", "customer_memberships"
        )

    def get_manager_count(self, obj: Building) -> int:
        return self._annotated_or_count(
            obj, "_manager_count", "manager_assignments"
        )

    def get_staff_count(self, obj: Building) -> int:
        return self._annotated_or_count(obj, "_staff_count", "staff_visibility")

    def get_contact_count(self, obj: Building) -> int:
        return self._annotated_or_count(obj, "_contact_count", "contact_links")

    def get_building_type_name(self, obj):
        """The type's name, or None when the building is unclassified.

        None rather than "" so the client can tell "no type" from "a type
        whose name is empty" — the latter cannot happen, but a serializer
        that erases the difference makes the client guess."""
        return obj.building_type.name if obj.building_type_id else None

    def get_customer_names(self, obj: Building) -> dict:
        """`{"names": [...], "total": N}` — the first few linked customer
        names plus the true total, so the column can render "A, B +3"
        without a second request and without an unbounded cell.

        Sorts and slices IN PYTHON off the prefetched
        `customer_memberships__customer` cache. Calling `.order_by()` or
        `.values_list()` on the related manager would ignore that cache
        and issue a fresh query per row, which is exactly the N+1 the
        annotations above avoid.
        """
        memberships = obj.customer_memberships.all()
        names = sorted(
            m.customer.name for m in memberships if m.customer_id is not None
        )
        return {
            "names": names[:CUSTOMER_NAME_PREVIEW_LIMIT],
            "total": self.get_customer_count(obj),
        }
