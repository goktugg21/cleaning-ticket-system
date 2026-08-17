from rest_framework import serializers

from accounts.models import UserRole

from .models import Customer, CustomerBuildingMembership, CustomerUserBuildingAccess


def _user_is_company_member(user, company_id) -> bool:
    """Is `user` a CompanyUserMembership holder of `company_id`?

    Memoised on the user INSTANCE, which in DRF lives exactly as long as
    the request does. Sprint 153: `compute_customer_actions` below ran
    this `.exists()` once PER ROW, so a COMPANY_ADMIN loading a 25-row
    customers page paid 25 extra queries for what is a single membership
    fact about themselves. That N+1 predates this sprint and is invisible
    on seed data; the §2.2 assertNumQueries guard is what surfaced it.

    Read-only helper, so a per-request memo cannot go stale: nothing in a
    GET mutates the caller's own company memberships. The answer is
    byte-identical to the uncached call.
    """
    from companies.models import CompanyUserMembership

    cache = getattr(user, "_customer_company_membership_cache", None)
    if cache is None:
        cache = {}
        try:
            user._customer_company_membership_cache = cache
        except AttributeError:  # pragma: no cover - exotic user objects
            return CompanyUserMembership.objects.filter(
                user=user, company_id=company_id
            ).exists()
    if company_id not in cache:
        cache[company_id] = CompanyUserMembership.objects.filter(
            user=user, company_id=company_id
        ).exists()
    return cache[company_id]


def compute_customer_actions(user, customer) -> dict:
    """
    Per-current-user, per-customer capability block. Used by the
    Customer detail endpoint and the membership-management endpoints.

    Surfaces three derived facts so the frontend can render a
    writable role dropdown + permission-management surface without
    re-deriving the rules:

      * `can_manage_customer_users` — mirrors
        `accounts.effective_actions.compute_effective_actions
        ["can_manage_customer_users"]` for the (viewer, customer) pair.
      * `can_manage_customer_company_admins` — mirrors the B5 toggle:
        SA always; CA in scope only when the provider Company's
        `provider_admin_may_manage_customer_company_admins` is True.
      * `allowed_target_customer_access_roles` — the set of
        `CustomerUserBuildingAccess.AccessRole` values the viewer may
        SET on a target customer-side user under this customer. Driven
        by the same H-7 grant gate the
        `CustomerUserBuildingAccessUpdateSerializer.validate_access_role`
        applies on PATCH.

    The action booleans are SAFE for an unauthenticated caller —
    every field returns its False / empty value when `user` is None or
    not authenticated. In practice this serializer is only reached
    behind authenticated gates, but defence in depth here means a
    future read path that drops the request context cannot leak
    capability hints.
    """
    if user is None or not getattr(user, "is_authenticated", False):
        return {
            "can_manage_customer_users": False,
            "can_manage_customer_company_admins": False,
            "allowed_target_customer_access_roles": [],
        }

    # Inline imports keep the customers app load order tolerant of the
    # accounts ↔ customers ↔ companies cycle (already exercised by
    # `customers.permissions`).
    from accounts.scoping import _user_in_actor_company
    from .permissions import user_can

    role = getattr(user, "role", None)
    company = customer.company

    is_super = role == UserRole.SUPER_ADMIN
    is_ca_in = role == UserRole.COMPANY_ADMIN and _user_is_company_member(
        user, company.id
    )

    # `can_manage_customer_users` — SA always; CA in scope always;
    # CUSTOMER_USER whose customer-level `customer.users.manage`
    # resolves True (CCA default). Mirrors B4 admit shape.
    if is_super or is_ca_in:
        can_manage_customer_users = True
    elif role == UserRole.CUSTOMER_USER:
        can_manage_customer_users = user_can(
            user, customer.id, None, "customer.users.manage"
        )
    else:
        can_manage_customer_users = False

    # `can_manage_customer_company_admins` — SA always; CA in scope
    # only when the policy is True. This mirrors
    # `effective_actions.compute_effective_actions` verbatim.
    if is_super:
        can_manage_customer_company_admins = True
    elif is_ca_in:
        can_manage_customer_company_admins = (
            company.provider_admin_may_manage_customer_company_admins
        )
    else:
        can_manage_customer_company_admins = False

    # `allowed_target_customer_access_roles` — what the viewer may
    # SET on a target user's CUBA row (PATCH `access_role`). H-7
    # restricts CCA-grant to SA, plus CA when B5 policy=True. Lower
    # tiers (CUSTOMER_USER, CUSTOMER_LOCATION_MANAGER) are reachable
    # by anyone who can manage customer users at all.
    #
    # Frontend renders a role dropdown directly from this list.
    lower_tiers = [
        CustomerUserBuildingAccess.AccessRole.CUSTOMER_USER,
        CustomerUserBuildingAccess.AccessRole.CUSTOMER_LOCATION_MANAGER,
    ]
    cca_tier = CustomerUserBuildingAccess.AccessRole.CUSTOMER_COMPANY_ADMIN
    if is_super:
        allowed_target_customer_access_roles = lower_tiers + [cca_tier]
    elif is_ca_in:
        if company.provider_admin_may_manage_customer_company_admins:
            allowed_target_customer_access_roles = lower_tiers + [cca_tier]
        else:
            allowed_target_customer_access_roles = list(lower_tiers)
    elif role == UserRole.CUSTOMER_USER and can_manage_customer_users:
        # CCA holder in scope may manage lower customer users but may
        # NEVER set access_role=CCA (H-7).
        allowed_target_customer_access_roles = list(lower_tiers)
    else:
        allowed_target_customer_access_roles = []

    return {
        "can_manage_customer_users": can_manage_customer_users,
        "can_manage_customer_company_admins": can_manage_customer_company_admins,
        "allowed_target_customer_access_roles": allowed_target_customer_access_roles,
    }


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
    # Sprint 153 §2.2 — per-row counts for the customers list table and
    # the customer overview chips. READ THE ANNOTATION FIRST: the
    # CustomerViewSet queryset annotates all three with
    # `Count(..., distinct=True)`, so a 25-row page costs zero extra
    # queries. The `.count()` fallback exists only for the single-object
    # paths that re-serialise a bare `Customer` outside the viewset
    # queryset (`reactivate`, and the objects returned by the membership
    # endpoints) — never for a list page.
    linked_building_count = serializers.SerializerMethodField()
    user_count = serializers.SerializerMethodField()
    contact_count = serializers.SerializerMethodField()
    # Per-current-user, per-customer capability block. Frontend reads
    # this to render writable role dropdowns (via
    # `allowed_target_customer_access_roles`) and to gate the
    # user-management / CCA-management UI surfaces without
    # re-implementing the H-7 / B4 / B5 rules.
    actions = serializers.SerializerMethodField()
    # RF-1 — customer logo URL (null when unset). The inbox avatar for
    # this customer's threads. Absolute so the frontend fetches the
    # authed blob directly.
    logo_url = serializers.SerializerMethodField()
    # Invoicing Phase 4a — informational contract-PDF URL (null when unset).
    # Read-only mirror of logo_url; the byte-serve endpoint is provider-only.
    contract_pdf_url = serializers.SerializerMethodField()

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
            # Sprint 153 §2.2 — annotated per-row counts (see the field
            # declarations above).
            "linked_building_count",
            "user_count",
            "contact_count",
            "name",
            "contact_email",
            "phone",
            "language",
            "logo_url",
            # Sprint 185 §1 — the BILLING address. Writable: an operator
            # fills it in on the customer page, which is the whole point.
            "address",
            "postal_code",
            "city",
            "country",
            # Derived, read-only: "is there enough here to put on an
            # invoice". One definition (`Customer.has_billing_address`)
            # so the screen's warning and the send-time guard cannot
            # disagree about what counts as an address.
            "has_billing_address",
            "is_active",
            # Sprint 185 §3 — DESCRIPTIVE only. `is_active` above still
            # decides access; this decides what the screens say.
            "lifecycle",
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
            # Invoicing Phase 4a — billing schedule (writable by OSIUS admins;
            # the CustomerViewSet write gate is IsSuperAdminOrCompanyAdminFor-
            # Company) + read-only contract-PDF URL. The schedule is
            # informational (drives the "who's due" list, gates nothing).
            "invoice_day_rule",
            "invoice_day_of_month",
            # Sprint 182 §3 — the two controls that replaced the single
            # granularity dropdown: WHO the invoice is addressed to, and
            # HOW FINELY it splits. These are the authoritative input.
            "invoice_billing_target",
            "invoice_split",
            # DEPRECATED as an input (Sprint 182 §3) but still readable
            # AND still writable, for back-compat: `Invoice.granularity`
            # speaks this vocabulary and the /due/ payload reports it.
            # `validate()` below translates a legacy-only write into the
            # pair, so an older client keeps working and there is still
            # exactly one source of truth.
            "invoice_granularity_default",
            "contract_pdf_url",
            "created_at",
            "updated_at",
            "actions",
        ]
        read_only_fields = [
            "id",
            "linked_building_ids",
            "linked_building_count",
            "user_count",
            "contact_count",
            "logo_url",
            "contract_pdf_url",
            "has_billing_address",
            "is_active",
            "actions",
            "created_at",
            "updated_at",
        ]
        # `building` is left writable but allow_null/required propagate
        # automatically from the model field (Sprint 14 made it
        # null=True/blank=True). Listed here for clarity:
        extra_kwargs = {
            "building": {"required": False, "allow_null": True},
        }

    def validate(self, attrs):
        """Sprint 182 §3 — reconcile the pair with the legacy field.

        Three cases, and the ordering matters:

          * the PAIR is supplied -> it wins, and the legacy value is
            derived from it in `create`/`update`. Any legacy value sent
            alongside is ignored rather than honoured, because the pair
            is what the operator actually saw and set.
          * ONLY the legacy field is supplied -> translated into the
            pair. This is what keeps an older client (or an integration
            written against the pre-split API) working instead of having
            its write silently ignored. A read-only field would have
            no-op'd here, which is the quiet kind of break.
          * neither -> nothing to do.
        """
        from invoicing.billing_target import pair_for_granularity

        attrs = super().validate(attrs)
        sent_pair = (
            "invoice_billing_target" in attrs or "invoice_split" in attrs
        )
        legacy = attrs.get("invoice_granularity_default")
        if not sent_pair and legacy:
            target, split = pair_for_granularity(legacy)
            attrs["invoice_billing_target"] = target
            attrs["invoice_split"] = split
        # Never let the legacy value through as an independent write; it
        # is derived in create/update from whatever pair we settled on.
        attrs.pop("invoice_granularity_default", None)
        return attrs

    def create(self, validated_data):
        # Sprint 182 §3 — a new customer's legacy mirror is derived from
        # whatever pair it was created with, so it is correct from the
        # first write rather than only after the first edit.
        # Imported locally: `invoicing` already depends on `customers`, so
        # a module-level import here would make the pair bidirectional at
        # app-load time. Same defensive style the cross-app helpers in this
        # codebase already use.
        from invoicing.billing_target import sync_legacy_granularity

        customer = super().create(validated_data)
        if sync_legacy_granularity(customer):
            customer.save(update_fields=["invoice_granularity_default"])
        return customer

    def update(self, instance, validated_data):
        # Sprint 182 §3 — keep the deprecated `invoice_granularity_default`
        # in step with the pair on every write. `validate()` has already
        # stripped any client-supplied value and settled the pair, so the
        # legacy column is always DERIVED here and the two cannot disagree;
        # `Invoice.granularity` and the /due/ payload keep speaking the old
        # vocabulary safely.
        from invoicing.billing_target import sync_legacy_granularity

        customer = super().update(instance, validated_data)
        if sync_legacy_granularity(customer):
            customer.save(update_fields=["invoice_granularity_default"])
        return customer

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

    # Sprint 153 §2.2 — the three count fields. Each reads the viewset's
    # queryset annotation when present and only falls back to a real
    # COUNT(*) for a bare instance. `getattr(obj, name, None)` is the
    # whole guard: an annotated value of 0 is a legitimate answer and
    # must NOT fall through to the query (hence the `is None` test, not
    # a truthiness test).
    #
    # NOTE on `linked_building_count` vs `linked_building_ids`: the count
    # is the number of M:N CustomerBuildingMembership rows, full stop. It
    # deliberately does NOT include the deprecated `Customer.building`
    # anchor that `get_linked_building_ids` still falls back to
    # (CLAUDE.md §8 — do not build on that FK). The 0003 migration
    # backfilled a membership row for every legacy customer, so the two
    # agree on real data.
    def get_linked_building_count(self, obj: Customer) -> int:
        annotated = getattr(obj, "_linked_building_count", None)
        if annotated is not None:
            return annotated
        return obj.building_memberships.count()

    def get_user_count(self, obj: Customer) -> int:
        annotated = getattr(obj, "_user_count", None)
        if annotated is not None:
            return annotated
        return obj.user_memberships.count()

    def get_contact_count(self, obj: Customer) -> int:
        annotated = getattr(obj, "_contact_count", None)
        if annotated is not None:
            return annotated
        return obj.contacts.count()

    def get_logo_url(self, obj: Customer):
        from .media_urls import customer_logo_url

        return customer_logo_url(obj, self.context.get("request"))

    def get_contract_pdf_url(self, obj: Customer):
        from .media_urls import customer_contract_pdf_url

        return customer_contract_pdf_url(obj, self.context.get("request"))

    def get_actions(self, obj: Customer) -> dict:
        request = self.context.get("request")
        user = getattr(request, "user", None) if request else None
        return compute_customer_actions(user, obj)
