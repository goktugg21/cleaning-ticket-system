"""P-15 — the derived default intent faces the same validator (S3).

P-14's C1 finding (EW 315, kept CANCELLED as evidence): a provider
creating an extra work with `request_intent` omitted got REQUEST_QUOTE
stamped — the very intent `validate_intent_for_cart` forbids a provider
to choose (400 on explicit send). The preview advertised the
contradiction: `allowed_intents: ["AUTO_START_AFTER_PRICING"]` beside
`default_intent: "REQUEST_QUOTE"`.

The fix: the derived default is judged by the SAME validator an
explicit choice faces. Where it fails, the create asks the caller to
choose (`intent_required`) — a default is never silently swapped for a
stronger one, because auto-start by omission would pre-authorise
skipping the customer's approval. The preview's `default_intent` is
null unless this actor may actually use it.
"""
from __future__ import annotations

from django.test import TestCase

from extra_work.models import ExtraWorkRequest, ExtraWorkRequestIntent

from .test_sprint2_request_intent import URL, IntentFixtureMixin

PREVIEW_URL = "/api/extra-work/preview/"


class DerivedDefaultIsValidatedTests(IntentFixtureMixin, TestCase):
    @classmethod
    def setUpTestData(cls):
        cls._setup_fixture()

    def test_provider_omitting_intent_on_a_non_agreed_cart_is_asked(self):
        before = ExtraWorkRequest.objects.count()
        response = self._api(self.provider_admin).post(
            URL,
            self._payload([self._non_agreed_line()]),
            format="json",
        )
        self.assertEqual(response.status_code, 400, response.data)
        self.assertIn(
            "intent_required", self._error_codes(response, "request_intent")
        )
        # Nothing was stamped, nothing was created.
        self.assertEqual(ExtraWorkRequest.objects.count(), before)

    def test_provider_omitting_intent_on_an_all_agreed_cart_still_defaults(self):
        response = self._api(self.provider_admin).post(
            URL,
            self._payload([self._agreed_line()]),
            format="json",
        )
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(
            response.data["request_intent"],
            ExtraWorkRequestIntent.DIRECT_AGREED_PRICE_ORDER,
        )

    def test_customer_omitting_intent_still_defaults_to_quote(self):
        response = self._api(self.cust_basic).post(
            URL,
            self._payload([self._non_agreed_line()]),
            format="json",
        )
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(
            response.data["request_intent"],
            ExtraWorkRequestIntent.REQUEST_QUOTE,
        )

    def test_preview_stops_advertising_a_forbidden_default(self):
        response = self._api(self.provider_admin).post(
            PREVIEW_URL,
            self._payload([self._non_agreed_line()]),
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.data)
        self.assertNotIn(
            ExtraWorkRequestIntent.REQUEST_QUOTE,
            response.data["allowed_intents"],
        )
        self.assertIsNone(response.data["default_intent"])

    def test_preview_default_stands_where_it_is_allowed(self):
        response = self._api(self.cust_basic).post(
            PREVIEW_URL,
            self._payload([self._non_agreed_line()]),
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(
            response.data["default_intent"],
            ExtraWorkRequestIntent.REQUEST_QUOTE,
        )
