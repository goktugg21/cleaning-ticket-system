"""
Sprint 26B — Extra Work MVP backend tests.

Covers the test matrix specified in the Sprint 26B brief:

  * Customer scope (basic / location-manager / company-admin) on
    list + detail + create
  * Provider scope (super-admin / company-admin / building-manager)
  * Customer cannot see provider-internal fields (manager_note,
    internal_cost_note, override_*) anywhere
  * Provider can create pricing line items and backend computes
    totals from quantity / unit_price / vat_rate
  * Customer approve / reject on PRICING_PROPOSED gated by
    `customer.extra_work.approve_own` / `approve_location`
  * Provider override needs a reason
  * Cross-provider URL ID guess returns safe 404
  * Cross-customer-company URL ID guess returns safe 404
"""
from __future__ import annotations

from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
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
    ExtraWorkCategory,
    ExtraWorkPricingLineItem,
    ExtraWorkRequest,
    ExtraWorkStatus,
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


class ExtraWorkFixtureMixin:
    """
    Two-provider, two-customer fixture used by every test class
    below. Mirrors the two-company shape `seed_demo_data` ships,
    but is fully self-contained so the test suite doesn't depend
    on a seeded database.

    Provider A: provider_a (Company)
      buildings: building_a1, building_a2
      customer_a -> linked to (building_a1, building_a2)
      customer_a_alt -> linked to building_a1 only (cross-customer test)
      super_admin (global)
      admin_a (provider COMPANY_ADMIN)
      manager_a1 (provider BUILDING_MANAGER on building_a1)
      manager_a2 (provider BUILDING_MANAGER on building_a2)
      cust_basic_a (CUSTOMER_USER on building_a1 - basic)
      cust_loc_a (CUSTOMER_USER on building_a1 - LOCATION_MANAGER)
      cust_comp_a (CUSTOMER_USER on building_a1 - COMPANY_ADMIN access role)
      cust_alt_basic (CUSTOMER_USER on customer_a_alt - basic)

    Provider B: provider_b (separate Company)
      building_b
      customer_b
      admin_b (provider COMPANY_ADMIN)
    """

    @classmethod
    def _setup_fixture(cls):
        cls.provider_a = Company.objects.create(name="Provider A", slug="prov-a")
        cls.provider_b = Company.objects.create(name="Provider B", slug="prov-b")

        cls.building_a1 = Building.objects.create(
            company=cls.provider_a, name="A1"
        )
        cls.building_a2 = Building.objects.create(
            company=cls.provider_a, name="A2"
        )
        cls.building_b = Building.objects.create(
            company=cls.provider_b, name="B1"
        )

        cls.customer_a = Customer.objects.create(
            company=cls.provider_a, name="Customer A", building=cls.building_a1
        )
        cls.customer_a_alt = Customer.objects.create(
            company=cls.provider_a, name="Customer A-alt", building=cls.building_a1
        )
        cls.customer_b = Customer.objects.create(
            company=cls.provider_b, name="Customer B", building=cls.building_b
        )

        for c, b in [
            (cls.customer_a, cls.building_a1),
            (cls.customer_a, cls.building_a2),
            (cls.customer_a_alt, cls.building_a1),
            (cls.customer_b, cls.building_b),
        ]:
            CustomerBuildingMembership.objects.create(customer=c, building=b)

        cls.super_admin = _mk(
            "super@example.com",
            UserRole.SUPER_ADMIN,
            is_staff=True,
            is_superuser=True,
        )

        cls.admin_a = _mk("admin-a@example.com", UserRole.COMPANY_ADMIN)
        CompanyUserMembership.objects.create(
            user=cls.admin_a, company=cls.provider_a
        )
        cls.admin_b = _mk("admin-b@example.com", UserRole.COMPANY_ADMIN)
        CompanyUserMembership.objects.create(
            user=cls.admin_b, company=cls.provider_b
        )

        cls.manager_a1 = _mk("mgr-a1@example.com", UserRole.BUILDING_MANAGER)
        BuildingManagerAssignment.objects.create(
            user=cls.manager_a1, building=cls.building_a1
        )
        cls.manager_a2 = _mk("mgr-a2@example.com", UserRole.BUILDING_MANAGER)
        BuildingManagerAssignment.objects.create(
            user=cls.manager_a2, building=cls.building_a2
        )

        # Customer-side: three different access roles on the SAME
        # building under customer_a so we can compare scope.
        def _make_customer(email, access_role, customer, building):
            u = _mk(email, UserRole.CUSTOMER_USER)
            m = CustomerUserMembership.objects.create(customer=customer, user=u)
            CustomerUserBuildingAccess.objects.create(
                membership=m, building=building, access_role=access_role
            )
            return u

        cls.cust_basic_a = _make_customer(
            "cust-basic-a@example.com",
            CustomerUserBuildingAccess.AccessRole.CUSTOMER_USER,
            cls.customer_a,
            cls.building_a1,
        )
        cls.cust_loc_a = _make_customer(
            "cust-loc-a@example.com",
            CustomerUserBuildingAccess.AccessRole.CUSTOMER_LOCATION_MANAGER,
            cls.customer_a,
            cls.building_a1,
        )
        # Company-admin gets access rows on BOTH buildings so the
        # view_company scope actually has something to span across.
        cls.cust_comp_a = _mk("cust-comp-a@example.com", UserRole.CUSTOMER_USER)
        comp_membership = CustomerUserMembership.objects.create(
            customer=cls.customer_a, user=cls.cust_comp_a
        )
        for b in [cls.building_a1, cls.building_a2]:
            CustomerUserBuildingAccess.objects.create(
                membership=comp_membership,
                building=b,
                access_role=CustomerUserBuildingAccess.AccessRole.CUSTOMER_COMPANY_ADMIN,
            )

        cls.cust_alt_basic = _make_customer(
            "cust-alt-a@example.com",
            CustomerUserBuildingAccess.AccessRole.CUSTOMER_USER,
            cls.customer_a_alt,
            cls.building_a1,
        )

    def _api(self, user):
        c = APIClient()
        c.force_authenticate(user=user)
        return c

    @staticmethod
    def _make_extra_work(
        *,
        customer,
        building,
        created_by,
        company=None,
        status_value=ExtraWorkStatus.REQUESTED,
        category=ExtraWorkCategory.DEEP_CLEANING,
    ) -> ExtraWorkRequest:
        return ExtraWorkRequest.objects.create(
            company=company or customer.company,
            building=building,
            customer=customer,
            created_by=created_by,
            title=f"EW for {customer.name} @ {building.name}",
            description="placeholder",
            category=category,
            status=status_value,
        )


# ---------------------------------------------------------------------------
# Customer-side scope tests
# ---------------------------------------------------------------------------
class CustomerScopeTests(ExtraWorkFixtureMixin, TestCase):
    @classmethod
    def setUpTestData(cls):
        cls._setup_fixture()
        # One ExtraWork per "interesting" pair.
        cls.ew_a1_basic = cls._make_extra_work(
            customer=cls.customer_a,
            building=cls.building_a1,
            created_by=cls.cust_basic_a,
        )
        # Created by a different user at the same (customer, building):
        # cust_basic_a (view_own only) must NOT see this row.
        cls.ew_a1_other_creator = cls._make_extra_work(
            customer=cls.customer_a,
            building=cls.building_a1,
            created_by=cls.cust_comp_a,
        )
        cls.ew_a2 = cls._make_extra_work(
            customer=cls.customer_a,
            building=cls.building_a2,
            created_by=cls.cust_comp_a,
        )
        # Cross-customer in same provider, same building — must not
        # leak to customer_a users at any access role.
        cls.ew_a_alt = cls._make_extra_work(
            customer=cls.customer_a_alt,
            building=cls.building_a1,
            created_by=cls.cust_alt_basic,
        )
        # Cross-provider.
        cls.ew_b = cls._make_extra_work(
            customer=cls.customer_b,
            building=cls.building_b,
            created_by=cls.admin_b,
        )

    def _list_ids(self, user) -> set[int]:
        response = self._api(user).get("/api/extra-work/")
        self.assertEqual(response.status_code, 200)
        return {row["id"] for row in response.data["results"]}

    def test_customer_basic_sees_only_own_creations(self):
        ids = self._list_ids(self.cust_basic_a)
        self.assertEqual(ids, {self.ew_a1_basic.id})

    def test_customer_location_manager_sees_location_scope(self):
        # LOCATION_MANAGER on building_a1 — sees every EW at (customer_a,
        # building_a1) regardless of creator. building_a2 is out of
        # scope (no access row).
        ids = self._list_ids(self.cust_loc_a)
        self.assertEqual(
            ids,
            {self.ew_a1_basic.id, self.ew_a1_other_creator.id},
        )

    def test_customer_company_admin_sees_company_wide(self):
        # COMPANY_ADMIN access on customer_a (across both buildings) —
        # sees every EW of customer_a regardless of building or creator,
        # but NOT customer_a_alt and NOT customer_b.
        ids = self._list_ids(self.cust_comp_a)
        self.assertEqual(
            ids,
            {
                self.ew_a1_basic.id,
                self.ew_a1_other_creator.id,
                self.ew_a2.id,
            },
        )

    def test_customer_cannot_see_other_customers_under_same_provider(self):
        for actor in (self.cust_basic_a, self.cust_loc_a, self.cust_comp_a):
            ids = self._list_ids(actor)
            self.assertNotIn(self.ew_a_alt.id, ids)

    def test_customer_cannot_see_other_provider_extra_work(self):
        for actor in (self.cust_basic_a, self.cust_loc_a, self.cust_comp_a):
            ids = self._list_ids(actor)
            self.assertNotIn(self.ew_b.id, ids)

    def test_customer_cross_provider_id_guess_returns_404(self):
        # cust_basic_a guesses the URL of ew_b (Provider B). Must 404.
        response = self._api(self.cust_basic_a).get(
            f"/api/extra-work/{self.ew_b.id}/"
        )
        self.assertEqual(response.status_code, 404)

    def test_customer_cross_customer_id_guess_returns_404(self):
        # cust_basic_a (customer_a) guesses the URL of an EW belonging
        # to customer_a_alt (same provider, same building). Must 404.
        response = self._api(self.cust_basic_a).get(
            f"/api/extra-work/{self.ew_a_alt.id}/"
        )
        self.assertEqual(response.status_code, 404)


# ---------------------------------------------------------------------------
# Provider-side scope tests
# ---------------------------------------------------------------------------
class ProviderScopeTests(ExtraWorkFixtureMixin, TestCase):
    @classmethod
    def setUpTestData(cls):
        cls._setup_fixture()
        cls.ew_a1 = cls._make_extra_work(
            customer=cls.customer_a,
            building=cls.building_a1,
            created_by=cls.cust_basic_a,
        )
        cls.ew_a2 = cls._make_extra_work(
            customer=cls.customer_a,
            building=cls.building_a2,
            created_by=cls.cust_comp_a,
        )
        cls.ew_b = cls._make_extra_work(
            customer=cls.customer_b,
            building=cls.building_b,
            created_by=cls.admin_b,
        )

    def _list_ids(self, user):
        response = self._api(user).get("/api/extra-work/")
        self.assertEqual(response.status_code, 200)
        return {row["id"] for row in response.data["results"]}

    def test_super_admin_sees_all_providers(self):
        ids = self._list_ids(self.super_admin)
        self.assertEqual(ids, {self.ew_a1.id, self.ew_a2.id, self.ew_b.id})

    def test_provider_company_admin_sees_only_own_provider(self):
        self.assertEqual(
            self._list_ids(self.admin_a), {self.ew_a1.id, self.ew_a2.id}
        )
        self.assertEqual(self._list_ids(self.admin_b), {self.ew_b.id})

    def test_provider_admin_cross_provider_id_guess_returns_404(self):
        # admin_a tries to GET an EW in Provider B.
        response = self._api(self.admin_a).get(
            f"/api/extra-work/{self.ew_b.id}/"
        )
        self.assertEqual(response.status_code, 404)

    def test_building_manager_sees_only_assigned_building(self):
        # manager_a1 -> only ew_a1. manager_a2 -> only ew_a2.
        self.assertEqual(self._list_ids(self.manager_a1), {self.ew_a1.id})
        self.assertEqual(self._list_ids(self.manager_a2), {self.ew_a2.id})

    def test_building_manager_cross_building_id_guess_returns_404(self):
        # manager_a1 tries to GET the EW in building_a2 (same provider).
        response = self._api(self.manager_a1).get(
            f"/api/extra-work/{self.ew_a2.id}/"
        )
        self.assertEqual(response.status_code, 404)


# ---------------------------------------------------------------------------
# Create tests
# ---------------------------------------------------------------------------
class CreateTests(ExtraWorkFixtureMixin, TestCase):
    @classmethod
    def setUpTestData(cls):
        cls._setup_fixture()

    def _create_payload(self, customer, building, **extra):
        payload = {
            "customer": customer.id,
            "building": building.id,
            "title": "Window cleaning needed",
            "description": "All 3rd-floor windows.",
            "category": ExtraWorkCategory.WINDOW_CLEANING,
        }
        payload.update(extra)
        return payload

    def test_customer_basic_can_create_in_own_building(self):
        response = self._api(self.cust_basic_a).post(
            "/api/extra-work/",
            self._create_payload(self.customer_a, self.building_a1),
            format="json",
        )
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data["status"], ExtraWorkStatus.REQUESTED)

    def test_customer_basic_cannot_create_in_unauthorised_building(self):
        # cust_basic_a has access only on building_a1; customer_a
        # is also linked to building_a2 but the actor has no access
        # row for it.
        response = self._api(self.cust_basic_a).post(
            "/api/extra-work/",
            self._create_payload(self.customer_a, self.building_a2),
            format="json",
        )
        self.assertEqual(response.status_code, 400)

    def test_customer_cannot_create_in_other_customer(self):
        # cust_basic_a tries to create under customer_a_alt.
        response = self._api(self.cust_basic_a).post(
            "/api/extra-work/",
            self._create_payload(self.customer_a_alt, self.building_a1),
            format="json",
        )
        self.assertEqual(response.status_code, 400)

    def test_category_other_requires_other_text(self):
        payload = self._create_payload(
            self.customer_a,
            self.building_a1,
            category=ExtraWorkCategory.OTHER,
        )
        # Missing category_other_text -> 400
        response = self._api(self.cust_basic_a).post(
            "/api/extra-work/", payload, format="json"
        )
        self.assertEqual(response.status_code, 400)
        # With category_other_text -> 201
        payload["category_other_text"] = "Sealant repair"
        response = self._api(self.cust_basic_a).post(
            "/api/extra-work/", payload, format="json"
        )
        self.assertEqual(response.status_code, 201, response.data)


# ---------------------------------------------------------------------------
# Pricing line items + totals
# ---------------------------------------------------------------------------
class PricingTests(ExtraWorkFixtureMixin, TestCase):
    @classmethod
    def setUpTestData(cls):
        cls._setup_fixture()
        cls.ew = cls._make_extra_work(
            customer=cls.customer_a,
            building=cls.building_a1,
            created_by=cls.cust_basic_a,
            status_value=ExtraWorkStatus.UNDER_REVIEW,
        )

    def test_backend_computes_totals_from_inputs(self):
        # 10 hours * 50.00 EUR * 21% VAT = 500 subtotal + 105 VAT = 605
        response = self._api(self.admin_a).post(
            f"/api/extra-work/{self.ew.id}/pricing-items/",
            {
                "description": "Crew time",
                "unit_type": "HOURS",
                "quantity": "10.00",
                "unit_price": "50.00",
                "vat_rate": "21.00",
            },
            format="json",
        )
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(Decimal(response.data["subtotal"]), Decimal("500.00"))
        self.assertEqual(Decimal(response.data["vat_amount"]), Decimal("105.00"))
        self.assertEqual(Decimal(response.data["total"]), Decimal("605.00"))

        # Aggregate also recomputed on the request row.
        self.ew.refresh_from_db()
        self.assertEqual(self.ew.subtotal_amount, Decimal("500.00"))
        self.assertEqual(self.ew.vat_amount, Decimal("105.00"))
        self.assertEqual(self.ew.total_amount, Decimal("605.00"))

    def test_frontend_supplied_totals_are_ignored(self):
        # Client sends totals=999999 — backend must overwrite them.
        response = self._api(self.admin_a).post(
            f"/api/extra-work/{self.ew.id}/pricing-items/",
            {
                "description": "x",
                "unit_type": "FIXED",
                "quantity": "2.00",
                "unit_price": "10.00",
                "vat_rate": "9.00",
                "subtotal": "999999.99",
                "total": "999999.99",
                "vat_amount": "999999.99",
            },
            format="json",
        )
        self.assertEqual(response.status_code, 201, response.data)
        # 2 * 10 = 20 subtotal; 20 * 9% = 1.80 vat; total = 21.80
        self.assertEqual(Decimal(response.data["subtotal"]), Decimal("20.00"))
        self.assertEqual(Decimal(response.data["vat_amount"]), Decimal("1.80"))
        self.assertEqual(Decimal(response.data["total"]), Decimal("21.80"))

    def test_negative_values_rejected(self):
        for field in ("quantity", "unit_price", "vat_rate"):
            payload = {
                "description": "x",
                "unit_type": "FIXED",
                "quantity": "1.00",
                "unit_price": "1.00",
                "vat_rate": "0.00",
            }
            payload[field] = "-1.00"
            response = self._api(self.admin_a).post(
                f"/api/extra-work/{self.ew.id}/pricing-items/",
                payload,
                format="json",
            )
            self.assertEqual(
                response.status_code, 400, f"{field} negative should 400"
            )

    def test_customer_cannot_create_pricing_line_item(self):
        response = self._api(self.cust_basic_a).post(
            f"/api/extra-work/{self.ew.id}/pricing-items/",
            {
                "description": "Trying to inject",
                "unit_type": "FIXED",
                "quantity": "1.00",
                "unit_price": "1.00",
                "vat_rate": "0.00",
            },
            format="json",
        )
        self.assertEqual(response.status_code, 403)


# ---------------------------------------------------------------------------
# Customer-internal-field leakage
# ---------------------------------------------------------------------------
class InternalFieldLeakageTests(ExtraWorkFixtureMixin, TestCase):
    @classmethod
    def setUpTestData(cls):
        cls._setup_fixture()
        cls.ew = cls._make_extra_work(
            customer=cls.customer_a,
            building=cls.building_a1,
            created_by=cls.cust_basic_a,
        )
        cls.ew.manager_note = "Internal manager note"
        cls.ew.internal_cost_note = "Cost: 30% margin"
        cls.ew.override_reason = "Provider justification"
        cls.ew.save()

        ExtraWorkPricingLineItem.objects.create(
            extra_work=cls.ew,
            description="Crew",
            unit_type="FIXED",
            quantity=Decimal("1"),
            unit_price=Decimal("100"),
            vat_rate=Decimal("21"),
            customer_visible_note="Visible to customer",
            internal_cost_note="Provider-only cost note",
        )

    def test_customer_sees_no_provider_internal_fields_on_detail(self):
        response = self._api(self.cust_basic_a).get(
            f"/api/extra-work/{self.ew.id}/"
        )
        self.assertEqual(response.status_code, 200)
        data = response.data
        for forbidden in (
            "manager_note",
            "internal_cost_note",
            "override_by",
            "override_reason",
            "override_at",
        ):
            self.assertNotIn(
                forbidden,
                data,
                f"Customer leaked provider-internal field: {forbidden}",
            )

    def test_provider_sees_provider_internal_fields_on_detail(self):
        response = self._api(self.admin_a).get(
            f"/api/extra-work/{self.ew.id}/"
        )
        self.assertEqual(response.status_code, 200)
        data = response.data
        self.assertEqual(data["manager_note"], "Internal manager note")
        self.assertEqual(data["internal_cost_note"], "Cost: 30% margin")

    def test_customer_pricing_item_strips_internal_cost_note(self):
        # Listing through the request detail.
        response = self._api(self.cust_basic_a).get(
            f"/api/extra-work/{self.ew.id}/"
        )
        line_items = response.data["pricing_line_items"]
        self.assertEqual(len(line_items), 1)
        self.assertNotIn(
            "internal_cost_note",
            line_items[0],
            "Customer leaked pricing internal_cost_note via detail.",
        )
        # And through the pricing-items endpoint.
        response = self._api(self.cust_basic_a).get(
            f"/api/extra-work/{self.ew.id}/pricing-items/"
        )
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("internal_cost_note", response.data[0])

    def test_provider_pricing_item_includes_internal_cost_note(self):
        response = self._api(self.admin_a).get(
            f"/api/extra-work/{self.ew.id}/pricing-items/"
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.data[0]["internal_cost_note"], "Provider-only cost note"
        )


# ---------------------------------------------------------------------------
# Transitions + customer approval permission
# ---------------------------------------------------------------------------
class CustomerApprovalTests(ExtraWorkFixtureMixin, TestCase):
    @classmethod
    def setUpTestData(cls):
        cls._setup_fixture()

    def _make_priced_ew(self, *, created_by=None, customer=None, building=None):
        ew = self._make_extra_work(
            customer=customer or self.customer_a,
            building=building or self.building_a1,
            created_by=created_by or self.cust_basic_a,
            status_value=ExtraWorkStatus.UNDER_REVIEW,
        )
        ExtraWorkPricingLineItem.objects.create(
            extra_work=ew,
            description="Crew",
            unit_type="FIXED",
            quantity=Decimal("1"),
            unit_price=Decimal("100"),
            vat_rate=Decimal("21"),
        )
        # Drive into PRICING_PROPOSED via the API as admin.
        response = self._api(self.admin_a).post(
            f"/api/extra-work/{ew.id}/transition/",
            {"to_status": ExtraWorkStatus.PRICING_PROPOSED},
            format="json",
        )
        if response.status_code != 200:
            raise AssertionError(
                f"Setup failed to drive PRICING_PROPOSED: {response.status_code} "
                f"{response.content!r}"
            )
        ew.refresh_from_db()
        return ew

    def test_customer_with_approve_own_can_approve(self):
        ew = self._make_priced_ew(created_by=self.cust_basic_a)
        response = self._api(self.cust_basic_a).post(
            f"/api/extra-work/{ew.id}/transition/",
            {"to_status": ExtraWorkStatus.CUSTOMER_APPROVED},
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.data)
        ew.refresh_from_db()
        self.assertEqual(ew.status, ExtraWorkStatus.CUSTOMER_APPROVED)

    def test_customer_with_revoked_approve_own_is_blocked(self):
        # Revoke approve_own via permission_overrides.
        access = CustomerUserBuildingAccess.objects.get(
            membership__user=self.cust_basic_a, building=self.building_a1
        )
        access.permission_overrides = {"customer.extra_work.approve_own": False}
        access.save()

        ew = self._make_priced_ew(created_by=self.cust_basic_a)
        response = self._api(self.cust_basic_a).post(
            f"/api/extra-work/{ew.id}/transition/",
            {"to_status": ExtraWorkStatus.CUSTOMER_APPROVED},
            format="json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data.get("code"), "forbidden_transition")
        ew.refresh_from_db()
        self.assertEqual(ew.status, ExtraWorkStatus.PRICING_PROPOSED)

    def test_non_creator_basic_customer_cannot_approve(self):
        # ew created by cust_comp_a -> cust_basic_a is not the creator
        # and has only approve_own (not approve_location) -> blocked.
        ew = self._make_priced_ew(created_by=self.cust_comp_a)
        response = self._api(self.cust_basic_a).post(
            f"/api/extra-work/{ew.id}/transition/",
            {"to_status": ExtraWorkStatus.CUSTOMER_APPROVED},
            format="json",
        )
        # cust_basic_a has view_own only, so they can't even see this
        # row -> 404 from get_object. Either way they don't approve.
        self.assertIn(response.status_code, (404, 400))
        ew.refresh_from_db()
        self.assertEqual(ew.status, ExtraWorkStatus.PRICING_PROPOSED)

    def test_location_manager_can_approve_others_extra_work(self):
        ew = self._make_priced_ew(created_by=self.cust_basic_a)
        response = self._api(self.cust_loc_a).post(
            f"/api/extra-work/{ew.id}/transition/",
            {"to_status": ExtraWorkStatus.CUSTOMER_APPROVED},
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.data)
        ew.refresh_from_db()
        self.assertEqual(ew.status, ExtraWorkStatus.CUSTOMER_APPROVED)


# ---------------------------------------------------------------------------
# Provider override
# ---------------------------------------------------------------------------
class ProviderOverrideTests(ExtraWorkFixtureMixin, TestCase):
    @classmethod
    def setUpTestData(cls):
        cls._setup_fixture()

    def _make_priced_ew(self):
        ew = self._make_extra_work(
            customer=self.customer_a,
            building=self.building_a1,
            created_by=self.cust_basic_a,
            status_value=ExtraWorkStatus.UNDER_REVIEW,
        )
        ExtraWorkPricingLineItem.objects.create(
            extra_work=ew,
            description="Crew",
            unit_type="FIXED",
            quantity=Decimal("1"),
            unit_price=Decimal("100"),
            vat_rate=Decimal("21"),
        )
        resp = self._api(self.admin_a).post(
            f"/api/extra-work/{ew.id}/transition/",
            {"to_status": ExtraWorkStatus.PRICING_PROPOSED},
            format="json",
        )
        assert resp.status_code == 200, resp.content
        ew.refresh_from_db()
        return ew

    def test_provider_customer_decision_without_override_flag_still_requires_reason(self):
        ew = self._make_priced_ew()
        response = self._api(self.admin_a).post(
            f"/api/extra-work/{ew.id}/transition/",
            {
                "to_status": ExtraWorkStatus.CUSTOMER_APPROVED,
            },
            format="json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data.get("code"), "override_reason_required")
        ew.refresh_from_db()
        self.assertEqual(ew.status, ExtraWorkStatus.PRICING_PROPOSED)

    def test_provider_override_requires_reason(self):
        ew = self._make_priced_ew()
        response = self._api(self.admin_a).post(
            f"/api/extra-work/{ew.id}/transition/",
            {
                "to_status": ExtraWorkStatus.CUSTOMER_APPROVED,
                "is_override": True,
                "override_reason": "",  # empty -> rejected
            },
            format="json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data.get("code"), "override_reason_required")
        ew.refresh_from_db()
        self.assertEqual(ew.status, ExtraWorkStatus.PRICING_PROPOSED)

    def test_provider_override_with_reason_persists_audit(self):
        ew = self._make_priced_ew()
        response = self._api(self.admin_a).post(
            f"/api/extra-work/{ew.id}/transition/",
            {
                "to_status": ExtraWorkStatus.CUSTOMER_APPROVED,
                "is_override": True,
                "override_reason": "Customer asked verbally; we are stamping "
                "the override per phone agreement of 2026-05-15.",
            },
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.data)
        ew.refresh_from_db()
        self.assertEqual(ew.status, ExtraWorkStatus.CUSTOMER_APPROVED)
        self.assertEqual(ew.override_by_id, self.admin_a.id)
        self.assertTrue(ew.override_reason)
        self.assertIsNotNone(ew.override_at)

        # And the status history row is flagged is_override=True.
        history_response = self._api(self.admin_a).get(
            f"/api/extra-work/{ew.id}/status-history/"
        )
        self.assertEqual(history_response.status_code, 200)
        last = history_response.data[-1]
        self.assertTrue(last["is_override"])


# ---------------------------------------------------------------------------
# PRICING_PROPOSED requires at least one line item
# ---------------------------------------------------------------------------
class PricingProposedRequirementTests(ExtraWorkFixtureMixin, TestCase):
    @classmethod
    def setUpTestData(cls):
        cls._setup_fixture()

    def test_cannot_propose_pricing_without_line_items(self):
        ew = self._make_extra_work(
            customer=self.customer_a,
            building=self.building_a1,
            created_by=self.cust_basic_a,
            status_value=ExtraWorkStatus.UNDER_REVIEW,
        )
        response = self._api(self.admin_a).post(
            f"/api/extra-work/{ew.id}/transition/",
            {"to_status": ExtraWorkStatus.PRICING_PROPOSED},
            format="json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.data.get("code"), "pricing_line_items_required"
        )
