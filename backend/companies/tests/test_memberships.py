from django.contrib.auth import get_user_model
from rest_framework import status
from rest_framework.test import APITestCase

from accounts.models import UserRole
from companies.models import CompanyUserMembership
from test_utils import TenantFixtureMixin


class CompanyAdminMembershipTests(TenantFixtureMixin, APITestCase):
    def list_url(self, company_id):
        return f"/api/companies/{company_id}/admins/"

    def detail_url(self, company_id, user_id):
        return f"/api/companies/{company_id}/admins/{user_id}/"

    # ---- List -------------------------------------------------------------

    def test_list_works_for_super_admin(self):
        self.authenticate(self.super_admin)
        response = self.client.get(self.list_url(self.company.id))
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_list_works_for_company_admin_in_scope(self):
        self.authenticate(self.company_admin)
        response = self.client.get(self.list_url(self.company.id))
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_list_403_for_company_admin_out_of_scope(self):
        self.authenticate(self.company_admin)
        response = self.client.get(self.list_url(self.other_company.id))
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_list_403_for_building_manager(self):
        self.authenticate(self.manager)
        response = self.client.get(self.list_url(self.company.id))
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_list_403_for_customer_user(self):
        self.authenticate(self.customer_user)
        response = self.client.get(self.list_url(self.company.id))
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    # ---- Create -----------------------------------------------------------

    def test_create_requires_company_admin_role_on_target(self):
        self.authenticate(self.super_admin)
        response = self.client.post(
            self.list_url(self.company.id),
            {"user_id": self.customer_user.id},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_create_works_with_correct_role(self):
        new_ca = get_user_model().objects.create_user(
            email="brand-new-ca@example.com",
            password=self.password,
            role=UserRole.COMPANY_ADMIN,
        )
        self.authenticate(self.super_admin)
        response = self.client.post(
            self.list_url(self.company.id),
            {"user_id": new_ca.id},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertTrue(
            CompanyUserMembership.objects.filter(user=new_ca, company=self.company).exists()
        )

    def test_create_is_idempotent(self):
        self.authenticate(self.super_admin)
        # company_admin is already in self.company.
        response = self.client.post(
            self.list_url(self.company.id),
            {"user_id": self.company_admin.id},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    # ---- Delete -----------------------------------------------------------

    def test_delete_works(self):
        self.authenticate(self.super_admin)
        response = self.client.delete(
            self.detail_url(self.company.id, self.company_admin.id)
        )
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(
            CompanyUserMembership.objects.filter(
                user=self.company_admin, company=self.company
            ).exists()
        )

    def test_delete_idempotency_404_on_second_attempt(self):
        self.authenticate(self.super_admin)
        first = self.client.delete(self.detail_url(self.company.id, self.company_admin.id))
        self.assertEqual(first.status_code, status.HTTP_204_NO_CONTENT)
        second = self.client.delete(self.detail_url(self.company.id, self.company_admin.id))
        self.assertEqual(second.status_code, status.HTTP_404_NOT_FOUND)

    def test_delete_out_of_scope_returns_403(self):
        self.authenticate(self.company_admin)
        response = self.client.delete(
            self.detail_url(self.other_company.id, self.other_company_admin.id)
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_list_does_not_paginate_returns_all_in_one_response(self):
        # Baseline fixture seats 1 admin (company_admin) in self.company.
        # Add 5 more so the total exceeds the standard page_size of 25
        # would not be triggered, but still proves the endpoint returns
        # every row in a single response with next/previous null.
        for i in range(5):
            extra = get_user_model().objects.create_user(
                email=f"extra-ca-{i}@example.com",
                password=self.password,
                role=UserRole.COMPANY_ADMIN,
            )
            CompanyUserMembership.objects.create(user=extra, company=self.company)
        self.authenticate(self.super_admin)
        response = self.client.get(self.list_url(self.company.id))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["count"], 6)
        self.assertIsNone(response.data["next"])
        self.assertIsNone(response.data["previous"])
        self.assertEqual(len(response.data["results"]), 6)
