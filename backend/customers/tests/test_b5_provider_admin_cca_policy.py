"""
B5 — Super Admin-controlled policy that disables Provider Company
Admin's ability to grant the `CUSTOMER_COMPANY_ADMIN` access role.

Policy field: `companies.Company.provider_admin_may_manage_customer_company_admins`
(BooleanField, default True). When True, COMPANY_ADMIN may grant CCA
on customers under that provider company. When False, only
SUPER_ADMIN may. B4 lower-user management (Customer User / Customer
Location Manager + their `permission_overrides`) is NOT affected by
this toggle — only CCA-level grant authority is.

Tests pinned in this file:

  1. Default behaviour (policy=True):
     - Provider Admin can grant CCA on a lower user.
     - Super Admin can grant CCA.
     - CCA cannot grant CCA (H-7 / cca_cannot_manage_cca / B4 guards).

  2. Toggle disabled (policy=False):
     - Provider Admin's CCA-grant attempt returns 400 with the
       documented validation error.
     - Provider Admin can still manage lower customer users' overrides
       (B4 behaviour preserved).
     - Super Admin can still grant CCA.

  3. Toggle write surface:
     - Only Super Admin may flip the policy via PATCH
       `/api/companies/<id>/`. Provider Admin attempt returns 400.

  4. Effective-permissions endpoint reflects the policy state:
     - `can_manage_customer_company_admins` follows the policy
       (True for SA always; True for COMPANY_ADMIN in scope only
       when policy=True).
     - `can_manage_customer_permissions` for COMPANY_ADMIN stays
       True regardless of policy — B5 narrows ONLY CCA-grant.
     - Notes list mentions the live policy state.

  5. B4 regression: CCA managing lower users continues to work
     regardless of policy state.

No new permission keys. One migration shipped with this batch.
No frontend changes.
"""
from __future__ import annotations

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework import status
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


def _mk(email: str, role: str, **extra) -> User:
    return User.objects.create_user(
        email=email,
        password=PASSWORD,
        role=role,
        full_name=email.split("@")[0],
        **extra,
    )


class _B5Fixture(TestCase):
    """One provider company + one customer + one building. CCA actor,
    Provider Admin actor, Super Admin actor, plus a lower customer
    user target that will be the subject of the grant attempts."""

    @classmethod
    def setUpTestData(cls):
        cls.company = Company.objects.create(name="Prov B5", slug="prov-b5")
        cls.building = Building.objects.create(
            company=cls.company, name="B5-B1"
        )
        cls.customer = Customer.objects.create(
            company=cls.company, name="Customer B5", building=cls.building
        )
        CustomerBuildingMembership.objects.create(
            customer=cls.customer, building=cls.building
        )

        # Actors.
        cls.super_admin = _mk(
            "super-b5@example.com",
            UserRole.SUPER_ADMIN,
            is_staff=True,
            is_superuser=True,
        )
        cls.admin = _mk("admin-b5@example.com", UserRole.COMPANY_ADMIN)
        CompanyUserMembership.objects.create(
            user=cls.admin, company=cls.company
        )

        # CCA actor (already a CCA) — needed for "CCA cannot grant CCA".
        cls.cca = _mk("cca-b5@example.com", UserRole.CUSTOMER_USER)
        cca_mem = CustomerUserMembership.objects.create(
            customer=cls.customer, user=cls.cca
        )
        CustomerUserBuildingAccess.objects.create(
            membership=cca_mem,
            building=cls.building,
            access_role=(
                CustomerUserBuildingAccess.AccessRole.CUSTOMER_COMPANY_ADMIN
            ),
        )

        # Lower target — currently access_role=CUSTOMER_USER. Tests
        # below try to PATCH this row's access_role to CCA.
        cls.cu_target = _mk("cu-target-b5@example.com", UserRole.CUSTOMER_USER)
        cu_mem = CustomerUserMembership.objects.create(
            customer=cls.customer, user=cls.cu_target
        )
        cls.cu_target_access = CustomerUserBuildingAccess.objects.create(
            membership=cu_mem,
            building=cls.building,
            access_role=CustomerUserBuildingAccess.AccessRole.CUSTOMER_USER,
        )

    # --- helpers -----------------------------------------------------
    def _api(self, user):
        c = APIClient()
        c.force_authenticate(user=user)
        return c

    def _access_url(self, customer_id, user_id, building_id):
        return (
            f"/api/customers/{customer_id}/users/{user_id}/access/{building_id}/"
        )

    def _company_url(self, company_id):
        return f"/api/companies/{company_id}/"

    def _effective_url(self, user_id, customer_id, building_id=None):
        url = (
            f"/api/users/{user_id}/effective-permissions/"
            f"?customer_id={customer_id}"
        )
        if building_id is not None:
            url += f"&building_id={building_id}"
        return url

    def _grant_cca_payload(self):
        return {
            "access_role": (
                CustomerUserBuildingAccess.AccessRole.CUSTOMER_COMPANY_ADMIN
            )
        }

    def _override_payload(self):
        return {"permission_overrides": {"customer.ticket.create": False}}


# ---------------------------------------------------------------------------
# 1. Default behaviour — policy=True (the migration default).
# ---------------------------------------------------------------------------
class DefaultBehaviourPolicyTrueTests(_B5Fixture):
    def test_policy_default_is_true(self):
        self.company.refresh_from_db()
        self.assertTrue(self.company.provider_admin_may_manage_customer_company_admins)

    def test_super_admin_can_grant_cca(self):
        response = self._api(self.super_admin).patch(
            self._access_url(
                self.customer.id, self.cu_target.id, self.building.id
            ),
            self._grant_cca_payload(),
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.cu_target_access.refresh_from_db()
        self.assertEqual(
            self.cu_target_access.access_role,
            (CustomerUserBuildingAccess.AccessRole.CUSTOMER_COMPANY_ADMIN),
        )

    def test_provider_admin_can_grant_cca_when_policy_true(self):
        response = self._api(self.admin).patch(
            self._access_url(
                self.customer.id, self.cu_target.id, self.building.id
            ),
            self._grant_cca_payload(),
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.cu_target_access.refresh_from_db()
        self.assertEqual(
            self.cu_target_access.access_role,
            (CustomerUserBuildingAccess.AccessRole.CUSTOMER_COMPANY_ADMIN),
        )

    def test_cca_cannot_grant_cca_even_when_policy_true(self):
        # CCA is blocked by the H-7 leg that rejects every non-SA /
        # non-COMPANY_ADMIN actor. (Plus the B4 CCA-cannot-manage-CCA
        # guard at the view layer; either refusal is acceptable but
        # the assertion below is "definitely refused".)
        response = self._api(self.cca).patch(
            self._access_url(
                self.customer.id, self.cu_target.id, self.building.id
            ),
            self._grant_cca_payload(),
            format="json",
        )
        self.assertIn(
            response.status_code,
            (status.HTTP_400_BAD_REQUEST, status.HTTP_403_FORBIDDEN),
        )
        self.cu_target_access.refresh_from_db()
        self.assertEqual(
            self.cu_target_access.access_role,
            CustomerUserBuildingAccess.AccessRole.CUSTOMER_USER,
        )


# ---------------------------------------------------------------------------
# 2. Toggle disabled — policy=False blocks Provider Admin from granting CCA
#    while preserving lower-user management.
# ---------------------------------------------------------------------------
class PolicyDisabledTests(_B5Fixture):
    def setUp(self):
        super().setUp()
        # Super Admin flips the toggle to False directly on the model
        # for setup brevity. The toggle-write endpoint is exercised in
        # `ToggleWriteSurfaceTests` below.
        self.company.provider_admin_may_manage_customer_company_admins = False
        self.company.save(
            update_fields=["provider_admin_may_manage_customer_company_admins"]
        )

    def test_provider_admin_cca_grant_attempt_returns_400(self):
        response = self._api(self.admin).patch(
            self._access_url(
                self.customer.id, self.cu_target.id, self.building.id
            ),
            self._grant_cca_payload(),
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.cu_target_access.refresh_from_db()
        self.assertEqual(
            self.cu_target_access.access_role,
            CustomerUserBuildingAccess.AccessRole.CUSTOMER_USER,
        )

    def test_super_admin_can_still_grant_cca_regardless_of_policy(self):
        response = self._api(self.super_admin).patch(
            self._access_url(
                self.customer.id, self.cu_target.id, self.building.id
            ),
            self._grant_cca_payload(),
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.cu_target_access.refresh_from_db()
        self.assertEqual(
            self.cu_target_access.access_role,
            (CustomerUserBuildingAccess.AccessRole.CUSTOMER_COMPANY_ADMIN),
        )

    def test_provider_admin_can_still_edit_lower_user_overrides(self):
        # B4 capability is unaffected by the B5 toggle: COMPANY_ADMIN
        # still manages lower-user permission_overrides freely.
        response = self._api(self.admin).patch(
            self._access_url(
                self.customer.id, self.cu_target.id, self.building.id
            ),
            self._override_payload(),
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.cu_target_access.refresh_from_db()
        self.assertEqual(
            self.cu_target_access.permission_overrides,
            {"customer.ticket.create": False},
        )

    def test_provider_admin_cannot_demote_existing_cca_when_policy_disabled(self):
        # Spec: "When disabled, Provider Company Admin must NOT be able
        # to create, grant, promote, edit, demote, revoke, or otherwise
        # manage Customer Company Admin access/permissions." Demote IS
        # listed — so the view-layer policy guard
        # `_company_admin_cca_policy_blocks_access_row` must fire when
        # the existing row's access_role is CCA, regardless of the
        # payload's target value.
        self.cu_target_access.access_role = (
            CustomerUserBuildingAccess.AccessRole.CUSTOMER_COMPANY_ADMIN
        )
        self.cu_target_access.save(update_fields=["access_role"])

        response = self._api(self.admin).patch(
            self._access_url(
                self.customer.id, self.cu_target.id, self.building.id
            ),
            {"access_role": CustomerUserBuildingAccess.AccessRole.CUSTOMER_USER},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(response.data.get("code"), "cca_policy_disabled")
        self.cu_target_access.refresh_from_db()
        self.assertEqual(
            self.cu_target_access.access_role,
            CustomerUserBuildingAccess.AccessRole.CUSTOMER_COMPANY_ADMIN,
        )

    def test_super_admin_can_still_demote_existing_cca_when_policy_disabled(self):
        # SA always retains the full CCA-management surface; the
        # policy gate exempts SA.
        self.cu_target_access.access_role = (
            CustomerUserBuildingAccess.AccessRole.CUSTOMER_COMPANY_ADMIN
        )
        self.cu_target_access.save(update_fields=["access_role"])

        response = self._api(self.super_admin).patch(
            self._access_url(
                self.customer.id, self.cu_target.id, self.building.id
            ),
            {"access_role": CustomerUserBuildingAccess.AccessRole.CUSTOMER_USER},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.cu_target_access.refresh_from_db()
        self.assertEqual(
            self.cu_target_access.access_role,
            CustomerUserBuildingAccess.AccessRole.CUSTOMER_USER,
        )

    def test_cca_still_cannot_grant_cca(self):
        # Sanity: regardless of toggle, CCA never grants CCA.
        response = self._api(self.cca).patch(
            self._access_url(
                self.customer.id, self.cu_target.id, self.building.id
            ),
            self._grant_cca_payload(),
            format="json",
        )
        self.assertIn(
            response.status_code,
            (status.HTTP_400_BAD_REQUEST, status.HTTP_403_FORBIDDEN),
        )

    def test_provider_admin_cannot_post_grant_cca_when_policy_disabled(self):
        """Explicit POST regression: a Provider Company Admin must not
        be able to create/grant a new CCA access row through a direct
        POST to `/api/customers/<cid>/users/<uid>/access/` with
        `access_role=CUSTOMER_COMPANY_ADMIN` smuggled in the body
        when the toggle is False. The view-layer defensive guard
        rejects with HTTP 403 + stable code `cca_policy_disabled`,
        and NO access row materialises on the second building.

        This locks the regression for the documented goal: the POST
        endpoint cannot be used as a back-door to bypass the
        serializer-layer PATCH grant gate."""
        # Add a second building so we can target a building where the
        # cu_target has no existing access row at all.
        second_building = Building.objects.create(
            company=self.company, name="B5-B2-post-grant"
        )
        CustomerBuildingMembership.objects.create(
            customer=self.customer, building=second_building
        )

        url = (
            f"/api/customers/{self.customer.id}/users/"
            f"{self.cu_target.id}/access/"
        )
        response = self._api(self.admin).post(
            url,
            {
                "building_id": second_building.id,
                "access_role": (
                    CustomerUserBuildingAccess.AccessRole.CUSTOMER_COMPANY_ADMIN
                ),
            },
            format="json",
        )
        self.assertEqual(
            response.status_code,
            status.HTTP_403_FORBIDDEN,
            response.content,
        )
        self.assertEqual(response.data.get("code"), "cca_policy_disabled")
        # And critically: no access row materialised on second_building
        # at any tier (the POST was rejected entirely, not silently
        # downgraded to CUSTOMER_USER).
        self.assertFalse(
            CustomerUserBuildingAccess.objects.filter(
                membership__user=self.cu_target,
                membership__customer=self.customer,
                building=second_building,
            ).exists()
        )


# ---------------------------------------------------------------------------
# 3. Toggle write surface — only Super Admin may flip the policy.
# ---------------------------------------------------------------------------
class ToggleWriteSurfaceTests(_B5Fixture):
    def test_super_admin_can_disable_the_policy(self):
        response = self._api(self.super_admin).patch(
            self._company_url(self.company.id),
            {"provider_admin_may_manage_customer_company_admins": False},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.company.refresh_from_db()
        self.assertFalse(
            self.company.provider_admin_may_manage_customer_company_admins
        )

    def test_super_admin_can_re_enable_the_policy(self):
        # Disable then re-enable round-trip.
        self.company.provider_admin_may_manage_customer_company_admins = False
        self.company.save(
            update_fields=["provider_admin_may_manage_customer_company_admins"]
        )
        response = self._api(self.super_admin).patch(
            self._company_url(self.company.id),
            {"provider_admin_may_manage_customer_company_admins": True},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.company.refresh_from_db()
        self.assertTrue(
            self.company.provider_admin_may_manage_customer_company_admins
        )

    def test_provider_admin_cannot_flip_the_policy(self):
        response = self._api(self.admin).patch(
            self._company_url(self.company.id),
            {"provider_admin_may_manage_customer_company_admins": False},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.company.refresh_from_db()
        # Field unchanged.
        self.assertTrue(
            self.company.provider_admin_may_manage_customer_company_admins
        )

    def test_provider_admin_can_still_patch_other_company_fields(self):
        # The toggle is field-scoped: editing `name` continues to work
        # for COMPANY_ADMIN as before.
        response = self._api(self.admin).patch(
            self._company_url(self.company.id),
            {"name": "Renamed Provider B5"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)


# ---------------------------------------------------------------------------
# 4. Effective-permissions endpoint reflects the policy state.
# ---------------------------------------------------------------------------
class EffectivePermissionsReflectsPolicyTests(_B5Fixture):
    def _fetch_actions_and_notes(self, caller, target):
        response = self._api(caller).get(
            self._effective_url(target.id, self.customer.id)
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        return response.data["effective_actions"], response.data["notes"]

    def test_super_admin_target_always_has_can_grant_cca_true(self):
        actions, _ = self._fetch_actions_and_notes(self.super_admin, self.super_admin)
        self.assertTrue(actions["can_manage_customer_company_admins"])

    def test_company_admin_target_has_can_grant_cca_true_when_policy_true(self):
        actions, notes = self._fetch_actions_and_notes(self.super_admin, self.admin)
        self.assertTrue(actions["can_manage_customer_company_admins"])
        # Notes must surface the policy state.
        joined_notes = " ".join(notes)
        self.assertIn("True", joined_notes)
        # And `can_manage_customer_permissions` remains True for the
        # COMPANY_ADMIN target — B5 narrows only CCA-grant.
        self.assertTrue(actions["can_manage_customer_permissions"])

    def test_company_admin_target_has_can_grant_cca_false_when_policy_false(self):
        self.company.provider_admin_may_manage_customer_company_admins = False
        self.company.save(
            update_fields=["provider_admin_may_manage_customer_company_admins"]
        )
        actions, notes = self._fetch_actions_and_notes(self.super_admin, self.admin)
        self.assertFalse(actions["can_manage_customer_company_admins"])
        # `can_manage_customer_permissions` stays True — B5 toggles
        # ONLY the CCA-grant action, NOT lower-user permission mgmt.
        self.assertTrue(actions["can_manage_customer_permissions"])
        # Notes must surface that the policy is disabled.
        joined_notes = " ".join(notes)
        self.assertIn("disabled", joined_notes.lower())

    def test_cca_target_does_not_get_can_grant_cca(self):
        actions, _ = self._fetch_actions_and_notes(self.super_admin, self.cca)
        self.assertFalse(actions["can_manage_customer_company_admins"])

    def test_lower_customer_user_target_does_not_get_can_grant_cca(self):
        actions, _ = self._fetch_actions_and_notes(self.super_admin, self.cu_target)
        self.assertFalse(actions["can_manage_customer_company_admins"])


# ---------------------------------------------------------------------------
# 4b. URL-smuggling regression — Provider Company Admin must not be able to
#     bypass the disabled toggle by calling the lower-level customer-user
#     management endpoints directly. Every URL that effectively edits /
#     demotes / revokes / extends a CCA target must return 403 with the
#     stable `cca_policy_disabled` code when policy=False.
# ---------------------------------------------------------------------------
class UrlSmugglingRegressionTests(_B5Fixture):
    """All five endpoint surfaces that touch the (customer, user, access)
    triple are pinned here. Each test uses the toggle-off state and a
    target that holds an active CCA access row; the Provider Admin
    actor must be blocked at the view layer."""

    def setUp(self):
        super().setUp()
        # Disable the toggle on the provider company.
        self.company.provider_admin_may_manage_customer_company_admins = False
        self.company.save(
            update_fields=["provider_admin_may_manage_customer_company_admins"]
        )
        # Promote cu_target to CCA so they are now a CCA-tier target
        # that the policy gate must protect from Provider Admin.
        self.cu_target_access.access_role = (
            CustomerUserBuildingAccess.AccessRole.CUSTOMER_COMPANY_ADMIN
        )
        self.cu_target_access.save(update_fields=["access_role"])
        # Add a second building so we can exercise the "extend reach
        # to a new building" path.
        self.second_building = Building.objects.create(
            company=self.company, name="B5-B2"
        )
        CustomerBuildingMembership.objects.create(
            customer=self.customer, building=self.second_building
        )

    def _assert_blocked(self, response):
        self.assertEqual(
            response.status_code,
            status.HTTP_403_FORBIDDEN,
            response.content,
        )
        self.assertEqual(response.data.get("code"), "cca_policy_disabled")

    # --- PATCH access row (edit overrides) ---
    def test_patch_permission_overrides_on_cca_row_is_blocked(self):
        response = self._api(self.admin).patch(
            self._access_url(
                self.customer.id, self.cu_target.id, self.building.id
            ),
            self._override_payload(),
            format="json",
        )
        self._assert_blocked(response)
        # And the row's overrides are untouched.
        self.cu_target_access.refresh_from_db()
        self.assertEqual(self.cu_target_access.permission_overrides, {})

    # --- PATCH access row (deactivate via is_active=False) ---
    def test_patch_is_active_false_on_cca_row_is_blocked(self):
        response = self._api(self.admin).patch(
            self._access_url(
                self.customer.id, self.cu_target.id, self.building.id
            ),
            {"is_active": False},
            format="json",
        )
        self._assert_blocked(response)
        self.cu_target_access.refresh_from_db()
        self.assertTrue(self.cu_target_access.is_active)

    # --- PATCH access row (no-op rewrite to CCA) ---
    def test_patch_access_role_cca_on_cca_row_is_blocked(self):
        # A no-op rewrite (CCA → CCA) is still "managing CCA". The
        # view-layer gate fires before the serializer's H-7 grant gate,
        # so the rejection code is `cca_policy_disabled` (403), NOT
        # the serializer's 400.
        response = self._api(self.admin).patch(
            self._access_url(
                self.customer.id, self.cu_target.id, self.building.id
            ),
            self._grant_cca_payload(),
            format="json",
        )
        self._assert_blocked(response)

    # --- DELETE access row (revoke) ---
    def test_delete_cca_access_row_is_blocked(self):
        response = self._api(self.admin).delete(
            self._access_url(
                self.customer.id, self.cu_target.id, self.building.id
            )
        )
        self._assert_blocked(response)
        # Row still present and still CCA.
        self.cu_target_access.refresh_from_db()
        self.assertEqual(
            self.cu_target_access.access_role,
            CustomerUserBuildingAccess.AccessRole.CUSTOMER_COMPANY_ADMIN,
        )

    # --- DELETE membership (cascades to all access rows incl. CCA) ---
    def test_delete_cca_membership_is_blocked(self):
        url = (
            f"/api/customers/{self.customer.id}/users/{self.cu_target.id}/"
        )
        response = self._api(self.admin).delete(url)
        self._assert_blocked(response)
        # Membership still present.
        self.assertTrue(
            CustomerUserMembership.objects.filter(
                customer=self.customer, user=self.cu_target
            ).exists()
        )

    # --- POST new access (extend reach of a CCA target) ---
    def test_post_new_access_on_cca_target_is_blocked(self):
        url = (
            f"/api/customers/{self.customer.id}/users/{self.cu_target.id}/access/"
        )
        response = self._api(self.admin).post(
            url, {"building_id": self.second_building.id}, format="json"
        )
        self._assert_blocked(response)
        # No new row materialised on the second building.
        self.assertFalse(
            CustomerUserBuildingAccess.objects.filter(
                membership__user=self.cu_target,
                membership__customer=self.customer,
                building=self.second_building,
            ).exists()
        )

    # --- Super Admin remains fully able on each surface ---
    def test_super_admin_can_still_perform_all_cca_actions_when_policy_disabled(self):
        sa = self._api(self.super_admin)
        # PATCH overrides on the CCA row.
        r1 = sa.patch(
            self._access_url(
                self.customer.id, self.cu_target.id, self.building.id
            ),
            self._override_payload(),
            format="json",
        )
        self.assertEqual(r1.status_code, status.HTTP_200_OK, r1.data)
        # DELETE the CCA access row.
        r2 = sa.delete(
            self._access_url(
                self.customer.id, self.cu_target.id, self.building.id
            )
        )
        self.assertEqual(r2.status_code, status.HTTP_204_NO_CONTENT, r2.content)
        # DELETE the membership now that no CCA access remains.
        r3 = sa.delete(
            f"/api/customers/{self.customer.id}/users/{self.cu_target.id}/"
        )
        self.assertEqual(r3.status_code, status.HTTP_204_NO_CONTENT, r3.content)

    # --- Lower-user management remains unaffected for Provider Admin ---
    def test_provider_admin_can_still_manage_non_cca_target_when_policy_disabled(self):
        # Add a second lower target with no CCA access at all.
        lower_target = _mk(
            "lower-b5@example.com", UserRole.CUSTOMER_USER
        )
        lower_mem = CustomerUserMembership.objects.create(
            customer=self.customer, user=lower_target
        )
        lower_access = CustomerUserBuildingAccess.objects.create(
            membership=lower_mem,
            building=self.building,
            access_role=CustomerUserBuildingAccess.AccessRole.CUSTOMER_USER,
        )
        # PATCH the lower target's overrides — must succeed despite the
        # disabled policy, because the target is NOT a CCA.
        response = self._api(self.admin).patch(
            self._access_url(
                self.customer.id, lower_target.id, self.building.id
            ),
            self._override_payload(),
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        lower_access.refresh_from_db()
        self.assertEqual(
            lower_access.permission_overrides,
            {"customer.ticket.create": False},
        )


# ---------------------------------------------------------------------------
# 5. B4 regression — CCA managing lower users keeps working regardless
#    of B5 policy state.
# ---------------------------------------------------------------------------
class B4RegressionUnderPolicyTests(_B5Fixture):
    def test_cca_can_still_manage_lower_user_with_policy_true(self):
        response = self._api(self.cca).patch(
            self._access_url(
                self.customer.id, self.cu_target.id, self.building.id
            ),
            self._override_payload(),
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)

    def test_cca_can_still_manage_lower_user_with_policy_false(self):
        self.company.provider_admin_may_manage_customer_company_admins = False
        self.company.save(
            update_fields=["provider_admin_may_manage_customer_company_admins"]
        )
        response = self._api(self.cca).patch(
            self._access_url(
                self.customer.id, self.cu_target.id, self.building.id
            ),
            self._override_payload(),
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
