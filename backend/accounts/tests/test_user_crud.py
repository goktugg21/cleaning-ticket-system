from django.contrib.auth import get_user_model
from rest_framework import status
from rest_framework.test import APITestCase

from accounts.models import UserRole
from buildings.models import Building, BuildingManagerAssignment
from companies.models import CompanyUserMembership
from customers.models import Customer, CustomerUserMembership
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
