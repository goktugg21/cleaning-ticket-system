"""
Per-record actions backend — customer detail + membership endpoint
`actions` blocks.

Surfaces three derived facts the frontend needs to render a writable
role dropdown + permission-management surface without re-deriving:

  * `can_manage_customer_users`
  * `can_manage_customer_company_admins`
  * `allowed_target_customer_access_roles`

The values mirror the live B4 / B5 rules + the H-7 grant gate. Two
endpoint surfaces are pinned:

  * `GET /api/customers/<id>/`           — actions on CustomerSerializer
  * `GET /api/customers/<id>/users/`     — actions on each membership row

This file is deliberately small — the underlying rules already have
exhaustive coverage in `test_b4_cca_user_management.py` and
`test_b5_provider_admin_cca_policy.py`. The tests here only pin the
SHAPE of the actions block and the few permutations the brief
explicitly calls out.
"""
from __future__ import annotations

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from accounts.models import UserRole
from buildings.models import Building
from companies.models import Company, CompanyUserMembership
from customers.models import (
    Customer,
    CustomerBuildingMembership,
    CustomerUserBuildingAccess,
    CustomerUserMembership,
)


User = get_user_model()
PASSWORD = "StrongerTestPassword123!"
ALL_ROLES = [
    CustomerUserBuildingAccess.AccessRole.CUSTOMER_USER,
    CustomerUserBuildingAccess.AccessRole.CUSTOMER_LOCATION_MANAGER,
    CustomerUserBuildingAccess.AccessRole.CUSTOMER_COMPANY_ADMIN,
]
LOWER_TIERS = [
    CustomerUserBuildingAccess.AccessRole.CUSTOMER_USER,
    CustomerUserBuildingAccess.AccessRole.CUSTOMER_LOCATION_MANAGER,
]


def _mk(email, role, **extra):
    return User.objects.create_user(
        email=email,
        password=PASSWORD,
        role=role,
        full_name=email.split("@")[0],
        **extra,
    )


class _CustomerActionsFixture(TestCase):
    """Provider company with the B5 toggle ON by default, one
    customer, two CUSTOMER_USER actors (one default CUSTOMER_USER,
    one CCA with `customer.users.manage`).
    """

    @classmethod
    def setUpTestData(cls):
        cls.company = Company.objects.create(
            name="Prov PR-CUST", slug="prov-pr-cust"
        )
        cls.building = Building.objects.create(
            company=cls.company, name="Building-PR-CUST"
        )
        cls.customer = Customer.objects.create(
            company=cls.company,
            name="Customer-PR-CUST",
            building=cls.building,
        )
        CustomerBuildingMembership.objects.create(
            customer=cls.customer, building=cls.building
        )

        cls.super_admin = _mk(
            "super-pr-cust@example.com",
            UserRole.SUPER_ADMIN,
            is_staff=True,
            is_superuser=True,
        )
        cls.admin = _mk("admin-pr-cust@example.com", UserRole.COMPANY_ADMIN)
        CompanyUserMembership.objects.create(
            user=cls.admin, company=cls.company
        )

        # Default-tier customer user.
        cls.cust_user = _mk(
            "cust-pr-cust@example.com", UserRole.CUSTOMER_USER
        )
        membership = CustomerUserMembership.objects.create(
            customer=cls.customer, user=cls.cust_user
        )
        CustomerUserBuildingAccess.objects.create(
            membership=membership,
            building=cls.building,
            access_role=CustomerUserBuildingAccess.AccessRole.CUSTOMER_USER,
        )

        # CCA actor (CUSTOMER_USER role, CCA access tier — has
        # `customer.users.manage` by role default).
        cls.cca = _mk("cca-pr-cust@example.com", UserRole.CUSTOMER_USER)
        cca_membership = CustomerUserMembership.objects.create(
            customer=cls.customer, user=cls.cca
        )
        CustomerUserBuildingAccess.objects.create(
            membership=cca_membership,
            building=cls.building,
            access_role=CustomerUserBuildingAccess.AccessRole.CUSTOMER_COMPANY_ADMIN,
        )

    def _api(self, user):
        c = APIClient()
        c.force_authenticate(user=user)
        return c

    def _detail(self, user):
        return self._api(user).get(f"/api/customers/{self.customer.id}/")

    def _memberships(self, user):
        return self._api(user).get(
            f"/api/customers/{self.customer.id}/users/"
        )


class CustomerDetailActionsTests(_CustomerActionsFixture):
    def test_super_admin_can_manage_users_and_ccas_and_all_roles(self):
        response = self._detail(self.super_admin)
        self.assertEqual(response.status_code, 200, response.data)
        actions = response.data["actions"]
        self.assertTrue(actions["can_manage_customer_users"])
        self.assertTrue(actions["can_manage_customer_company_admins"])
        self.assertEqual(
            sorted(actions["allowed_target_customer_access_roles"]),
            sorted(ALL_ROLES),
        )

    def test_company_admin_in_scope_with_policy_on_can_manage_all(self):
        response = self._detail(self.admin)
        self.assertEqual(response.status_code, 200, response.data)
        actions = response.data["actions"]
        self.assertTrue(actions["can_manage_customer_users"])
        # Default policy is True -> CA may manage CCAs.
        self.assertTrue(actions["can_manage_customer_company_admins"])
        self.assertEqual(
            sorted(actions["allowed_target_customer_access_roles"]),
            sorted(ALL_ROLES),
        )

    def test_company_admin_with_policy_off_loses_cca_management(self):
        # Flip the B5 toggle. CA keeps lower-tier management, loses
        # CCA grant authority.
        self.company.provider_admin_may_manage_customer_company_admins = False
        self.company.save(
            update_fields=["provider_admin_may_manage_customer_company_admins"]
        )
        response = self._detail(self.admin)
        self.assertEqual(response.status_code, 200, response.data)
        actions = response.data["actions"]
        self.assertTrue(actions["can_manage_customer_users"])  # still True
        self.assertFalse(actions["can_manage_customer_company_admins"])
        self.assertEqual(
            sorted(actions["allowed_target_customer_access_roles"]),
            sorted(LOWER_TIERS),
        )

    def test_cca_holder_can_manage_lower_users_but_never_grant_cca(self):
        response = self._detail(self.cca)
        self.assertEqual(response.status_code, 200, response.data)
        actions = response.data["actions"]
        self.assertTrue(actions["can_manage_customer_users"])
        # CCA NEVER reaches "manage CCA" — H-7 grant gate.
        self.assertFalse(actions["can_manage_customer_company_admins"])
        # Allowed tiers: lower tiers only (CCA can promote CU -> CLM
        # but can never set CCA).
        self.assertEqual(
            sorted(actions["allowed_target_customer_access_roles"]),
            sorted(LOWER_TIERS),
        )

    def test_default_customer_user_cannot_manage_anything(self):
        response = self._detail(self.cust_user)
        self.assertEqual(response.status_code, 200, response.data)
        actions = response.data["actions"]
        self.assertFalse(actions["can_manage_customer_users"])
        self.assertFalse(actions["can_manage_customer_company_admins"])
        self.assertEqual(actions["allowed_target_customer_access_roles"], [])


class CustomerMembershipListActionsTests(_CustomerActionsFixture):
    """Each membership row in the list response carries the same
    actions block as the customer detail. Duplication is acceptable —
    the list is bounded by the customer's user count, and the
    pagination shape stays JSON-stable."""

    def test_membership_list_rows_carry_actions_block_matching_customer(self):
        # Detail and list should report identical actions for the
        # same viewer (the actions describe the viewer's authority on
        # the parent customer, not on a specific membership row).
        detail = self._detail(self.admin)
        memberships = self._memberships(self.admin)
        self.assertEqual(memberships.status_code, 200, memberships.data)
        rows = memberships.data.get("results", memberships.data)
        self.assertGreater(len(rows), 0)
        for row in rows:
            self.assertIn("actions", row)
            self.assertEqual(
                sorted(row["actions"]["allowed_target_customer_access_roles"]),
                sorted(
                    detail.data["actions"]["allowed_target_customer_access_roles"]
                ),
            )
            self.assertEqual(
                row["actions"]["can_manage_customer_users"],
                detail.data["actions"]["can_manage_customer_users"],
            )
            self.assertEqual(
                row["actions"]["can_manage_customer_company_admins"],
                detail.data["actions"]["can_manage_customer_company_admins"],
            )
