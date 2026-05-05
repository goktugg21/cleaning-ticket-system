from django.contrib.auth import get_user_model
from django.contrib.auth.tokens import PasswordResetTokenGenerator
from django.core import mail
from django.test import override_settings
from django.urls import reverse
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode
from rest_framework import status
from rest_framework.test import APITestCase

from accounts.models import LoginLog, UserRole
from notifications.models import NotificationEventType, NotificationLog
from test_utils import TenantFixtureMixin


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
class AuthTests(TenantFixtureMixin, APITestCase):
    def test_login_active_user_succeeds(self):
        response = self.client.post(
            reverse("token_obtain_pair"),
            {"email": self.customer_user.email, "password": self.password},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("access", response.data)
        self.assertIn("refresh", response.data)

    def test_login_inactive_user_fails(self):
        self.customer_user.is_active = False
        self.customer_user.save(update_fields=["is_active"])

        response = self.client.post(
            reverse("token_obtain_pair"),
            {"email": self.customer_user.email, "password": self.password},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_login_soft_deleted_user_fails(self):
        self.customer_user.soft_delete(deleted_by=self.super_admin)

        response = self.client.post(
            reverse("token_obtain_pair"),
            {"email": self.customer_user.email, "password": self.password},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_refresh_rotates_and_old_refresh_cannot_be_reused(self):
        login = self.client.post(
            reverse("token_obtain_pair"),
            {"email": self.customer_user.email, "password": self.password},
            format="json",
        )
        old_refresh = login.data["refresh"]

        first_refresh = self.client.post(
            reverse("token_refresh"),
            {"refresh": old_refresh},
            format="json",
        )

        self.assertEqual(first_refresh.status_code, status.HTTP_200_OK)
        self.assertIn("refresh", first_refresh.data)
        self.assertNotEqual(old_refresh, first_refresh.data["refresh"])

        second_refresh = self.client.post(
            reverse("token_refresh"),
            {"refresh": old_refresh},
            format="json",
        )

        self.assertEqual(second_refresh.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_logout_blacklists_refresh_token(self):
        login = self.client.post(
            reverse("token_obtain_pair"),
            {"email": self.customer_user.email, "password": self.password},
            format="json",
        )
        refresh = login.data["refresh"]

        self.authenticate(self.customer_user)
        logout = self.client.post(reverse("auth_logout"), {"refresh": refresh}, format="json")
        self.assertEqual(logout.status_code, status.HTTP_204_NO_CONTENT)

        reused = self.client.post(reverse("token_refresh"), {"refresh": refresh}, format="json")
        self.assertEqual(reused.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_login_success_and_failure_write_login_log(self):
        self.client.post(
            reverse("token_obtain_pair"),
            {"email": self.customer_user.email, "password": self.password},
            format="json",
        )
        self.client.post(
            reverse("token_obtain_pair"),
            {"email": self.customer_user.email, "password": "wrong"},
            format="json",
        )

        self.assertTrue(LoginLog.objects.filter(email=self.customer_user.email, success=True).exists())
        self.assertTrue(LoginLog.objects.filter(email=self.customer_user.email, success=False).exists())

    def test_repeated_failed_login_is_locked(self):
        for _ in range(5):
            self.client.post(
                reverse("token_obtain_pair"),
                {"email": self.customer_user.email, "password": "wrong"},
                format="json",
            )

        response = self.client.post(
            reverse("token_obtain_pair"),
            {"email": self.customer_user.email, "password": self.password},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertEqual(response.data["code"], "too_many_failed_attempts")

    def test_password_reset_request_sends_email_for_existing_active_user(self):
        response = self.client.post(
            reverse("password_reset"),
            {"email": self.customer_user.email},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(mail.outbox), 1)
        self.assertTrue(
            NotificationLog.objects.filter(
                recipient_user=self.customer_user,
                event_type=NotificationEventType.PASSWORD_RESET,
                status="SENT",
            ).exists()
        )

    def test_password_reset_request_does_not_disclose_unknown_email(self):
        response = self.client.post(
            reverse("password_reset"),
            {"email": "missing@example.com"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(mail.outbox), 0)

    def test_inactive_or_soft_deleted_user_does_not_get_usable_reset(self):
        self.customer_user.is_active = False
        self.customer_user.save(update_fields=["is_active"])

        response = self.client.post(
            reverse("password_reset"),
            {"email": self.customer_user.email},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(mail.outbox), 0)

    def test_password_reset_confirm_rejects_invalid_token(self):
        uid = urlsafe_base64_encode(force_bytes(self.customer_user.pk))
        response = self.client.post(
            reverse("password_reset_confirm"),
            {"uid": uid, "token": "invalid", "new_password": "AnotherStrongPassword123!"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_password_reset_confirm_rejects_weak_password(self):
        uid = urlsafe_base64_encode(force_bytes(self.customer_user.pk))
        token = PasswordResetTokenGenerator().make_token(self.customer_user)
        response = self.client.post(
            reverse("password_reset_confirm"),
            {"uid": uid, "token": token, "new_password": "password"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_password_reset_confirm_sets_new_password(self):
        uid = urlsafe_base64_encode(force_bytes(self.customer_user.pk))
        token = PasswordResetTokenGenerator().make_token(self.customer_user)
        new_password = "AnotherStrongPassword123!"

        response = self.client.post(
            reverse("password_reset_confirm"),
            {"uid": uid, "token": token, "new_password": new_password},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        user = get_user_model().objects.get(pk=self.customer_user.pk)
        self.assertTrue(user.check_password(new_password))
        self.assertFalse(user.check_password(self.password))
