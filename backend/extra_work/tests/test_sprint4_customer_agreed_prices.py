"""
Sprint 4B — customer-side agreed-price read access, copy-from-
provider-default action, and soft-archive DELETE semantics on
CustomerServicePrice.

Locks the contract from
`docs/product/Osius_Source_of_Truth_FINAL_2026-05-30.md` §5.7 +
§5.9 plus the Sprint 4 checklist:

  * Customer users see only their own active / currently-valid
    agreed prices.
  * Provider default prices are never exposed by this endpoint.
  * Provider operators can seed CSP rows from
    `Service.default_unit_price` / `default_vat_pct` via a
    dedicated action (idempotent overlap-skip).
  * `DELETE /api/customers/<cid>/pricing/<pid>/` flips
    `is_active=False` instead of hard-deleting (preserves the FK
    target of Sprint 2A snapshots).
"""
from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from accounts.models import UserRole
from audit.models import AuditAction, AuditLog
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
    Service,
    ServiceCategory,
)


User = get_user_model()
PASSWORD = "StrongerTestPassword123!"


def _mk(email: str, role: str, **extra) -> User:
    return User.objects.create_user(
        email=email,
        password=PASSWORD,
        role=role,
        full_name=email.split("@")[0],
        **extra,
    )


class Sprint4BFixtureMixin:
    """
    Two-provider fixture covering every Sprint 4B actor.

    Roles:
      * super_admin                — global
      * pa_a                       — COMPANY_ADMIN of provider_a
      * pa_b                       — COMPANY_ADMIN of provider_b
      * bm_a                       — BUILDING_MANAGER of building_a1
      * staff_a                    — STAFF
      * cust_user_a                — CUSTOMER_USER under customer_a
                                      (basic access)
      * cust_loc_a                 — CUSTOMER_USER under customer_a
                                      (CUSTOMER_LOCATION_MANAGER)
      * cust_cca_a                 — CUSTOMER_USER under customer_a
                                      (CUSTOMER_COMPANY_ADMIN-side)
      * cust_user_b                — CUSTOMER_USER under customer_b
                                      (to verify cross-customer block)
      * cust_user_a_inactive       — CUSTOMER_USER under customer_a
                                      with INACTIVE access row
                                      (must be 403)

    Catalog:
      * svc_a (priced)             — provider_a, has CSP for cust A
      * svc_a_other (priced)       — provider_a, second active CSP
      * svc_b (priced)             — provider_b
    """

    @classmethod
    def _setup_fixture(cls):
        cls.provider_a = Company.objects.create(
            name="Provider A S4B", slug="prov-a-s4b"
        )
        cls.provider_b = Company.objects.create(
            name="Provider B S4B", slug="prov-b-s4b"
        )
        cls.building_a1 = Building.objects.create(
            company=cls.provider_a, name="A1-S4B"
        )
        cls.building_b1 = Building.objects.create(
            company=cls.provider_b, name="B1-S4B"
        )
        cls.customer_a = Customer.objects.create(
            company=cls.provider_a,
            name="Customer A S4B",
            building=cls.building_a1,
        )
        cls.customer_b = Customer.objects.create(
            company=cls.provider_b,
            name="Customer B S4B",
            building=cls.building_b1,
        )
        CustomerBuildingMembership.objects.create(
            customer=cls.customer_a, building=cls.building_a1
        )
        CustomerBuildingMembership.objects.create(
            customer=cls.customer_b, building=cls.building_b1
        )

        cls.super_admin = _mk(
            "super-s4b@example.com",
            UserRole.SUPER_ADMIN,
            is_staff=True,
            is_superuser=True,
        )
        cls.pa_a = _mk("pa-a-s4b@example.com", UserRole.COMPANY_ADMIN)
        CompanyUserMembership.objects.create(
            user=cls.pa_a, company=cls.provider_a
        )
        cls.pa_b = _mk("pa-b-s4b@example.com", UserRole.COMPANY_ADMIN)
        CompanyUserMembership.objects.create(
            user=cls.pa_b, company=cls.provider_b
        )
        cls.bm_a = _mk("bm-a-s4b@example.com", UserRole.BUILDING_MANAGER)
        BuildingManagerAssignment.objects.create(
            user=cls.bm_a, building=cls.building_a1
        )
        cls.staff_a = _mk("staff-a-s4b@example.com", UserRole.STAFF)

        # Customer-side actors with the three access roles.
        cls.cust_user_a = _mk(
            "cu-basic-s4b@example.com", UserRole.CUSTOMER_USER
        )
        m_user = CustomerUserMembership.objects.create(
            customer=cls.customer_a, user=cls.cust_user_a
        )
        CustomerUserBuildingAccess.objects.create(
            membership=m_user,
            building=cls.building_a1,
            access_role=CustomerUserBuildingAccess.AccessRole.CUSTOMER_USER,
            is_active=True,
        )

        cls.cust_loc_a = _mk(
            "cu-loc-s4b@example.com", UserRole.CUSTOMER_USER
        )
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

        cls.cust_cca_a = _mk(
            "cu-cca-s4b@example.com", UserRole.CUSTOMER_USER
        )
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

        cls.cust_user_b = _mk(
            "cu-b-s4b@example.com", UserRole.CUSTOMER_USER
        )
        m_b = CustomerUserMembership.objects.create(
            customer=cls.customer_b, user=cls.cust_user_b
        )
        CustomerUserBuildingAccess.objects.create(
            membership=m_b,
            building=cls.building_b1,
            access_role=CustomerUserBuildingAccess.AccessRole.CUSTOMER_USER,
            is_active=True,
        )

        # Customer A user with INACTIVE access — must be forbidden.
        cls.cust_user_a_inactive = _mk(
            "cu-inactive-s4b@example.com", UserRole.CUSTOMER_USER
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

        # Catalog.
        cls.category = ServiceCategory.objects.create(name="Cleaning S4B")
        cls.svc_a = Service.objects.create(
            company=cls.provider_a,
            category=cls.category,
            name="Window cleaning A S4B",
            unit_type=ExtraWorkPricingUnitType.HOURS,
            default_unit_price=Decimal("50.00"),
            default_vat_pct=Decimal("21.00"),
        )
        cls.svc_a_other = Service.objects.create(
            company=cls.provider_a,
            category=cls.category,
            name="Floor cleaning A S4B",
            unit_type=ExtraWorkPricingUnitType.SQUARE_METERS,
            default_unit_price=Decimal("4.00"),
            default_vat_pct=Decimal("21.00"),
        )
        cls.svc_a_inactive = Service.objects.create(
            company=cls.provider_a,
            category=cls.category,
            name="Discontinued A S4B",
            unit_type=ExtraWorkPricingUnitType.FIXED,
            default_unit_price=Decimal("99.00"),
            default_vat_pct=Decimal("21.00"),
            is_active=False,
        )
        cls.svc_b = Service.objects.create(
            company=cls.provider_b,
            category=cls.category,
            name="Window cleaning B S4B",
            unit_type=ExtraWorkPricingUnitType.HOURS,
            default_unit_price=Decimal("60.00"),
            default_vat_pct=Decimal("21.00"),
        )

    def _api(self, user):
        c = APIClient()
        c.force_authenticate(user=user)
        return c

    def _list_url(self, customer):
        return f"/api/customers/{customer.id}/pricing/"

    def _detail_url(self, customer, price):
        return f"/api/customers/{customer.id}/pricing/{price.id}/"

    def _copy_url(self, customer):
        return f"/api/customers/{customer.id}/pricing/copy-from-default/"

    def _error_codes(self, response, field):
        errors = response.data.get(field, [])
        if isinstance(errors, dict):
            errors = [errors]
        codes = []
        for err in errors:
            if hasattr(err, "code"):
                codes.append(err.code)
        return codes


# ---------------------------------------------------------------------------
# 1-10 — Customer-side read access
# ---------------------------------------------------------------------------
class CustomerSideReadTests(Sprint4BFixtureMixin, TestCase):
    @classmethod
    def setUpTestData(cls):
        cls._setup_fixture()
        today = date(2026, 6, 1)
        cls.price_active = CustomerServicePrice.objects.create(
            service=cls.svc_a,
            customer=cls.customer_a,
            unit_price=Decimal("48.50"),
            vat_pct=Decimal("21.00"),
            valid_from=today - timedelta(days=30),
            valid_to=None,
            is_active=True,
        )
        cls.price_expired = CustomerServicePrice.objects.create(
            service=cls.svc_a_other,
            customer=cls.customer_a,
            unit_price=Decimal("3.50"),
            vat_pct=Decimal("21.00"),
            valid_from=date(2025, 1, 1),
            valid_to=date(2025, 12, 31),
            is_active=True,
        )
        cls.price_inactive = CustomerServicePrice.objects.create(
            service=cls.svc_a,
            customer=cls.customer_a,
            unit_price=Decimal("999.00"),
            vat_pct=Decimal("21.00"),
            valid_from=today - timedelta(days=30),
            valid_to=None,
            is_active=False,
        )
        cls.price_future = CustomerServicePrice.objects.create(
            service=cls.svc_a_other,
            customer=cls.customer_a,
            unit_price=Decimal("5.00"),
            vat_pct=Decimal("21.00"),
            valid_from=today + timedelta(days=365),
            valid_to=None,
            is_active=True,
        )

    def test_1_basic_customer_user_can_list_own_active_current_prices(self):
        response = self._api(self.cust_user_a).get(
            self._list_url(self.customer_a)
        )
        self.assertEqual(response.status_code, 200, response.data)
        ids = {row["id"] for row in response.data["results"]}
        self.assertIn(self.price_active.id, ids)
        # Expired / inactive / future filtered out by default.
        self.assertNotIn(self.price_expired.id, ids)
        self.assertNotIn(self.price_inactive.id, ids)
        self.assertNotIn(self.price_future.id, ids)

    def test_2_customer_location_manager_can_list_own_prices(self):
        response = self._api(self.cust_loc_a).get(
            self._list_url(self.customer_a)
        )
        self.assertEqual(response.status_code, 200, response.data)
        ids = {row["id"] for row in response.data["results"]}
        self.assertIn(self.price_active.id, ids)

    def test_3_customer_company_admin_can_list_own_prices(self):
        response = self._api(self.cust_cca_a).get(
            self._list_url(self.customer_a)
        )
        self.assertEqual(response.status_code, 200, response.data)
        ids = {row["id"] for row in response.data["results"]}
        self.assertIn(self.price_active.id, ids)

    def test_4_customer_user_cannot_list_other_customer_prices(self):
        response = self._api(self.cust_user_a).get(
            self._list_url(self.customer_b)
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(
            response.data.get("code"), "customer_price_read_forbidden"
        )

    def test_5_customer_user_sees_only_active_current_rows(self):
        response = self._api(self.cust_user_a).get(
            self._list_url(self.customer_a)
        )
        self.assertEqual(response.status_code, 200)
        for row in response.data["results"]:
            self.assertNotEqual(row["id"], self.price_expired.id)
            self.assertNotEqual(row["id"], self.price_inactive.id)
            self.assertNotEqual(row["id"], self.price_future.id)

    def test_6_valid_on_filter_works_for_past_and_future_dates(self):
        # Past date — should surface the expired row.
        past = "2025-06-15"
        response = self._api(self.cust_user_a).get(
            f"{self._list_url(self.customer_a)}?valid_on={past}"
        )
        self.assertEqual(response.status_code, 200)
        ids = {row["id"] for row in response.data["results"]}
        self.assertIn(self.price_expired.id, ids)
        # Future date — surfaces the future row.
        future = "2030-01-01"
        response2 = self._api(self.cust_user_a).get(
            f"{self._list_url(self.customer_a)}?valid_on={future}"
        )
        self.assertEqual(response2.status_code, 200)
        ids2 = {row["id"] for row in response2.data["results"]}
        self.assertIn(self.price_future.id, ids2)

    def test_7_invalid_valid_on_returns_400_with_stable_code(self):
        response = self._api(self.cust_user_a).get(
            f"{self._list_url(self.customer_a)}?valid_on=not-a-date"
        )
        self.assertEqual(response.status_code, 400)
        codes = self._error_codes(response, "valid_on")
        self.assertIn("invalid_valid_on", codes)

    def test_8_customer_side_post_patch_delete_forbidden(self):
        api = self._api(self.cust_user_a)
        # POST
        post = api.post(
            self._list_url(self.customer_a),
            {
                "service": self.svc_a.id,
                "unit_price": "10.00",
                "valid_from": "2026-01-01",
            },
            format="json",
        )
        self.assertEqual(post.status_code, 403)
        # PATCH
        patch = api.patch(
            self._detail_url(self.customer_a, self.price_active),
            {"unit_price": "1.00"},
            format="json",
        )
        self.assertEqual(patch.status_code, 403)
        # DELETE
        delete = api.delete(
            self._detail_url(self.customer_a, self.price_active)
        )
        self.assertEqual(delete.status_code, 403)
        # And the row is still active.
        self.price_active.refresh_from_db()
        self.assertTrue(self.price_active.is_active)

    def test_9_response_does_not_include_provider_default_fields(self):
        # CustomerServicePriceSerializer's existing field list never
        # included default_unit_price / default_vat_pct — assert
        # defensively here so a future refactor cannot leak them.
        response = self._api(self.cust_user_a).get(
            self._list_url(self.customer_a)
        )
        self.assertEqual(response.status_code, 200)
        for row in response.data["results"]:
            self.assertNotIn("default_unit_price", row)
            self.assertNotIn("default_vat_pct", row)

    def test_10_foreign_company_csp_does_not_leak_to_customer_list(self):
        # Force-create a CSP row referencing Provider B's service for
        # customer A. The create serializer would normally reject this
        # via `service_customer_company_mismatch`, but a direct ORM
        # write (e.g. legacy data) could land such a row. The
        # customer-side list must filter it out.
        rogue = CustomerServicePrice.objects.create(
            service=self.svc_b,
            customer=self.customer_a,
            unit_price=Decimal("1.00"),
            vat_pct=Decimal("21.00"),
            valid_from=date(2026, 1, 1),
            is_active=True,
        )
        response = self._api(self.cust_user_a).get(
            self._list_url(self.customer_a)
        )
        self.assertEqual(response.status_code, 200)
        ids = {row["id"] for row in response.data["results"]}
        self.assertNotIn(rogue.id, ids)

    def test_inactive_access_user_blocked(self):
        # Sanity test: a customer user without an active building
        # access row must be denied (in addition to the 10 mandated
        # tests above; not numbered).
        response = self._api(self.cust_user_a_inactive).get(
            self._list_url(self.customer_a)
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(
            response.data.get("code"), "customer_price_read_forbidden"
        )

    def test_bm_blocked_on_customer_side_read(self):
        response = self._api(self.bm_a).get(
            self._list_url(self.customer_a)
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(
            response.data.get("code"), "customer_price_read_forbidden"
        )

    def test_staff_blocked_on_customer_side_read(self):
        response = self._api(self.staff_a).get(
            self._list_url(self.customer_a)
        )
        self.assertEqual(response.status_code, 403)


# ---------------------------------------------------------------------------
# 11-13 — Provider regression
# ---------------------------------------------------------------------------
class ProviderRegressionTests(Sprint4BFixtureMixin, TestCase):
    @classmethod
    def setUpTestData(cls):
        cls._setup_fixture()
        cls.price = CustomerServicePrice.objects.create(
            service=cls.svc_a,
            customer=cls.customer_a,
            unit_price=Decimal("48.50"),
            vat_pct=Decimal("21.00"),
            valid_from=date(2026, 1, 1),
            is_active=True,
        )

    def test_11_super_admin_can_list_create_update(self):
        api = self._api(self.super_admin)
        list_resp = api.get(self._list_url(self.customer_a))
        self.assertEqual(list_resp.status_code, 200)

        post = api.post(
            self._list_url(self.customer_a),
            {
                "service": self.svc_a_other.id,
                "unit_price": "3.50",
                "valid_from": "2026-02-01",
            },
            format="json",
        )
        self.assertEqual(post.status_code, 201, post.data)
        new_id = post.data["id"]

        patch = api.patch(
            f"{self._list_url(self.customer_a)}{new_id}/",
            {"unit_price": "4.00"},
            format="json",
        )
        self.assertEqual(patch.status_code, 200, patch.data)

    def test_12_company_admin_can_crud_when_toggle_true(self):
        api = self._api(self.pa_a)
        post = api.post(
            self._list_url(self.customer_a),
            {
                "service": self.svc_a_other.id,
                "unit_price": "3.50",
                "valid_from": "2026-02-01",
            },
            format="json",
        )
        self.assertEqual(post.status_code, 201, post.data)

    def test_13_company_admin_blocked_when_toggle_false(self):
        self.provider_a.provider_admin_may_manage_customer_prices = False
        self.provider_a.save(
            update_fields=[
                "provider_admin_may_manage_customer_prices",
            ]
        )
        api = self._api(self.pa_a)
        post = api.post(
            self._list_url(self.customer_a),
            {
                "service": self.svc_a_other.id,
                "unit_price": "3.50",
                "valid_from": "2026-02-01",
            },
            format="json",
        )
        self.assertEqual(post.status_code, 403)
        self.assertEqual(
            post.data.get("code"),
            "provider_admin_customer_price_management_disabled",
        )


# ---------------------------------------------------------------------------
# 14-23 — Copy-from-default action
# ---------------------------------------------------------------------------
class CopyFromDefaultTests(Sprint4BFixtureMixin, TestCase):
    @classmethod
    def setUpTestData(cls):
        cls._setup_fixture()

    def _payload(self, service_ids, valid_from="2026-07-01", valid_to=None):
        return {
            "services": service_ids,
            "valid_from": valid_from,
            "valid_to": valid_to,
        }

    def test_14_super_admin_can_copy_single_and_multiple_services(self):
        api = self._api(self.super_admin)
        response = api.post(
            self._copy_url(self.customer_a),
            self._payload([self.svc_a.id, self.svc_a_other.id]),
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["created_count"], 2)
        self.assertEqual(response.data["skipped_count"], 0)
        # Newly-created rows reflect Service.default_* values.
        for r in response.data["results"]:
            self.assertEqual(r["status"], "created")
            row = CustomerServicePrice.objects.get(
                pk=r["customer_service_price"]
            )
            if row.service_id == self.svc_a.id:
                self.assertEqual(row.unit_price, Decimal("50.00"))
                self.assertEqual(row.vat_pct, Decimal("21.00"))
            else:
                self.assertEqual(row.unit_price, Decimal("4.00"))

    def test_15_company_admin_can_copy_own_company_services_when_toggle_true(self):
        api = self._api(self.pa_a)
        response = api.post(
            self._copy_url(self.customer_a),
            self._payload([self.svc_a.id]),
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["created_count"], 1)

    def test_16_company_admin_blocked_when_toggle_false(self):
        self.provider_a.provider_admin_may_manage_customer_prices = False
        self.provider_a.save(
            update_fields=[
                "provider_admin_may_manage_customer_prices",
            ]
        )
        api = self._api(self.pa_a)
        response = api.post(
            self._copy_url(self.customer_a),
            self._payload([self.svc_a.id]),
            format="json",
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(
            response.data.get("code"),
            "provider_admin_customer_price_management_disabled",
        )

    def test_17_company_admin_cannot_copy_for_another_company_customer(self):
        # PA-A acting on customer_b (provider_b) — IsSuperAdminOr
        # CompanyAdminForCompany rejects at the object check.
        api = self._api(self.pa_a)
        response = api.post(
            self._copy_url(self.customer_b),
            self._payload([self.svc_b.id]),
            format="json",
        )
        self.assertEqual(response.status_code, 403)

    def test_18_cross_company_service_rejected(self):
        api = self._api(self.super_admin)
        response = api.post(
            self._copy_url(self.customer_a),
            self._payload([self.svc_b.id]),  # svc_b lives in provider_b
            format="json",
        )
        self.assertEqual(response.status_code, 400, response.data)
        codes = self._error_codes(response, "services")
        self.assertIn("service_customer_company_mismatch", codes)
        # Defensive: no rows written.
        self.assertEqual(
            CustomerServicePrice.objects.filter(
                customer=self.customer_a, service=self.svc_b
            ).count(),
            0,
        )

    def test_19_inactive_service_rejected(self):
        api = self._api(self.super_admin)
        response = api.post(
            self._copy_url(self.customer_a),
            self._payload([self.svc_a_inactive.id]),
            format="json",
        )
        self.assertEqual(response.status_code, 400, response.data)
        codes = self._error_codes(response, "services")
        self.assertIn("copy_from_default_service_invalid", codes)

    def test_20_existing_overlapping_active_price_skipped(self):
        # Seed an active overlapping row for svc_a, then ask to copy.
        CustomerServicePrice.objects.create(
            service=self.svc_a,
            customer=self.customer_a,
            unit_price=Decimal("48.50"),
            vat_pct=Decimal("21.00"),
            valid_from=date(2026, 1, 1),
            valid_to=None,
            is_active=True,
        )
        api = self._api(self.super_admin)
        response = api.post(
            self._copy_url(self.customer_a),
            self._payload([self.svc_a.id], valid_from="2026-07-01"),
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["created_count"], 0)
        self.assertEqual(response.data["skipped_count"], 1)
        self.assertEqual(
            response.data["results"][0]["status"], "skipped_existing"
        )
        # Total CSP rows for the (service, customer) pair stays at 1.
        self.assertEqual(
            CustomerServicePrice.objects.filter(
                service=self.svc_a, customer=self.customer_a
            ).count(),
            1,
        )

    def test_21_non_overlapping_window_creates_new_row(self):
        # Seed an active row valid 2025 only; copy with valid_from
        # 2026 — non-overlapping → CREATE.
        CustomerServicePrice.objects.create(
            service=self.svc_a,
            customer=self.customer_a,
            unit_price=Decimal("48.50"),
            vat_pct=Decimal("21.00"),
            valid_from=date(2025, 1, 1),
            valid_to=date(2025, 12, 31),
            is_active=True,
        )
        api = self._api(self.super_admin)
        response = api.post(
            self._copy_url(self.customer_a),
            self._payload([self.svc_a.id], valid_from="2026-01-01"),
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["created_count"], 1)

    def test_22_copied_row_immune_to_service_default_edit(self):
        api = self._api(self.super_admin)
        response = api.post(
            self._copy_url(self.customer_a),
            self._payload([self.svc_a.id]),
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.data)
        new_id = response.data["results"][0]["customer_service_price"]
        row = CustomerServicePrice.objects.get(pk=new_id)
        self.assertEqual(row.unit_price, Decimal("50.00"))

        # Mutate Service.default_unit_price + default_vat_pct after
        # the copy.
        self.svc_a.default_unit_price = Decimal("999.00")
        self.svc_a.default_vat_pct = Decimal("9.00")
        self.svc_a.save(
            update_fields=[
                "default_unit_price",
                "default_vat_pct",
            ]
        )
        row.refresh_from_db()
        self.assertEqual(row.unit_price, Decimal("50.00"))
        self.assertEqual(row.vat_pct, Decimal("21.00"))

    def test_23_copy_creates_audit_row_with_reason_marker(self):
        # Establish a baseline CREATE-count before the action.
        before = AuditLog.objects.filter(
            target_model="extra_work.CustomerServicePrice",
            action=AuditAction.CREATE,
        ).count()
        response = self._api(self.super_admin).post(
            self._copy_url(self.customer_a),
            self._payload([self.svc_a.id, self.svc_a_other.id]),
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.data)
        after = AuditLog.objects.filter(
            target_model="extra_work.CustomerServicePrice",
            action=AuditAction.CREATE,
        ).count()
        self.assertEqual(after, before + 2)

        # The audit context reason marker should land on the CSP
        # CREATE rows.
        recent = AuditLog.objects.filter(
            target_model="extra_work.CustomerServicePrice",
            action=AuditAction.CREATE,
        ).order_by("-id")[:2]
        reasons = {row.reason for row in recent}
        self.assertEqual(reasons, {"copy_from_provider_default"})

    def test_customer_user_cannot_call_copy_action(self):
        # Extra defensive coverage (not numbered in the brief but
        # required by §B "Forbidden" rules).
        api = self._api(self.cust_user_a)
        response = api.post(
            self._copy_url(self.customer_a),
            self._payload([self.svc_a.id]),
            format="json",
        )
        self.assertEqual(response.status_code, 403)

    def test_bm_and_staff_cannot_call_copy_action(self):
        for actor in (self.bm_a, self.staff_a):
            with self.subTest(actor=actor.email):
                response = self._api(actor).post(
                    self._copy_url(self.customer_a),
                    self._payload([self.svc_a.id]),
                    format="json",
                )
                self.assertEqual(response.status_code, 403)

    def test_copy_rejects_missing_valid_from(self):
        api = self._api(self.super_admin)
        response = api.post(
            self._copy_url(self.customer_a),
            {"services": [self.svc_a.id]},
            format="json",
        )
        self.assertEqual(response.status_code, 400)

    def test_copy_rejects_empty_services_list(self):
        api = self._api(self.super_admin)
        response = api.post(
            self._copy_url(self.customer_a),
            self._payload([]),
            format="json",
        )
        self.assertEqual(response.status_code, 400)


# ---------------------------------------------------------------------------
# 24-29 — Soft-archive DELETE
# ---------------------------------------------------------------------------
class SoftArchiveDeleteTests(Sprint4BFixtureMixin, TestCase):
    @classmethod
    def setUpTestData(cls):
        cls._setup_fixture()

    def setUp(self):
        # Create a fresh CSP per test so the DELETE pass is hermetic.
        self.price = CustomerServicePrice.objects.create(
            service=self.svc_a,
            customer=self.customer_a,
            unit_price=Decimal("48.50"),
            vat_pct=Decimal("21.00"),
            valid_from=date(2026, 1, 1),
            is_active=True,
        )

    def test_24_delete_sets_is_active_false_and_row_remains(self):
        before_count = CustomerServicePrice.objects.filter(
            pk=self.price.pk
        ).count()
        self.assertEqual(before_count, 1)
        api = self._api(self.super_admin)
        response = api.delete(self._detail_url(self.customer_a, self.price))
        self.assertEqual(response.status_code, 204)
        self.price.refresh_from_db()
        self.assertFalse(self.price.is_active)
        # Row still exists in DB.
        self.assertTrue(
            CustomerServicePrice.objects.filter(pk=self.price.pk).exists()
        )

    def test_25_delete_returns_204(self):
        response = self._api(self.super_admin).delete(
            self._detail_url(self.customer_a, self.price)
        )
        self.assertEqual(response.status_code, 204)

    def test_26_delete_idempotent_when_already_inactive(self):
        # First DELETE archives.
        api = self._api(self.super_admin)
        first = api.delete(self._detail_url(self.customer_a, self.price))
        self.assertEqual(first.status_code, 204)
        # Second DELETE on the same row is also 204 (idempotent).
        second = api.delete(self._detail_url(self.customer_a, self.price))
        self.assertEqual(second.status_code, 204)
        self.price.refresh_from_db()
        self.assertFalse(self.price.is_active)

    def test_27_company_admin_blocked_when_toggle_false(self):
        self.provider_a.provider_admin_may_manage_customer_prices = False
        self.provider_a.save(
            update_fields=[
                "provider_admin_may_manage_customer_prices",
            ]
        )
        api = self._api(self.pa_a)
        response = api.delete(self._detail_url(self.customer_a, self.price))
        self.assertEqual(response.status_code, 403)
        self.assertEqual(
            response.data.get("code"),
            "provider_admin_customer_price_management_disabled",
        )
        # Row remains active.
        self.price.refresh_from_db()
        self.assertTrue(self.price.is_active)

    def test_28_customer_side_delete_forbidden(self):
        for actor in (
            self.cust_user_a,
            self.cust_loc_a,
            self.cust_cca_a,
        ):
            with self.subTest(actor=actor.email):
                response = self._api(actor).delete(
                    self._detail_url(self.customer_a, self.price)
                )
                self.assertEqual(response.status_code, 403)
        self.price.refresh_from_db()
        self.assertTrue(self.price.is_active)

    def test_29_audit_records_is_active_change(self):
        before = AuditLog.objects.filter(
            target_model="extra_work.CustomerServicePrice",
            target_id=self.price.id,
            action=AuditAction.UPDATE,
        ).count()
        response = self._api(self.super_admin).delete(
            self._detail_url(self.customer_a, self.price)
        )
        self.assertEqual(response.status_code, 204)
        after = AuditLog.objects.filter(
            target_model="extra_work.CustomerServicePrice",
            target_id=self.price.id,
            action=AuditAction.UPDATE,
        ).count()
        self.assertEqual(after, before + 1)

        last_update = (
            AuditLog.objects.filter(
                target_model="extra_work.CustomerServicePrice",
                target_id=self.price.id,
                action=AuditAction.UPDATE,
            )
            .order_by("-id")
            .first()
        )
        # Audit reason marker rides along with the soft-archive.
        self.assertEqual(last_update.reason, "customer_price_soft_archive")
        # Diff records is_active flip.
        is_active_change = last_update.changes.get("is_active") or {}
        self.assertEqual(is_active_change.get("before"), True)
        self.assertEqual(is_active_change.get("after"), False)
