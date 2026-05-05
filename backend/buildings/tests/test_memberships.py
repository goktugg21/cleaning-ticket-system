from django.contrib.auth import get_user_model
from rest_framework import status
from rest_framework.test import APITestCase

from accounts.models import UserRole
from buildings.models import BuildingManagerAssignment
from test_utils import TenantFixtureMixin


class BuildingManagerMembershipTests(TenantFixtureMixin, APITestCase):
    def list_url(self, building_id):
        return f"/api/buildings/{building_id}/managers/"

    def detail_url(self, building_id, user_id):
        return f"/api/buildings/{building_id}/managers/{user_id}/"

    def test_list_works_for_super_admin(self):
        self.authenticate(self.super_admin)
        response = self.client.get(self.list_url(self.building.id))
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_list_works_for_company_admin_in_scope(self):
        self.authenticate(self.company_admin)
        response = self.client.get(self.list_url(self.building.id))
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_list_403_for_company_admin_out_of_scope(self):
        self.authenticate(self.company_admin)
        response = self.client.get(self.list_url(self.other_building.id))
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_list_403_for_building_manager(self):
        self.authenticate(self.manager)
        response = self.client.get(self.list_url(self.building.id))
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_list_403_for_customer_user(self):
        self.authenticate(self.customer_user)
        response = self.client.get(self.list_url(self.building.id))
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_create_requires_building_manager_role_on_target(self):
        self.authenticate(self.super_admin)
        response = self.client.post(
            self.list_url(self.building.id),
            {"user_id": self.customer_user.id},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_create_works_with_correct_role(self):
        new_bm = get_user_model().objects.create_user(
            email="brand-new-bm@example.com",
            password=self.password,
            role=UserRole.BUILDING_MANAGER,
        )
        self.authenticate(self.super_admin)
        response = self.client.post(
            self.list_url(self.building.id),
            {"user_id": new_bm.id},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    def test_create_is_idempotent(self):
        self.authenticate(self.super_admin)
        response = self.client.post(
            self.list_url(self.building.id),
            {"user_id": self.manager.id},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_delete_works(self):
        self.authenticate(self.super_admin)
        response = self.client.delete(self.detail_url(self.building.id, self.manager.id))
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(
            BuildingManagerAssignment.objects.filter(
                user=self.manager, building=self.building
            ).exists()
        )

    def test_delete_idempotency_404_on_second_attempt(self):
        self.authenticate(self.super_admin)
        first = self.client.delete(self.detail_url(self.building.id, self.manager.id))
        self.assertEqual(first.status_code, status.HTTP_204_NO_CONTENT)
        second = self.client.delete(self.detail_url(self.building.id, self.manager.id))
        self.assertEqual(second.status_code, status.HTTP_404_NOT_FOUND)

    def test_delete_out_of_scope_returns_403(self):
        self.authenticate(self.company_admin)
        response = self.client.delete(
            self.detail_url(self.other_building.id, self.other_manager.id)
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_list_does_not_paginate_returns_all_in_one_response(self):
        for i in range(5):
            extra = get_user_model().objects.create_user(
                email=f"extra-bm-{i}@example.com",
                password=self.password,
                role=UserRole.BUILDING_MANAGER,
            )
            BuildingManagerAssignment.objects.create(user=extra, building=self.building)
        self.authenticate(self.super_admin)
        response = self.client.get(self.list_url(self.building.id))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["count"], 6)
        self.assertIsNone(response.data["next"])
        self.assertIsNone(response.data["previous"])
        self.assertEqual(len(response.data["results"]), 6)
