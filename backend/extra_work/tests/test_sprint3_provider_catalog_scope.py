"""
Sprint 3B — provider-scoped Service catalog + safe default-price
visibility tests.

Locks the rules from
`docs/product/source-of-truth.md` §1.6 +
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
    ManagedUnit,
    Service,
    ServiceCategory,
)


User = get_user_model()
PASSWORD = "StrongerTestPassword123!"
SERVICE_LIST_URL = "/api/services/"
SERVICE_DETAIL_URL = "/api/services/{svc_id}/"
CATEGORY_LIST_URL = "/api/services/categories/"
CUSTOMER_PRICING_LIST_URL = "/api/customers/{cid}/pricing/"
UNITS_URL = "/api/services/units/"
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
      * category / category_b  — one ServiceCategory per provider
                                  (Sprint 142; `category` was a single
                                  GLOBAL row before)
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

        # Sprint 142 — categories are company-scoped too, so provider B
        # gets its own. Same name on both, which is exactly what
        # per-company uniqueness now permits.
        cls.category = ServiceCategory.objects.create(
            company=cls.provider_a, name="Cleaning S3B"
        )
        cls.category_b = ServiceCategory.objects.create(
            company=cls.provider_b, name="Cleaning S3B"
        )
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
            category=cls.category_b,
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

    def test_customer_user_sees_only_their_agreed_services_without_defaults(
        self,
    ):
        """Sprint 147 — a customer sees ONLY the services a price has
        been agreed with them for.

        This test used to assert the Sprint 3B rule: a customer saw
        their PROVIDER's whole catalog, narrowed by company alone. The
        owner changed that rule deliberately — a customer has no
        business browsing the provider's general catalog — so the
        assertion moves with it rather than the code being reverted.

        Company scoping is still asserted (`svc_b` belongs to the other
        provider), and so is the Sprint 3B rule that survives untouched:
        provider default prices are never serialized to a customer.

        `svc_a_other` is the load-bearing half. It belongs to the SAME
        provider as `svc_a` and has NO agreed price, so it is exactly
        what the old rule would have shown and the new one must not.
        """
        CustomerServicePrice.objects.create(
            service=self.svc_a,
            customer=self.customer_a,
            unit_price=Decimal("42.00"),
            vat_pct=Decimal("21.00"),
            valid_from=date(2020, 1, 1),
            valid_to=None,
            is_active=True,
        )
        for actor in (self.cust_user_a, self.cust_loc_a, self.cust_cca_a):
            with self.subTest(actor=actor.email):
                response = self._api(actor).get(SERVICE_LIST_URL)
                self.assertEqual(response.status_code, 200)
                ids = {row["id"] for row in response.data["results"]}
                # Agreed with them -> visible.
                self.assertIn(self.svc_a.id, ids)
                # Same provider, NOT agreed with them -> not visible.
                self.assertNotIn(self.svc_a_other.id, ids)
                # Another provider entirely -> still not visible.
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
        # Sprint 142 — `category_b` too: a Service's category must
        # belong to the Service's own company, so naming provider B
        # here means naming provider B's category as well.
        payload = self._payload(
            name="SA-explicit-company",
            company=self.provider_b.id,
            category=self.category_b.id,
        )
        response = self._api(self.super_admin).post(
            SERVICE_LIST_URL, payload, format="json"
        )
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data["company"], self.provider_b.id)


# ---------------------------------------------------------------------------
# Sprint 3B BLOCKER 3 — ServiceCategory writes (Sprint 142: now the ordinary
# per-company catalog gate, not SUPER_ADMIN-only)
# ---------------------------------------------------------------------------
class ServiceCategoryWriteRestrictionTests(TwoProviderFixtureMixin, TestCase):
    """Sprint 142 rewrote this class.

    Sprint 3B locked category writes to SUPER_ADMIN and these tests
    asserted the stable code `global_category_management_super_admin_
    only` on the three CA paths. That rule existed for one reason —
    categories were GLOBAL, so one Provider Admin's edit reached every
    provider's catalog — and Sprint 142's `company` FK removes it. The
    tests are updated to the new behaviour rather than deleted, because
    what they were really guarding is still worth guarding: a CA must
    not reach ANOTHER company's category. That half is asserted below,
    now as a 404 (the scoped queryset) rather than a 403.
    """

    @classmethod
    def setUpTestData(cls):
        cls._setup_fixture()

    def test_super_admin_can_create_and_update_and_delete_category(self):
        api = self._api(self.super_admin)
        # `company` is REQUIRED for SA here since Sprint 142: with two
        # Companies in the DB, `_resolve_catalog_create_company` refuses
        # to guess (400 `service_company_required`) exactly as it does
        # for a Service.
        create = api.post(
            CATEGORY_LIST_URL,
            {"name": "S3B SA Cat", "company": self.provider_a.id},
            format="json",
        )
        self.assertEqual(create.status_code, 201, create.data)
        cat_id = create.data["id"]
        self.assertEqual(create.data["company"], self.provider_a.id)
        self.assertEqual(create.data["company_name"], self.provider_a.name)

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

    def test_super_admin_must_disambiguate_company_on_create(self):
        response = self._api(self.super_admin).post(
            CATEGORY_LIST_URL, {"name": "SA-ambiguous"}, format="json"
        )
        self.assertEqual(response.status_code, 400, response.data)
        self.assertIn(
            "service_company_required", self._error_code(response, "company")
        )

    def test_company_admin_creates_category_for_own_company(self):
        """Was `test_company_admin_create_category_rejected` (403
        `global_category_management_super_admin_only`). A CA now manages
        their own catalog groupings, which is what
        `Company.provider_admin_may_manage_catalog` has claimed to
        govern since Sprint 3B without actually doing so."""
        response = self._api(self.pa_a).post(
            CATEGORY_LIST_URL, {"name": "PA-own-cat"}, format="json"
        )
        self.assertEqual(response.status_code, 201, response.data)
        # `company` omitted on the wire -> defaulted to the actor's own,
        # the same `_resolve_catalog_create_company` rule Service uses.
        self.assertEqual(response.data["company"], self.provider_a.id)
        self.assertTrue(
            ServiceCategory.objects.filter(
                name="PA-own-cat", company=self.provider_a
            ).exists()
        )

    def test_company_admin_updates_own_category(self):
        """Was `test_company_admin_update_category_rejected`."""
        response = self._api(self.pa_a).patch(
            f"{CATEGORY_LIST_URL}{self.category.id}/",
            {"description": "Renamed by its owner"},
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.data)
        self.category.refresh_from_db()
        self.assertEqual(self.category.description, "Renamed by its owner")

    def test_company_admin_deletes_own_empty_category(self):
        """Was `test_company_admin_delete_category_rejected`. Still an
        EMPTY category — `Service.category` is PROTECT, which is a
        separate rule this sprint did not touch."""
        cat = ServiceCategory.objects.create(
            company=self.provider_a, name="S3B PA-delete-own"
        )
        response = self._api(self.pa_a).delete(
            f"{CATEGORY_LIST_URL}{cat.id}/"
        )
        self.assertEqual(response.status_code, 204, response.data)
        self.assertFalse(
            ServiceCategory.objects.filter(pk=cat.id).exists()
        )

    def test_company_admin_cannot_create_category_for_another_company(self):
        response = self._api(self.pa_a).post(
            CATEGORY_LIST_URL,
            {"name": "PA-cross-attempt", "company": self.provider_b.id},
            format="json",
        )
        self.assertEqual(response.status_code, 403, response.data)
        self.assertEqual(
            response.data.get("code"), "catalog_cross_company_forbidden"
        )
        self.assertFalse(
            ServiceCategory.objects.filter(name="PA-cross-attempt").exists()
        )

    def test_company_admin_cannot_touch_another_companys_category(self):
        """404, not 403: `ServiceCategoryDetailView.get_queryset` runs
        `filter_categories_for`, so a foreign id does not resolve at
        all. Asserted on all three write verbs plus the read."""
        api = self._api(self.pa_a)
        url = f"{CATEGORY_LIST_URL}{self.category_b.id}/"
        self.assertEqual(api.get(url).status_code, 404)
        self.assertEqual(
            api.patch(url, {"description": "hijack"}, format="json").status_code,
            404,
        )
        self.assertEqual(api.delete(url).status_code, 404)
        self.category_b.refresh_from_db()
        self.assertNotEqual(self.category_b.description, "hijack")

    def test_company_admin_blocked_when_catalog_policy_disabled(self):
        """The policy toggle now really governs categories — the whole
        point of retiring the SA-only gate in favour of
        `_enforce_catalog_management`."""
        self.provider_a.provider_admin_may_manage_catalog = False
        self.provider_a.save(
            update_fields=["provider_admin_may_manage_catalog"]
        )
        try:
            response = self._api(self.pa_a).post(
                CATEGORY_LIST_URL, {"name": "PA-policy-off"}, format="json"
            )
            self.assertEqual(response.status_code, 403, response.data)
            self.assertEqual(
                response.data.get("code"),
                "provider_admin_catalog_management_disabled",
            )
        finally:
            self.provider_a.provider_admin_may_manage_catalog = True
            self.provider_a.save(
                update_fields=["provider_admin_may_manage_catalog"]
            )

    def test_same_category_name_allowed_in_two_companies(self):
        """The platform-wide unique `name` is gone; uniqueness is
        per-company and case/whitespace-insensitive."""
        first = self._api(self.pa_a).post(
            CATEGORY_LIST_URL, {"name": "Shared Name"}, format="json"
        )
        self.assertEqual(first.status_code, 201, first.data)
        second = self._api(self.pa_b).post(
            CATEGORY_LIST_URL, {"name": "Shared Name"}, format="json"
        )
        self.assertEqual(second.status_code, 201, second.data)
        self.assertNotEqual(first.data["company"], second.data["company"])

    def test_duplicate_name_within_one_company_is_a_400(self):
        self._api(self.pa_a).post(
            CATEGORY_LIST_URL, {"name": "Dup Guard"}, format="json"
        )
        # Different case AND surrounding whitespace -- the constraint
        # normalizes with Lower(Trim(...)), so this is the same name.
        response = self._api(self.pa_a).post(
            CATEGORY_LIST_URL, {"name": "  dup guard  "}, format="json"
        )
        self.assertEqual(response.status_code, 400, response.data)
        self.assertEqual(
            ServiceCategory.objects.filter(
                company=self.provider_a, name__iexact="dup guard"
            ).count(),
            1,
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
# Sprint 142.1 — the uniqueness PRE-CHECK must not become a name oracle
# ---------------------------------------------------------------------------
class UniquenessPreCheckIsScopedTests(TwoProviderFixtureMixin, TestCase):
    """H-1. Sprint 142 added a friendly-400 uniqueness pre-check to
    `ServiceCategorySerializer.validate` (replacing the `UniqueValidator`
    DRF derived from the removed field-level `unique=True`), copying the
    shape `ManagedUnitSerializer` has had since Sprint 123. Both queried
    an UNSCOPED sibling set keyed on whatever `company` the client sent.

    DRF runs `is_valid()` BEFORE `perform_create()`, so that 400 fired
    ahead of `_resolve_catalog_create_company`'s 403 — making the status
    code itself report whether a RIVAL company owns a given name:

        400 -> the rival has it       403 -> the rival does not

    Both are now 403, byte-identical. The existing
    `test_duplicate_name_within_one_company_is_a_400` could not have
    caught this: it posts as a CA with `company` OMITTED, which skips the
    pre-check entirely and exercises only the view's `IntegrityError`
    backstop.
    """

    @classmethod
    def setUpTestData(cls):
        cls._setup_fixture()

    # -- ServiceCategory ------------------------------------------------
    def test_foreign_company_probe_is_indistinguishable(self):
        """THE oracle test. `category_b` is provider B's and is named
        "Cleaning S3B"; "Definitely Not There" is not. A COMPANY_ADMIN of
        provider A must not be able to tell those two apart."""
        api = self._api(self.pa_a)
        hit = api.post(
            CATEGORY_LIST_URL,
            {"company": self.provider_b.id, "name": self.category_b.name},
            format="json",
        )
        miss = api.post(
            CATEGORY_LIST_URL,
            {"company": self.provider_b.id, "name": "Definitely Not There"},
            format="json",
        )
        # Same status...
        self.assertEqual(hit.status_code, 403, hit.data)
        self.assertEqual(miss.status_code, 403, miss.data)
        # ...and the same body. Equal status codes alone would still leak
        # if the payloads differed.
        self.assertEqual(hit.data, miss.data)
        self.assertEqual(
            hit.data.get("code"), "catalog_cross_company_forbidden"
        )
        # And nothing was written into the rival's catalog either way.
        self.assertFalse(
            ServiceCategory.objects.filter(
                company=self.provider_b, name="Definitely Not There"
            ).exists()
        )

    def test_super_admin_explicit_company_still_gets_the_friendly_400(self):
        """The pre-check must still WORK for an actor in scope — a
        SUPER_ADMIN's scope is `None`, so the queryset comes back
        unfiltered."""
        response = self._api(self.super_admin).post(
            CATEGORY_LIST_URL,
            {"company": self.provider_a.id, "name": self.category.name},
            format="json",
        )
        self.assertEqual(response.status_code, 400, response.data)
        self.assertIn(
            "service_category_name_not_unique",
            self._error_code(response, "name"),
        )

    def test_company_admin_explicit_own_company_gets_the_friendly_400(self):
        response = self._api(self.pa_a).post(
            CATEGORY_LIST_URL,
            {"company": self.provider_a.id, "name": self.category.name},
            format="json",
        )
        self.assertEqual(response.status_code, 400, response.data)
        self.assertIn(
            "service_category_name_not_unique",
            self._error_code(response, "name"),
        )

    def test_rename_to_a_duplicate_is_a_400(self):
        """The PATCH path, where `exclude(pk=self.instance.pk)` is the
        only thing between a rename and a false positive — so this is
        also the regression guard for that self-exclusion."""
        other = ServiceCategory.objects.create(
            company=self.provider_a, name="Rename Target"
        )
        response = self._api(self.pa_a).patch(
            f"{CATEGORY_LIST_URL}{other.id}/",
            {"name": self.category.name},
            format="json",
        )
        self.assertEqual(response.status_code, 400, response.data)
        other.refresh_from_db()
        self.assertEqual(other.name, "Rename Target")

    def test_renaming_a_category_to_its_own_name_is_not_a_duplicate(self):
        """The self-exclusion working in the other direction: a no-op
        rename must not collide with the row being renamed."""
        response = self._api(self.pa_a).patch(
            f"{CATEGORY_LIST_URL}{self.category.id}/",
            {"name": self.category.name, "description": "touched"},
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.data)

    # -- ManagedUnit (the ORIGINAL of the shape, Sprint 123) -------------
    def test_managed_unit_foreign_probe_is_indistinguishable(self):
        ManagedUnit.objects.create(company=self.provider_b, label="pallet")
        api = self._api(self.pa_a)
        hit = api.post(
            UNITS_URL,
            {"company": self.provider_b.id, "label": "pallet"},
            format="json",
        )
        miss = api.post(
            UNITS_URL,
            {"company": self.provider_b.id, "label": "not-there-at-all"},
            format="json",
        )
        self.assertEqual(hit.status_code, 403, hit.data)
        self.assertEqual(miss.status_code, 403, miss.data)
        self.assertEqual(hit.data, miss.data)
        self.assertFalse(
            ManagedUnit.objects.filter(
                company=self.provider_b, label="not-there-at-all"
            ).exists()
        )

    def test_managed_unit_super_admin_explicit_company_still_400s(self):
        ManagedUnit.objects.create(company=self.provider_a, label="m3")
        response = self._api(self.super_admin).post(
            UNITS_URL,
            {"company": self.provider_a.id, "label": "  M3 "},
            format="json",
        )
        self.assertEqual(response.status_code, 400, response.data)
        self.assertIn(
            "managed_unit_label_not_unique",
            self._error_code(response, "label"),
        )

    def test_managed_unit_rename_to_a_duplicate_is_a_400(self):
        ManagedUnit.objects.create(company=self.provider_a, label="m3")
        other = ManagedUnit.objects.create(
            company=self.provider_a, label="pallet"
        )
        response = self._api(self.pa_a).patch(
            f"{UNITS_URL}{other.id}/", {"label": "m3"}, format="json"
        )
        self.assertEqual(response.status_code, 400, response.data)
        other.refresh_from_db()
        self.assertEqual(other.label, "pallet")

    def test_managed_unit_rename_to_its_own_label_is_allowed(self):
        unit = ManagedUnit.objects.create(company=self.provider_a, label="m3")
        response = self._api(self.pa_a).patch(
            f"{UNITS_URL}{unit.id}/", {"label": "m3"}, format="json"
        )
        self.assertEqual(response.status_code, 200, response.data)


# ---------------------------------------------------------------------------
# Sprint 142 — category READ scoping (the leak this sprint closes) and the
# Service <-> category same-company rule
# ---------------------------------------------------------------------------
class CategoryReadScopeTests(TwoProviderFixtureMixin, TestCase):
    """RBAC H-1. Category GET is open to any authenticated user, because
    a CUSTOMER_USER needs it to populate the Extra Work cart form. While
    `filter_categories_for` was the identity that meant every customer
    of every provider could enumerate EVERY provider's category names.
    """

    @classmethod
    def setUpTestData(cls):
        cls._setup_fixture()

    def _names(self, user):
        response = self._api(user).get(CATEGORY_LIST_URL)
        self.assertEqual(response.status_code, 200, response.data)
        return {row["name"] for row in response.data["results"]}, {
            row["id"] for row in response.data["results"]
        }

    def test_customer_user_cannot_enumerate_another_providers_categories(self):
        """THE test that locks the leak shut."""
        names, ids = self._names(self.cust_user_a)
        self.assertIn(self.category.id, ids)
        self.assertNotIn(self.category_b.id, ids)

    def test_customer_user_gets_404_on_a_foreign_category_by_id(self):
        response = self._api(self.cust_user_a).get(
            f"{CATEGORY_LIST_URL}{self.category_b.id}/"
        )
        self.assertEqual(response.status_code, 404)

    def test_company_admin_and_bm_and_staff_are_scoped_too(self):
        for user in (self.pa_a, self.bm_a, self.staff_a):
            with self.subTest(user=user.email):
                _names, ids = self._names(user)
                self.assertIn(self.category.id, ids)
                self.assertNotIn(self.category_b.id, ids)

    def test_super_admin_sees_every_companys_categories(self):
        _names, ids = self._names(self.super_admin)
        self.assertIn(self.category.id, ids)
        self.assertIn(self.category_b.id, ids)

    def test_company_param_narrows_and_cannot_widen(self):
        """Same rule the services list documents: `?company=` is applied
        BEFORE the scope filter, so it can only ever narrow."""
        sa_response = self._api(self.super_admin).get(
            CATEGORY_LIST_URL, {"company": self.provider_b.id}
        )
        self.assertEqual(
            {row["id"] for row in sa_response.data["results"]},
            {self.category_b.id},
        )

        ca_response = self._api(self.pa_a).get(
            CATEGORY_LIST_URL, {"company": self.provider_b.id}
        )
        self.assertEqual(ca_response.status_code, 200)
        self.assertEqual(ca_response.data["results"], [])

    def test_company_param_garbage_is_empty_not_500(self):
        response = self._api(self.super_admin).get(
            CATEGORY_LIST_URL, {"company": "not-an-int"}
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["results"], [])


class ServiceCategorySameCompanyTests(TwoProviderFixtureMixin, TestCase):
    """Sprint 142 — a Service's `category` must belong to the Service's
    own company. Nothing enforced this before, because there was nothing
    to enforce. HTTP 400, not 403: the actor may write here, the VALUE is
    just not a legal one (same call as `_enforce_same_company_managed_
    unit`)."""

    @classmethod
    def setUpTestData(cls):
        cls._setup_fixture()

    def test_company_admin_cannot_file_a_service_under_a_foreign_category(self):
        response = self._api(self.pa_a).post(
            SERVICE_LIST_URL,
            {
                "category": self.category_b.id,
                "name": "cross-category-attempt",
                "unit_type": ExtraWorkPricingUnitType.HOURS,
                "default_unit_price": "10.00",
            },
            format="json",
        )
        self.assertEqual(response.status_code, 400, response.data)
        self.assertIn(
            "category_company_mismatch",
            self._error_code(response, "category"),
        )
        self.assertFalse(
            Service.objects.filter(name="cross-category-attempt").exists()
        )

    def test_super_admin_cannot_either(self):
        """A SUPER_ADMIN may write to any company, but this is a data
        rule, not a permission one — it binds every actor."""
        response = self._api(self.super_admin).post(
            SERVICE_LIST_URL,
            {
                "company": self.provider_a.id,
                "category": self.category_b.id,
                "name": "sa-cross-category-attempt",
                "unit_type": ExtraWorkPricingUnitType.HOURS,
                "default_unit_price": "10.00",
            },
            format="json",
        )
        self.assertEqual(response.status_code, 400, response.data)
        self.assertIn(
            "category_company_mismatch",
            self._error_code(response, "category"),
        )

    def test_service_cannot_be_moved_into_a_foreign_category_on_update(self):
        response = self._api(self.pa_a).patch(
            f"{SERVICE_LIST_URL}{self.svc_a.id}/",
            {"category": self.category_b.id},
            format="json",
        )
        self.assertEqual(response.status_code, 400, response.data)
        self.assertIn(
            "category_company_mismatch",
            self._error_code(response, "category"),
        )
        self.svc_a.refresh_from_db()
        self.assertEqual(self.svc_a.category_id, self.category.id)

    def test_unrelated_patch_does_not_revalidate_category(self):
        """The guard is keyed on `"category" in validated_data`, so a
        PATCH that never sends the field is untouched by it."""
        response = self._api(self.pa_a).patch(
            f"{SERVICE_LIST_URL}{self.svc_a.id}/",
            {"is_active": False},
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.data)
        self.svc_a.refresh_from_db()
        self.assertFalse(self.svc_a.is_active)
        self.svc_a.is_active = True
        self.svc_a.save(update_fields=["is_active"])

    def test_own_category_is_accepted(self):
        response = self._api(self.pa_a).post(
            SERVICE_LIST_URL,
            {
                "category": self.category.id,
                "name": "same-company-ok",
                "unit_type": ExtraWorkPricingUnitType.HOURS,
                "default_unit_price": "10.00",
            },
            format="json",
        )
        self.assertEqual(response.status_code, 201, response.data)


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
                    # P-16 repin - the per-line requested_date was
                    # retired (P-8 §4); preferred_date is request-level.
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
                    # P-16 repin - the per-line requested_date was
                    # retired (P-8 §4); preferred_date is request-level.
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

        cat = ServiceCategory.objects.get_or_create(
            company=helper_company, name="Backfill Cat"
        )[0]
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
