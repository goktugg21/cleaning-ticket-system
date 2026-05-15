"""
Sprint 27D — provider-side management permission keys (closes G-B9).

The three keys live in `OSIUS_PERMISSION_KEYS` since Sprint 23A but
were not consumed by `user_has_osius_permission` — they returned
the default True for SUPER_ADMIN / COMPANY_ADMIN (via the global
"return True" branches) and False for BUILDING_MANAGER / STAFF.
There was no building-scoped check, so a COMPANY_ADMIN of provider
A would resolve `osius.customer_company.manage` to True when called
with `building_id=<building of provider B>` — a latent cross-
provider leak waiting for the first call site.

Sprint 27D wires the three keys properly:

  * SUPER_ADMIN: always True for every osius.* key (unchanged).
  * COMPANY_ADMIN: True only when the actor is a member (via
    CompanyUserMembership) of a provider company that owns the
    building referenced by `building_id`. If `building_id` is None,
    True iff the actor has any CompanyUserMembership at all
    (i.e. they are a valid COMPANY_ADMIN with a scoped surface).
  * BUILDING_MANAGER: False — company-level management is above
    the building-manager pay grade by design (G-B9 acceptance:
    "BUILDING_MANAGER and STAFF must not accidentally gain
    company-level management keys").
  * STAFF: False (same reason).
  * CUSTOMER_USER: False (osius.* keys are provider-side only).

These tests are exhaustive across the three new keys and lock the
cross-provider leak guard.
"""
from __future__ import annotations

from django.contrib.auth import get_user_model
from django.test import TestCase

from accounts.models import StaffProfile, UserRole
from accounts.permissions_effective import has_permission
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


User = get_user_model()
PASSWORD = "StrongerTestPassword123!"


PROVIDER_MANAGEMENT_KEYS = (
    "osius.staff.manage",
    "osius.building.manage",
    "osius.customer_company.manage",
)


def _mk(email, role, **extra):
    return User.objects.create_user(
        email=email,
        password=PASSWORD,
        role=role,
        full_name=email.split("@")[0],
        **extra,
    )


class ProviderManagementKeyFixture(TestCase):
    """Two-provider fixture: lets us exercise the cross-provider
    isolation invariant for each new management key."""

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
        cls.admin_b = _mk("admin-b@example.com", UserRole.COMPANY_ADMIN)
        CompanyUserMembership.objects.create(
            user=cls.admin_b, company=cls.company_b
        )

        cls.manager_a = _mk("mgr-a@example.com", UserRole.BUILDING_MANAGER)
        BuildingManagerAssignment.objects.create(
            user=cls.manager_a, building=cls.building_a
        )

        cls.staff_a = _mk("staff-a@example.com", UserRole.STAFF)
        StaffProfile.objects.create(user=cls.staff_a, is_active=True)
        BuildingStaffVisibility.objects.create(
            user=cls.staff_a, building=cls.building_a
        )

        cls.customer_user = _mk(
            "cu@example.com", UserRole.CUSTOMER_USER
        )


# ---------------------------------------------------------------------------
# Super admin gets every osius.* key including the three management keys.
# ---------------------------------------------------------------------------
class SuperAdminProviderKeyTests(ProviderManagementKeyFixture):
    def test_super_admin_has_all_stubbed_provider_management_keys(self):
        for key in PROVIDER_MANAGEMENT_KEYS:
            self.assertTrue(
                user_has_osius_permission(self.super_admin, key),
                f"SUPER_ADMIN must have {key}",
            )
            # And building-scoped — SUPER_ADMIN crosses provider boundaries.
            self.assertTrue(
                user_has_osius_permission(
                    self.super_admin, key, building_id=self.building_a.id
                ),
                f"SUPER_ADMIN must have {key} for building_a",
            )
            self.assertTrue(
                user_has_osius_permission(
                    self.super_admin, key, building_id=self.building_b.id
                ),
                f"SUPER_ADMIN must have {key} for building_b",
            )


# ---------------------------------------------------------------------------
# Company admin gets management keys only inside their own provider company.
# ---------------------------------------------------------------------------
class CompanyAdminProviderKeyTests(ProviderManagementKeyFixture):
    def test_company_admin_has_provider_management_keys_for_own_company_context(self):
        # No building_id: True iff the admin has at least one
        # CompanyUserMembership — admin_a does, so True for every key.
        for key in PROVIDER_MANAGEMENT_KEYS:
            self.assertTrue(
                user_has_osius_permission(self.admin_a, key),
                f"COMPANY_ADMIN must have {key} in their own provider scope",
            )
            # building_a belongs to admin_a's company → True.
            self.assertTrue(
                user_has_osius_permission(
                    self.admin_a, key, building_id=self.building_a.id
                ),
                f"COMPANY_ADMIN-A must have {key} for own-company building",
            )

    def test_company_admin_does_not_gain_cross_provider_management_scope(self):
        """admin_a is a member of company_a only. Asking about a building
        owned by company_b must return False for the three new management
        keys — the resolver may not silently widen scope to other
        providers, even though `building_id` is the only sub-scope
        argument it accepts."""
        for key in PROVIDER_MANAGEMENT_KEYS:
            self.assertFalse(
                user_has_osius_permission(
                    self.admin_a, key, building_id=self.building_b.id
                ),
                f"Cross-provider leak: COMPANY_ADMIN-A got {key} for "
                f"building owned by Provider B.",
            )
            self.assertFalse(
                user_has_osius_permission(
                    self.admin_b, key, building_id=self.building_a.id
                ),
                f"Cross-provider leak: COMPANY_ADMIN-B got {key} for "
                f"building owned by Provider A.",
            )

    def test_orphan_company_admin_with_no_membership_does_not_get_management_keys(self):
        """A COMPANY_ADMIN whose CompanyUserMembership has been revoked
        (or never created) is effectively scopeless. They must not
        retain the management keys — the role alone is not enough,
        membership is the scope anchor."""
        orphan = _mk("admin-orphan@example.com", UserRole.COMPANY_ADMIN)
        for key in PROVIDER_MANAGEMENT_KEYS:
            self.assertFalse(
                user_has_osius_permission(orphan, key),
                f"Orphan COMPANY_ADMIN must not get {key} with no membership",
            )
            self.assertFalse(
                user_has_osius_permission(
                    orphan, key, building_id=self.building_a.id
                ),
                f"Orphan COMPANY_ADMIN must not get {key} for any building",
            )


# ---------------------------------------------------------------------------
# Building manager / staff / customer user never get the management keys.
# ---------------------------------------------------------------------------
class NonAdminProviderKeyTests(ProviderManagementKeyFixture):
    def test_building_manager_does_not_get_company_level_management_keys(self):
        # Even with an in-scope building, BM is below company-level management.
        for key in PROVIDER_MANAGEMENT_KEYS:
            self.assertFalse(
                user_has_osius_permission(self.manager_a, key),
                f"BUILDING_MANAGER must not get {key} (no-building check)",
            )
            self.assertFalse(
                user_has_osius_permission(
                    self.manager_a, key, building_id=self.building_a.id
                ),
                f"BUILDING_MANAGER must not get {key} for in-scope building",
            )
            self.assertFalse(
                user_has_osius_permission(
                    self.manager_a, key, building_id=self.building_b.id
                ),
                f"BUILDING_MANAGER must not get {key} for out-of-scope building",
            )

    def test_staff_does_not_get_company_level_management_keys(self):
        for key in PROVIDER_MANAGEMENT_KEYS:
            self.assertFalse(
                user_has_osius_permission(self.staff_a, key),
                f"STAFF must not get {key}",
            )
            self.assertFalse(
                user_has_osius_permission(
                    self.staff_a, key, building_id=self.building_a.id
                ),
                f"STAFF must not get {key} for in-scope building",
            )

    def test_customer_user_does_not_get_provider_keys(self):
        for key in PROVIDER_MANAGEMENT_KEYS:
            self.assertFalse(
                user_has_osius_permission(self.customer_user, key),
                f"CUSTOMER_USER must not get provider key {key}",
            )


# ---------------------------------------------------------------------------
# Composer parity — the read-only facade must stay in sync with the resolver
# after the Sprint 27D rules tighten COMPANY_ADMIN behavior.
# ---------------------------------------------------------------------------
class EffectivePermissionsParityForProviderKeysTests(ProviderManagementKeyFixture):
    def test_effective_permissions_matches_provider_resolver_for_new_provider_keys(self):
        """has_permission()(osius.*) must equal user_has_osius_permission()
        for every actor × building context after the Sprint 27D rules."""
        actors = (
            self.super_admin,
            self.admin_a,
            self.admin_b,
            self.manager_a,
            self.staff_a,
            self.customer_user,
        )
        buildings = (None, self.building_a.id, self.building_b.id)
        for actor in actors:
            for building_id in buildings:
                for key in PROVIDER_MANAGEMENT_KEYS:
                    expected = user_has_osius_permission(
                        actor, key, building_id=building_id
                    )
                    actual = has_permission(
                        actor, key, building_id=building_id
                    )
                    self.assertEqual(
                        actual,
                        expected,
                        f"key={key} actor={actor.email} "
                        f"building_id={building_id} composer={actual} "
                        f"resolver={expected}",
                    )

    def test_all_osius_keys_still_covered_in_resolver(self):
        """Regression net: the three management keys are still in
        OSIUS_PERMISSION_KEYS, so the composer routes them correctly."""
        for key in PROVIDER_MANAGEMENT_KEYS:
            self.assertIn(key, OSIUS_PERMISSION_KEYS)
