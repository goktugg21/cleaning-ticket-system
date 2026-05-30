"""
Sprint 2A — request intent + ad-hoc cart line + agreed-price
snapshot coverage.

Locks the rules from
`docs/product/Osius_Source_of_Truth_FINAL_2026-05-30.md` §5.1–§5.9
and §11.2 against the backend serializer:

  * Three explicit intents: DIRECT_AGREED_PRICE_ORDER /
    AUTO_START_AFTER_PRICING / REQUEST_QUOTE.
  * Intent × cart × actor rules with stable error codes.
  * Ad-hoc / free-text cart line (no Service FK) is supported and
    classifies as AD_HOC.
  * Agreed-price snapshots survive a later CustomerServicePrice /
    Service edit.

NB: one-ticket-per-request grouping is explicitly deferred — Sprint
2A keeps the per-line spawn behaviour on DIRECT_AGREED_PRICE_ORDER
unchanged.
"""
from __future__ import annotations

from datetime import date
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

from extra_work.classification import (
    ACTOR_CUSTOMER_COMPANY_ADMIN,
    ACTOR_CUSTOMER_LOCATION_MANAGER,
    ACTOR_CUSTOMER_USER,
    ACTOR_PROVIDER,
    classify_cart,
    classify_line,
    derive_default_intent,
)
from extra_work.models import (
    CustomerServicePrice,
    ExtraWorkCategory,
    ExtraWorkLinePriceSource,
    ExtraWorkPricingUnitType,
    ExtraWorkRequest,
    ExtraWorkRequestIntent,
    ExtraWorkRequestItem,
    ExtraWorkRoutingDecision,
    Service,
    ServiceCategory,
)


User = get_user_model()
PASSWORD = "StrongerTestPassword123!"
URL = "/api/extra-work/"


def _mk(email: str, role: str, **extra) -> User:
    return User.objects.create_user(
        email=email,
        password=PASSWORD,
        role=role,
        full_name=email.split("@")[0],
        **extra,
    )


class IntentFixtureMixin:
    """
    Two-customer / one-provider fixture wide enough to cover every
    actor and cart shape required by Sprint 2A.

    Roles laid out for the helper API:
      * super_admin                  — system role SUPER_ADMIN
      * provider_admin               — COMPANY_ADMIN member of provider_a
      * building_manager             — BUILDING_MANAGER assigned to building_a1
      * staff                        — STAFF (blocked at endpoint)
      * cust_basic                   — CUSTOMER_USER + access_role CUSTOMER_USER
      * cust_location_manager        — CUSTOMER_USER + access_role
                                        CUSTOMER_LOCATION_MANAGER
      * cust_company_admin           — CUSTOMER_USER + access_role
                                        CUSTOMER_COMPANY_ADMIN

    Service catalog:
      * service_priced               — has an active CustomerServicePrice
                                        row for customer_a
      * service_unpriced             — no contract row anywhere
    """

    @classmethod
    def _setup_fixture(cls):
        cls.provider_a = Company.objects.create(
            name="Provider A", slug="prov-a-s2a"
        )
        cls.building_a1 = Building.objects.create(
            company=cls.provider_a, name="A1-S2A"
        )

        cls.customer_a = Customer.objects.create(
            company=cls.provider_a,
            name="Customer A S2A",
            building=cls.building_a1,
        )
        CustomerBuildingMembership.objects.create(
            customer=cls.customer_a, building=cls.building_a1
        )

        cls.super_admin = _mk(
            "super-s2a@example.com",
            UserRole.SUPER_ADMIN,
            is_staff=True,
            is_superuser=True,
        )
        cls.provider_admin = _mk(
            "padmin-s2a@example.com", UserRole.COMPANY_ADMIN
        )
        CompanyUserMembership.objects.create(
            user=cls.provider_admin, company=cls.provider_a
        )
        cls.building_manager = _mk(
            "bm-s2a@example.com", UserRole.BUILDING_MANAGER
        )
        BuildingManagerAssignment.objects.create(
            user=cls.building_manager, building=cls.building_a1
        )
        cls.staff = _mk("staff-s2a@example.com", UserRole.STAFF)

        cls.cust_basic = _mk(
            "cust-basic-s2a@example.com", UserRole.CUSTOMER_USER
        )
        basic_membership = CustomerUserMembership.objects.create(
            customer=cls.customer_a, user=cls.cust_basic
        )
        CustomerUserBuildingAccess.objects.create(
            membership=basic_membership,
            building=cls.building_a1,
            access_role=CustomerUserBuildingAccess.AccessRole.CUSTOMER_USER,
        )

        cls.cust_location_manager = _mk(
            "cust-loc-s2a@example.com", UserRole.CUSTOMER_USER
        )
        loc_membership = CustomerUserMembership.objects.create(
            customer=cls.customer_a, user=cls.cust_location_manager
        )
        CustomerUserBuildingAccess.objects.create(
            membership=loc_membership,
            building=cls.building_a1,
            access_role=(
                CustomerUserBuildingAccess.AccessRole.CUSTOMER_LOCATION_MANAGER
            ),
        )

        cls.cust_company_admin = _mk(
            "cust-cca-s2a@example.com", UserRole.CUSTOMER_USER
        )
        cca_membership = CustomerUserMembership.objects.create(
            customer=cls.customer_a, user=cls.cust_company_admin
        )
        CustomerUserBuildingAccess.objects.create(
            membership=cca_membership,
            building=cls.building_a1,
            access_role=(
                CustomerUserBuildingAccess.AccessRole.CUSTOMER_COMPANY_ADMIN
            ),
        )

        cls.service_cat = ServiceCategory.objects.create(name="Cleaning S2A")
        cls.service_priced = Service.objects.create(
            category=cls.service_cat,
            name="Window cleaning S2A",
            unit_type=ExtraWorkPricingUnitType.HOURS,
            default_unit_price=Decimal("50.00"),
            default_vat_pct=Decimal("21.00"),
        )
        cls.service_unpriced = Service.objects.create(
            category=cls.service_cat,
            name="Floor maintenance S2A",
            unit_type=ExtraWorkPricingUnitType.SQUARE_METERS,
            default_unit_price=Decimal("3.50"),
            default_vat_pct=Decimal("21.00"),
        )
        cls.contract_price = CustomerServicePrice.objects.create(
            service=cls.service_priced,
            customer=cls.customer_a,
            unit_price=Decimal("48.50"),
            vat_pct=Decimal("21.00"),
            valid_from=date(2026, 1, 1),
            valid_to=None,
            is_active=True,
        )

    def _api(self, user):
        c = APIClient()
        c.force_authenticate(user=user)
        return c

    # Cart-line builders --------------------------------------------------

    def _agreed_line(self, qty="1.00"):
        return {
            "service": self.service_priced.id,
            "quantity": qty,
            "requested_date": "2026-06-15",
            "customer_note": "",
        }

    def _non_agreed_line(self, qty="1.00"):
        return {
            "service": self.service_unpriced.id,
            "quantity": qty,
            "requested_date": "2026-06-15",
            "customer_note": "",
        }

    def _ad_hoc_line(self, qty="1.00", description="Move grand piano"):
        return {
            "custom_description": description,
            "quantity": qty,
            "requested_date": "2026-06-15",
            "customer_note": "",
        }

    def _payload(
        self,
        line_items,
        *,
        intent=None,
        customer=None,
        building=None,
        title="Sprint 2A cart",
    ):
        customer = customer or self.customer_a
        building = building or self.building_a1
        body = {
            "customer": customer.id,
            "building": building.id,
            "title": title,
            "description": "Sprint 2A cart description",
            "category": ExtraWorkCategory.DEEP_CLEANING,
            "line_items": list(line_items),
        }
        if intent is not None:
            body["request_intent"] = intent
        return body

    def _error_codes(self, response, field):
        """Pull the DRF ErrorDetail `.code` values for one field."""
        errors = response.data.get(field, [])
        return [getattr(err, "code", None) for err in errors]


# ---------------------------------------------------------------------------
# Pure helper coverage — classify_line / classify_cart / derive_default_intent
# ---------------------------------------------------------------------------
class ClassificationHelperTests(IntentFixtureMixin, TestCase):
    @classmethod
    def setUpTestData(cls):
        cls._setup_fixture()

    def test_classify_line_agreed(self):
        result = classify_line(
            service=self.service_priced,
            customer=self.customer_a,
            requested_date=date(2026, 6, 15),
            custom_description="",
        )
        self.assertEqual(
            result.source, ExtraWorkLinePriceSource.AGREED_CUSTOMER_PRICE
        )
        self.assertIsNotNone(result.contract)
        self.assertEqual(result.snapshot_unit_price, Decimal("48.50"))
        self.assertEqual(result.snapshot_vat_pct, Decimal("21.00"))
        self.assertEqual(
            result.snapshot_service_name, self.service_priced.name
        )
        self.assertEqual(
            result.snapshot_service_category_name, self.service_cat.name
        )

    def test_classify_line_needs_pricing(self):
        result = classify_line(
            service=self.service_unpriced,
            customer=self.customer_a,
            requested_date=date(2026, 6, 15),
            custom_description="",
        )
        self.assertEqual(
            result.source, ExtraWorkLinePriceSource.NEEDS_PROVIDER_PRICING
        )
        self.assertIsNone(result.contract)
        self.assertIsNone(result.snapshot_unit_price)
        # The catalog name/category still snapshot so reports can
        # show what was originally requested even after a deletion.
        self.assertEqual(
            result.snapshot_service_name, self.service_unpriced.name
        )

    def test_classify_line_ad_hoc(self):
        result = classify_line(
            service=None,
            customer=self.customer_a,
            requested_date=date(2026, 6, 15),
            custom_description="One-off carpet rip-up",
        )
        self.assertEqual(result.source, ExtraWorkLinePriceSource.AD_HOC)
        self.assertIsNone(result.contract)
        self.assertEqual(result.snapshot_service_name, "")
        self.assertEqual(result.snapshot_service_category_name, "")

    def test_classify_cart_aggregates(self):
        agreed = classify_line(
            service=self.service_priced,
            customer=self.customer_a,
            requested_date=date(2026, 6, 15),
            custom_description="",
        )
        needs = classify_line(
            service=self.service_unpriced,
            customer=self.customer_a,
            requested_date=date(2026, 6, 15),
            custom_description="",
        )
        cart = classify_cart([agreed, needs])
        self.assertFalse(cart.all_agreed)
        self.assertTrue(cart.has_non_agreed)
        self.assertFalse(cart.has_ad_hoc)

    def test_derive_default_intent_all_agreed(self):
        agreed = classify_line(
            service=self.service_priced,
            customer=self.customer_a,
            requested_date=date(2026, 6, 15),
            custom_description="",
        )
        cart = classify_cart([agreed])
        self.assertEqual(
            derive_default_intent(cart),
            ExtraWorkRequestIntent.DIRECT_AGREED_PRICE_ORDER,
        )

    def test_derive_default_intent_non_agreed_picks_quote(self):
        ad_hoc = classify_line(
            service=None,
            customer=self.customer_a,
            requested_date=date(2026, 6, 15),
            custom_description="Something custom",
        )
        cart = classify_cart([ad_hoc])
        # REQUEST_QUOTE is the safe default — AUTO_START would skip
        # customer approval and must be opt-in explicitly.
        self.assertEqual(
            derive_default_intent(cart),
            ExtraWorkRequestIntent.REQUEST_QUOTE,
        )


# ---------------------------------------------------------------------------
# DIRECT_AGREED_PRICE_ORDER
# ---------------------------------------------------------------------------
class DirectAgreedPriceOrderTests(IntentFixtureMixin, TestCase):
    @classmethod
    def setUpTestData(cls):
        cls._setup_fixture()

    def test_customer_can_submit_direct_with_all_agreed_lines(self):
        payload = self._payload(
            [self._agreed_line()],
            intent=ExtraWorkRequestIntent.DIRECT_AGREED_PRICE_ORDER,
        )
        response = self._api(self.cust_basic).post(URL, payload, format="json")
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(
            response.data["request_intent"],
            ExtraWorkRequestIntent.DIRECT_AGREED_PRICE_ORDER,
        )
        self.assertEqual(
            response.data["routing_decision"],
            ExtraWorkRoutingDecision.INSTANT,
        )

    def test_direct_rejected_when_any_line_needs_pricing(self):
        payload = self._payload(
            [self._agreed_line(), self._non_agreed_line()],
            intent=ExtraWorkRequestIntent.DIRECT_AGREED_PRICE_ORDER,
        )
        response = self._api(self.cust_basic).post(URL, payload, format="json")
        self.assertEqual(response.status_code, 400, response.data)
        self.assertIn(
            "intent_requires_all_agreed",
            self._error_codes(response, "request_intent"),
        )

    def test_direct_rejected_when_any_line_is_ad_hoc(self):
        payload = self._payload(
            [self._agreed_line(), self._ad_hoc_line()],
            intent=ExtraWorkRequestIntent.DIRECT_AGREED_PRICE_ORDER,
        )
        response = self._api(self.cust_basic).post(URL, payload, format="json")
        self.assertEqual(response.status_code, 400, response.data)
        self.assertIn(
            "intent_requires_all_agreed",
            self._error_codes(response, "request_intent"),
        )

    def test_provider_admin_can_submit_direct_on_behalf_of_customer(self):
        payload = self._payload(
            [self._agreed_line()],
            intent=ExtraWorkRequestIntent.DIRECT_AGREED_PRICE_ORDER,
        )
        response = self._api(self.provider_admin).post(
            URL, payload, format="json"
        )
        self.assertEqual(response.status_code, 201, response.data)

    def test_super_admin_can_submit_direct(self):
        payload = self._payload(
            [self._agreed_line()],
            intent=ExtraWorkRequestIntent.DIRECT_AGREED_PRICE_ORDER,
        )
        response = self._api(self.super_admin).post(URL, payload, format="json")
        self.assertEqual(response.status_code, 201, response.data)


# ---------------------------------------------------------------------------
# AUTO_START_AFTER_PRICING
# ---------------------------------------------------------------------------
class AutoStartAfterPricingTests(IntentFixtureMixin, TestCase):
    @classmethod
    def setUpTestData(cls):
        cls._setup_fixture()

    def test_basic_customer_user_forbidden_from_auto_start(self):
        payload = self._payload(
            [self._non_agreed_line()],
            intent=ExtraWorkRequestIntent.AUTO_START_AFTER_PRICING,
        )
        response = self._api(self.cust_basic).post(URL, payload, format="json")
        self.assertEqual(response.status_code, 400, response.data)
        self.assertIn(
            "intent_forbidden_for_role",
            self._error_codes(response, "request_intent"),
        )

    def test_customer_location_manager_can_use_auto_start(self):
        payload = self._payload(
            [self._non_agreed_line()],
            intent=ExtraWorkRequestIntent.AUTO_START_AFTER_PRICING,
        )
        response = self._api(self.cust_location_manager).post(
            URL, payload, format="json"
        )
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(
            response.data["request_intent"],
            ExtraWorkRequestIntent.AUTO_START_AFTER_PRICING,
        )

    def test_customer_company_admin_can_use_auto_start(self):
        payload = self._payload(
            [self._non_agreed_line()],
            intent=ExtraWorkRequestIntent.AUTO_START_AFTER_PRICING,
        )
        response = self._api(self.cust_company_admin).post(
            URL, payload, format="json"
        )
        self.assertEqual(response.status_code, 201, response.data)

    def test_provider_admin_can_use_auto_start_on_behalf(self):
        payload = self._payload(
            [self._non_agreed_line()],
            intent=ExtraWorkRequestIntent.AUTO_START_AFTER_PRICING,
        )
        response = self._api(self.provider_admin).post(
            URL, payload, format="json"
        )
        self.assertEqual(response.status_code, 201, response.data)

    def test_auto_start_rejected_when_all_lines_agreed(self):
        payload = self._payload(
            [self._agreed_line()],
            intent=ExtraWorkRequestIntent.AUTO_START_AFTER_PRICING,
        )
        response = self._api(self.cust_location_manager).post(
            URL, payload, format="json"
        )
        self.assertEqual(response.status_code, 400, response.data)
        self.assertIn(
            "intent_requires_non_agreed_line",
            self._error_codes(response, "request_intent"),
        )

    def test_auto_start_allowed_with_ad_hoc_line(self):
        payload = self._payload(
            [self._ad_hoc_line()],
            intent=ExtraWorkRequestIntent.AUTO_START_AFTER_PRICING,
        )
        response = self._api(self.cust_location_manager).post(
            URL, payload, format="json"
        )
        self.assertEqual(response.status_code, 201, response.data)


# ---------------------------------------------------------------------------
# REQUEST_QUOTE
# ---------------------------------------------------------------------------
class RequestQuoteTests(IntentFixtureMixin, TestCase):
    @classmethod
    def setUpTestData(cls):
        cls._setup_fixture()

    def test_basic_customer_user_can_request_quote(self):
        payload = self._payload(
            [self._non_agreed_line()],
            intent=ExtraWorkRequestIntent.REQUEST_QUOTE,
        )
        response = self._api(self.cust_basic).post(URL, payload, format="json")
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(
            response.data["request_intent"],
            ExtraWorkRequestIntent.REQUEST_QUOTE,
        )

    def test_customer_location_manager_can_request_quote(self):
        payload = self._payload(
            [self._non_agreed_line()],
            intent=ExtraWorkRequestIntent.REQUEST_QUOTE,
        )
        response = self._api(self.cust_location_manager).post(
            URL, payload, format="json"
        )
        self.assertEqual(response.status_code, 201, response.data)

    def test_customer_company_admin_can_request_quote(self):
        payload = self._payload(
            [self._non_agreed_line()],
            intent=ExtraWorkRequestIntent.REQUEST_QUOTE,
        )
        response = self._api(self.cust_company_admin).post(
            URL, payload, format="json"
        )
        self.assertEqual(response.status_code, 201, response.data)

    def test_request_quote_rejected_when_all_lines_agreed(self):
        payload = self._payload(
            [self._agreed_line()],
            intent=ExtraWorkRequestIntent.REQUEST_QUOTE,
        )
        response = self._api(self.cust_basic).post(URL, payload, format="json")
        self.assertEqual(response.status_code, 400, response.data)
        self.assertIn(
            "intent_requires_non_agreed_line",
            self._error_codes(response, "request_intent"),
        )

    def test_provider_admin_forbidden_from_request_quote(self):
        payload = self._payload(
            [self._non_agreed_line()],
            intent=ExtraWorkRequestIntent.REQUEST_QUOTE,
        )
        response = self._api(self.provider_admin).post(
            URL, payload, format="json"
        )
        self.assertEqual(response.status_code, 400, response.data)
        self.assertIn(
            "intent_forbidden_for_provider",
            self._error_codes(response, "request_intent"),
        )

    def test_building_manager_forbidden_from_request_quote(self):
        # BMs are provider-side actors per the matrix; the
        # `intent_forbidden_for_provider` code is the right
        # rejection. Scope check passes for this BM (assigned to
        # building_a1).
        payload = self._payload(
            [self._non_agreed_line()],
            intent=ExtraWorkRequestIntent.REQUEST_QUOTE,
        )
        response = self._api(self.building_manager).post(
            URL, payload, format="json"
        )
        self.assertEqual(response.status_code, 400, response.data)
        self.assertIn(
            "intent_forbidden_for_provider",
            self._error_codes(response, "request_intent"),
        )

    def test_super_admin_forbidden_from_request_quote(self):
        # SUPER_ADMIN counts as provider-side for the intent gate —
        # they cannot ask themselves for a quote either.
        payload = self._payload(
            [self._non_agreed_line()],
            intent=ExtraWorkRequestIntent.REQUEST_QUOTE,
        )
        response = self._api(self.super_admin).post(URL, payload, format="json")
        self.assertEqual(response.status_code, 400, response.data)
        self.assertIn(
            "intent_forbidden_for_provider",
            self._error_codes(response, "request_intent"),
        )


# ---------------------------------------------------------------------------
# Ad-hoc cart line shape rules
# ---------------------------------------------------------------------------
class AdHocLineShapeTests(IntentFixtureMixin, TestCase):
    @classmethod
    def setUpTestData(cls):
        cls._setup_fixture()

    def test_ad_hoc_line_does_not_create_service(self):
        before = Service.objects.count()
        payload = self._payload(
            [self._ad_hoc_line(description="Polish brass railings")],
            intent=ExtraWorkRequestIntent.REQUEST_QUOTE,
        )
        response = self._api(self.cust_basic).post(URL, payload, format="json")
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(Service.objects.count(), before)

        request = ExtraWorkRequest.objects.get(id=response.data["id"])
        line = request.line_items.get()
        self.assertIsNone(line.service_id)
        self.assertEqual(line.custom_description, "Polish brass railings")
        self.assertEqual(
            line.line_price_source, ExtraWorkLinePriceSource.AD_HOC
        )

    def test_ad_hoc_line_with_request_quote_intent_allowed(self):
        payload = self._payload(
            [self._ad_hoc_line()],
            intent=ExtraWorkRequestIntent.REQUEST_QUOTE,
        )
        response = self._api(self.cust_basic).post(URL, payload, format="json")
        self.assertEqual(response.status_code, 201, response.data)

    def test_ad_hoc_line_with_auto_start_allowed_for_location_manager(self):
        payload = self._payload(
            [self._ad_hoc_line()],
            intent=ExtraWorkRequestIntent.AUTO_START_AFTER_PRICING,
        )
        response = self._api(self.cust_location_manager).post(
            URL, payload, format="json"
        )
        self.assertEqual(response.status_code, 201, response.data)

    def test_ad_hoc_line_with_direct_intent_rejected(self):
        payload = self._payload(
            [self._ad_hoc_line()],
            intent=ExtraWorkRequestIntent.DIRECT_AGREED_PRICE_ORDER,
        )
        response = self._api(self.cust_basic).post(URL, payload, format="json")
        self.assertEqual(response.status_code, 400, response.data)

    def test_line_with_neither_service_nor_description_rejected(self):
        payload = self._payload(
            [
                {
                    "quantity": "1.00",
                    "requested_date": "2026-06-15",
                    "customer_note": "",
                }
            ],
            intent=ExtraWorkRequestIntent.REQUEST_QUOTE,
        )
        response = self._api(self.cust_basic).post(URL, payload, format="json")
        self.assertEqual(response.status_code, 400, response.data)
        # DRF nests the line-level errors under "line_items".
        line_errors = response.data.get("line_items", [])
        # First (and only) line carries the non_field_errors.
        if line_errors:
            non_field = line_errors[0].get("non_field_errors", [])
            codes = [getattr(err, "code", None) for err in non_field]
            self.assertIn("line_requires_service_or_description", codes)

    def test_line_with_both_service_and_description_rejected(self):
        bad_line = {
            "service": self.service_priced.id,
            "custom_description": "Both set is ambiguous",
            "quantity": "1.00",
            "requested_date": "2026-06-15",
            "customer_note": "",
        }
        payload = self._payload(
            [bad_line], intent=ExtraWorkRequestIntent.DIRECT_AGREED_PRICE_ORDER
        )
        response = self._api(self.cust_basic).post(URL, payload, format="json")
        self.assertEqual(response.status_code, 400, response.data)

    def test_two_ad_hoc_lines_are_not_duplicates(self):
        # Two ad-hoc lines must not be rejected by the duplicate-
        # service guard (they have no service FK).
        payload = self._payload(
            [
                self._ad_hoc_line(description="Item A"),
                self._ad_hoc_line(description="Item B"),
            ],
            intent=ExtraWorkRequestIntent.REQUEST_QUOTE,
        )
        response = self._api(self.cust_basic).post(URL, payload, format="json")
        self.assertEqual(response.status_code, 201, response.data)
        request = ExtraWorkRequest.objects.get(id=response.data["id"])
        self.assertEqual(request.line_items.count(), 2)


# ---------------------------------------------------------------------------
# Agreed-price snapshot durability
# ---------------------------------------------------------------------------
class AgreedPriceSnapshotTests(IntentFixtureMixin, TestCase):
    @classmethod
    def setUpTestData(cls):
        cls._setup_fixture()

    def _submit_agreed(self):
        payload = self._payload(
            [self._agreed_line()],
            intent=ExtraWorkRequestIntent.DIRECT_AGREED_PRICE_ORDER,
        )
        response = self._api(self.cust_basic).post(URL, payload, format="json")
        self.assertEqual(response.status_code, 201, response.data)
        return ExtraWorkRequest.objects.get(id=response.data["id"])

    def test_snapshots_populated_on_agreed_line(self):
        request = self._submit_agreed()
        line = request.line_items.get()
        self.assertEqual(
            line.line_price_source,
            ExtraWorkLinePriceSource.AGREED_CUSTOMER_PRICE,
        )
        self.assertEqual(line.snapshot_unit_price, Decimal("48.50"))
        self.assertEqual(line.snapshot_vat_pct, Decimal("21.00"))
        self.assertEqual(line.snapshot_service_name, self.service_priced.name)
        self.assertEqual(
            line.snapshot_service_category_name, self.service_cat.name
        )
        self.assertEqual(
            line.snapshot_customer_service_price_id, self.contract_price.id
        )

    def test_snapshot_immune_to_customer_service_price_edit(self):
        request = self._submit_agreed()
        line = request.line_items.get()

        # Mutate the contract row after submission — snapshots must
        # not move.
        self.contract_price.unit_price = Decimal("999.00")
        self.contract_price.vat_pct = Decimal("9.00")
        self.contract_price.save(update_fields=["unit_price", "vat_pct"])

        line.refresh_from_db()
        self.assertEqual(line.snapshot_unit_price, Decimal("48.50"))
        self.assertEqual(line.snapshot_vat_pct, Decimal("21.00"))

    def test_snapshot_immune_to_service_default_price_edit(self):
        request = self._submit_agreed()
        line = request.line_items.get()

        self.service_priced.default_unit_price = Decimal("777.00")
        self.service_priced.default_vat_pct = Decimal("9.00")
        self.service_priced.save(
            update_fields=["default_unit_price", "default_vat_pct"]
        )

        line.refresh_from_db()
        self.assertEqual(line.snapshot_unit_price, Decimal("48.50"))
        self.assertEqual(line.snapshot_vat_pct, Decimal("21.00"))
        self.assertEqual(line.snapshot_service_name, "Window cleaning S2A")

    def test_snapshot_survives_contract_row_deletion(self):
        request = self._submit_agreed()
        line = request.line_items.get()
        contract_id = line.snapshot_customer_service_price_id

        # Soft-delete via is_active does not move the FK; hard delete
        # nulls the FK (SET_NULL) but leaves the snapshot columns.
        self.contract_price.delete()

        line.refresh_from_db()
        self.assertIsNone(line.snapshot_customer_service_price_id)
        self.assertEqual(line.snapshot_unit_price, Decimal("48.50"))
        self.assertEqual(line.snapshot_vat_pct, Decimal("21.00"))
        self.assertEqual(
            line.line_price_source,
            ExtraWorkLinePriceSource.AGREED_CUSTOMER_PRICE,
        )
        self.assertEqual(
            line.snapshot_service_name, self.service_priced.name
        )

    def test_needs_pricing_line_has_null_snapshot_price(self):
        payload = self._payload(
            [self._non_agreed_line()],
            intent=ExtraWorkRequestIntent.REQUEST_QUOTE,
        )
        response = self._api(self.cust_basic).post(URL, payload, format="json")
        self.assertEqual(response.status_code, 201, response.data)
        request = ExtraWorkRequest.objects.get(id=response.data["id"])
        line = request.line_items.get()
        self.assertEqual(
            line.line_price_source,
            ExtraWorkLinePriceSource.NEEDS_PROVIDER_PRICING,
        )
        self.assertIsNone(line.snapshot_unit_price)
        self.assertIsNone(line.snapshot_vat_pct)
        self.assertIsNone(line.snapshot_customer_service_price_id)


# ---------------------------------------------------------------------------
# Backward compatibility: intent omitted on the wire
# ---------------------------------------------------------------------------
class IntentOmittedBackcompatTests(IntentFixtureMixin, TestCase):
    @classmethod
    def setUpTestData(cls):
        cls._setup_fixture()

    def test_omitted_intent_with_all_agreed_cart_derives_direct(self):
        payload = self._payload([self._agreed_line()])  # no intent supplied
        response = self._api(self.cust_basic).post(URL, payload, format="json")
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(
            response.data["request_intent"],
            ExtraWorkRequestIntent.DIRECT_AGREED_PRICE_ORDER,
        )

    def test_omitted_intent_with_non_agreed_cart_derives_quote(self):
        payload = self._payload([self._non_agreed_line()])
        response = self._api(self.cust_basic).post(URL, payload, format="json")
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(
            response.data["request_intent"],
            ExtraWorkRequestIntent.REQUEST_QUOTE,
        )
        # And critically, NOT AUTO_START_AFTER_PRICING — auto-start
        # silently skipping the customer approval step would be a
        # safety regression.
        self.assertNotEqual(
            response.data["request_intent"],
            ExtraWorkRequestIntent.AUTO_START_AFTER_PRICING,
        )

    def test_omitted_intent_with_ad_hoc_cart_derives_quote(self):
        payload = self._payload([self._ad_hoc_line()])
        response = self._api(self.cust_basic).post(URL, payload, format="json")
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(
            response.data["request_intent"],
            ExtraWorkRequestIntent.REQUEST_QUOTE,
        )


# ---------------------------------------------------------------------------
# Read-path projection
# ---------------------------------------------------------------------------
class ReadPathExposureTests(IntentFixtureMixin, TestCase):
    @classmethod
    def setUpTestData(cls):
        cls._setup_fixture()

    def test_detail_exposes_request_intent_and_snapshot_fields(self):
        payload = self._payload(
            [self._agreed_line()],
            intent=ExtraWorkRequestIntent.DIRECT_AGREED_PRICE_ORDER,
        )
        create_response = self._api(self.cust_basic).post(
            URL, payload, format="json"
        )
        self.assertEqual(create_response.status_code, 201)
        ew_id = create_response.data["id"]

        detail = self._api(self.cust_basic).get(f"{URL}{ew_id}/")
        self.assertEqual(detail.status_code, 200, detail.data)
        self.assertEqual(
            detail.data["request_intent"],
            ExtraWorkRequestIntent.DIRECT_AGREED_PRICE_ORDER,
        )
        line_payload = detail.data["line_items"][0]
        self.assertEqual(
            line_payload["line_price_source"],
            ExtraWorkLinePriceSource.AGREED_CUSTOMER_PRICE,
        )
        self.assertEqual(line_payload["snapshot_unit_price"], "48.50")
        self.assertEqual(line_payload["snapshot_vat_pct"], "21.00")

    def test_list_exposes_request_intent(self):
        payload = self._payload(
            [self._agreed_line()],
            intent=ExtraWorkRequestIntent.DIRECT_AGREED_PRICE_ORDER,
        )
        create_response = self._api(self.cust_basic).post(
            URL, payload, format="json"
        )
        self.assertEqual(create_response.status_code, 201)

        list_response = self._api(self.cust_basic).get(URL)
        self.assertEqual(list_response.status_code, 200)
        results = list_response.data["results"]
        self.assertTrue(
            any(
                row.get("request_intent")
                == ExtraWorkRequestIntent.DIRECT_AGREED_PRICE_ORDER
                for row in results
            ),
            results,
        )


# ---------------------------------------------------------------------------
# Sprint 2A — migration 0006 backfill semantics
# ---------------------------------------------------------------------------
class BackfillSemanticsTests(IntentFixtureMixin, TestCase):
    """
    Locks the migration-0006 backfill rule for `line_price_source`:

      * service IS NULL + custom_description == "" ⇒ NEEDS_PROVIDER_PRICING
        (this is what migration-0003 legacy backfill rows look like —
        they are SYNTHETIC placeholders, not customer-typed free-text
        lines, and must NOT be relabelled AD_HOC).
      * service IS NULL + custom_description != "" ⇒ AD_HOC
        (forward-compat: a future reapply with an operator-set
        custom_description should land as AD_HOC).
      * service set + parent.routing_decision == INSTANT ⇒ AGREED.
      * service set + otherwise ⇒ NEEDS_PROVIDER_PRICING.

    Exercises the migration's `backfill_intent_and_line_source`
    function directly against the live model registry. The test
    creates ExtraWorkRequest + ExtraWorkRequestItem rows with
    `line_price_source = None` (the post-AddField state, before the
    backfill runs) and confirms the function sets each row to the
    correct value.
    """

    @classmethod
    def setUpTestData(cls):
        cls._setup_fixture()

    @staticmethod
    def _backfill_fn():
        # Migration module filenames start with a digit, which makes
        # them un-importable through the normal `from X import Y`
        # syntax. Use importlib to grab the function.
        import importlib

        module = importlib.import_module(
            "extra_work.migrations."
            "0006_sprint2a_request_intent_and_line_snapshots"
        )
        return module.backfill_intent_and_line_source

    def test_legacy_service_null_blank_description_backfills_to_needs(self):
        from django.apps import apps as django_apps

        backfill_intent_and_line_source = self._backfill_fn()

        ew = ExtraWorkRequest.objects.create(
            company=self.provider_a,
            building=self.building_a1,
            customer=self.customer_a,
            created_by=self.cust_basic,
            title="Legacy-shape row",
            description="",
            category=ExtraWorkCategory.OTHER,
            category_other_text="Other",
            routing_decision=ExtraWorkRoutingDecision.PROPOSAL,
        )
        item = ExtraWorkRequestItem.objects.create(
            extra_work_request=ew,
            service=None,
            custom_description="",
            quantity=Decimal("1.00"),
            unit_type=ExtraWorkPricingUnitType.OTHER,
            requested_date=date(2026, 6, 15),
            customer_note="",
        )
        # Reset to the post-AddField pre-backfill state. The
        # serializer-created rows above are already stamped by the
        # live create() path; null both fields out so the backfill
        # function has work to do.
        ExtraWorkRequest.objects.filter(pk=ew.pk).update(
            request_intent=None
        )
        ExtraWorkRequestItem.objects.filter(pk=item.pk).update(
            line_price_source=None
        )

        backfill_intent_and_line_source(django_apps, None)

        item.refresh_from_db()
        ew.refresh_from_db()
        self.assertEqual(
            item.line_price_source,
            ExtraWorkLinePriceSource.NEEDS_PROVIDER_PRICING,
            "Legacy service-null + blank custom_description must NOT "
            "be backfilled as AD_HOC.",
        )
        self.assertNotEqual(
            item.line_price_source,
            ExtraWorkLinePriceSource.AD_HOC,
        )
        # Parent: PROPOSAL ⇒ REQUEST_QUOTE.
        self.assertEqual(
            ew.request_intent, ExtraWorkRequestIntent.REQUEST_QUOTE
        )

    def test_forward_compat_service_null_with_description_backfills_ad_hoc(
        self,
    ):
        from django.apps import apps as django_apps

        backfill_intent_and_line_source = self._backfill_fn()

        ew = ExtraWorkRequest.objects.create(
            company=self.provider_a,
            building=self.building_a1,
            customer=self.customer_a,
            created_by=self.cust_basic,
            title="Forward-compat ad-hoc row",
            description="",
            category=ExtraWorkCategory.OTHER,
            category_other_text="Other",
            routing_decision=ExtraWorkRoutingDecision.PROPOSAL,
        )
        item = ExtraWorkRequestItem.objects.create(
            extra_work_request=ew,
            service=None,
            custom_description="Polish brass",
            quantity=Decimal("1.00"),
            unit_type=ExtraWorkPricingUnitType.OTHER,
            requested_date=date(2026, 6, 15),
            customer_note="",
        )
        ExtraWorkRequest.objects.filter(pk=ew.pk).update(
            request_intent=None
        )
        ExtraWorkRequestItem.objects.filter(pk=item.pk).update(
            line_price_source=None
        )

        backfill_intent_and_line_source(django_apps, None)

        item.refresh_from_db()
        self.assertEqual(
            item.line_price_source, ExtraWorkLinePriceSource.AD_HOC
        )

    def test_instant_routed_parent_backfills_lines_as_agreed(self):
        from django.apps import apps as django_apps

        backfill_intent_and_line_source = self._backfill_fn()

        ew = ExtraWorkRequest.objects.create(
            company=self.provider_a,
            building=self.building_a1,
            customer=self.customer_a,
            created_by=self.cust_basic,
            title="INSTANT-routed parent",
            description="",
            category=ExtraWorkCategory.OTHER,
            category_other_text="Other",
            routing_decision=ExtraWorkRoutingDecision.INSTANT,
        )
        item = ExtraWorkRequestItem.objects.create(
            extra_work_request=ew,
            service=self.service_priced,
            custom_description="",
            quantity=Decimal("1.00"),
            unit_type=ExtraWorkPricingUnitType.HOURS,
            requested_date=date(2026, 6, 15),
            customer_note="",
        )
        ExtraWorkRequest.objects.filter(pk=ew.pk).update(
            request_intent=None
        )
        ExtraWorkRequestItem.objects.filter(pk=item.pk).update(
            line_price_source=None
        )

        backfill_intent_and_line_source(django_apps, None)

        ew.refresh_from_db()
        item.refresh_from_db()
        self.assertEqual(
            ew.request_intent,
            ExtraWorkRequestIntent.DIRECT_AGREED_PRICE_ORDER,
        )
        self.assertEqual(
            item.line_price_source,
            ExtraWorkLinePriceSource.AGREED_CUSTOMER_PRICE,
        )
