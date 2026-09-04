"""P-8R D — the Settings header band reads three account facts from
``/api/auth/me/``: ``date_joined`` (member since), ``last_login`` (last
sign-in, ``null`` until the first sign-in) and the scope id sets (the
access summary). This pins that contract: the fields are present for
every role, ``last_login`` is null-safe, and the sets are lists.
"""

from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from test_utils import TenantFixtureMixin


class MeAccountFactsTests(TenantFixtureMixin, APITestCase):
    def test_me_carries_date_joined_and_null_last_login(self):
        self.customer_user.last_login = None
        self.customer_user.save(update_fields=["last_login"])
        self.authenticate(self.customer_user)

        response = self.client.get(reverse("auth_me"))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("date_joined", response.data)
        self.assertIsNotNone(response.data["date_joined"])
        self.assertIn("last_login", response.data)
        self.assertIsNone(response.data["last_login"])

    def test_me_renders_last_login_once_set(self):
        signed_in_at = timezone.now()
        self.customer_user.last_login = signed_in_at
        self.customer_user.save(update_fields=["last_login"])
        self.authenticate(self.customer_user)

        response = self.client.get(reverse("auth_me"))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIsInstance(response.data["last_login"], str)
        # P-16 repin — the wire renders the LOCAL time (Amsterdam);
        # comparing against the naive UTC date made this a
        # midnight-window flake (it failed only in a suite run that
        # crossed 00:00 local, exactly how the full-suite run found it).
        self.assertTrue(response.data["last_login"].startswith(
            timezone.localtime(signed_in_at).strftime("%Y-%m-%d")
        ))

    def test_me_carries_the_scope_id_sets_for_a_provider_role(self):
        self.authenticate(self.super_admin)

        response = self.client.get(reverse("auth_me"))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        for key in ("company_ids", "building_ids", "customer_ids"):
            self.assertIn(key, response.data)
            self.assertIsInstance(response.data[key], list)
        self.assertIn("date_joined", response.data)
        self.assertIn("last_login", response.data)
