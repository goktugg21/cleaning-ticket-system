"""
Sprint 3B — provider-scoped Service catalog + safe default-price
visibility tests.

Locks the rules from
`docs/product/Osius_Source_of_Truth_FINAL_2026-05-30.md` §1.6 +
§2.1 + §5.7 + §5.8 against the backend serializer + view layers.

Coverage:

  * Provider-company scope on Service:
      - SUPER_ADMIN sees every provider's catalog.
      - Provider Admin / Building Manager see only own provider's
        catalog.
      - Non-superadmin foreign actors get 404 on detail / empty
        list (no existence leak).
  * Default-price visibility on the ServiceSerializer:
      - SA / CA-of-company / BM-of-company see
        `default_unit_price` + `default_vat_pct`.
      - STAFF + every CUSTOMER_USER access role do NOT see them
        (fields are dropped from the response).
  * Provider-Admin write toggles on Company:
      - `provider_admin_may_manage_catalog=False` → CA gets HTTP
        403 + stable code `provider_admin_catalog_management_disabled`.
      - `provider_admin_may_manage_customer_prices=False` → CA gets
        HTTP 403 + stable code
        `provider_admin_customer_price_management_disabled`.
  * Cross-company guards:
      - `CustomerServicePrice` POST rejects mismatched
        service/customer with stable code
        `service_customer_company_mismatch`.
      - Extra Work cart POST rejects a cart line whose service
        belongs to another provider with stable code
        `line_service_company_mismatch`.
  * Migration backfill helper:
      - Single-Company fast path assigns every legacy Service.
      - CustomerServicePrice-inferred unambiguous case assigns
        the unique Company.
      - Multi-Company ambiguous Service raises RuntimeError.
      - No-CSP multi-Company case raises RuntimeError.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase, TransactionTestCase
from rest_framework import status
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
    ExtraWorkCategory,
    ExtraWorkPricingUnitType,
    ExtraWorkRequest,
    ExtraWorkRequestIntent,
    Service,
    ServiceCategory,
)


User = get_user_model()
PASSWORD = "StrongerTestPassword123!"
SERVICE_LIST_URL = "/api/services/"
SERVICE_DETAIL_URL = "/api/services/{svc_id}/"
CATEGORY_LIST_URL = "/api/services/categories/"
CUSTOMER_PRICING_LIST_URL = "/api/customers/{cid}/pricing/"
EW_URL = "/api/extra-work/"


def _mk(email: str, role: str, **extra) -> User:
    return User.objects.create_user(
        email=email,
        password=PASSWORD,
        role=role,
        full_name=email.split("@")[0],
        **extra,
    )


class TwoProviderFixtureMixin:
    """
    Two-provider fixture wide enough for every Sprint 3B test.

    Providers:
      * provider_a / building_a / customer_a
      * provider_b / building_b / customer_b

    Roles:
      * super_admin            — global
      * pa_a                   — COMPANY_ADMIN of provider_a
      * pa_b                   — COMPANY_ADMIN of provider_b
      * bm_a                   — BUILDING_MANAGER of building_a (so
                                  in scope for provider_a)
      * staff_a                — STAFF with BuildingStaffVisibility
                                  on building_a
      * cust_user_a            — CUSTOMER_USER under customer_a with
                                  baseline CUSTOMER_USER access role
      * cust_loc_a             — CUSTOMER_USER under customer_a with
                                  CUSTOMER_LOCATION_MANAGER access
      * cust_cca_a             — CUSTOMER_USER under customer_a with
                                  CUSTOMER_COMPANY_ADMIN access

    Catalog:
      * category               — global ServiceCategory
      * svc_a / svc_a_other    — Services owned by provider_a
      * svc_b                  — Service owned by provider_b
    """

    @classmethod
    def _setup_fixture(cls):
        cls.provider_a = Company.objects.create(
            name="Provider A S3B", slug="prov-a-s3b"
        )
        cls.provider_b = Company.objects.create(
            name="Provider B S3B", slug="prov-b-s3b"
        )
        cls.building_a = Building.objects.create(
            company=cls.provider_a, name="A-bld"
        )
        cls.building_b = Building.objects.create(
            company=cls.provider_b, name="B-bld"
        )
        cls.customer_a = Customer.objects.create(
            company=cls.provider_a,
            name="Customer A S3B",
            building=cls.building_a,
        )
        cls.customer_b = Customer.objects.create(
            company=cls.provider_b,
            name="Customer B S3B",
            building=cls.building_b,
        )
        CustomerBuildingMembership.objects.create(
            customer=cls.customer_a, building=cls.building_a
        )
        CustomerBuildingMembership.objects.create(
            customer=cls.customer_b, building=cls.building_b
        )

        cls.super_admin = _mk(
            "super-s3b@example.com",
            UserRole.SUPER_ADMIN,
            is_staff=True,
            is_superuser=True,
        )
        cls.pa_a = _mk("pa-a-s3b@example.com", UserRole.COMPANY_ADMIN)
        CompanyUserMembership.objects.create(
            user=cls.pa_a, company=cls.provider_a
        )
        cls.pa_b = _mk("pa-b-s3b@example.com", UserRole.COMPANY_ADMIN)
        CompanyUserMembership.objects.create(
            user=cls.pa_b, company=cls.provider_b
        )
        cls.bm_a = _mk("bm-a-s3b@example.com", UserRole.BUILDING_MANAGER)
        BuildingManagerAssignment.objects.create(
            user=cls.bm_a, building=cls.building_a
        )

        cls.staff_a = _mk("staff-a-s3b@example.com", UserRole.STAFF)
        from buildings.models import BuildingStaffVisibility

        BuildingStaffVisibility.objects.create(
            user=cls.staff_a, building=cls.building_a
        )

        # Three customer-side actors with different access_roles.
        cls.cust_user_a = _mk(
            "cust-user-s3b@example.com", UserRole.CUSTOMER_USER
        )
        membership_user = CustomerUserMembership.objects.create(
            customer=cls.customer_a, user=cls.cust_user_a
        )
        CustomerUserBuildingAccess.objects.create(
            membership=membership_user,
            building=cls.building_a,
            access_role=(
                CustomerUserBuildingAccess.AccessRole.CUSTOMER_USER
            ),
        )

        cls.cust_loc_a = _mk(
            "cust-loc-s3b@example.com", UserRole.CUSTOMER_USER
        )
        membership_loc = CustomerUserMembership.objects.create(
            customer=cls.customer_a, user=cls.cust_loc_a
        )
        CustomerUserBuildingAccess.objects.create(
            membership=membership_loc,
            building=cls.building_a,
            access_role=(
                CustomerUserBuildingAccess.AccessRole.CUSTOMER_LOCATION_MANAGER
            ),
        )

        cls.cust_cca_a = _mk(
            "cust-cca-s3b@example.com", UserRole.CUSTOMER_USER
        )
        membership_cca = CustomerUserMembership.objects.create(
            customer=cls.customer_a, user=cls.cust_cca_a
        )
        CustomerUserBuildingAccess.objects.create(
            membership=membership_cca,
            building=cls.building_a,
            access_role=(
                CustomerUserBuildingAccess.AccessRole.CUSTOMER_COMPANY_ADMIN
            ),
        )

        cls.category = ServiceCategory.objects.create(name="Cleaning S3B")
        cls.svc_a = Service.objects.create(
            company=cls.provider_a,
            category=cls.category,
            name="Window cleaning A",
            unit_type=ExtraWorkPricingUnitType.HOURS,
            default_unit_price=Decimal("50.00"),
            default_vat_pct=Decimal("21.00"),
        )
        cls.svc_a_other = Service.objects.create(
            company=cls.provider_a,
            category=cls.category,
            name="Floor cleaning A",
            unit_type=ExtraWorkPricingUnitType.SQUARE_METERS,
            default_unit_price=Decimal("4.00"),
            default_vat_pct=Decimal("21.00"),
        )
        cls.svc_b = Service.objects.create(
            company=cls.provider_b,
            category=cls.category,
            name="Window cleaning B",
            unit_type=ExtraWorkPricingUnitType.HOURS,
            default_unit_price=Decimal("60.00"),
            default_vat_pct=Decimal("21.00"),
        )

    def _api(self, user):
        c = APIClient()
        c.force_authenticate(user=user)
        return c

    def _error_code(self, response, field):
        errors = response.data.get(field, [])
        if isinstance(errors, dict):
            errors = [errors]
        # Handle nested ErrorDetail or string codes.
        codes = []
        for err in errors:
            if hasattr(err, "code"):
                codes.append(err.code)
            elif isinstance(err, dict):
                # Cross-field nested errors land as dicts; unwrap.
                for nested in err.values():
                    if isinstance(nested, list):
                        for item in nested:
                            if hasattr(item, "code"):
                                codes.append(item.code)
        return codes


# ---------------------------------------------------------------------------
# Catalog list / detail scope
# ---------------------------------------------------------------------------
class CatalogScopeListTests(TwoProviderFixtureMixin, TestCase):
    @classmethod
    def setUpTestData(cls):
        cls._setup_fixture()

    def test_super_admin_sees_both_providers(self):
        response = self._api(self.super_admin).get(SERVICE_LIST_URL)
        self.assertEqual(response.status_code, 200)
        ids = {row["id"] for row in response.data["results"]}
        self.assertIn(self.svc_a.id, ids)
        self.assertIn(self.svc_a_other.id, ids)
        self.assertIn(self.svc_b.id, ids)
        # SA sees defaults.
        a_row = next(
            row for row in response.data["results"] if row["id"] == self.svc_a.id
        )
        self.assertIn("default_unit_price", a_row)
        self.assertEqual(a_row["default_unit_price"], "50.00")

    def test_provider_admin_sees_only_own_company(self):
        response = self._api(self.pa_a).get(SERVICE_LIST_URL)
        self.assertEqual(response.status_code, 200)
        ids = {row["id"] for row in response.data["results"]}
        self.assertIn(self.svc_a.id, ids)
        self.assertIn(self.svc_a_other.id, ids)
        self.assertNotIn(self.svc_b.id, ids)
        a_row = next(
            row for row in response.data["results"] if row["id"] == self.svc_a.id
        )
        self.assertIn("default_unit_price", a_row)

    def test_provider_admin_cannot_retrieve_foreign_service(self):
        response = self._api(self.pa_a).get(
            SERVICE_DETAIL_URL.format(svc_id=self.svc_b.id)
        )
        # 404 (queryset filter prevents existence leak), not 403.
        self.assertEqual(response.status_code, 404)

    def test_building_manager_sees_own_provider_catalog_and_defaults(self):
        response = self._api(self.bm_a).get(SERVICE_LIST_URL)
        self.assertEqual(response.status_code, 200)
        ids = {row["id"] for row in response.data["results"]}
        self.assertIn(self.svc_a.id, ids)
        self.assertNotIn(self.svc_b.id, ids)
        # BM in scope sees defaults (SoT §5.8: BM may view default
        # prices by default).
        a_row = next(
            row for row in response.data["results"] if row["id"] == self.svc_a.id
        )
        self.assertIn("default_unit_price", a_row)
        self.assertEqual(a_row["default_unit_price"], "50.00")

    def test_staff_sees_own_provider_catalog_without_defaults(self):
        response = self._api(self.staff_a).get(SERVICE_LIST_URL)
        self.assertEqual(response.status_code, 200)
        ids = {row["id"] for row in response.data["results"]}
        self.assertIn(self.svc_a.id, ids)
        self.assertNotIn(self.svc_b.id, ids)
        a_row = next(
            row for row in response.data["results"] if row["id"] == self.svc_a.id
        )
        # STAFF must NOT see default_unit_price / default_vat_pct.
        self.assertNotIn("default_unit_price", a_row)
        self.assertNotIn("default_vat_pct", a_row)

    def test_customer_user_sees_own_provider_catalog_without_defaults(self):
        for actor in (self.cust_user_a, self.cust_loc_a, self.cust_cca_a):
            with self.subTest(actor=actor.email):
                response = self._api(actor).get(SERVICE_LIST_URL)
                self.assertEqual(response.status_code, 200)
                ids = {row["id"] for row in response.data["results"]}
                self.assertIn(self.svc_a.id, ids)
                self.assertNotIn(self.svc_b.id, ids)
                a_row = next(
                    row
                    for row in response.data["results"]
                    if row["id"] == self.svc_a.id
                )
                self.assertNotIn("default_unit_price", a_row)
                self.assertNotIn("default_vat_pct", a_row)


# ---------------------------------------------------------------------------
# Catalog write — policy toggle
# ---------------------------------------------------------------------------
class CatalogWriteToggleTests(TwoProviderFixtureMixin, TestCase):
    @classmethod
    def setUpTestData(cls):
        cls._setup_fixture()

    def test_provider_admin_can_write_when_toggle_true(self):
        # Default state: True. PA-A can create a Service for provider_a.
        payload = {
            "company": self.provider_a.id,
            "category": self.category.id,
            "name": "New svc A",
            "unit_type": ExtraWorkPricingUnitType.HOURS,
            "default_unit_price": "10.00",
        }
        response = self._api(self.pa_a).post(
            SERVICE_LIST_URL, payload, format="json"
        )
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data["company"], self.provider_a.id)
        self.assertEqual(response.data["company_name"], "Provider A S3B")

    def test_provider_admin_blocked_when_toggle_false(self):
        # Disable policy.
        self.provider_a.provider_admin_may_manage_catalog = False
        self.provider_a.save(
            update_fields=["provider_admin_may_manage_catalog"]
        )
        payload = {
            "company": self.provider_a.id,
            "category": self.category.id,
            "name": "Blocked svc",
            "unit_type": ExtraWorkPricingUnitType.HOURS,
            "default_unit_price": "5.00",
        }
        response = self._api(self.pa_a).post(
            SERVICE_LIST_URL, payload, format="json"
        )
        self.assertEqual(response.status_code, 403, response.data)
        # Stable error code carried in the detail payload.
        self.assertEqual(
            response.data.get("code"),
            "provider_admin_catalog_management_disabled",
        )

    def test_super_admin_bypasses_disabled_toggle(self):
        self.provider_a.provider_admin_may_manage_catalog = False
        self.provider_a.save(
            update_fields=["provider_admin_may_manage_catalog"]
        )
        payload = {
            "company": self.provider_a.id,
            "category": self.category.id,
            "name": "SA bypass svc",
            "unit_type": ExtraWorkPricingUnitType.HOURS,
            "default_unit_price": "5.00",
        }
        response = self._api(self.super_admin).post(
            SERVICE_LIST_URL, payload, format="json"
        )
        self.assertEqual(response.status_code, 201, response.data)

    def test_provider_admin_cannot_create_for_foreign_company(self):
        payload = {
            "company": self.provider_b.id,
            "category": self.category.id,
            "name": "Cross-provider attempt",
            "unit_type": ExtraWorkPricingUnitType.HOURS,
            "default_unit_price": "1.00",
        }
        response = self._api(self.pa_a).post(
            SERVICE_LIST_URL, payload, format="json"
        )
        self.assertEqual(response.status_code, 403, response.data)
        self.assertEqual(
            response.data.get("code"),
            "catalog_cross_company_forbidden",
        )

    def test_provider_admin_can_update_own_service(self):
        response = self._api(self.pa_a).patch(
            SERVICE_DETAIL_URL.format(svc_id=self.svc_a.id),
            {"default_unit_price": "55.00"},
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.data)
        self.svc_a.refresh_from_db()
        self.assertEqual(self.svc_a.default_unit_price, Decimal("55.00"))

    def test_provider_admin_update_blocked_when_toggle_false(self):
        self.provider_a.provider_admin_may_manage_catalog = False
        self.provider_a.save(
            update_fields=["provider_admin_may_manage_catalog"]
        )
        response = self._api(self.pa_a).patch(
            SERVICE_DETAIL_URL.format(svc_id=self.svc_a.id),
            {"default_unit_price": "55.00"},
            format="json",
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(
            response.data.get("code"),
            "provider_admin_catalog_management_disabled",
        )

    def test_building_manager_blocked_on_write(self):
        payload = {
            "company": self.provider_a.id,
            "category": self.category.id,
            "name": "BM attempt",
            "unit_type": ExtraWorkPricingUnitType.HOURS,
            "default_unit_price": "1.00",
        }
        response = self._api(self.bm_a).post(
            SERVICE_LIST_URL, payload, format="json"
        )
        self.assertEqual(response.status_code, 403)


# ---------------------------------------------------------------------------
# Sprint 3B BLOCKER 2 — Service create company defaulting
# ---------------------------------------------------------------------------
class ServiceCreateCompanyResolutionTests(TwoProviderFixtureMixin, TestCase):
    @classmethod
    def setUpTestData(cls):
        cls._setup_fixture()

    def _payload(self, **overrides):
        body = {
            "category": self.category.id,
            "name": "Resolved-service",
            "unit_type": ExtraWorkPricingUnitType.HOURS,
            "default_unit_price": "10.00",
        }
        body.update(overrides)
        return body

    def test_company_admin_post_without_company_defaults_to_own(self):
        payload = self._payload(name="PA-default-company")
        response = self._api(self.pa_a).post(
            SERVICE_LIST_URL, payload, format="json"
        )
        self.assertEqual(response.status_code, 201, response.data)
        # Response surfaces the defaulted company.
        self.assertEqual(response.data["company"], self.provider_a.id)
        self.assertEqual(
            response.data["company_name"], self.provider_a.name
        )
        # Stored row carries the resolved company.
        svc = Service.objects.get(pk=response.data["id"])
        self.assertEqual(svc.company_id, self.provider_a.id)

    def test_company_admin_post_with_own_company_explicit_ok(self):
        payload = self._payload(
            name="PA-explicit-own", company=self.provider_a.id
        )
        response = self._api(self.pa_a).post(
            SERVICE_LIST_URL, payload, format="json"
        )
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data["company"], self.provider_a.id)

    def test_company_admin_post_with_foreign_company_rejected(self):
        payload = self._payload(
            name="PA-cross-attempt", company=self.provider_b.id
        )
        response = self._api(self.pa_a).post(
            SERVICE_LIST_URL, payload, format="json"
        )
        self.assertEqual(response.status_code, 403, response.data)
        self.assertEqual(
            response.data.get("code"), "catalog_cross_company_forbidden"
        )

    def test_super_admin_post_without_company_rejects_when_multi_company(self):
        # Fixture has two Companies. SA must disambiguate.
        payload = self._payload(name="SA-no-company")
        response = self._api(self.super_admin).post(
            SERVICE_LIST_URL, payload, format="json"
        )
        self.assertEqual(response.status_code, 400, response.data)
        # Field-level ErrorDetail.code lookup.
        codes = []
        for err in response.data.get("company", []):
            if hasattr(err, "code"):
                codes.append(err.code)
        self.assertIn("service_company_required", codes)

    def test_super_admin_post_with_company_creates(self):
        payload = self._payload(
            name="SA-explicit-company", company=self.provider_b.id
        )
        response = self._api(self.super_admin).post(
            SERVICE_LIST_URL, payload, format="json"
        )
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data["company"], self.provider_b.id)


# ---------------------------------------------------------------------------
# Sprint 3B BLOCKER 3 — ServiceCategory writes restricted to SUPER_ADMIN
# ---------------------------------------------------------------------------
class ServiceCategoryWriteRestrictionTests(TwoProviderFixtureMixin, TestCase):
    @classmethod
    def setUpTestData(cls):
        cls._setup_fixture()

    def test_super_admin_can_create_and_update_and_delete_category(self):
        api = self._api(self.super_admin)
        create = api.post(
            CATEGORY_LIST_URL,
            {"name": "S3B SA-only Cat"},
            format="json",
        )
        self.assertEqual(create.status_code, 201, create.data)
        cat_id = create.data["id"]

        patch = api.patch(
            f"{CATEGORY_LIST_URL}{cat_id}/",
            {"description": "Updated"},
            format="json",
        )
        self.assertEqual(patch.status_code, 200, patch.data)

        delete = api.delete(f"{CATEGORY_LIST_URL}{cat_id}/")
        self.assertEqual(delete.status_code, 204)
        self.assertFalse(
            ServiceCategory.objects.filter(pk=cat_id).exists()
        )

    def test_company_admin_create_category_rejected(self):
        response = self._api(self.pa_a).post(
            CATEGORY_LIST_URL,
            {"name": "PA-cat-attempt"},
            format="json",
        )
        self.assertEqual(response.status_code, 403, response.data)
        self.assertEqual(
            response.data.get("code"),
            "global_category_management_super_admin_only",
        )
        self.assertFalse(
            ServiceCategory.objects.filter(name="PA-cat-attempt").exists()
        )

    def test_company_admin_update_category_rejected(self):
        # Existing category (created by SA in fixture).
        response = self._api(self.pa_a).patch(
            f"{CATEGORY_LIST_URL}{self.category.id}/",
            {"description": "Hijack"},
            format="json",
        )
        self.assertEqual(response.status_code, 403, response.data)
        self.assertEqual(
            response.data.get("code"),
            "global_category_management_super_admin_only",
        )

    def test_company_admin_delete_category_rejected(self):
        # Make a fresh, child-less category we could delete.
        cat = ServiceCategory.objects.create(name="S3B PA-delete-attempt")
        response = self._api(self.pa_a).delete(
            f"{CATEGORY_LIST_URL}{cat.id}/"
        )
        self.assertEqual(response.status_code, 403, response.data)
        self.assertEqual(
            response.data.get("code"),
            "global_category_management_super_admin_only",
        )
        self.assertTrue(
            ServiceCategory.objects.filter(pk=cat.id).exists()
        )

    def test_building_manager_create_category_rejected(self):
        response = self._api(self.bm_a).post(
            CATEGORY_LIST_URL, {"name": "BM-attempt"}, format="json"
        )
        self.assertEqual(response.status_code, 403, response.data)

    def test_customer_user_create_category_rejected(self):
        response = self._api(self.cust_user_a).post(
            CATEGORY_LIST_URL, {"name": "Cust-attempt"}, format="json"
        )
        self.assertEqual(response.status_code, 403, response.data)

    def test_provider_admin_can_still_crud_own_services_using_existing_categories(self):
        # Categories are SA-only to mutate, but PAs can still build
        # Service rows under them when their company's catalog
        # policy is True.
        payload = {
            "category": self.category.id,
            "name": "PA-service-existing-cat",
            "unit_type": ExtraWorkPricingUnitType.HOURS,
            "default_unit_price": "12.00",
        }
        response = self._api(self.pa_a).post(
            SERVICE_LIST_URL, payload, format="json"
        )
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data["company"], self.provider_a.id)


# ---------------------------------------------------------------------------
# Customer-specific pricing — policy toggle + cross-company
# ---------------------------------------------------------------------------
class CustomerPricingPolicyTests(TwoProviderFixtureMixin, TestCase):
    @classmethod
    def setUpTestData(cls):
        cls._setup_fixture()

    def _list_url(self, customer):
        return CUSTOMER_PRICING_LIST_URL.format(cid=customer.id)

    def test_provider_admin_can_write_when_toggle_true(self):
        response = self._api(self.pa_a).post(
            self._list_url(self.customer_a),
            {
                "service": self.svc_a.id,
                "unit_price": "42.00",
                "vat_pct": "21.00",
                "valid_from": "2026-01-01",
            },
            format="json",
        )
        self.assertEqual(response.status_code, 201, response.data)

    def test_provider_admin_blocked_when_toggle_false(self):
        self.provider_a.provider_admin_may_manage_customer_prices = False
        self.provider_a.save(
            update_fields=[
                "provider_admin_may_manage_customer_prices"
            ]
        )
        response = self._api(self.pa_a).post(
            self._list_url(self.customer_a),
            {
                "service": self.svc_a.id,
                "unit_price": "42.00",
                "valid_from": "2026-01-01",
            },
            format="json",
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(
            response.data.get("code"),
            "provider_admin_customer_price_management_disabled",
        )

    def test_super_admin_bypasses_customer_price_toggle(self):
        self.provider_a.provider_admin_may_manage_customer_prices = False
        self.provider_a.save(
            update_fields=[
                "provider_admin_may_manage_customer_prices"
            ]
        )
        response = self._api(self.super_admin).post(
            self._list_url(self.customer_a),
            {
                "service": self.svc_a.id,
                "unit_price": "42.00",
                "valid_from": "2026-01-01",
            },
            format="json",
        )
        self.assertEqual(response.status_code, 201, response.data)

    def test_cross_company_csp_rejected(self):
        # POSTing svc_b (provider B) onto customer_a (provider A)
        # must fail with stable code.
        response = self._api(self.super_admin).post(
            self._list_url(self.customer_a),
            {
                "service": self.svc_b.id,
                "unit_price": "42.00",
                "valid_from": "2026-01-01",
            },
            format="json",
        )
        self.assertEqual(response.status_code, 400, response.data)
        codes = self._error_code(response, "service")
        self.assertIn("service_customer_company_mismatch", codes)


# ---------------------------------------------------------------------------
# Extra Work cart cross-company guard
# ---------------------------------------------------------------------------
class ExtraWorkCrossCompanyTests(TwoProviderFixtureMixin, TestCase):
    @classmethod
    def setUpTestData(cls):
        cls._setup_fixture()

    def test_ew_create_rejects_cross_provider_line(self):
        # Customer A trying to order svc_b (provider B). Must
        # reject with stable code.
        payload = {
            "customer": self.customer_a.id,
            "building": self.building_a.id,
            "title": "Cross-provider attempt",
            "description": "Should fail",
            "category": ExtraWorkCategory.DEEP_CLEANING,
            "request_intent": ExtraWorkRequestIntent.REQUEST_QUOTE,
            "line_items": [
                {
                    "service": self.svc_b.id,
                    "quantity": "1.00",
                    "requested_date": "2026-06-15",
                    "customer_note": "",
                }
            ],
        }
        response = self._api(self.cust_user_a).post(
            EW_URL, payload, format="json"
        )
        self.assertEqual(response.status_code, 400, response.data)
        # The error is nested under line_items → entry → service.
        line_errors = response.data.get("line_items", [])
        codes = []
        for entry in line_errors:
            if isinstance(entry, dict):
                for err in entry.get("service", []):
                    if hasattr(err, "code"):
                        codes.append(err.code)
        self.assertIn("line_service_company_mismatch", codes)

    def test_ew_create_accepts_same_provider_line(self):
        payload = {
            "customer": self.customer_a.id,
            "building": self.building_a.id,
            "title": "Same-provider order",
            "description": "Should succeed",
            "category": ExtraWorkCategory.DEEP_CLEANING,
            "request_intent": ExtraWorkRequestIntent.REQUEST_QUOTE,
            "line_items": [
                {
                    "service": self.svc_a_other.id,
                    "quantity": "1.00",
                    "requested_date": "2026-06-15",
                    "customer_note": "",
                }
            ],
        }
        response = self._api(self.cust_user_a).post(
            EW_URL, payload, format="json"
        )
        self.assertEqual(response.status_code, 201, response.data)


# ---------------------------------------------------------------------------
# Migration backfill helper
# ---------------------------------------------------------------------------
class BackfillHelperTests(TransactionTestCase):
    """Exercises `backfill_service_company` directly. The migration
    runs on a fresh test DB that has zero orphan Services, so the
    function is normally a no-op there. To exercise the inference +
    abort branches we temporarily drop the `NOT NULL` constraint at
    DB level, create orphans, run the function, then restore the
    constraint.

    Inherits `TransactionTestCase` because PostgreSQL refuses
    `ALTER TABLE ... DROP NOT NULL` inside a transaction with
    pending trigger events — the default Django `TestCase` wraps
    each test in such a transaction. `TransactionTestCase` runs
    without that wrapping (slower; truncates the DB between tests).
    """

    @staticmethod
    def _backfill_fn():
        import importlib

        module = importlib.import_module(
            "extra_work.migrations."
            "0008_sprint3b_service_company_backfill"
        )
        return module.backfill_service_company

    def setUp(self):
        # Drop NOT NULL on extra_work_service.company_id for the
        # duration of the test; restored in tearDown. PostgreSQL
        # accepts `DROP NOT NULL` even when no NOT NULL is present,
        # so the restore branch is idempotent.
        from django.db import connection

        with connection.cursor() as cursor:
            cursor.execute(
                "ALTER TABLE extra_work_service ALTER COLUMN "
                "company_id DROP NOT NULL"
            )

    def tearDown(self):
        from django.db import connection

        # Drop any still-null rows so the NOT NULL restoration
        # succeeds even when an abort-branch test left an orphan
        # behind (it raises BEFORE the helper writes company_id).
        # CSP rows pointing at orphans go first because of the
        # PROTECT FK.
        with connection.cursor() as cursor:
            cursor.execute(
                "DELETE FROM extra_work_customerserviceprice "
                "WHERE service_id IN ("
                "  SELECT id FROM extra_work_service "
                "  WHERE company_id IS NULL"
                ")"
            )
            cursor.execute(
                "DELETE FROM extra_work_service "
                "WHERE company_id IS NULL"
            )
            cursor.execute(
                "ALTER TABLE extra_work_service ALTER COLUMN "
                "company_id SET NOT NULL"
            )

    def _make_orphan_service(self, *, name, helper_company):
        """Create a Service row whose `company_id` is NULL.

        We must initially insert with a real company (model still
        requires it on .create()), then NULL the column via raw
        SQL since `Service.objects.update(company=None)` would
        trip the Django-level NOT NULL check during the model
        re-fetch even though the DB constraint has been dropped.
        """
        from django.db import connection

        cat = ServiceCategory.objects.get_or_create(name="Backfill Cat")[0]
        svc = Service.objects.create(
            company=helper_company,
            category=cat,
            name=name,
            unit_type=ExtraWorkPricingUnitType.HOURS,
            default_unit_price=Decimal("1.00"),
        )
        with connection.cursor() as cursor:
            cursor.execute(
                "UPDATE extra_work_service SET company_id = NULL "
                "WHERE id = %s",
                [svc.id],
            )
        svc.refresh_from_db()
        return svc

    def test_single_company_fast_path(self):
        from django.apps import apps as django_apps

        backfill = self._backfill_fn()
        # Ensure exactly one Company in the DB → fast path.
        Company.objects.all().delete()
        company = Company.objects.create(
            name="Backfill Single", slug="bf-single"
        )
        svc = self._make_orphan_service(
            name="legacy-single", helper_company=company
        )

        backfill(django_apps, None)
        svc.refresh_from_db()
        self.assertEqual(svc.company_id, company.id)

    def test_inferred_from_unique_customer_service_price(self):
        from django.apps import apps as django_apps

        backfill = self._backfill_fn()
        Company.objects.all().delete()
        # Two Companies in the DB → fast path is OFF.
        company_a = Company.objects.create(
            name="Infer A", slug="infer-a"
        )
        company_b = Company.objects.create(
            name="Infer B", slug="infer-b"
        )
        building_a = Building.objects.create(
            company=company_a, name="ifa-bld"
        )
        customer_a = Customer.objects.create(
            company=company_a, name="Infer cust A", building=building_a
        )

        svc = self._make_orphan_service(
            name="legacy-infer", helper_company=company_a
        )
        CustomerServicePrice.objects.create(
            service=svc,
            customer=customer_a,
            unit_price=Decimal("1.00"),
            valid_from=date(2026, 1, 1),
        )

        backfill(django_apps, None)
        svc.refresh_from_db()
        self.assertEqual(svc.company_id, company_a.id)
        self.assertNotEqual(svc.company_id, company_b.id)

    def test_cross_company_csp_raises(self):
        from django.apps import apps as django_apps

        backfill = self._backfill_fn()
        Company.objects.all().delete()
        company_a = Company.objects.create(
            name="Conflict A", slug="conf-a"
        )
        company_b = Company.objects.create(
            name="Conflict B", slug="conf-b"
        )
        building_a = Building.objects.create(
            company=company_a, name="conf-bld-a"
        )
        building_b = Building.objects.create(
            company=company_b, name="conf-bld-b"
        )
        cust_a = Customer.objects.create(
            company=company_a, name="conf-A", building=building_a
        )
        cust_b = Customer.objects.create(
            company=company_b, name="conf-B", building=building_b
        )

        svc = self._make_orphan_service(
            name="legacy-conflict", helper_company=company_a
        )
        CustomerServicePrice.objects.create(
            service=svc,
            customer=cust_a,
            unit_price=Decimal("1.00"),
            valid_from=date(2026, 1, 1),
        )
        CustomerServicePrice.objects.create(
            service=svc,
            customer=cust_b,
            unit_price=Decimal("1.00"),
            valid_from=date(2026, 1, 1),
        )

        with self.assertRaises(RuntimeError) as ctx:
            backfill(django_apps, None)
        self.assertIn("Sprint 3B backfill", str(ctx.exception))
        self.assertIn("different Companies", str(ctx.exception))

    def test_no_csp_multi_company_raises(self):
        from django.apps import apps as django_apps

        backfill = self._backfill_fn()
        Company.objects.all().delete()
        company_a = Company.objects.create(
            name="No-CSP A", slug="nocsp-a"
        )
        Company.objects.create(name="No-CSP B", slug="nocsp-b")

        svc = self._make_orphan_service(
            name="legacy-no-csp", helper_company=company_a
        )

        with self.assertRaises(RuntimeError) as ctx:
            backfill(django_apps, None)
        self.assertIn("Sprint 3B backfill", str(ctx.exception))
        self.assertIn("no CustomerServicePrice", str(ctx.exception))


# ---------------------------------------------------------------------------
# Audit smoke
# ---------------------------------------------------------------------------
class AuditSmokeTests(TwoProviderFixtureMixin, TestCase):
    @classmethod
    def setUpTestData(cls):
        cls._setup_fixture()

    def test_service_default_price_update_creates_audit_log(self):
        from audit.models import AuditAction, AuditLog

        before = AuditLog.objects.filter(
            target_model="extra_work.Service",
            target_id=self.svc_a.id,
            action=AuditAction.UPDATE,
        ).count()
        response = self._api(self.pa_a).patch(
            SERVICE_DETAIL_URL.format(svc_id=self.svc_a.id),
            {"default_unit_price": "77.00"},
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.data)
        after = AuditLog.objects.filter(
            target_model="extra_work.Service",
            target_id=self.svc_a.id,
            action=AuditAction.UPDATE,
        ).count()
        self.assertEqual(after, before + 1)

    def test_company_toggle_update_creates_audit_log(self):
        from audit.models import AuditAction, AuditLog

        before = AuditLog.objects.filter(
            target_model="companies.Company",
            target_id=self.provider_a.id,
            action=AuditAction.UPDATE,
        ).count()
        self.provider_a.provider_admin_may_manage_catalog = False
        self.provider_a.save(
            update_fields=["provider_admin_may_manage_catalog"]
        )
        after = AuditLog.objects.filter(
            target_model="companies.Company",
            target_id=self.provider_a.id,
            action=AuditAction.UPDATE,
        ).count()
        self.assertEqual(after, before + 1)
