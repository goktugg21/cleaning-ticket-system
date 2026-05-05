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
