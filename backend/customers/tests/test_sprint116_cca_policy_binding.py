"""
Sprint 116 — CustomerCompanyPolicy binds a company-wide Customer Company Admin.

Owner decision (2026-07-26, SoT Addendum A.1): the company-level
`CustomerCompanyPolicy` toggles MUST bind a company-wide Customer Company
Admin (CCA). Turning a policy family off for the customer denies that
family's keys even for a CCA.

Per Addendum A.1 the CCA otherwise stays the un-downgradable top customer-side
role: the per-building `is_active` and `permission_overrides` layers still do
NOT apply to a company-wide CCA, and no per-building row can downgrade one. The
company-level policy is the ONLY layer that narrows a CCA.

A company-wide CCA carries `CustomerUserMembership.is_company_admin=True` with
ZERO `CustomerUserBuildingAccess` rows.
"""
from __future__ import annotations

from django.contrib.auth import get_user_model
from django.test import TestCase

from accounts.models import UserRole
from buildings.models import Building
from companies.models import Company
from customers.models import (
    CustomerCompanyPolicy,
    Customer,
    CustomerBuildingMembership,
    CustomerUserBuildingAccess,
    CustomerUserMembership,
)
from customers.permissions import user_can

User = get_user_model()
PASSWORD = "StrongerTestPassword123!"
CU = CustomerUserBuildingAccess.AccessRole.CUSTOMER_USER

# The four policy fields and the permission key(s) each one governs
# (mirrors customers.permissions._POLICY_FAMILY_FIELD, from the other side).
TOGGLES: dict[str, list[str]] = {
    "customer_users_can_create_tickets": ["customer.ticket.create"],
    "customer_users_can_approve_ticket_completion": [
        "customer.ticket.approve_own",
        "customer.ticket.approve_location",
    ],
    "customer_users_can_create_extra_work": ["customer.extra_work.create"],
    "customer_users_can_approve_extra_work_pricing": [
        "customer.extra_work.approve_own",
        "customer.extra_work.approve_location",
    ],
}


class CCAPolicyBindingTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.company = Company.objects.create(name="Prov 116", slug="prov-116")
        cls.b1 = Building.objects.create(company=cls.company, name="B116-1")
        cls.customer = Customer.objects.create(
            company=cls.company, name="Cust 116", building=cls.b1
        )
        CustomerBuildingMembership.objects.create(
            customer=cls.customer, building=cls.b1
        )
        cls.cca_user = User.objects.create_user(
            email="cca116@example.com",
            password=PASSWORD,
            role=UserRole.CUSTOMER_USER,
            full_name="CCA 116",
        )
        # Company-wide CCA: membership flag set, ZERO per-building rows.
        cls.cca_mem = CustomerUserMembership.objects.create(
            customer=cls.customer, user=cls.cca_user, is_company_admin=True
        )

    def setUp(self):
        # The auto-create signal made a policy row at safe defaults (all
        # True). Fetch it fresh each test (per-test savepoint rollback keeps
        # tests isolated).
        self.policy = CustomerCompanyPolicy.objects.get(customer=self.customer)

    def _can(self, key, building_id=None):
        return user_can(self.cca_user, self.customer.id, building_id, key)

    def _set(self, field, value):
        setattr(self.policy, field, value)
        self.policy.save(update_fields=[field, "updated_at"])

    def test_each_policy_toggle_binds_the_cca(self):
        """For every policy field: True -> CCA allowed for its key(s);
        False -> CCA denied for its key(s)."""
        for field, keys in TOGGLES.items():
            for key in keys:
                self._set(field, True)
                with self.subTest(field=field, key=key, toggle=True):
                    self.assertTrue(
                        self._can(key),
                        f"{key} must be allowed for a CCA when {field}=True",
                    )
                self._set(field, False)
                with self.subTest(field=field, key=key, toggle=False):
                    self.assertFalse(
                        self._can(key),
                        f"{key} must be denied for a CCA when {field}=False",
                    )
                # Reset so a shared-field key (approve_own/approve_location)
                # starts the next iteration from True.
                self._set(field, True)

    def test_key_outside_policy_map_unaffected_by_any_toggle(self):
        """A CCA-granted key that is NOT in the policy map stays True even
        with every policy toggle turned OFF."""
        for field in TOGGLES:
            self._set(field, False)
        for key in (
            "customer.ticket.view_company",
            "customer.users.manage",
            "customer.users.manage_permissions",
        ):
            with self.subTest(key=key):
                self.assertTrue(
                    self._can(key),
                    f"{key} is outside the policy map; a CCA must still pass",
                )

    def test_cca_with_no_access_rows_resolves_when_policy_permits(self):
        """The A.1 guarantee: a company-wide CCA with ZERO per-building rows
        still resolves (True) for its keys when the policy permits."""
        self.assertEqual(
            CustomerUserBuildingAccess.objects.filter(
                membership=self.cca_mem
            ).count(),
            0,
        )
        for key in (
            "customer.ticket.create",
            "customer.extra_work.approve_location",
            "customer.ticket.view_company",
        ):
            with self.subTest(key=key):
                self.assertTrue(self._can(key))

    def test_per_building_row_cannot_downgrade_a_cca(self):
        """An inactive per-building row AND a restrictive permission_overrides
        row must NOT downgrade a CCA — the short-circuit ignores per-building
        rows entirely. (Policy permits here, so only the per-building layers
        could have denied — they must not.)"""
        CustomerUserBuildingAccess.objects.create(
            membership=self.cca_mem,
            building=self.b1,
            access_role=CU,
            is_active=False,
            permission_overrides={
                "customer.ticket.create": False,
                "customer.extra_work.approve_own": False,
            },
        )
        for key in (
            "customer.ticket.create",
            "customer.extra_work.approve_own",
            "customer.ticket.approve_location",
        ):
            with self.subTest(key=key, building=self.b1.id):
                self.assertTrue(
                    self._can(key, building_id=self.b1.id),
                    f"{key}: a per-building row must not downgrade a CCA",
                )
            with self.subTest(key=key, building=None):
                self.assertTrue(
                    self._can(key),
                    f"{key}: a per-building row must not downgrade a CCA",
                )
