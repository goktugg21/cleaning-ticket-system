"""
B4 — Customer Company Admin lower-user management.

Pins the new CCA-callable surface on the four user-management endpoints
in `customers.views_memberships`:

  * `CustomerUserListCreateView`   — list / add membership
  * `CustomerUserDeleteView`        — remove membership
  * `CustomerUserAccessListCreateView` — list / grant CUBA
  * `CustomerUserAccessDeleteView`     — PATCH / DELETE CUBA

Auth gate (`accounts.permissions.CanManageCustomerSideUsers`) admits
SUPER_ADMIN + COMPANY_ADMIN + CCA-with-`customer.users.manage`. Each
endpoint additionally enforces:

  * CCA cannot self-manage (membership / access).
  * CCA cannot touch a target who currently carries a CCA-tier access
    row under this customer (no CCA-on-CCA).
  * CCA cannot grant access at a building where their own
    `customer.users.manage` does not resolve to True.
  * CCA cannot promote anyone to CCA — the existing H-7 serializer
    guard (`validate_access_role`) blocks any non-SUPER_ADMIN attempt
    to set `access_role=CUSTOMER_COMPANY_ADMIN`.

This file also includes URL-smuggling regression tests targeted at
the CCA actor specifically (cross-customer URL typing).

B3 effective-permissions endpoint reflection is asserted last: a CCA
with `customer.users.manage` resolves `can_manage_customer_users=True`
in their own customer context; a customer user without the key
resolves False; `can_manage_customer_permissions` stays False for CCA.

No new permission keys. No migration. No frontend changes.
"""
from __future__ import annotations

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework import status
from rest_framework.test import APIClient

from accounts.models import StaffProfile, UserRole
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


# ---------------------------------------------------------------------------
# Fixture — provider company A with two buildings (B1, B2), one customer
# (customer A) linked to both. Customer A has:
#   * one CCA actor `cca` with manage at B1 and B2 (CUBA rows on both)
#   * one CCA `cca_limited_b1` with manage only at B1
#   * one Customer User target `cu_target` with a CUBA at B1
#   * one CLM target `clm_target` with a CUBA at B1 (access_role=CLM)
#   * one CCA target `cca_target` that CCA must never touch
#
# Provider company B has its own customer / users so cross-tenant
# smuggling can be exercised.
# ---------------------------------------------------------------------------
class _B4Fixture(TestCase):
    @classmethod
    def setUpTestData(cls):
        # Provider company A + customer A across two buildings.
        cls.company_a = Company.objects.create(name="Prov A B4", slug="prov-a-b4")
        cls.b1 = Building.objects.create(company=cls.company_a, name="A-B1")
        cls.b2 = Building.objects.create(company=cls.company_a, name="A-B2")
        cls.customer_a = Customer.objects.create(
            company=cls.company_a, name="Customer A B4", building=cls.b1
        )
        CustomerBuildingMembership.objects.create(
            customer=cls.customer_a, building=cls.b1
        )
        CustomerBuildingMembership.objects.create(
            customer=cls.customer_a, building=cls.b2
        )

        # Provider-side admin actors.
        cls.super_admin = _mk(
            "super-b4@example.com",
            UserRole.SUPER_ADMIN,
            is_staff=True,
            is_superuser=True,
        )
        cls.admin_a = _mk("admin-a-b4@example.com", UserRole.COMPANY_ADMIN)
        CompanyUserMembership.objects.create(user=cls.admin_a, company=cls.company_a)
        cls.bm_a = _mk("bm-a-b4@example.com", UserRole.BUILDING_MANAGER)
        BuildingManagerAssignment.objects.create(user=cls.bm_a, building=cls.b1)
        cls.staff_a = _mk("staff-a-b4@example.com", UserRole.STAFF)
        StaffProfile.objects.create(user=cls.staff_a)
        BuildingStaffVisibility.objects.create(user=cls.staff_a, building=cls.b1)

        # Customer-side actors on customer A.
        cls.cca = _mk("cca-b4@example.com", UserRole.CUSTOMER_USER)
        cca_mem = CustomerUserMembership.objects.create(
            customer=cls.customer_a, user=cls.cca
        )
        cls.cca_access_b1 = CustomerUserBuildingAccess.objects.create(
            membership=cca_mem,
            building=cls.b1,
            access_role=(
                CustomerUserBuildingAccess.AccessRole.CUSTOMER_COMPANY_ADMIN
            ),
        )
        cls.cca_access_b2 = CustomerUserBuildingAccess.objects.create(
            membership=cca_mem,
            building=cls.b2,
            access_role=(
                CustomerUserBuildingAccess.AccessRole.CUSTOMER_COMPANY_ADMIN
            ),
        )

        # A CCA who only has manage at B1, used to assert per-building
        # `customer.users.manage` enforcement.
        cls.cca_limited_b1 = _mk(
            "cca-limited-b4@example.com", UserRole.CUSTOMER_USER
        )
        limited_mem = CustomerUserMembership.objects.create(
            customer=cls.customer_a, user=cls.cca_limited_b1
        )
        CustomerUserBuildingAccess.objects.create(
            membership=limited_mem,
            building=cls.b1,
            access_role=(
                CustomerUserBuildingAccess.AccessRole.CUSTOMER_COMPANY_ADMIN
            ),
        )
        # NOTE: no row at B2 → this CCA cannot manage anything at B2.

        # A second CCA target — the one CCA actors must never touch.
        cls.cca_target = _mk("cca-target-b4@example.com", UserRole.CUSTOMER_USER)
        cca_target_mem = CustomerUserMembership.objects.create(
            customer=cls.customer_a, user=cls.cca_target
        )
        cls.cca_target_access = CustomerUserBuildingAccess.objects.create(
            membership=cca_target_mem,
            building=cls.b1,
            access_role=(
                CustomerUserBuildingAccess.AccessRole.CUSTOMER_COMPANY_ADMIN
            ),
        )

        # Lower-tier target users CCA may manage.
        cls.cu_target = _mk("cu-target-b4@example.com", UserRole.CUSTOMER_USER)
        cu_mem = CustomerUserMembership.objects.create(
            customer=cls.customer_a, user=cls.cu_target
        )
        cls.cu_target_access_b1 = CustomerUserBuildingAccess.objects.create(
            membership=cu_mem,
            building=cls.b1,
            access_role=CustomerUserBuildingAccess.AccessRole.CUSTOMER_USER,
        )

        cls.clm_target = _mk("clm-target-b4@example.com", UserRole.CUSTOMER_USER)
        clm_mem = CustomerUserMembership.objects.create(
            customer=cls.customer_a, user=cls.clm_target
        )
        cls.clm_target_access_b1 = CustomerUserBuildingAccess.objects.create(
            membership=clm_mem,
            building=cls.b1,
            access_role=(
                CustomerUserBuildingAccess.AccessRole.CUSTOMER_LOCATION_MANAGER
            ),
        )

        # A spare unlinked customer-user account with role CUSTOMER_USER
        # for "link a new lower user" POST tests.
        cls.spare_cu = _mk("spare-cu-b4@example.com", UserRole.CUSTOMER_USER)

        # Provider company B + its own customer / CCA / lower user
        # for cross-tenant smuggling tests.
        cls.company_b = Company.objects.create(name="Prov B B4", slug="prov-b-b4")
        cls.b3_other = Building.objects.create(
            company=cls.company_b, name="B-B3"
        )
        cls.customer_b = Customer.objects.create(
            company=cls.company_b, name="Customer B B4", building=cls.b3_other
        )
        CustomerBuildingMembership.objects.create(
            customer=cls.customer_b, building=cls.b3_other
        )
        cls.cca_b = _mk("cca-other-b4@example.com", UserRole.CUSTOMER_USER)
        cca_b_mem = CustomerUserMembership.objects.create(
            customer=cls.customer_b, user=cls.cca_b
        )
        CustomerUserBuildingAccess.objects.create(
            membership=cca_b_mem,
            building=cls.b3_other,
            access_role=(
                CustomerUserBuildingAccess.AccessRole.CUSTOMER_COMPANY_ADMIN
            ),
        )
        cls.cu_b = _mk("cu-other-b4@example.com", UserRole.CUSTOMER_USER)
        cu_b_mem = CustomerUserMembership.objects.create(
            customer=cls.customer_b, user=cls.cu_b
        )
        CustomerUserBuildingAccess.objects.create(
            membership=cu_b_mem,
            building=cls.b3_other,
            access_role=CustomerUserBuildingAccess.AccessRole.CUSTOMER_USER,
        )

    # --- helpers ----------------------------------------------------------
    def _api(self, user):
        c = APIClient()
        c.force_authenticate(user=user)
        return c

    def _users_url(self, customer_id):
        return f"/api/customers/{customer_id}/users/"

    def _user_delete_url(self, customer_id, user_id):
        return f"/api/customers/{customer_id}/users/{user_id}/"

    def _access_list_url(self, customer_id, user_id):
        return f"/api/customers/{customer_id}/users/{user_id}/access/"

    def _access_detail_url(self, customer_id, user_id, building_id):
        return (
            f"/api/customers/{customer_id}/users/{user_id}/access/{building_id}/"
        )


# ---------------------------------------------------------------------------
# 1-2. Existing SA + Provider Admin behaviour is unchanged.
# ---------------------------------------------------------------------------
class ExistingAdminBehaviorTests(_B4Fixture):
    def test_super_admin_can_list_customer_users(self):
        response = self._api(self.super_admin).get(
            self._users_url(self.customer_a.id)
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_provider_admin_can_list_customer_users(self):
        response = self._api(self.admin_a).get(
            self._users_url(self.customer_a.id)
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_provider_admin_can_patch_lower_user_access_role(self):
        response = self._api(self.admin_a).patch(
            self._access_detail_url(
                self.customer_a.id, self.cu_target.id, self.b1.id
            ),
            {"access_role": CustomerUserBuildingAccess.AccessRole.CUSTOMER_LOCATION_MANAGER},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)

    def test_super_admin_cannot_grant_cca_per_building_anymore(self):
        # Single-path CCA (SoT A.1): CCA is a company-wide membership
        # flag, never a per-building access_role. Even SA's per-building
        # grant is rejected with 400 + `cca_is_company_wide`.
        response = self._api(self.super_admin).patch(
            self._access_detail_url(
                self.customer_a.id, self.cu_target.id, self.b1.id
            ),
            {"access_role": CustomerUserBuildingAccess.AccessRole.CUSTOMER_COMPANY_ADMIN},
            format="json",
        )
        self.assertEqual(
            response.status_code, status.HTTP_400_BAD_REQUEST, response.data
        )
        self.assertEqual(response.data.get("code"), "cca_is_company_wide")


# ---------------------------------------------------------------------------
# 3-4. CCA with customer.users.manage can manage lower users.
# ---------------------------------------------------------------------------
class CCAManagesLowerUsersTests(_B4Fixture):
    def test_cca_can_list_users_in_own_customer(self):
        response = self._api(self.cca).get(self._users_url(self.customer_a.id))
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_cca_can_list_lower_user_access_rows(self):
        response = self._api(self.cca).get(
            self._access_list_url(self.customer_a.id, self.cu_target.id)
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_cca_can_link_spare_customer_user_to_own_customer(self):
        response = self._api(self.cca).post(
            self._users_url(self.customer_a.id),
            {"user_id": self.spare_cu.id},
            format="json",
        )
        self.assertEqual(
            response.status_code, status.HTTP_201_CREATED, response.data
        )

    def test_cca_can_grant_b2_access_to_cu_target(self):
        response = self._api(self.cca).post(
            self._access_list_url(self.customer_a.id, self.cu_target.id),
            {"building_id": self.b2.id},
            format="json",
        )
        self.assertEqual(
            response.status_code, status.HTTP_201_CREATED, response.data
        )

    def test_cca_can_patch_lower_user_access_role_clm(self):
        # Promote CU target to CLM (still below CCA). H-7 only blocks CCA.
        response = self._api(self.cca).patch(
            self._access_detail_url(
                self.customer_a.id, self.cu_target.id, self.b1.id
            ),
            {"access_role": CustomerUserBuildingAccess.AccessRole.CUSTOMER_LOCATION_MANAGER},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)

    def test_cca_can_patch_clm_target_back_to_customer_user(self):
        response = self._api(self.cca).patch(
            self._access_detail_url(
                self.customer_a.id, self.clm_target.id, self.b1.id
            ),
            {"access_role": CustomerUserBuildingAccess.AccessRole.CUSTOMER_USER},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)

    def test_cca_can_delete_lower_user_access(self):
        response = self._api(self.cca).delete(
            self._access_detail_url(
                self.customer_a.id, self.cu_target.id, self.b1.id
            )
        )
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)

    def test_cca_can_delete_lower_user_membership(self):
        response = self._api(self.cca).delete(
            self._user_delete_url(self.customer_a.id, self.cu_target.id)
        )
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)


# ---------------------------------------------------------------------------
# 5. CCA without customer.users.manage cannot manage.
# ---------------------------------------------------------------------------
class CCAWithoutManageKeyTests(_B4Fixture):
    def setUp(self):
        super().setUp()
        # Revoke `customer.users.manage` on the CCA actor via the
        # explicit `permission_overrides` JSON. This simulates an
        # admin restricting one CCA's user-management capability.
        for access in CustomerUserBuildingAccess.objects.filter(
            membership__user=self.cca
        ):
            access.permission_overrides = {"customer.users.manage": False}
            access.save(update_fields=["permission_overrides"])

    def test_revoked_cca_cannot_list_users(self):
        response = self._api(self.cca).get(self._users_url(self.customer_a.id))
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_revoked_cca_cannot_grant_access(self):
        response = self._api(self.cca).post(
            self._access_list_url(self.customer_a.id, self.cu_target.id),
            {"building_id": self.b2.id},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)


# ---------------------------------------------------------------------------
# 6-9. CCA cannot create / grant / edit / touch another CCA.
# ---------------------------------------------------------------------------
class CCACannotTouchCCATests(_B4Fixture):
    def test_cca_cannot_grant_cca_access_role_on_lower_user(self):
        # H-7 serializer guard re-pinned: non-SA cannot set access_role=CCA.
        response = self._api(self.cca).patch(
            self._access_detail_url(
                self.customer_a.id, self.cu_target.id, self.b1.id
            ),
            {"access_role": CustomerUserBuildingAccess.AccessRole.CUSTOMER_COMPANY_ADMIN},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_cca_cannot_patch_other_ccas_access_row(self):
        response = self._api(self.cca).patch(
            self._access_detail_url(
                self.customer_a.id, self.cca_target.id, self.b1.id
            ),
            {"access_role": CustomerUserBuildingAccess.AccessRole.CUSTOMER_USER},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(response.data.get("code"), "cca_cannot_manage_cca")

    def test_cca_cannot_delete_other_ccas_access_row(self):
        response = self._api(self.cca).delete(
            self._access_detail_url(
                self.customer_a.id, self.cca_target.id, self.b1.id
            )
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(response.data.get("code"), "cca_cannot_manage_cca")

    def test_cca_cannot_delete_other_ccas_membership(self):
        response = self._api(self.cca).delete(
            self._user_delete_url(self.customer_a.id, self.cca_target.id)
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(response.data.get("code"), "cca_cannot_manage_cca")

    def test_cca_cannot_grant_new_building_access_on_cca_target(self):
        response = self._api(self.cca).post(
            self._access_list_url(self.customer_a.id, self.cca_target.id),
            {"building_id": self.b2.id},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(response.data.get("code"), "cca_cannot_manage_cca")


# ---------------------------------------------------------------------------
# 10. CCA cannot manage user from another customer company.
# ---------------------------------------------------------------------------
class CCACrossCustomerTests(_B4Fixture):
    def test_cca_cannot_list_other_customers_users(self):
        response = self._api(self.cca).get(self._users_url(self.customer_b.id))
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_cca_cannot_link_user_under_other_customer(self):
        response = self._api(self.cca).post(
            self._users_url(self.customer_b.id),
            {"user_id": self.spare_cu.id},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_cca_cannot_patch_access_in_other_customer(self):
        response = self._api(self.cca).patch(
            self._access_detail_url(
                self.customer_b.id, self.cu_b.id, self.b3_other.id
            ),
            {"access_role": CustomerUserBuildingAccess.AccessRole.CUSTOMER_LOCATION_MANAGER},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_cca_cannot_delete_access_in_other_customer(self):
        response = self._api(self.cca).delete(
            self._access_detail_url(
                self.customer_b.id, self.cu_b.id, self.b3_other.id
            )
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)


# ---------------------------------------------------------------------------
# 11. CCA cannot grant access to a building not linked to the customer.
# ---------------------------------------------------------------------------
class CCABuildingLinkTests(_B4Fixture):
    def test_cca_cannot_grant_access_to_unlinked_building(self):
        # b3_other belongs to company B and is not linked to customer A.
        response = self._api(self.cca).post(
            self._access_list_url(self.customer_a.id, self.cu_target.id),
            {"building_id": self.b3_other.id},
            format="json",
        )
        # Either the building-not-linked guard fires (400) or the
        # per-building manage check fires (403). Both refusals are
        # acceptable; we assert "not created".
        self.assertGreaterEqual(response.status_code, 400)
        self.assertNotEqual(response.status_code, 201)


# ---------------------------------------------------------------------------
# 12. CCA whose manage permission is building-scoped cannot exceed it.
# ---------------------------------------------------------------------------
class CCAPerBuildingScopeTests(_B4Fixture):
    def test_cca_with_manage_only_at_b1_cannot_grant_at_b2(self):
        response = self._api(self.cca_limited_b1).post(
            self._access_list_url(self.customer_a.id, self.cu_target.id),
            {"building_id": self.b2.id},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(response.data.get("code"), "cca_lacks_building_manage")

    def test_cca_with_manage_only_at_b1_can_grant_at_b1(self):
        # cu_target already has B1 access; grant returns 200 (existing
        # row reused via get_or_create) — which is still success.
        response = self._api(self.cca_limited_b1).post(
            self._access_list_url(self.customer_a.id, self.cu_target.id),
            {"building_id": self.b1.id},
            format="json",
        )
        self.assertIn(
            response.status_code, (status.HTTP_200_OK, status.HTTP_201_CREATED)
        )


# ---------------------------------------------------------------------------
# 13-16. Other roles cannot manage customer users.
# ---------------------------------------------------------------------------
class OtherRolesBlockedTests(_B4Fixture):
    def test_clm_cannot_manage_users(self):
        # Make a CLM actor and confirm 403.
        clm = _mk("clm-actor-b4@example.com", UserRole.CUSTOMER_USER)
        mem = CustomerUserMembership.objects.create(
            customer=self.customer_a, user=clm
        )
        CustomerUserBuildingAccess.objects.create(
            membership=mem,
            building=self.b1,
            access_role=(
                CustomerUserBuildingAccess.AccessRole.CUSTOMER_LOCATION_MANAGER
            ),
        )
        response = self._api(clm).get(self._users_url(self.customer_a.id))
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_plain_customer_user_cannot_manage(self):
        response = self._api(self.cu_target).get(
            self._users_url(self.customer_a.id)
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_staff_cannot_manage_customer_users(self):
        response = self._api(self.staff_a).get(
            self._users_url(self.customer_a.id)
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_building_manager_cannot_manage_customer_users(self):
        response = self._api(self.bm_a).get(
            self._users_url(self.customer_a.id)
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)


# ---------------------------------------------------------------------------
# 17. URL-smuggling regression — CCA actor variants.
# ---------------------------------------------------------------------------
class CCAURLSmugglingTests(_B4Fixture):
    def test_cca_cannot_patch_membership_smuggled_via_other_customer_url(self):
        # CCA on customer A tries to PATCH a CUBA row that BELONGS to
        # customer B by URL-typing customer A's id but a foreign
        # user_id + building_id. The view's nested lookup filters by
        # (customer, user, building) and 404s.
        response = self._api(self.cca).patch(
            self._access_detail_url(
                self.customer_a.id, self.cu_b.id, self.b3_other.id
            ),
            {"access_role": CustomerUserBuildingAccess.AccessRole.CUSTOMER_LOCATION_MANAGER},
            format="json",
        )
        self.assertIn(
            response.status_code,
            (status.HTTP_403_FORBIDDEN, status.HTTP_404_NOT_FOUND),
        )

    def test_cca_cannot_assign_other_companys_building(self):
        # Same as test in CCABuildingLinkTests; included here under
        # the URL-smuggling matrix for completeness.
        response = self._api(self.cca).post(
            self._access_list_url(self.customer_a.id, self.cu_target.id),
            {"building_id": self.b3_other.id},
            format="json",
        )
        self.assertGreaterEqual(response.status_code, 400)
        self.assertNotEqual(response.status_code, 201)

    def test_cca_cannot_grant_cca_via_payload_manipulation(self):
        # Even when CCA hits PATCH with a hand-crafted payload trying
        # to set access_role=CCA, the H-7 validate_access_role guard
        # rejects with 400. (CCAs are not SUPER_ADMIN.)
        response = self._api(self.cca).patch(
            self._access_detail_url(
                self.customer_a.id, self.clm_target.id, self.b1.id
            ),
            {"access_role": CustomerUserBuildingAccess.AccessRole.CUSTOMER_COMPANY_ADMIN},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)


# ---------------------------------------------------------------------------
# 18. B3 effective-permissions endpoint reflects B4.
# ---------------------------------------------------------------------------
class B3EffectivePermissionsReflectsB4Tests(_B4Fixture):
    def _fetch_actions(self, caller, target, customer):
        response = self._api(caller).get(
            f"/api/users/{target.id}/effective-permissions/"
            f"?customer_id={customer.id}"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        return response.data["effective_actions"]

    def test_cca_target_has_can_manage_customer_users_true(self):
        actions = self._fetch_actions(self.super_admin, self.cca, self.customer_a)
        self.assertTrue(actions["can_manage_customer_users"])

    def test_cca_target_does_not_have_can_manage_customer_permissions(self):
        # B5 (SA toggle / Provider Admin override) is future; today
        # CCA does not get can_manage_customer_permissions. The
        # endpoint must NOT advertise it as True.
        actions = self._fetch_actions(self.super_admin, self.cca, self.customer_a)
        self.assertFalse(actions["can_manage_customer_permissions"])

    def test_plain_customer_user_has_can_manage_customer_users_false(self):
        actions = self._fetch_actions(self.super_admin, self.cu_target, self.customer_a)
        self.assertFalse(actions["can_manage_customer_users"])

    def test_clm_target_has_can_manage_customer_users_false(self):
        # CLM default does NOT include customer.users.manage.
        actions = self._fetch_actions(self.super_admin, self.clm_target, self.customer_a)
        self.assertFalse(actions["can_manage_customer_users"])

    def test_cca_with_revoked_manage_override_has_false(self):
        # Revoke manage via override on every access row of the CCA.
        for access in CustomerUserBuildingAccess.objects.filter(
            membership__user=self.cca
        ):
            access.permission_overrides = {"customer.users.manage": False}
            access.save(update_fields=["permission_overrides"])
        actions = self._fetch_actions(self.super_admin, self.cca, self.customer_a)
        self.assertFalse(actions["can_manage_customer_users"])
