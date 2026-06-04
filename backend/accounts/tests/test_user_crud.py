from django.contrib.auth import get_user_model
from rest_framework import status
from rest_framework.test import APITestCase

from accounts.models import UserRole
from buildings.models import Building, BuildingManagerAssignment
from companies.models import CompanyUserMembership
from customers.models import (
    Customer,
    CustomerBuildingMembership,
    CustomerUserBuildingAccess,
    CustomerUserMembership,
)
from test_utils import TenantFixtureMixin


class UserCRUDTests(TenantFixtureMixin, APITestCase):
    URL = "/api/users/"

    def detail_url(self, pk):
        return f"/api/users/{pk}/"

    def reactivate_url(self, pk):
        return f"/api/users/{pk}/reactivate/"

    # ---- List + scope -----------------------------------------------------

    def test_super_admin_can_list_all_users(self):
        self.authenticate(self.super_admin)
        response = self.client.get(self.URL)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        emails = {row["email"] for row in response.data.get("results", response.data)}
        self.assertIn(self.company_admin.email, emails)
        self.assertIn(self.other_company_admin.email, emails)

    def test_company_admin_only_sees_users_in_own_company(self):
        self.authenticate(self.company_admin)
        response = self.client.get(self.URL)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        emails = {row["email"] for row in response.data.get("results", response.data)}
        self.assertIn(self.company_admin.email, emails)
        self.assertNotIn(self.other_company_admin.email, emails)
        self.assertNotIn(self.other_manager.email, emails)
        self.assertNotIn(self.other_customer_user.email, emails)

    def test_company_admin_lists_user_with_building_manager_in_their_company(self):
        # self.manager has BuildingManagerAssignment on self.building (company A).
        self.authenticate(self.company_admin)
        response = self.client.get(self.URL)
        emails = {row["email"] for row in response.data.get("results", response.data)}
        self.assertIn(self.manager.email, emails)

    def test_company_admin_lists_user_with_customer_user_in_their_company(self):
        # self.customer_user has CustomerUserMembership on self.customer (company A).
        self.authenticate(self.company_admin)
        response = self.client.get(self.URL)
        emails = {row["email"] for row in response.data.get("results", response.data)}
        self.assertIn(self.customer_user.email, emails)

    def test_building_manager_cannot_list_users(self):
        self.authenticate(self.manager)
        response = self.client.get(self.URL)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_customer_user_cannot_list_users(self):
        self.authenticate(self.customer_user)
        response = self.client.get(self.URL)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    # ---- Filters ----------------------------------------------------------

    def test_role_filter_works(self):
        self.authenticate(self.super_admin)
        response = self.client.get(self.URL, {"role": UserRole.BUILDING_MANAGER})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        roles = {row["role"] for row in response.data.get("results", response.data)}
        self.assertEqual(roles, {UserRole.BUILDING_MANAGER})

    def test_role_filter_multi_value(self):
        self.authenticate(self.super_admin)
        response = self.client.get(
            self.URL,
            {"role": f"{UserRole.BUILDING_MANAGER},{UserRole.CUSTOMER_USER}"},
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        roles = {row["role"] for row in response.data.get("results", response.data)}
        self.assertEqual(roles, {UserRole.BUILDING_MANAGER, UserRole.CUSTOMER_USER})

    # ---- Sprint 2c follow-up — effective, company-scoped ?access_role= ----

    def _set_anchor_role(self, user, role, is_active=True):
        """Set the user's single (anchor) CUBA grant to `role` + active."""
        access = CustomerUserBuildingAccess.objects.get(membership__user=user)
        access.access_role = role
        access.is_active = is_active
        access.save(update_fields=["access_role", "is_active"])
        return access

    def _emails(self, response):
        return {row["email"] for row in response.data.get("results", response.data)}

    def test_access_role_filter_matches_effective_role(self):
        AR = CustomerUserBuildingAccess.AccessRole
        # customer_user (company A) keeps CUSTOMER_USER; other_customer_user
        # (company B) -> CUSTOMER_LOCATION_MANAGER.
        self._set_anchor_role(
            self.other_customer_user, AR.CUSTOMER_LOCATION_MANAGER
        )
        self.authenticate(self.super_admin)

        cu = self.client.get(self.URL, {"access_role": "CUSTOMER_USER"})
        self.assertEqual(cu.status_code, status.HTTP_200_OK)
        self.assertIn(self.customer_user.email, self._emails(cu))
        self.assertNotIn(self.other_customer_user.email, self._emails(cu))
        self.assertNotIn(self.super_admin.email, self._emails(cu))  # provider

        lm = self.client.get(
            self.URL, {"access_role": "CUSTOMER_LOCATION_MANAGER"}
        )
        self.assertIn(self.other_customer_user.email, self._emails(lm))
        self.assertNotIn(self.customer_user.email, self._emails(lm))

    def test_access_role_filter_excludes_lower_when_higher_present(self):
        # A user with BOTH a CCA and an LM grant has EFFECTIVE role CCA, so
        # ?access_role=CCA returns them but ?access_role=LM must NOT.
        AR = CustomerUserBuildingAccess.AccessRole
        membership = CustomerUserMembership.objects.get(
            user=self.customer_user, customer=self.customer
        )
        self._set_anchor_role(self.customer_user, AR.CUSTOMER_LOCATION_MANAGER)
        extra = Building.objects.create(company=self.company, name="Wing CCA")
        CustomerBuildingMembership.objects.create(
            customer=self.customer, building=extra
        )
        CustomerUserBuildingAccess.objects.create(
            membership=membership,
            building=extra,
            access_role=AR.CUSTOMER_COMPANY_ADMIN,
        )
        self.authenticate(self.super_admin)

        cca = self.client.get(
            self.URL, {"access_role": "CUSTOMER_COMPANY_ADMIN"}
        )
        self.assertIn(self.customer_user.email, self._emails(cca))
        lm = self.client.get(
            self.URL, {"access_role": "CUSTOMER_LOCATION_MANAGER"}
        )
        self.assertNotIn(self.customer_user.email, self._emails(lm))

    def test_access_role_filter_cu_excludes_when_higher_present(self):
        # Symmetric to the LM case above: a user with CU + LM grants has
        # EFFECTIVE role LM, so ?access_role=CUSTOMER_USER must NOT return
        # them (guards the CU-branch double-negation), only ?access_role=LM.
        AR = CustomerUserBuildingAccess.AccessRole
        membership = CustomerUserMembership.objects.get(
            user=self.customer_user, customer=self.customer
        )
        # Anchor grant stays CUSTOMER_USER; add an LM grant on a 2nd building.
        extra = Building.objects.create(company=self.company, name="Wing CU+LM")
        CustomerBuildingMembership.objects.create(
            customer=self.customer, building=extra
        )
        CustomerUserBuildingAccess.objects.create(
            membership=membership,
            building=extra,
            access_role=AR.CUSTOMER_LOCATION_MANAGER,
        )
        self.authenticate(self.super_admin)

        cu = self.client.get(self.URL, {"access_role": "CUSTOMER_USER"})
        self.assertNotIn(self.customer_user.email, self._emails(cu))
        lm = self.client.get(
            self.URL, {"access_role": "CUSTOMER_LOCATION_MANAGER"}
        )
        self.assertIn(self.customer_user.email, self._emails(lm))

    def test_access_role_filter_no_duplicate_rows(self):
        # A user with TWO matching grants must appear EXACTLY once (Exists,
        # not a join).
        AR = CustomerUserBuildingAccess.AccessRole
        extra = Building.objects.create(company=self.company, name="Wing Dup")
        CustomerBuildingMembership.objects.create(
            customer=self.customer, building=extra
        )
        membership = CustomerUserMembership.objects.get(
            user=self.customer_user, customer=self.customer
        )
        CustomerUserBuildingAccess.objects.filter(membership=membership).update(
            access_role=AR.CUSTOMER_LOCATION_MANAGER
        )
        CustomerUserBuildingAccess.objects.create(
            membership=membership,
            building=extra,
            access_role=AR.CUSTOMER_LOCATION_MANAGER,
        )
        self.authenticate(self.super_admin)
        response = self.client.get(
            self.URL, {"access_role": "CUSTOMER_LOCATION_MANAGER"}
        )
        rows = response.data.get("results", response.data)
        matching = [row for row in rows if row["id"] == self.customer_user.id]
        self.assertEqual(len(matching), 1)

    def test_access_role_filter_unknown_value_returns_empty(self):
        # Mirror ?role= — NO validation; an unknown value matches zero rows
        # (200, not 400).
        self.authenticate(self.super_admin)
        response = self.client.get(self.URL, {"access_role": "BOGUS"})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data.get("results", response.data)), 0)

    def test_access_role_filter_excludes_inactive_grants(self):
        # customer_user's only grant -> LM but inactive: not matched by LM.
        self._set_anchor_role(
            self.customer_user,
            CustomerUserBuildingAccess.AccessRole.CUSTOMER_LOCATION_MANAGER,
            is_active=False,
        )
        self.authenticate(self.super_admin)
        response = self.client.get(
            self.URL, {"access_role": "CUSTOMER_LOCATION_MANAGER"}
        )
        self.assertNotIn(self.customer_user.email, self._emails(response))

    def test_access_role_filter_company_scoped(self):
        # Codex scenario for the FILTER: customer_user has a CUSTOMER_USER
        # grant in company A and a CUSTOMER_COMPANY_ADMIN grant in company B.
        # A company-A admin filtering by CCA must NOT match them (B grant is
        # out of scope); a super admin must. The A admin DOES match them by
        # their in-company CUSTOMER_USER role.
        AR = CustomerUserBuildingAccess.AccessRole
        cross_customer = Customer.objects.create(
            company=self.other_company,
            building=self.other_building,
            name="Cross Filter B",
            contact_email="cross-filter-b@example.com",
        )
        CustomerBuildingMembership.objects.create(
            customer=cross_customer, building=self.other_building
        )
        m_b = CustomerUserMembership.objects.create(
            user=self.customer_user, customer=cross_customer
        )
        CustomerUserBuildingAccess.objects.create(
            membership=m_b,
            building=self.other_building,
            access_role=AR.CUSTOMER_COMPANY_ADMIN,
        )

        self.authenticate(self.super_admin)
        sup = self.client.get(
            self.URL, {"access_role": "CUSTOMER_COMPANY_ADMIN"}
        )
        self.assertIn(self.customer_user.email, self._emails(sup))

        self.authenticate(self.company_admin)
        ca_cca = self.client.get(
            self.URL, {"access_role": "CUSTOMER_COMPANY_ADMIN"}
        )
        self.assertNotIn(self.customer_user.email, self._emails(ca_cca))
        ca_cu = self.client.get(self.URL, {"access_role": "CUSTOMER_USER"})
        self.assertIn(self.customer_user.email, self._emails(ca_cu))

    def test_is_active_false_returns_only_deactivated(self):
        self.customer_user.soft_delete(deleted_by=self.super_admin)
        self.authenticate(self.super_admin)
        response = self.client.get(self.URL, {"is_active": "false"})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        emails = {row["email"] for row in response.data.get("results", response.data)}
        self.assertEqual(emails, {self.customer_user.email})

    # ---- Role mutability --------------------------------------------------

    def test_super_admin_can_change_any_role(self):
        self.authenticate(self.super_admin)
        response = self.client.patch(
            self.detail_url(self.customer_user.id),
            {"role": UserRole.BUILDING_MANAGER},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.customer_user.refresh_from_db()
        self.assertEqual(self.customer_user.role, UserRole.BUILDING_MANAGER)

    def test_company_admin_can_change_role_within_company_within_allowed_set(self):
        # CUSTOMER_USER -> BUILDING_MANAGER is allowed for COMPANY_ADMIN.
        self.authenticate(self.company_admin)
        response = self.client.patch(
            self.detail_url(self.customer_user.id),
            {"role": UserRole.BUILDING_MANAGER},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_company_admin_cannot_promote_to_super_admin(self):
        self.authenticate(self.company_admin)
        response = self.client.patch(
            self.detail_url(self.customer_user.id),
            {"role": UserRole.SUPER_ADMIN},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_company_admin_cannot_promote_to_company_admin(self):
        self.authenticate(self.company_admin)
        response = self.client.patch(
            self.detail_url(self.customer_user.id),
            {"role": UserRole.COMPANY_ADMIN},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_company_admin_cannot_demote_company_admin(self):
        # Make a second company_admin in the same company so the actor has
        # CanManageUser.has_object_permission == False and gets 403; if it
        # somehow reached the serializer, validate_role would also reject.
        from django.contrib.auth import get_user_model

        target = get_user_model().objects.create_user(
            email="another-ca@example.com",
            password=self.password,
            role=UserRole.COMPANY_ADMIN,
        )
        CompanyUserMembership.objects.create(user=target, company=self.company)

        self.authenticate(self.company_admin)
        response = self.client.patch(
            self.detail_url(target.id),
            {"role": UserRole.BUILDING_MANAGER},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_user_cannot_change_own_role(self):
        # company_admin on self
        self.authenticate(self.company_admin)
        response = self.client.patch(
            self.detail_url(self.company_admin.id),
            {"role": UserRole.BUILDING_MANAGER},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_super_admin_can_change_own_role(self):
        # Self-target rule applies regardless of role: super admin cannot
        # change their own role.
        self.authenticate(self.super_admin)
        response = self.client.patch(
            self.detail_url(self.super_admin.id),
            {"role": UserRole.COMPANY_ADMIN},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    # ---- Soft-delete + reactivate ----------------------------------------

    def test_delete_user_soft_deletes(self):
        self.authenticate(self.super_admin)
        response = self.client.delete(self.detail_url(self.customer_user.id))
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.customer_user.refresh_from_db()
        self.assertFalse(self.customer_user.is_active)
        self.assertIsNotNone(self.customer_user.deleted_at)
        self.assertEqual(self.customer_user.deleted_by, self.super_admin)

    def test_super_admin_can_reactivate_user(self):
        self.customer_user.soft_delete(deleted_by=self.super_admin)
        self.authenticate(self.super_admin)
        response = self.client.post(self.reactivate_url(self.customer_user.id))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.customer_user.refresh_from_db()
        self.assertTrue(self.customer_user.is_active)
        self.assertIsNone(self.customer_user.deleted_at)

    # ---- PATCH/GET response shape parity ---------------------------------

    def test_patch_response_shape_matches_get(self):
        # Regression for Sprint 2.1: UserUpdateSerializer used to return
        # only the four writable fields, leaving the frontend with no
        # id/email/*_ids in the PATCH response. The frontend masked this
        # with `?? []` defensive guards. UserUpdateSerializer.to_representation
        # now delegates to UserDetailSerializer so PATCH and GET emit the
        # same keys, and the array membership fields are always present.
        self.authenticate(self.super_admin)
        get_response = self.client.get(self.detail_url(self.customer_user.id))
        self.assertEqual(get_response.status_code, status.HTTP_200_OK)
        get_keys = set(get_response.data.keys())

        patch_response = self.client.patch(
            self.detail_url(self.customer_user.id),
            {"full_name": "Customer Renamed"},
            format="json",
        )
        self.assertEqual(patch_response.status_code, status.HTTP_200_OK)
        patch_keys = set(patch_response.data.keys())

        self.assertEqual(
            get_keys,
            patch_keys,
            f"PATCH response missing keys vs GET: {get_keys - patch_keys}; "
            f"extra keys: {patch_keys - get_keys}",
        )
        for arr_field in ("company_ids", "building_ids", "customer_ids"):
            self.assertIn(arr_field, patch_response.data)
            self.assertIsInstance(
                patch_response.data[arr_field],
                list,
                f"{arr_field} must be a list in the PATCH response",
            )

    def test_company_admin_cannot_reactivate_user(self):
        self.customer_user.soft_delete(deleted_by=self.super_admin)
        self.authenticate(self.company_admin)
        response = self.client.post(self.reactivate_url(self.customer_user.id))
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_post_to_users_returns_405(self):
        self.authenticate(self.super_admin)
        response = self.client.post(
            self.URL,
            {"email": "no@example.com", "role": UserRole.CUSTOMER_USER},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)

    # ---- Search filter ----------------------------------------------------

    def test_search_filter_matches_email_substring(self):
        get_user_model().objects.create_user(
            email="alice@findme.example",
            password=self.password,
            role=UserRole.CUSTOMER_USER,
            full_name="Alice",
        )
        self.authenticate(self.super_admin)
        response = self.client.get(self.URL, {"search": "findme"})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        emails = {row["email"] for row in response.data.get("results", response.data)}
        self.assertEqual(emails, {"alice@findme.example"})

    def test_search_filter_matches_full_name_substring(self):
        get_user_model().objects.create_user(
            email="bob@example.com",
            password=self.password,
            role=UserRole.CUSTOMER_USER,
            full_name="Bob Searchable",
        )
        self.authenticate(self.super_admin)
        response = self.client.get(self.URL, {"search": "Searchable"})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        emails = {row["email"] for row in response.data.get("results", response.data)}
        self.assertEqual(emails, {"bob@example.com"})

    def test_search_filter_combined_with_role_and_is_active(self):
        # Same search token "needle", different roles. The role filter should
        # narrow first, the search filter should further restrict within that
        # set.
        get_user_model().objects.create_user(
            email="needle-manager@example.com",
            password=self.password,
            role=UserRole.BUILDING_MANAGER,
            full_name="Needle Manager",
        )
        get_user_model().objects.create_user(
            email="needle-customer@example.com",
            password=self.password,
            role=UserRole.CUSTOMER_USER,
            full_name="Needle Customer",
        )
        self.authenticate(self.super_admin)
        response = self.client.get(
            self.URL,
            {"search": "needle", "role": UserRole.BUILDING_MANAGER},
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        emails = {row["email"] for row in response.data.get("results", response.data)}
        self.assertEqual(emails, {"needle-manager@example.com"})

    # ---- Retrieve of soft-deleted users (CHANGE-17.6) --------------------

    def test_super_admin_can_retrieve_inactive_user(self):
        # Without the retrieve-action carve-out, the queryset filter
        # `is_active=True` would 404 the soft-deleted user even for the super
        # admin, leaving the Reactivate button on /admin/users/:id unreachable.
        self.customer_user.soft_delete(deleted_by=self.super_admin)
        self.authenticate(self.super_admin)
        response = self.client.get(self.detail_url(self.customer_user.id))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["id"], self.customer_user.id)
        self.assertFalse(response.data["is_active"])

    def test_company_admin_cannot_retrieve_inactive_user(self):
        # Boundary: only SUPER_ADMIN gets the carve-out. A company admin in the
        # same scope must still get 404 for a soft-deleted user.
        self.customer_user.soft_delete(deleted_by=self.super_admin)
        self.authenticate(self.company_admin)
        response = self.client.get(self.detail_url(self.customer_user.id))
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
