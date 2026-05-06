from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from test_utils import TenantFixtureMixin


class MePatchTests(TenantFixtureMixin, APITestCase):
    def test_authenticated_user_can_update_full_name(self):
        self.authenticate(self.customer_user)

        response = self.client.patch(
            reverse("auth_me"),
            {"full_name": "New Name"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["full_name"], "New Name")

        self.customer_user.refresh_from_db()
        self.assertEqual(self.customer_user.full_name, "New Name")

    def test_authenticated_user_can_update_language(self):
        self.assertEqual(self.customer_user.language, "nl")
        self.authenticate(self.customer_user)

        response = self.client.patch(
            reverse("auth_me"),
            {"language": "en"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["language"], "en")

        self.customer_user.refresh_from_db()
        self.assertEqual(self.customer_user.language, "en")

    def test_empty_full_name_returns_400(self):
        self.authenticate(self.customer_user)

        response = self.client.patch(
            reverse("auth_me"),
            {"full_name": "   "},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("full_name", response.data)

    def test_invalid_language_returns_400(self):
        self.authenticate(self.customer_user)

        response = self.client.patch(
            reverse("auth_me"),
            {"language": "fr"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("language", response.data)

    def test_unauthenticated_returns_401(self):
        response = self.client.patch(
            reverse("auth_me"),
            {"full_name": "Anything"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_read_only_fields_are_silently_ignored(self):
        original_email = self.customer_user.email
        original_role = self.customer_user.role
        original_is_active = self.customer_user.is_active
        self.authenticate(self.customer_user)

        response = self.client.patch(
            reverse("auth_me"),
            {
                "full_name": "Updated Name",
                "email": "hijack@example.com",
                "role": "SUPER_ADMIN",
                "is_active": False,
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.customer_user.refresh_from_db()
        self.assertEqual(self.customer_user.email, original_email)
        self.assertEqual(self.customer_user.role, original_role)
        self.assertEqual(self.customer_user.is_active, original_is_active)
        self.assertEqual(self.customer_user.full_name, "Updated Name")

    def test_response_body_includes_updated_values(self):
        self.authenticate(self.customer_user)

        response = self.client.patch(
            reverse("auth_me"),
            {"full_name": "Refreshed", "language": "en"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["full_name"], "Refreshed")
        self.assertEqual(response.data["language"], "en")
        # Same shape as GET — confirm the scoped id lists are present.
        self.assertIn("company_ids", response.data)
        self.assertIn("building_ids", response.data)
        self.assertIn("customer_ids", response.data)


class PasswordChangeTests(TenantFixtureMixin, APITestCase):
    def test_correct_current_and_valid_new_password_succeeds(self):
        self.authenticate(self.customer_user)
        new_password = "FreshSecret789!"

        response = self.client.post(
            reverse("auth_password_change"),
            {
                "current_password": self.password,
                "new_password": new_password,
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # Re-authenticate using the new password and confirm the old one fails.
        self.client.force_authenticate(user=None)
        login_with_new = self.client.post(
            reverse("token_obtain_pair"),
            {"email": self.customer_user.email, "password": new_password},
            format="json",
        )
        self.assertEqual(login_with_new.status_code, status.HTTP_200_OK)

        login_with_old = self.client.post(
            reverse("token_obtain_pair"),
            {"email": self.customer_user.email, "password": self.password},
            format="json",
        )
        self.assertEqual(login_with_old.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_wrong_current_password_returns_400(self):
        self.authenticate(self.customer_user)

        response = self.client.post(
            reverse("auth_password_change"),
            {
                "current_password": "not-my-password",
                "new_password": "AnotherStrongOne456!",
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("current_password", response.data)

        # Password must not have changed.
        self.customer_user.refresh_from_db()
        self.assertTrue(self.customer_user.check_password(self.password))

    def test_weak_new_password_returns_400(self):
        self.authenticate(self.customer_user)

        response = self.client.post(
            reverse("auth_password_change"),
            {
                "current_password": self.password,
                "new_password": "abc",
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("new_password", response.data)

        # Password must not have changed.
        self.customer_user.refresh_from_db()
        self.assertTrue(self.customer_user.check_password(self.password))

    def test_unauthenticated_returns_401(self):
        response = self.client.post(
            reverse("auth_password_change"),
            {
                "current_password": "anything",
                "new_password": "AnotherStrongOne456!",
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_missing_fields_return_400(self):
        self.authenticate(self.customer_user)

        missing_new = self.client.post(
            reverse("auth_password_change"),
            {"current_password": self.password},
            format="json",
        )
        self.assertEqual(missing_new.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("new_password", missing_new.data)

        missing_current = self.client.post(
            reverse("auth_password_change"),
            {"new_password": "AnotherStrongOne456!"},
            format="json",
        )
        self.assertEqual(missing_current.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("current_password", missing_current.data)
