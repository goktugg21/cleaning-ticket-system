from rest_framework import serializers

from .models import Customer, CustomerBuildingMembership


class CustomerSerializer(serializers.ModelSerializer):
    """
    Sprint 14 hotfix — expose `linked_building_ids` so the ticket-create
    page can offer customers whose only link to a building lives in the
    new M:N CustomerBuildingMembership table (i.e. consolidated
    customers like B Amsterdam, where `Customer.building` is NULL).

    Behaviour:

      - `linked_building_ids` is the de-duplicated, sorted list of
        building IDs linked to this customer via
        CustomerBuildingMembership.
      - For legacy safety: when a customer has *no* membership rows but
        DOES have a non-null `Customer.building`, that legacy id is
        included so pre-Sprint-14 customers without a backfilled M:N
        row still match in the frontend filter. (After the standard
        0003 migration backfill this fallback is unused — every legacy
        row has its own membership entry — but defence in depth.)

    Scope/permission contract:

      The list / detail endpoints already wrap their queryset in
      `scope_customers_for(user)` (see customers/views.py), so a
      caller never sees a customer outside their scope. The
      linked_building_ids list returned for a *visible* customer is
      the FULL set of buildings linked to that customer — it is NOT
      filtered to the caller's allowed buildings. That is on purpose:

        - The frontend Location dropdown is already filtered by
          `building_ids_for(user)` (a CUSTOMER_USER like Amanda only
          sees buildings she has CustomerUserBuildingAccess for).
        - The ticket-create endpoint validates the caller's
          per-(customer, building) access on the server. The frontend
          filter is convenience only.

      Returning the full linked-building list keeps this serializer
      simple and lets a CUSTOMER_USER who picks an in-scope building
      correctly find the customer in the dropdown.
    """

    linked_building_ids = serializers.SerializerMethodField()

    class Meta:
        model = Customer
        fields = [
            "id",
            "company",
            # Sprint 14: legacy `building` is optional. New consolidated
            # customers can be created without an anchor building and
            # later linked to many buildings via CustomerBuildingMembership.
            "building",
            "linked_building_ids",
            "name",
            "contact_email",
            "phone",
            "language",
            "is_active",
            # Sprint 23B — assigned-staff contact-visibility policy.
            # The CustomerViewSet permission gate is already
            # IsSuperAdminOrCompanyAdmin for write operations, so
            # only OSIUS-side admins can flip these flags. Customer
            # users hitting GET /api/customers/ never list this
            # customer at all (queryset gate) so leaking the bool
            # values back to a customer-side caller is impossible.
            "show_assigned_staff_name",
            "show_assigned_staff_email",
            "show_assigned_staff_phone",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "linked_building_ids",
            "is_active",
            "created_at",
            "updated_at",
        ]
        # `building` is left writable but allow_null/required propagate
        # automatically from the model field (Sprint 14 made it
        # null=True/blank=True). Listed here for clarity:
        extra_kwargs = {
            "building": {"required": False, "allow_null": True},
        }

    def get_linked_building_ids(self, obj: Customer) -> list[int]:
        # When the view's queryset has prefetched
        # `building_memberships`, the iteration below uses the cached
        # list — no additional DB hit per row. The customer list
        # endpoint adds the prefetch in views.py to avoid N+1.
        ids = sorted(
            {m.building_id for m in obj.building_memberships.all()}
        )
        if ids:
            return ids
        # Legacy fallback for an unmigrated row.
        if obj.building_id is not None:
            return [obj.building_id]
        return []
