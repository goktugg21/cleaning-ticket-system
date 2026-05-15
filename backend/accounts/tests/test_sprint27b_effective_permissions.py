"""
Sprint 27B — parity / shadow tests for the effective-permissions service.

The composer at `accounts.permissions_effective` does NOT introduce
new permission rules. It is a read-only facade that delegates to the
two existing resolvers:

  * `accounts.permissions_v2.user_has_osius_permission` (provider side)
  * `customers.permissions.user_can` (customer side, which itself
    walks `access_has_permission` over the user's
    CustomerUserBuildingAccess rows)

These tests assert that for every osius.* and customer.* key the
composer answers identically to the underlying resolver, across
representative actors (SUPER_ADMIN, COMPANY_ADMIN, BUILDING_MANAGER,
STAFF, CUSTOMER_USER in each of the three access_role variants).
They also lock the hard invariants from the Sprint 27 RBAC matrix:

  * Anonymous → False for every key.
  * Unknown key → False.
  * Permission overrides in `CustomerUserBuildingAccess.permission_overrides`
    are honoured.
  * `CustomerUserBuildingAccess.is_active=False` short-circuits every
    customer.* key to False.
  * No cross-customer or cross-provider leak via the composer.

These tests are intentionally exhaustive against the
`OSIUS_PERMISSION_KEYS` and `CUSTOMER_PERMISSION_KEYS` frozensets —
adding a new key to either set will surface here first.
"""
from __future__ import annotations

from django.contrib.auth import get_user_model
from django.test import TestCase

from accounts.models import StaffProfile, UserRole
from accounts.permissions_effective import (
    effective_permissions,
    has_permission,
)
from accounts.permissions_v2 import (
    OSIUS_PERMISSION_KEYS,
    user_has_osius_permission,
)
from buildings.models import (
    Building,
    BuildingManagerAssignment,
    BuildingStaffVisibility,
)
from companies.models import Company, CompanyUserMembership
from customers.models import (
    Customer,
    CustomerBuildingMembership,
    CustomerUserBuildingAccess,
    CustomerUserMembership,
)
from customers.permissions import (
    CUSTOMER_PERMISSION_KEYS,
    user_can,
)


User = get_user_model()
PASSWORD = "StrongerTestPassword123!"


def _mk(email, role, **extra):
    return User.objects.create_user(
        email=email,
        password=PASSWORD,
        role=role,
        full_name=email.split("@")[0],
        **extra,
    )


class EffectivePermissionsFixture(TestCase):
    """Two-provider, multi-customer fixture used by every test class."""

    @classmethod
    def setUpTestData(cls):
        cls.company_a = Company.objects.create(name="Provider A", slug="prov-a")
        cls.company_b = Company.objects.create(name="Provider B", slug="prov-b")
        cls.building_a1 = Building.objects.create(
            company=cls.company_a, name="A1"
        )
        cls.building_a2 = Building.objects.create(
            company=cls.company_a, name="A2"
        )
        cls.building_b = Building.objects.create(
            company=cls.company_b, name="B1"
        )
        cls.customer_a = Customer.objects.create(
            company=cls.company_a, name="Customer A", building=cls.building_a1
        )
        cls.customer_b = Customer.objects.create(
            company=cls.company_b, name="Customer B", building=cls.building_b
        )
        for c, b in [
            (cls.customer_a, cls.building_a1),
            (cls.customer_a, cls.building_a2),
            (cls.customer_b, cls.building_b),
        ]:
            CustomerBuildingMembership.objects.create(customer=c, building=b)

        cls.super_admin = _mk(
            "super@example.com",
            UserRole.SUPER_ADMIN,
            is_staff=True,
            is_superuser=True,
        )

        cls.admin_a = _mk("admin-a@example.com", UserRole.COMPANY_ADMIN)
        CompanyUserMembership.objects.create(
            user=cls.admin_a, company=cls.company_a
        )

        cls.manager_a1 = _mk("mgr-a1@example.com", UserRole.BUILDING_MANAGER)
        BuildingManagerAssignment.objects.create(
            user=cls.manager_a1, building=cls.building_a1
        )

        cls.staff_a = _mk("staff-a@example.com", UserRole.STAFF)
        StaffProfile.objects.create(user=cls.staff_a, is_active=True)
        BuildingStaffVisibility.objects.create(
            user=cls.staff_a,
            building=cls.building_a1,
            can_request_assignment=True,
        )

        def _make_customer(email, access_role, customer, building):
            u = _mk(email, UserRole.CUSTOMER_USER)
            m = CustomerUserMembership.objects.create(customer=customer, user=u)
            CustomerUserBuildingAccess.objects.create(
                membership=m, building=building, access_role=access_role
            )
            return u

        cls.cust_basic = _make_customer(
            "cust-basic@example.com",
            CustomerUserBuildingAccess.AccessRole.CUSTOMER_USER,
            cls.customer_a,
            cls.building_a1,
        )
        cls.cust_location_manager = _make_customer(
            "cust-loc@example.com",
            CustomerUserBuildingAccess.AccessRole.CUSTOMER_LOCATION_MANAGER,
            cls.customer_a,
            cls.building_a1,
        )
        cls.cust_company_admin = _make_customer(
            "cust-co@example.com",
            CustomerUserBuildingAccess.AccessRole.CUSTOMER_COMPANY_ADMIN,
            cls.customer_a,
            cls.building_a1,
        )


# ---------------------------------------------------------------------------
# Provider-side parity (osius.* keys)
# ---------------------------------------------------------------------------
class ProviderResolverParityTests(EffectivePermissionsFixture):
    def _assert_parity(self, user, building_id=None):
        """For every osius.* key, the composer's `has_permission`
        answer must equal `user_has_osius_permission`."""
        for key in OSIUS_PERMISSION_KEYS:
            expected = user_has_osius_permission(
                user, key, building_id=building_id
            )
            actual = has_permission(user, key, building_id=building_id)
            self.assertEqual(
                actual,
                expected,
                f"key={key} actor={user.email} building_id={building_id} "
                f"composer={actual} resolver={expected}",
            )

    def test_effective_permissions_matches_provider_resolver_for_super_admin(self):
        self._assert_parity(self.super_admin)
        self._assert_parity(self.super_admin, building_id=self.building_a1.id)

    def test_effective_permissions_matches_provider_resolver_for_company_admin(self):
        self._assert_parity(self.admin_a)
        self._assert_parity(self.admin_a, building_id=self.building_a1.id)

    def test_effective_permissions_matches_provider_resolver_for_building_manager(self):
        # In-scope building + out-of-scope building + no-building cases.
        self._assert_parity(self.manager_a1)
        self._assert_parity(self.manager_a1, building_id=self.building_a1.id)
        self._assert_parity(self.manager_a1, building_id=self.building_a2.id)
        self._assert_parity(self.manager_a1, building_id=self.building_b.id)

    def test_effective_permissions_matches_provider_resolver_for_staff(self):
        self._assert_parity(self.staff_a)
        self._assert_parity(self.staff_a, building_id=self.building_a1.id)
        self._assert_parity(self.staff_a, building_id=self.building_a2.id)


# ---------------------------------------------------------------------------
# Customer-side parity (customer.* keys)
# ---------------------------------------------------------------------------
class CustomerResolverParityTests(EffectivePermissionsFixture):
    def _assert_parity(self, user, customer_id, building_id):
        for key in CUSTOMER_PERMISSION_KEYS:
            expected = user_can(user, customer_id, building_id, key)
            actual = has_permission(
                user, key, customer_id=customer_id, building_id=building_id
            )
            self.assertEqual(
                actual,
                expected,
                f"key={key} actor={user.email} customer_id={customer_id} "
                f"building_id={building_id} composer={actual} resolver={expected}",
            )

    def test_effective_permissions_matches_customer_access_role_defaults(self):
        for actor in (
            self.cust_basic,
            self.cust_location_manager,
            self.cust_company_admin,
        ):
            self._assert_parity(
                actor, self.customer_a.id, self.building_a1.id
            )

    def test_effective_permissions_respects_customer_permission_overrides(self):
        access = CustomerUserBuildingAccess.objects.get(
            membership__user=self.cust_basic,
            building=self.building_a1,
        )
        # Toggle a couple of keys both ways and confirm composer reflects.
        access.permission_overrides = {
            "customer.ticket.create": False,           # revoke default-True
            "customer.extra_work.view_location": True,  # grant default-False
        }
        access.save(update_fields=["permission_overrides"])

        self.assertFalse(
            has_permission(
                self.cust_basic,
                "customer.ticket.create",
                customer_id=self.customer_a.id,
                building_id=self.building_a1.id,
            ),
            "Override `customer.ticket.create=False` must revoke the default-True.",
        )
        self.assertTrue(
            has_permission(
                self.cust_basic,
                "customer.extra_work.view_location",
                customer_id=self.customer_a.id,
                building_id=self.building_a1.id,
            ),
            "Override `customer.extra_work.view_location=True` must grant.",
        )
        # And the composer still matches the underlying resolver for every key.
        self._assert_parity(
            self.cust_basic, self.customer_a.id, self.building_a1.id
        )

    def test_effective_permissions_respects_inactive_customer_access(self):
        access = CustomerUserBuildingAccess.objects.get(
            membership__user=self.cust_company_admin,
            building=self.building_a1,
        )
        access.is_active = False
        access.save(update_fields=["is_active"])

        for key in CUSTOMER_PERMISSION_KEYS:
            self.assertFalse(
                has_permission(
                    self.cust_company_admin,
                    key,
                    customer_id=self.customer_a.id,
                    building_id=self.building_a1.id,
                ),
                f"Inactive access must collapse {key} to False.",
            )


# ---------------------------------------------------------------------------
# Cross-provider / cross-customer leak guard
# ---------------------------------------------------------------------------
class CrossTenantLeakTests(EffectivePermissionsFixture):
    def test_effective_permissions_does_not_grant_cross_customer_or_cross_provider_scope(self):
        # A basic customer-side user under customer_a / building_a1 has
        # default-True customer.* permissions THERE. The composer must
        # NOT grant the same keys when queried against customer_b (other
        # provider company entirely) or against building_a2 (under the
        # same customer but with no access row for this user).
        for forbidden_ctx in (
            (self.customer_b.id, self.building_b.id),
            (self.customer_a.id, self.building_a2.id),
        ):
            customer_id, building_id = forbidden_ctx
            for key in CUSTOMER_PERMISSION_KEYS:
                actual = has_permission(
                    self.cust_basic,
                    key,
                    customer_id=customer_id,
                    building_id=building_id,
                )
                self.assertFalse(
                    actual,
                    f"Composer leaked {key} into ({customer_id},{building_id}) "
                    f"for user with access only at (customer_a, building_a1).",
                )

        # And no provider-side user (admin_a in company_a) gets a
        # customer.* permission anywhere — those keys are gated by the
        # CustomerUserBuildingAccess row count, which is zero for
        # provider-side users.
        for key in CUSTOMER_PERMISSION_KEYS:
            self.assertFalse(
                has_permission(
                    self.admin_a,
                    key,
                    customer_id=self.customer_a.id,
                    building_id=self.building_a1.id,
                ),
                f"Provider COMPANY_ADMIN must not get customer.* key {key}.",
            )


# ---------------------------------------------------------------------------
# API edge cases
# ---------------------------------------------------------------------------
class HasPermissionEdgeCaseTests(EffectivePermissionsFixture):
    def test_has_permission_unknown_key_returns_false(self):
        for actor in (
            self.super_admin,
            self.admin_a,
            self.manager_a1,
            self.staff_a,
            self.cust_basic,
        ):
            self.assertFalse(
                has_permission(
                    actor,
                    "this.is.not.a.real.key",
                    customer_id=self.customer_a.id,
                    building_id=self.building_a1.id,
                ),
            )

    def test_has_permission_anonymous_returns_false(self):
        from django.contrib.auth.models import AnonymousUser

        anon = AnonymousUser()
        for key in (
            "osius.ticket.view_building",
            "customer.ticket.create",
        ):
            self.assertFalse(
                has_permission(
                    anon,
                    key,
                    customer_id=self.customer_a.id,
                    building_id=self.building_a1.id,
                ),
            )

    def test_has_permission_customer_key_without_customer_id_returns_false(self):
        # Customer-side keys are inherently per-(customer, building);
        # without a customer_id the composer cannot resolve which access
        # row to consult and must return False.
        for actor in (self.cust_basic, self.cust_company_admin):
            self.assertFalse(
                has_permission(
                    actor,
                    "customer.ticket.create",
                    building_id=self.building_a1.id,
                ),
            )


# ---------------------------------------------------------------------------
# effective_permissions() dict shape
# ---------------------------------------------------------------------------
class EffectivePermissionsDictTests(EffectivePermissionsFixture):
    def test_dict_covers_every_known_key(self):
        result = effective_permissions(
            self.cust_basic,
            customer_id=self.customer_a.id,
            building_id=self.building_a1.id,
        )
        for key in OSIUS_PERMISSION_KEYS:
            self.assertIn(key, result, f"missing osius key {key}")
        for key in CUSTOMER_PERMISSION_KEYS:
            self.assertIn(key, result, f"missing customer key {key}")

    def test_dict_matches_per_key_has_permission(self):
        # Walk a few representative actors; for each key, the dict
        # value must equal a direct has_permission() call.
        for actor, customer_id, building_id in (
            (self.super_admin, self.customer_a.id, self.building_a1.id),
            (self.admin_a, self.customer_a.id, self.building_a1.id),
            (self.manager_a1, self.customer_a.id, self.building_a1.id),
            (self.staff_a, self.customer_a.id, self.building_a1.id),
            (self.cust_basic, self.customer_a.id, self.building_a1.id),
            (self.cust_location_manager, self.customer_a.id, self.building_a1.id),
            (self.cust_company_admin, self.customer_a.id, self.building_a1.id),
        ):
            dict_view = effective_permissions(
                actor, customer_id=customer_id, building_id=building_id
            )
            for key, value in dict_view.items():
                expected = has_permission(
                    actor,
                    key,
                    customer_id=customer_id,
                    building_id=building_id,
                )
                self.assertEqual(
                    value,
                    expected,
                    f"dict[{key!r}]={value} vs has_permission={expected} for "
                    f"actor={actor.email} customer_id={customer_id} "
                    f"building_id={building_id}",
                )
