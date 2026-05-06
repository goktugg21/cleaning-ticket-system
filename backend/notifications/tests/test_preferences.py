from django.test import TestCase, override_settings
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from notifications.models import (
    NotificationEventType,
    NotificationPreference,
)
from notifications.services import (
    _drop_muted,
    send_password_reset_email,
    send_ticket_created_email,
)
from test_utils import TenantFixtureMixin


class NotificationPreferencesGetTests(TenantFixtureMixin, APITestCase):
    def test_authenticated_user_gets_all_user_mutable_types_with_default_unmuted(self):
        self.authenticate(self.customer_user)

        response = self.client.get(reverse("auth_notification_prefs"))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        prefs = response.data["preferences"]

        returned_types = [entry["event_type"] for entry in prefs]
        self.assertEqual(
            set(returned_types),
            {
                NotificationEventType.TICKET_CREATED,
                NotificationEventType.TICKET_STATUS_CHANGED,
                NotificationEventType.TICKET_ASSIGNED,
                NotificationEventType.TICKET_UNASSIGNED,
            },
        )
        for entry in prefs:
            self.assertFalse(entry["muted"])
            self.assertTrue(entry["label"])

    def test_get_reflects_stored_preference(self):
        NotificationPreference.objects.create(
            user=self.customer_user,
            event_type=NotificationEventType.TICKET_CREATED,
            muted=True,
        )
        self.authenticate(self.customer_user)

        response = self.client.get(reverse("auth_notification_prefs"))

        muted_map = {
            entry["event_type"]: entry["muted"]
            for entry in response.data["preferences"]
        }
        self.assertTrue(muted_map[NotificationEventType.TICKET_CREATED])
        self.assertFalse(muted_map[NotificationEventType.TICKET_ASSIGNED])

    def test_response_does_not_include_transactional_types(self):
        self.authenticate(self.customer_user)

        response = self.client.get(reverse("auth_notification_prefs"))

        types = [entry["event_type"] for entry in response.data["preferences"]]
        self.assertNotIn(NotificationEventType.PASSWORD_RESET, types)
        self.assertNotIn(NotificationEventType.INVITATION_SENT, types)

    def test_unauthenticated_returns_401(self):
        response = self.client.get(reverse("auth_notification_prefs"))
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)


class NotificationPreferencesPatchTests(TenantFixtureMixin, APITestCase):
    def test_patching_creates_a_row(self):
        self.authenticate(self.customer_user)

        response = self.client.patch(
            reverse("auth_notification_prefs"),
            {
                "preferences": [
                    {
                        "event_type": NotificationEventType.TICKET_CREATED,
                        "muted": True,
                    }
                ]
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        pref = NotificationPreference.objects.get(
            user=self.customer_user,
            event_type=NotificationEventType.TICKET_CREATED,
        )
        self.assertTrue(pref.muted)

    def test_patching_same_type_twice_updates_in_place(self):
        self.authenticate(self.customer_user)
        url = reverse("auth_notification_prefs")

        self.client.patch(
            url,
            {"preferences": [{"event_type": "TICKET_CREATED", "muted": True}]},
            format="json",
        )
        self.client.patch(
            url,
            {"preferences": [{"event_type": "TICKET_CREATED", "muted": False}]},
            format="json",
        )

        rows = NotificationPreference.objects.filter(
            user=self.customer_user,
            event_type=NotificationEventType.TICKET_CREATED,
        )
        self.assertEqual(rows.count(), 1)
        self.assertFalse(rows.first().muted)

    def test_patching_multiple_types_at_once(self):
        self.authenticate(self.customer_user)

        response = self.client.patch(
            reverse("auth_notification_prefs"),
            {
                "preferences": [
                    {"event_type": "TICKET_CREATED", "muted": True},
                    {"event_type": "TICKET_ASSIGNED", "muted": True},
                ]
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        muted_types = set(
            NotificationPreference.objects.filter(
                user=self.customer_user,
                muted=True,
            ).values_list("event_type", flat=True)
        )
        self.assertEqual(
            muted_types,
            {
                NotificationEventType.TICKET_CREATED,
                NotificationEventType.TICKET_ASSIGNED,
            },
        )

    def test_patching_transactional_type_returns_400(self):
        self.authenticate(self.customer_user)

        response = self.client.patch(
            reverse("auth_notification_prefs"),
            {
                "preferences": [
                    {
                        "event_type": NotificationEventType.PASSWORD_RESET,
                        "muted": True,
                    }
                ]
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertFalse(
            NotificationPreference.objects.filter(
                user=self.customer_user,
                event_type=NotificationEventType.PASSWORD_RESET,
            ).exists()
        )

    def test_unauthenticated_returns_401(self):
        response = self.client.patch(
            reverse("auth_notification_prefs"),
            {"preferences": [{"event_type": "TICKET_CREATED", "muted": True}]},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
class NotificationPreferenceFilterTests(TenantFixtureMixin, TestCase):
    def test_muted_user_is_dropped_from_ticket_created(self):
        # The manager is the only TICKET_CREATED recipient when actor is the
        # company_admin (per the existing email pipeline tests).
        NotificationPreference.objects.create(
            user=self.manager,
            event_type=NotificationEventType.TICKET_CREATED,
            muted=True,
        )

        logs = send_ticket_created_email(self.ticket, actor=self.company_admin)

        self.assertEqual(logs, [])

    def test_mute_does_not_block_password_reset(self):
        NotificationPreference.objects.create(
            user=self.customer_user,
            event_type=NotificationEventType.TICKET_CREATED,
            muted=True,
        )

        log = send_password_reset_email(
            self.customer_user, uid="abc", token="token"
        )

        self.assertIsNotNone(log)
        self.assertEqual(log.recipient_email, self.customer_user.email)

    def test_user_without_preferences_receives_emails(self):
        self.assertFalse(
            NotificationPreference.objects.filter(user=self.manager).exists()
        )

        logs = send_ticket_created_email(self.ticket, actor=self.company_admin)

        recipients = {log.recipient_email for log in logs}
        self.assertIn(self.manager.email, recipients)

    def test_drop_muted_is_noop_for_transactional_types(self):
        # Even with a muted row, transactional types short-circuit.
        NotificationPreference.objects.create(
            user=self.customer_user,
            event_type=NotificationEventType.TICKET_CREATED,
            muted=True,
        )

        result = _drop_muted(
            [self.customer_user],
            NotificationEventType.PASSWORD_RESET,
        )

        self.assertEqual(result, [self.customer_user])
