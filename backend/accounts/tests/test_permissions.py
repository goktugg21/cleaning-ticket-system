from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from test_utils import TenantFixtureMixin


class AccountPermissionTests(TenantFixtureMixin, APITestCase):
    def test_me_rejects_inactive_user(self):
        self.customer_user.is_active = False
        self.customer_user.save(update_fields=["is_active"])
        self.authenticate(self.customer_user)

        response = self.client.get(reverse("auth_me"))

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_me_rejects_soft_deleted_user(self):
        self.customer_user.soft_delete(deleted_by=self.super_admin)
        self.authenticate(self.customer_user)

        response = self.client.get(reverse("auth_me"))

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
