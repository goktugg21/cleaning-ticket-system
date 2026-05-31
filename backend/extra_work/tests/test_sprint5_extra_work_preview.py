"""
Sprint 5 — Extra Work cart preview / classification endpoint.

`POST /api/extra-work/preview/` is a STRICTLY NON-MUTATING endpoint
that mirrors the create cart's scope + permission gate and the same
per-line classification logic (single source of truth:
`extra_work.classification`). It answers, for a given (customer,
building, cart) tuple and the calling actor:

  * per-line price_source (AGREED / NEEDS_PROVIDER_PRICING / AD_HOC),
  * the customer's OWN agreed price (snapshot) for AGREED lines only
    — provider default prices are NEVER returned,
  * cart-level booleans (all_agreed / has_non_agreed / has_ad_hoc),
  * which `request_intent` values are allowed for THIS actor + cart,
  * the safe default intent,
  * and (when a request_intent is supplied) whether it is allowed
    plus a stable error code when not.

Security floor (H-1/H-2/H-5): no cross-customer/company bleed, STAFF
cannot preview, provider default prices never leak, zero DB writes.
"""
from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from accounts.models import UserRole
from buildings.models import Building, BuildingManagerAssignment
from companies.models import Company, CompanyUserMembership
from customers.models import (
    Customer,
    CustomerBuildingMembership,
    CustomerUserBuildingAccess,
    CustomerUserMembership,
)

from extra_work.models import (
    CustomerServicePrice,
    ExtraWorkPricingUnitType,
    ExtraWorkRequest,
    ExtraWorkRequestItem,
    Service,
    ServiceCategory,
)


User = get_user_model()
PASSWORD = "StrongerTestPassword123!"
PREVIEW_URL = "/api/extra-work/preview/"


def _mk(email: str, role: str, **extra) -> User:
    return User.objects.create_user(
        email=email,
        password=PASSWORD,
        role=role,
        full_name=email.split("@")[0],
        **extra,
    )


class Sprint5PreviewFixtureMixin:
    """
    Two-provider fixture covering every preview actor.

      * super_admin                — global provider operator
      * pa_a                       — COMPANY_ADMIN of provider_a
      * pa_b                       — COMPANY_ADMIN of provider_b
      * bm_a                       — BUILDING_MANAGER of building_a1
      * staff_a                    — STAFF (must be blocked)
      * cust_user_a                — CUSTOMER_USER access on customer_a
      * cust_loc_a                 — CUSTOMER_LOCATION_MANAGER on customer_a
      * cust_cca_a                 — CUSTOMER_COMPANY_ADMIN on customer_a
      * cust_user_b                — CUSTOMER_USER on customer_b (cross)
      * cust_user_a_inactive       — inactive access row (blocked)

    Catalog:
      * svc_agreed       — provider_a, HAS active CSP for customer_a
      * svc_needs        — provider_a, NO CSP (needs provider pricing)
      * svc_inactive     — provider_a, is_active=False
      * svc_b            — provider_b (cross-company)
    """

    @classmethod
    def _setup_fixture(cls):
        cls.provider_a = Company.objects.create(
            name="Provider A S5", slug="prov-a-s5"
        )
        cls.provider_b = Company.objects.create(
            name="Provider B S5", slug="prov-b-s5"
        )
        cls.building_a1 = Building.objects.create(
            company=cls.provider_a, name="A1-S5"
        )
        cls.building_b1 = Building.objects.create(
            company=cls.provider_b, name="B1-S5"
        )
        cls.customer_a = Customer.objects.create(
            company=cls.provider_a,
            name="Customer A S5",
            building=cls.building_a1,
        )
        cls.customer_b = Customer.objects.create(
            company=cls.provider_b,
            name="Customer B S5",
            building=cls.building_b1,
        )
        CustomerBuildingMembership.objects.create(
            customer=cls.customer_a, building=cls.building_a1
        )
        CustomerBuildingMembership.objects.create(
            customer=cls.customer_b, building=cls.building_b1
        )

        cls.super_admin = _mk(
            "super-s5@example.com",
            UserRole.SUPER_ADMIN,
            is_staff=True,
            is_superuser=True,
        )
        cls.pa_a = _mk("pa-a-s5@example.com", UserRole.COMPANY_ADMIN)
        CompanyUserMembership.objects.create(
            user=cls.pa_a, company=cls.provider_a
        )
        cls.pa_b = _mk("pa-b-s5@example.com", UserRole.COMPANY_ADMIN)
        CompanyUserMembership.objects.create(
            user=cls.pa_b, company=cls.provider_b
        )
        cls.bm_a = _mk("bm-a-s5@example.com", UserRole.BUILDING_MANAGER)
        BuildingManagerAssignment.objects.create(
            user=cls.bm_a, building=cls.building_a1
        )
        cls.staff_a = _mk("staff-a-s5@example.com", UserRole.STAFF)

        cls.cust_user_a = _mk("cu-basic-s5@example.com", UserRole.CUSTOMER_USER)
        m_user = CustomerUserMembership.objects.create(
            customer=cls.customer_a, user=cls.cust_user_a
        )
        CustomerUserBuildingAccess.objects.create(
            membership=m_user,
            building=cls.building_a1,
            access_role=CustomerUserBuildingAccess.AccessRole.CUSTOMER_USER,
            is_active=True,
        )

        cls.cust_loc_a = _mk("cu-loc-s5@example.com", UserRole.CUSTOMER_USER)
        m_loc = CustomerUserMembership.objects.create(
            customer=cls.customer_a, user=cls.cust_loc_a
        )
        CustomerUserBuildingAccess.objects.create(
            membership=m_loc,
            building=cls.building_a1,
            access_role=(
                CustomerUserBuildingAccess.AccessRole.CUSTOMER_LOCATION_MANAGER
            ),
            is_active=True,
        )

        cls.cust_cca_a = _mk("cu-cca-s5@example.com", UserRole.CUSTOMER_USER)
        m_cca = CustomerUserMembership.objects.create(
            customer=cls.customer_a, user=cls.cust_cca_a
        )
        CustomerUserBuildingAccess.objects.create(
            membership=m_cca,
            building=cls.building_a1,
            access_role=(
                CustomerUserBuildingAccess.AccessRole.CUSTOMER_COMPANY_ADMIN
            ),
            is_active=True,
        )

        cls.cust_user_b = _mk("cu-b-s5@example.com", UserRole.CUSTOMER_USER)
        m_b = CustomerUserMembership.objects.create(
            customer=cls.customer_b, user=cls.cust_user_b
        )
        CustomerUserBuildingAccess.objects.create(
            membership=m_b,
            building=cls.building_b1,
            access_role=CustomerUserBuildingAccess.AccessRole.CUSTOMER_USER,
            is_active=True,
        )

        cls.cust_user_a_inactive = _mk(
            "cu-inactive-s5@example.com", UserRole.CUSTOMER_USER
        )
        m_inact = CustomerUserMembership.objects.create(
            customer=cls.customer_a, user=cls.cust_user_a_inactive
        )
        CustomerUserBuildingAccess.objects.create(
            membership=m_inact,
            building=cls.building_a1,
            access_role=CustomerUserBuildingAccess.AccessRole.CUSTOMER_USER,
            is_active=False,
        )

        cls.category = ServiceCategory.objects.create(name="Cleaning S5")
        cls.svc_agreed = Service.objects.create(
            company=cls.provider_a,
            category=cls.category,
            name="Window cleaning S5",
            unit_type=ExtraWorkPricingUnitType.HOURS,
            default_unit_price=Decimal("50.00"),
            default_vat_pct=Decimal("21.00"),
        )
        cls.svc_needs = Service.objects.create(
            company=cls.provider_a,
            category=cls.category,
            name="Deep clean S5",
            unit_type=ExtraWorkPricingUnitType.SQUARE_METERS,
            default_unit_price=Decimal("7.77"),
            default_vat_pct=Decimal("9.00"),
        )
        cls.svc_inactive = Service.objects.create(
            company=cls.provider_a,
            category=cls.category,
            name="Discontinued S5",
            unit_type=ExtraWorkPricingUnitType.FIXED,
            default_unit_price=Decimal("99.00"),
            default_vat_pct=Decimal("21.00"),
            is_active=False,
        )
        cls.svc_b = Service.objects.create(
            company=cls.provider_b,
            category=cls.category,
            name="Window cleaning B S5",
            unit_type=ExtraWorkPricingUnitType.HOURS,
            default_unit_price=Decimal("60.00"),
            default_vat_pct=Decimal("21.00"),
        )

        # Customer A's OWN agreed price for svc_agreed.
        today = date(2026, 6, 1)
        cls.csp_agreed = CustomerServicePrice.objects.create(
            service=cls.svc_agreed,
            customer=cls.customer_a,
            unit_price=Decimal("48.50"),
            vat_pct=Decimal("21.00"),
            valid_from=today - timedelta(days=30),
            valid_to=None,
            is_active=True,
        )

    def _api(self, user):
        c = APIClient()
        c.force_authenticate(user=user)
        return c

    def _line(self, *, service=None, custom_description="", quantity="1.00",
              requested_date="2026-06-10", customer_note=""):
        return {
            "service": service,
            "custom_description": custom_description,
            "quantity": quantity,
            "requested_date": requested_date,
            "customer_note": customer_note,
        }

    def _body(self, *, customer, building, lines, request_intent=None):
        body = {
            "customer": customer.id,
            "building": building.id,
            "line_items": lines,
        }
        if request_intent is not None:
            body["request_intent"] = request_intent
        return body


class PreviewClassificationTests(Sprint5PreviewFixtureMixin, TestCase):
    @classmethod
    def setUpTestData(cls):
        cls._setup_fixture()

    def test_1_all_agreed_cart(self):
        body = self._body(
            customer=self.customer_a,
            building=self.building_a1,
            lines=[self._line(service=self.svc_agreed.id)],
        )
        resp = self._api(self.cust_loc_a).post(
            PREVIEW_URL, body, format="json"
        )
        self.assertEqual(resp.status_code, 200, resp.data)
        self.assertEqual(len(resp.data["lines"]), 1)
        line = resp.data["lines"][0]
        self.assertEqual(line["price_source"], "AGREED_CUSTOMER_PRICE")
        self.assertEqual(line["agreed_unit_price"], "48.50")
        self.assertEqual(line["agreed_vat_pct"], "21.00")
        self.assertTrue(resp.data["cart"]["all_agreed"])
        self.assertFalse(resp.data["cart"]["has_non_agreed"])
        self.assertEqual(
            resp.data["allowed_intents"], ["DIRECT_AGREED_PRICE_ORDER"]
        )
        self.assertEqual(
            resp.data["default_intent"], "DIRECT_AGREED_PRICE_ORDER"
        )

    def test_2_mixed_cart_location_manager(self):
        body = self._body(
            customer=self.customer_a,
            building=self.building_a1,
            lines=[
                self._line(service=self.svc_agreed.id),
                self._line(service=self.svc_needs.id),
            ],
        )
        resp = self._api(self.cust_loc_a).post(
            PREVIEW_URL, body, format="json"
        )
        self.assertEqual(resp.status_code, 200, resp.data)
        self.assertTrue(resp.data["cart"]["has_non_agreed"])
        self.assertFalse(resp.data["cart"]["all_agreed"])
        self.assertEqual(
            resp.data["allowed_intents"],
            ["AUTO_START_AFTER_PRICING", "REQUEST_QUOTE"],
        )
        self.assertEqual(resp.data["default_intent"], "REQUEST_QUOTE")
        # The needs-pricing line carries no price.
        needs = next(
            l for l in resp.data["lines"]
            if l["service"] == self.svc_needs.id
        )
        self.assertEqual(needs["price_source"], "NEEDS_PROVIDER_PRICING")
        self.assertIsNone(needs["agreed_unit_price"])
        self.assertIsNone(needs["agreed_vat_pct"])

    def test_3_ad_hoc_line(self):
        body = self._body(
            customer=self.customer_a,
            building=self.building_a1,
            lines=[
                self._line(custom_description="Special one-off task"),
            ],
        )
        resp = self._api(self.cust_loc_a).post(
            PREVIEW_URL, body, format="json"
        )
        self.assertEqual(resp.status_code, 200, resp.data)
        line = resp.data["lines"][0]
        self.assertEqual(line["price_source"], "AD_HOC")
        self.assertIsNone(line["service"])
        self.assertIsNone(line["agreed_unit_price"])
        self.assertIsNone(line["agreed_vat_pct"])
        self.assertTrue(resp.data["cart"]["has_ad_hoc"])
        self.assertTrue(resp.data["cart"]["has_non_agreed"])

    def test_4_basic_customer_user_no_auto_start(self):
        body = self._body(
            customer=self.customer_a,
            building=self.building_a1,
            lines=[self._line(service=self.svc_needs.id)],
        )
        resp = self._api(self.cust_user_a).post(
            PREVIEW_URL, body, format="json"
        )
        self.assertEqual(resp.status_code, 200, resp.data)
        self.assertNotIn(
            "AUTO_START_AFTER_PRICING", resp.data["allowed_intents"]
        )
        self.assertIn("REQUEST_QUOTE", resp.data["allowed_intents"])
        self.assertEqual(resp.data["actor_kind"], "CUSTOMER_USER")

    def test_5_provider_company_admin_intents(self):
        # All-agreed cart -> DIRECT allowed, REQUEST_QUOTE forbidden.
        agreed_body = self._body(
            customer=self.customer_a,
            building=self.building_a1,
            lines=[self._line(service=self.svc_agreed.id)],
        )
        resp = self._api(self.pa_a).post(
            PREVIEW_URL, agreed_body, format="json"
        )
        self.assertEqual(resp.status_code, 200, resp.data)
        self.assertEqual(resp.data["actor_kind"], "PROVIDER")
        self.assertIn(
            "DIRECT_AGREED_PRICE_ORDER", resp.data["allowed_intents"]
        )
        self.assertNotIn("REQUEST_QUOTE", resp.data["allowed_intents"])

        # Non-agreed cart -> AUTO_START allowed, REQUEST_QUOTE forbidden.
        needs_body = self._body(
            customer=self.customer_a,
            building=self.building_a1,
            lines=[self._line(service=self.svc_needs.id)],
        )
        resp2 = self._api(self.pa_a).post(
            PREVIEW_URL, needs_body, format="json"
        )
        self.assertEqual(resp2.status_code, 200, resp2.data)
        self.assertIn(
            "AUTO_START_AFTER_PRICING", resp2.data["allowed_intents"]
        )
        self.assertNotIn("REQUEST_QUOTE", resp2.data["allowed_intents"])

    def test_6_staff_blocked(self):
        body = self._body(
            customer=self.customer_a,
            building=self.building_a1,
            lines=[self._line(service=self.svc_agreed.id)],
        )
        resp = self._api(self.staff_a).post(PREVIEW_URL, body, format="json")
        self.assertIn(resp.status_code, (400, 403), resp.data)

    def test_7_customer_no_access_blocked(self):
        # cust_user_b has no access to customer_a / building_a1.
        body = self._body(
            customer=self.customer_a,
            building=self.building_a1,
            lines=[self._line(service=self.svc_agreed.id)],
        )
        resp = self._api(self.cust_user_b).post(
            PREVIEW_URL, body, format="json"
        )
        self.assertIn(resp.status_code, (400, 403), resp.data)

    def test_7b_inactive_access_blocked(self):
        body = self._body(
            customer=self.customer_a,
            building=self.building_a1,
            lines=[self._line(service=self.svc_agreed.id)],
        )
        resp = self._api(self.cust_user_a_inactive).post(
            PREVIEW_URL, body, format="json"
        )
        self.assertIn(resp.status_code, (400, 403), resp.data)

    def test_8_cross_company_service_rejected(self):
        body = self._body(
            customer=self.customer_a,
            building=self.building_a1,
            lines=[self._line(service=self.svc_b.id)],
        )
        resp = self._api(self.super_admin).post(
            PREVIEW_URL, body, format="json"
        )
        self.assertEqual(resp.status_code, 400, resp.data)
        self.assertIn(
            "line_service_company_mismatch",
            self._all_codes(resp),
        )

    def test_9_inactive_service_rejected(self):
        body = self._body(
            customer=self.customer_a,
            building=self.building_a1,
            lines=[self._line(service=self.svc_inactive.id)],
        )
        resp = self._api(self.super_admin).post(
            PREVIEW_URL, body, format="json"
        )
        self.assertEqual(resp.status_code, 400, resp.data)

    def test_10_provider_default_price_never_leaks(self):
        body = self._body(
            customer=self.customer_a,
            building=self.building_a1,
            lines=[self._line(service=self.svc_needs.id)],
        )
        resp = self._api(self.cust_loc_a).post(
            PREVIEW_URL, body, format="json"
        )
        self.assertEqual(resp.status_code, 200, resp.data)
        line = resp.data["lines"][0]
        self.assertIsNone(line["agreed_unit_price"])
        self.assertIsNone(line["agreed_vat_pct"])
        # No default_* keys anywhere in the serialized response.
        import json
        blob = json.dumps(resp.data, default=str)
        self.assertNotIn("default_unit_price", blob)
        self.assertNotIn("default_vat_pct", blob)
        # The provider default value (7.77 / 9.00) must never appear.
        self.assertNotIn("7.77", blob)
        self.assertNotIn("9.00", blob)

    def test_11_customer_sees_own_agreed_price(self):
        body = self._body(
            customer=self.customer_a,
            building=self.building_a1,
            lines=[self._line(service=self.svc_agreed.id)],
        )
        resp = self._api(self.cust_user_a).post(
            PREVIEW_URL, body, format="json"
        )
        self.assertEqual(resp.status_code, 200, resp.data)
        line = resp.data["lines"][0]
        # Value equals the CSP unit_price, NOT the provider default.
        self.assertEqual(line["agreed_unit_price"], "48.50")
        self.assertNotEqual(line["agreed_unit_price"], "50.00")

    def test_12_no_db_writes(self):
        ew_before = ExtraWorkRequest.objects.count()
        item_before = ExtraWorkRequestItem.objects.count()
        body = self._body(
            customer=self.customer_a,
            building=self.building_a1,
            lines=[
                self._line(service=self.svc_agreed.id),
                self._line(service=self.svc_needs.id),
                self._line(custom_description="adhoc"),
            ],
        )
        resp = self._api(self.cust_loc_a).post(
            PREVIEW_URL, body, format="json"
        )
        self.assertEqual(resp.status_code, 200, resp.data)
        self.assertEqual(ExtraWorkRequest.objects.count(), ew_before)
        self.assertEqual(ExtraWorkRequestItem.objects.count(), item_before)

    def test_13_supplied_request_intent_echo_and_validation(self):
        # Invalid: REQUEST_QUOTE on an all-agreed cart -> not allowed.
        agreed_body = self._body(
            customer=self.customer_a,
            building=self.building_a1,
            lines=[self._line(service=self.svc_agreed.id)],
            request_intent="REQUEST_QUOTE",
        )
        resp = self._api(self.cust_loc_a).post(
            PREVIEW_URL, agreed_body, format="json"
        )
        self.assertEqual(resp.status_code, 200, resp.data)
        self.assertEqual(resp.data["requested_intent"], "REQUEST_QUOTE")
        self.assertFalse(resp.data["requested_intent_allowed"])
        self.assertEqual(
            resp.data["requested_intent_error"]["code"],
            "intent_requires_non_agreed_line",
        )

        # Valid: DIRECT on an all-agreed cart -> allowed.
        ok_body = self._body(
            customer=self.customer_a,
            building=self.building_a1,
            lines=[self._line(service=self.svc_agreed.id)],
            request_intent="DIRECT_AGREED_PRICE_ORDER",
        )
        resp2 = self._api(self.cust_loc_a).post(
            PREVIEW_URL, ok_body, format="json"
        )
        self.assertEqual(resp2.status_code, 200, resp2.data)
        self.assertTrue(resp2.data["requested_intent_allowed"])
        self.assertNotIn("requested_intent_error", resp2.data)

    def test_14_empty_line_items_rejected(self):
        body = self._body(
            customer=self.customer_a,
            building=self.building_a1,
            lines=[],
        )
        resp = self._api(self.cust_loc_a).post(
            PREVIEW_URL, body, format="json"
        )
        self.assertEqual(resp.status_code, 400, resp.data)

    def test_15_malformed_requested_date_rejected(self):
        body = self._body(
            customer=self.customer_a,
            building=self.building_a1,
            lines=[
                self._line(
                    service=self.svc_agreed.id, requested_date="not-a-date"
                )
            ],
        )
        resp = self._api(self.cust_loc_a).post(
            PREVIEW_URL, body, format="json"
        )
        self.assertEqual(resp.status_code, 400, resp.data)

    def test_xor_line_requires_service_or_description(self):
        body = self._body(
            customer=self.customer_a,
            building=self.building_a1,
            lines=[self._line()],  # neither service nor description
        )
        resp = self._api(self.cust_loc_a).post(
            PREVIEW_URL, body, format="json"
        )
        self.assertEqual(resp.status_code, 400, resp.data)
        self.assertIn(
            "line_requires_service_or_description", self._all_codes(resp)
        )

    def test_response_shape_keys(self):
        body = self._body(
            customer=self.customer_a,
            building=self.building_a1,
            lines=[self._line(service=self.svc_agreed.id)],
        )
        resp = self._api(self.cust_loc_a).post(
            PREVIEW_URL, body, format="json"
        )
        self.assertEqual(resp.status_code, 200, resp.data)
        for key in (
            "customer",
            "building",
            "actor_kind",
            "lines",
            "cart",
            "allowed_intents",
            "default_intent",
        ):
            self.assertIn(key, resp.data)
        line = resp.data["lines"][0]
        for key in (
            "index",
            "service",
            "custom_description",
            "requested_date",
            "quantity",
            "price_source",
            "service_name",
            "service_category_name",
            "agreed_unit_price",
            "agreed_vat_pct",
        ):
            self.assertIn(key, line)

    def _all_codes(self, response):
        """Recursively collect every ErrorDetail.code in the response."""
        codes = []

        def walk(node):
            if hasattr(node, "code"):
                codes.append(node.code)
            if isinstance(node, dict):
                for v in node.values():
                    walk(v)
            elif isinstance(node, (list, tuple)):
                for v in node:
                    walk(v)

        walk(response.data)
        return codes
