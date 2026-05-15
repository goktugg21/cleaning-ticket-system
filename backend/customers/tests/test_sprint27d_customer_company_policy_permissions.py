"""
Sprint 27D — wire CustomerCompanyPolicy permission booleans into
the customer-side permission resolver (continues G-B5).

Sprint 27C added the four permission-policy booleans:

  * customer_users_can_create_tickets
  * customer_users_can_approve_ticket_completion
  * customer_users_can_create_extra_work
  * customer_users_can_approve_extra_work_pricing

…but no runtime consumer. Sprint 27D wires them as a "policy deny
layer" between explicit overrides and role defaults. The precedence
order is:

  1. If `access.is_active=False` → False (highest priority — an
     inactive access row collapses every key to False, including
     keys with an explicit override grant. This preserves the
     Sprint 23A short-circuit.)
  2. If the key appears in `access.permission_overrides` → the
     override value wins (True grants, False revokes). The brief
     calls out override-wins-over-policy explicitly. An override
     is an intentional per-user opt-in/opt-out that an operator
     wrote AFTER setting the policy, so it represents the operator's
     newer intent.
  3. If `CustomerCompanyPolicy.<field> = False` for the key's policy
     family → False (policy denies the broad action family even
     when role default would have granted it). The policy CANNOT
     grant keys that the role default does not — it only narrows.
  4. Otherwise → role default (as before).

Policy mapping (a policy field denies multiple keys when False):

  customer_users_can_create_tickets             → customer.ticket.create
  customer_users_can_approve_ticket_completion  → customer.ticket.approve_own,
                                                  customer.ticket.approve_location
  customer_users_can_create_extra_work          → customer.extra_work.create
  customer_users_can_approve_extra_work_pricing → customer.extra_work.approve_own,
                                                  customer.extra_work.approve_location

Tests below pin every cell of the precedence table and confirm
no cross-customer policy leakage.
"""
from __future__ import annotations

from django.contrib.auth import get_user_model
from django.test import TestCase

from accounts.models import UserRole
from accounts.permissions_effective import has_permission
from buildings.models import Building
from companies.models import Company
from customers.models import (
    Customer,
    CustomerBuildingMembership,
    CustomerCompanyPolicy,
    CustomerUserBuildingAccess,
    CustomerUserMembership,
)
from customers.permissions import (
    CUSTOMER_PERMISSION_KEYS,
    access_has_permission,
    user_can,
)


User = get_user_model()
PASSWORD = "StrongerTestPassword123!"


def _mk(email, role=UserRole.CUSTOMER_USER):
    return User.objects.create_user(
        email=email,
        password=PASSWORD,
        role=role,
        full_name=email.split("@")[0],
    )


# Keys subject to the new policy layer.
POLICY_FAMILY_KEYS = {
    "customer.ticket.create": "customer_users_can_create_tickets",
    "customer.ticket.approve_own": "customer_users_can_approve_ticket_completion",
    "customer.ticket.approve_location": "customer_users_can_approve_ticket_completion",
    "customer.extra_work.create": "customer_users_can_create_extra_work",
    "customer.extra_work.approve_own": "customer_users_can_approve_extra_work_pricing",
    "customer.extra_work.approve_location": "customer_users_can_approve_extra_work_pricing",
}


class CustomerCompanyPolicyResolverFixture(TestCase):
    """Two customers in two providers, each with the three access-role
    flavors. Lets us exercise the precedence layers AND the
    cross-customer leak guard."""

    @classmethod
    def setUpTestData(cls):
        cls.company_a = Company.objects.create(name="Provider A", slug="prov-a")
        cls.company_b = Company.objects.create(name="Provider B", slug="prov-b")
        cls.building_a = Building.objects.create(
            company=cls.company_a, name="A1"
        )
        cls.building_b = Building.objects.create(
            company=cls.company_b, name="B1"
        )
        cls.customer_a = Customer.objects.create(
            company=cls.company_a, name="Customer A", building=cls.building_a
        )
        cls.customer_b = Customer.objects.create(
            company=cls.company_b, name="Customer B", building=cls.building_b
        )
        CustomerBuildingMembership.objects.create(
            customer=cls.customer_a, building=cls.building_a
        )
        CustomerBuildingMembership.objects.create(
            customer=cls.customer_b, building=cls.building_b
        )

        def _add_customer_user(email, access_role, customer, building):
            u = _mk(email)
            m = CustomerUserMembership.objects.create(customer=customer, user=u)
            access = CustomerUserBuildingAccess.objects.create(
                membership=m, building=building, access_role=access_role
            )
            return u, access

        (
            cls.basic_a,
            cls.basic_a_access,
        ) = _add_customer_user(
            "basic-a@example.com",
            CustomerUserBuildingAccess.AccessRole.CUSTOMER_USER,
            cls.customer_a,
            cls.building_a,
        )
        (
            cls.loc_mgr_a,
            cls.loc_mgr_a_access,
        ) = _add_customer_user(
            "loc-a@example.com",
            CustomerUserBuildingAccess.AccessRole.CUSTOMER_LOCATION_MANAGER,
            cls.customer_a,
            cls.building_a,
        )
        (
            cls.co_admin_a,
            cls.co_admin_a_access,
        ) = _add_customer_user(
            "co-a@example.com",
            CustomerUserBuildingAccess.AccessRole.CUSTOMER_COMPANY_ADMIN,
            cls.customer_a,
            cls.building_a,
        )
        (
            cls.basic_b,
            cls.basic_b_access,
        ) = _add_customer_user(
            "basic-b@example.com",
            CustomerUserBuildingAccess.AccessRole.CUSTOMER_USER,
            cls.customer_b,
            cls.building_b,
        )

    def setUp(self):
        # Re-fetch the auto-created policy rows so tests can mutate them.
        self.policy_a = CustomerCompanyPolicy.objects.get(
            customer=self.customer_a
        )
        self.policy_b = CustomerCompanyPolicy.objects.get(
            customer=self.customer_b
        )


# ---------------------------------------------------------------------------
# Policy DENY layer — flips role-default True to False.
# ---------------------------------------------------------------------------
class PolicyDenyAgainstRoleDefaultsTests(CustomerCompanyPolicyResolverFixture):
    """When CustomerCompanyPolicy disables a family, role-default-True
    keys in that family must resolve to False for ALL three customer-side
    access roles, unless an explicit override grants them back."""

    def test_policy_can_disable_basic_customer_ticket_create_default(self):
        # CUSTOMER_USER default grants `customer.ticket.create=True`.
        self.assertTrue(
            user_can(
                self.basic_a,
                self.customer_a.id,
                self.building_a.id,
                "customer.ticket.create",
            ),
            "Pre-policy default must be True for basic customer.",
        )
        self.policy_a.customer_users_can_create_tickets = False
        self.policy_a.save(update_fields=["customer_users_can_create_tickets"])

        self.assertFalse(
            user_can(
                self.basic_a,
                self.customer_a.id,
                self.building_a.id,
                "customer.ticket.create",
            ),
            "Policy disable of create_tickets must collapse "
            "customer.ticket.create to False for the basic customer.",
        )

    def test_policy_can_disable_basic_customer_ticket_completion_approval_default(self):
        self.policy_a.customer_users_can_approve_ticket_completion = False
        self.policy_a.save(
            update_fields=["customer_users_can_approve_ticket_completion"]
        )
        for key in (
            "customer.ticket.approve_own",
            "customer.ticket.approve_location",
        ):
            # Approve_own is a CUSTOMER_USER default; approve_location is
            # a LOCATION_MANAGER default. Both must collapse to False.
            self.assertFalse(
                user_can(
                    self.basic_a,
                    self.customer_a.id,
                    self.building_a.id,
                    key,
                ),
                f"Policy must disable {key} for basic.",
            )
            self.assertFalse(
                user_can(
                    self.loc_mgr_a,
                    self.customer_a.id,
                    self.building_a.id,
                    key,
                ),
                f"Policy must disable {key} for loc manager.",
            )

    def test_policy_can_disable_basic_customer_extra_work_create_default(self):
        self.policy_a.customer_users_can_create_extra_work = False
        self.policy_a.save(
            update_fields=["customer_users_can_create_extra_work"]
        )
        self.assertFalse(
            user_can(
                self.basic_a,
                self.customer_a.id,
                self.building_a.id,
                "customer.extra_work.create",
            ),
        )

    def test_policy_can_disable_basic_customer_extra_work_pricing_approval_default(self):
        self.policy_a.customer_users_can_approve_extra_work_pricing = False
        self.policy_a.save(
            update_fields=["customer_users_can_approve_extra_work_pricing"]
        )
        for key in (
            "customer.extra_work.approve_own",
            "customer.extra_work.approve_location",
        ):
            self.assertFalse(
                user_can(
                    self.basic_a,
                    self.customer_a.id,
                    self.building_a.id,
                    key,
                ),
                f"Policy must disable {key} for basic.",
            )

    def test_policy_denies_location_manager_defaults_when_disabled(self):
        """A LOCATION_MANAGER has approve_location default-True; policy
        must override that."""
        self.policy_a.customer_users_can_approve_ticket_completion = False
        self.policy_a.save(
            update_fields=["customer_users_can_approve_ticket_completion"]
        )
        self.assertFalse(
            user_can(
                self.loc_mgr_a,
                self.customer_a.id,
                self.building_a.id,
                "customer.ticket.approve_location",
            ),
        )

    def test_policy_denies_company_admin_defaults_when_disabled(self):
        """COMPANY_ADMIN gets every key by default; policy must still
        override those defaults. Override-by-explicit is tested
        separately."""
        self.policy_a.customer_users_can_create_extra_work = False
        self.policy_a.customer_users_can_approve_extra_work_pricing = False
        self.policy_a.save(
            update_fields=[
                "customer_users_can_create_extra_work",
                "customer_users_can_approve_extra_work_pricing",
            ]
        )
        for key in (
            "customer.extra_work.create",
            "customer.extra_work.approve_own",
            "customer.extra_work.approve_location",
        ):
            self.assertFalse(
                user_can(
                    self.co_admin_a,
                    self.customer_a.id,
                    self.building_a.id,
                    key,
                ),
                f"Policy must override company-admin default on {key}.",
            )

    def test_policy_does_not_grant_keys_outside_policy_families(self):
        """Policy fields only narrow — they cannot grant a key the
        role default doesn't already grant. Disabling a policy field
        for an access role that doesn't have the key True by default
        is a no-op."""
        # CUSTOMER_USER does NOT have customer.ticket.view_location by
        # default. Flipping any policy must not grant it.
        self.policy_a.customer_users_can_create_tickets = False
        self.policy_a.save(update_fields=["customer_users_can_create_tickets"])
        self.assertFalse(
            user_can(
                self.basic_a,
                self.customer_a.id,
                self.building_a.id,
                "customer.ticket.view_location",
            ),
        )

    def test_policy_does_not_affect_keys_outside_its_families(self):
        """Disabling a policy field must not touch unrelated keys."""
        self.policy_a.customer_users_can_create_tickets = False
        self.policy_a.save(update_fields=["customer_users_can_create_tickets"])

        # view_own / extra_work.create remain at their role defaults.
        self.assertTrue(
            user_can(
                self.basic_a,
                self.customer_a.id,
                self.building_a.id,
                "customer.ticket.view_own",
            ),
        )
        self.assertTrue(
            user_can(
                self.basic_a,
                self.customer_a.id,
                self.building_a.id,
                "customer.extra_work.create",
            ),
        )


# ---------------------------------------------------------------------------
# Precedence: override > policy > role default > False
# ---------------------------------------------------------------------------
class PrecedenceTests(CustomerCompanyPolicyResolverFixture):
    def test_permission_override_explicit_grant_wins_over_policy_deny_if_that_is_the_chosen_precedence(self):
        """The chosen precedence is: explicit override beats policy
        deny. (An operator who writes an override AFTER setting policy
        is intentionally opting one user in.)"""
        self.policy_a.customer_users_can_create_tickets = False
        self.policy_a.save(update_fields=["customer_users_can_create_tickets"])

        # Without override: policy denies.
        self.assertFalse(
            user_can(
                self.basic_a,
                self.customer_a.id,
                self.building_a.id,
                "customer.ticket.create",
            ),
        )

        # With explicit override=True: override wins.
        self.basic_a_access.permission_overrides = {
            "customer.ticket.create": True
        }
        self.basic_a_access.save(update_fields=["permission_overrides"])
        self.assertTrue(
            user_can(
                self.basic_a,
                self.customer_a.id,
                self.building_a.id,
                "customer.ticket.create",
            ),
            "Explicit override=True must win over policy deny.",
        )

    def test_permission_override_explicit_revoke_still_wins(self):
        """Override=False on a key whose role default + policy would
        both grant True must still revoke."""
        # Defaults: policy True (default), role default True for basic.
        self.basic_a_access.permission_overrides = {
            "customer.ticket.create": False
        }
        self.basic_a_access.save(update_fields=["permission_overrides"])
        self.assertFalse(
            user_can(
                self.basic_a,
                self.customer_a.id,
                self.building_a.id,
                "customer.ticket.create",
            ),
        )

    def test_inactive_access_denies_even_when_policy_and_override_would_grant(self):
        """is_active=False short-circuit beats override and policy.
        Preserves the Sprint 23A `access_has_permission` invariant."""
        self.basic_a_access.permission_overrides = {
            "customer.ticket.create": True
        }
        self.basic_a_access.is_active = False
        self.basic_a_access.save(
            update_fields=["permission_overrides", "is_active"]
        )
        for key in CUSTOMER_PERMISSION_KEYS:
            self.assertFalse(
                user_can(
                    self.basic_a,
                    self.customer_a.id,
                    self.building_a.id,
                    key,
                ),
                f"is_active=False must deny {key} even with override grant.",
            )

    def test_role_default_unchanged_when_policy_is_true_and_no_override(self):
        """All four policy fields default to True; with no overrides,
        every customer-side key must resolve exactly to the role
        default."""
        for actor, access in (
            (self.basic_a, self.basic_a_access),
            (self.loc_mgr_a, self.loc_mgr_a_access),
            (self.co_admin_a, self.co_admin_a_access),
        ):
            for key in CUSTOMER_PERMISSION_KEYS:
                role_default = access_has_permission(access, key)
                actual = user_can(
                    actor,
                    self.customer_a.id,
                    self.building_a.id,
                    key,
                )
                self.assertEqual(
                    actual,
                    role_default,
                    f"With policy=True defaults and no overrides, {key} "
                    f"for {actor.email} must match role default "
                    f"(got {actual}, expected {role_default}).",
                )


# ---------------------------------------------------------------------------
# Composer parity — has_permission() must stay in sync with user_can()
# after the policy layer lands.
# ---------------------------------------------------------------------------
class EffectivePermissionsParityWithPolicyLayerTests(
    CustomerCompanyPolicyResolverFixture
):
    def test_effective_permissions_matches_customer_resolver_with_policy_layer(self):
        """For every CUSTOMER_PERMISSION_KEY × representative actor ×
        policy state, the composer must equal the underlying resolver."""
        # Flip a couple of policy fields and one override to exercise
        # the precedence layers.
        self.policy_a.customer_users_can_create_tickets = False
        self.policy_a.customer_users_can_approve_extra_work_pricing = False
        self.policy_a.save(
            update_fields=[
                "customer_users_can_create_tickets",
                "customer_users_can_approve_extra_work_pricing",
            ]
        )
        self.basic_a_access.permission_overrides = {
            "customer.ticket.create": True,  # override beats policy
            "customer.extra_work.view_location": True,  # outside policy
        }
        self.basic_a_access.save(update_fields=["permission_overrides"])

        for actor in (self.basic_a, self.loc_mgr_a, self.co_admin_a):
            for key in CUSTOMER_PERMISSION_KEYS:
                expected = user_can(
                    actor,
                    self.customer_a.id,
                    self.building_a.id,
                    key,
                )
                actual = has_permission(
                    actor,
                    key,
                    customer_id=self.customer_a.id,
                    building_id=self.building_a.id,
                )
                self.assertEqual(
                    actual,
                    expected,
                    f"key={key} actor={actor.email} "
                    f"composer={actual} resolver={expected}",
                )


# ---------------------------------------------------------------------------
# Cross-customer leak guard — Customer A's policy may not affect Customer B.
# ---------------------------------------------------------------------------
class NoCrossCustomerPolicyLeakTests(CustomerCompanyPolicyResolverFixture):
    def test_no_cross_customer_policy_leak(self):
        """Disabling create_tickets on Customer A's policy must NOT
        affect basic_b under Customer B."""
        self.policy_a.customer_users_can_create_tickets = False
        self.policy_a.save(update_fields=["customer_users_can_create_tickets"])

        # basic_b is at customer_b — still gets the default True.
        self.assertTrue(
            user_can(
                self.basic_b,
                self.customer_b.id,
                self.building_b.id,
                "customer.ticket.create",
            ),
            "Cross-customer leak: Customer A's policy reduced "
            "Customer B's user's permissions.",
        )
        # And the inverse: disabling on B does not touch A.
        self.policy_b.customer_users_can_approve_extra_work_pricing = False
        self.policy_b.save(
            update_fields=["customer_users_can_approve_extra_work_pricing"]
        )
        self.assertTrue(
            user_can(
                self.co_admin_a,
                self.customer_a.id,
                self.building_a.id,
                "customer.extra_work.approve_own",
            ),
            "Cross-customer leak: Customer B's policy reduced "
            "Customer A's user's permissions.",
        )

    def test_policy_applies_per_access_row_customer_anchor(self):
        """The policy looked up is the one for the access row's
        customer, not the calling customer_id. (Defense in depth —
        access rows are already pre-filtered by customer in user_can,
        but the policy lookup must follow the same anchor.)"""
        # Disable on A; basic_a access row is anchored at customer_a;
        # therefore the policy_a deny applies.
        self.policy_a.customer_users_can_create_extra_work = False
        self.policy_a.save(
            update_fields=["customer_users_can_create_extra_work"]
        )
        self.assertFalse(
            access_has_permission(
                self.basic_a_access, "customer.extra_work.create"
            ),
        )
        # basic_b's access row is anchored at customer_b — policy_a
        # does not apply.
        self.assertTrue(
            access_has_permission(
                self.basic_b_access, "customer.extra_work.create"
            ),
        )
