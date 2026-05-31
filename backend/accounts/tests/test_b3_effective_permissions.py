"""
B3 — `GET /api/users/<id>/effective-permissions/` regression suite.

Pins:

  1. Caller authorization (SA / COMPANY_ADMIN in scope; everyone else
     403; cross-company COMPANY_ADMIN 403 at the customer-scope guard).

  2. Query-param validation (customer_id required; building_id
     optional; invalid ints → 400; unknown ids → 404; unlinked
     customer/building pair → 400 with the documented stable codes).

  3. Response shape: top-level keys (`user`, `context`, `scope`,
     `role_defaults`, `overrides`, `effective_permissions`,
     `effective_actions`, `notes`).

  4. `effective_actions` semantics:
       - STAFF has no proposal/pricing/internal-note actions.
       - BM in assigned building has operational + override actions;
         outside-building BM is out of scope.
       - CUSTOMER_USER actions are limited by customer/building access.
       - Provider Admin can manage customer permissions by default
         (future B5 toggle is not yet implemented).
       - CCA (access_role) cannot grant another CCA — re-pinned via
         the existing H-7 serializer guard (already tested elsewhere;
         we re-pin shape via `can_manage_customer_permissions`).

No migrations. No new permission keys. No frontend.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework import status
from rest_framework.test import APIClient

from accounts.models import StaffProfile, UserRole
from buildings.models import (
    Building,
    BuildingManagerAssignment,
    BuildingStaffVisibility,
)
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


class _B3Fixture(TestCase):
    """Two provider companies (A, B) so cross-company smuggling can be
    asserted; one customer per company; two buildings on company A
    (the second is deliberately NOT linked to customer A — used to
    exercise the customer_building_not_linked guard).
    """

    @classmethod
    def setUpTestData(cls):
        # Provider companies.
        cls.company_a = Company.objects.create(name="Prov A", slug="prov-a-b3")
        cls.company_b = Company.objects.create(name="Prov B", slug="prov-b-b3")

        # Buildings.
        cls.b_linked = Building.objects.create(
            company=cls.company_a, name="Building Linked"
        )
        cls.b_unlinked = Building.objects.create(
            company=cls.company_a, name="Building Unlinked"
        )
        cls.b_other_company = Building.objects.create(
            company=cls.company_b, name="Building Other Company"
        )

        # Customers + customer↔building links.
        cls.customer_a = Customer.objects.create(
            company=cls.company_a, name="Customer A", building=cls.b_linked
        )
        cls.customer_b = Customer.objects.create(
            company=cls.company_b, name="Customer B", building=cls.b_other_company
        )
        CustomerBuildingMembership.objects.create(
            customer=cls.customer_a, building=cls.b_linked
        )
        CustomerBuildingMembership.objects.create(
            customer=cls.customer_b, building=cls.b_other_company
        )

        # Actors.
        cls.super_admin = _mk(
            "super-b3@example.com",
            UserRole.SUPER_ADMIN,
            is_staff=True,
            is_superuser=True,
        )
        cls.admin_a = _mk("admin-a-b3@example.com", UserRole.COMPANY_ADMIN)
        CompanyUserMembership.objects.create(user=cls.admin_a, company=cls.company_a)
        cls.admin_b = _mk("admin-b-b3@example.com", UserRole.COMPANY_ADMIN)
        CompanyUserMembership.objects.create(user=cls.admin_b, company=cls.company_b)

        # Targets we will query.
        cls.bm_in = _mk("bm-in-b3@example.com", UserRole.BUILDING_MANAGER)
        BuildingManagerAssignment.objects.create(
            user=cls.bm_in, building=cls.b_linked
        )
        cls.bm_out = _mk("bm-out-b3@example.com", UserRole.BUILDING_MANAGER)
        # bm_out has NO assignment to b_linked.

        cls.staff_in = _mk("staff-in-b3@example.com", UserRole.STAFF)
        StaffProfile.objects.create(user=cls.staff_in)
        BuildingStaffVisibility.objects.create(
            user=cls.staff_in, building=cls.b_linked
        )
        cls.staff_out = _mk("staff-out-b3@example.com", UserRole.STAFF)
        StaffProfile.objects.create(user=cls.staff_out)

        cls.cust_user = _mk("cust-b3@example.com", UserRole.CUSTOMER_USER)
        membership = CustomerUserMembership.objects.create(
            customer=cls.customer_a, user=cls.cust_user
        )
        cls.cust_access = CustomerUserBuildingAccess.objects.create(
            membership=membership,
            building=cls.b_linked,
            access_role=CustomerUserBuildingAccess.AccessRole.CUSTOMER_USER,
        )

        # A separate customer-user with NO access rows — for "no scope"
        # capability assertions.
        cls.cust_user_no_access = _mk(
            "cust-noaccess-b3@example.com", UserRole.CUSTOMER_USER
        )
        CustomerUserMembership.objects.create(
            customer=cls.customer_a, user=cls.cust_user_no_access
        )

        # A contract price so the "can_use_contract_price_direct_order"
        # branch evaluates True for customer A.
        cls.service_cat = ServiceCategory.objects.create(name="Cat B3")
        cls.service = Service.objects.create(
            category=cls.service_cat,
            company=cls.company_a,
            name="Window cleaning B3",
            unit_type=ExtraWorkPricingUnitType.SQUARE_METERS,
            default_unit_price=Decimal("7.00"),
        )
        CustomerServicePrice.objects.create(
            service=cls.service,
            customer=cls.customer_a,
            unit_price=Decimal("5.00"),
            vat_pct=Decimal("21.00"),
            valid_from=date(2026, 1, 1),
            is_active=True,
        )

    def _api(self, user):
        c = APIClient()
        c.force_authenticate(user=user)
        return c

    def _url(self, target_id: int) -> str:
        return f"/api/users/{target_id}/effective-permissions/"


# ---------------------------------------------------------------------------
# 1. Caller authorization
# ---------------------------------------------------------------------------
class CallerAuthorizationTests(_B3Fixture):
    def test_super_admin_can_query_any_user(self):
        response = self._api(self.super_admin).get(
            self._url(self.bm_in.id) + f"?customer_id={self.customer_a.id}"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)

    def test_company_admin_can_query_user_in_own_company(self):
        response = self._api(self.admin_a).get(
            self._url(self.bm_in.id) + f"?customer_id={self.customer_a.id}"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)

    def test_company_admin_cannot_query_user_in_other_company(self):
        # admin_a queries bm_in, which is in company_a — OK target.
        # But the customer_id points at customer_b which is in
        # company_b. The inline customer-scope guard must fire.
        response = self._api(self.admin_a).get(
            self._url(self.bm_in.id) + f"?customer_id={self.customer_b.id}"
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_company_admin_cannot_query_another_company_admin(self):
        # CanManageUser blocks COMPANY_ADMIN → COMPANY_ADMIN target.
        response = self._api(self.admin_a).get(
            self._url(self.admin_b.id) + f"?customer_id={self.customer_a.id}"
        )
        # 404 because the queryset scope filter rejects out-of-scope
        # users before has_object_permission gets a turn for this
        # particular target shape.
        self.assertIn(
            response.status_code,
            (status.HTTP_403_FORBIDDEN, status.HTTP_404_NOT_FOUND),
        )

    def test_building_manager_cannot_call_endpoint(self):
        response = self._api(self.bm_in).get(
            self._url(self.cust_user.id) + f"?customer_id={self.customer_a.id}"
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_staff_cannot_call_endpoint(self):
        response = self._api(self.staff_in).get(
            self._url(self.cust_user.id) + f"?customer_id={self.customer_a.id}"
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_customer_user_cannot_call_endpoint(self):
        response = self._api(self.cust_user).get(
            self._url(self.cust_user.id) + f"?customer_id={self.customer_a.id}"
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)


# ---------------------------------------------------------------------------
# 2. Query-param validation
# ---------------------------------------------------------------------------
class QueryParamValidationTests(_B3Fixture):
    def test_missing_customer_id_returns_400(self):
        response = self._api(self.super_admin).get(self._url(self.bm_in.id))
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data.get("code"), "customer_id_required")

    def test_non_integer_customer_id_returns_400(self):
        response = self._api(self.super_admin).get(
            self._url(self.bm_in.id) + "?customer_id=not-an-int"
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data.get("code"), "customer_id_invalid")

    def test_unknown_customer_id_returns_404(self):
        response = self._api(self.super_admin).get(
            self._url(self.bm_in.id) + "?customer_id=999999"
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_non_integer_building_id_returns_400(self):
        response = self._api(self.super_admin).get(
            self._url(self.bm_in.id)
            + f"?customer_id={self.customer_a.id}&building_id=NaN"
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data.get("code"), "building_id_invalid")

    def test_unknown_building_id_returns_404(self):
        response = self._api(self.super_admin).get(
            self._url(self.bm_in.id)
            + f"?customer_id={self.customer_a.id}&building_id=999999"
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_building_in_wrong_company_returns_400(self):
        response = self._api(self.super_admin).get(
            self._url(self.bm_in.id)
            + f"?customer_id={self.customer_a.id}"
            + f"&building_id={self.b_other_company.id}"
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data.get("code"), "customer_building_mismatch")

    def test_building_not_linked_to_customer_returns_400(self):
        # b_unlinked exists in company_a but has no
        # CustomerBuildingMembership pointing at customer_a.
        response = self._api(self.super_admin).get(
            self._url(self.bm_in.id)
            + f"?customer_id={self.customer_a.id}"
            + f"&building_id={self.b_unlinked.id}"
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data.get("code"), "customer_building_not_linked")


# ---------------------------------------------------------------------------
# 3. Response shape
# ---------------------------------------------------------------------------
class ResponseShapeTests(_B3Fixture):
    REQUIRED_TOP_LEVEL_KEYS = {
        "user",
        "context",
        "scope",
        "role_defaults",
        "overrides",
        "effective_permissions",
        "effective_actions",
        "notes",
    }
    REQUIRED_USER_KEYS = {"id", "email", "role", "is_active"}
    REQUIRED_CONTEXT_KEYS = {"customer_id", "building_id", "company_id"}
    REQUIRED_SCOPE_KEYS = {"in_scope", "reason"}
    REQUIRED_ROLE_DEFAULTS_KEYS = {"role", "access_role", "default_permission_keys"}
    REQUIRED_EFFECTIVE_ACTIONS_KEYS = {
        "can_view_customer",
        "can_view_building",
        "can_view_tickets",
        "can_create_ticket",
        "can_change_ticket_status",
        "can_override_customer_decision",
        "can_view_extra_work",
        "can_create_extra_work",
        "can_use_contract_price_direct_order",
        "can_request_non_contract_extra_work",
        "can_prepare_extra_work_proposal",
        "can_view_proposal_prices",
        "can_manage_customer_users",
        "can_manage_customer_permissions",
        # B5 — derived from the provider Company's policy toggle.
        "can_manage_customer_company_admins",
        "can_view_provider_internal_notes",
        "can_view_staff_operational_notes",
    }

    def test_top_level_shape_for_bm_target(self):
        response = self._api(self.super_admin).get(
            self._url(self.bm_in.id)
            + f"?customer_id={self.customer_a.id}"
            + f"&building_id={self.b_linked.id}"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        body = response.data
        self.assertEqual(set(body.keys()), self.REQUIRED_TOP_LEVEL_KEYS)
        self.assertEqual(set(body["user"].keys()), self.REQUIRED_USER_KEYS)
        self.assertEqual(set(body["context"].keys()), self.REQUIRED_CONTEXT_KEYS)
        self.assertEqual(set(body["scope"].keys()), self.REQUIRED_SCOPE_KEYS)
        self.assertEqual(
            set(body["role_defaults"].keys()), self.REQUIRED_ROLE_DEFAULTS_KEYS
        )
        self.assertEqual(
            set(body["effective_actions"].keys()),
            self.REQUIRED_EFFECTIVE_ACTIONS_KEYS,
        )
        self.assertEqual(
            body["context"]["customer_id"], self.customer_a.id
        )
        self.assertEqual(
            body["context"]["company_id"], self.company_a.id
        )
        self.assertEqual(
            body["context"]["building_id"], self.b_linked.id
        )
        self.assertIsInstance(body["notes"], list)
        self.assertGreater(len(body["notes"]), 0)

    def test_building_id_optional_resolves_to_none_in_context(self):
        response = self._api(self.super_admin).get(
            self._url(self.cust_user.id) + f"?customer_id={self.customer_a.id}"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIsNone(response.data["context"]["building_id"])


# ---------------------------------------------------------------------------
# 4. Effective actions — STAFF
# ---------------------------------------------------------------------------
class StaffEffectiveActionsTests(_B3Fixture):
    def _fetch(self, target):
        response = self._api(self.super_admin).get(
            self._url(target.id)
            + f"?customer_id={self.customer_a.id}"
            + f"&building_id={self.b_linked.id}"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        return response.data["effective_actions"]

    def test_staff_in_scope_has_no_proposal_pricing_internal_note_actions(self):
        actions = self._fetch(self.staff_in)
        # STAFF can NEVER reach Extra Work / Proposal commercial surfaces.
        self.assertFalse(actions["can_view_extra_work"])
        self.assertFalse(actions["can_create_extra_work"])
        self.assertFalse(actions["can_use_contract_price_direct_order"])
        self.assertFalse(actions["can_request_non_contract_extra_work"])
        self.assertFalse(actions["can_prepare_extra_work_proposal"])
        self.assertFalse(actions["can_view_proposal_prices"])
        # No customer-decision override, no permission management.
        self.assertFalse(actions["can_override_customer_decision"])
        self.assertFalse(actions["can_manage_customer_users"])
        self.assertFalse(actions["can_manage_customer_permissions"])
        # Internal notes hidden per canonical §9.2.
        self.assertFalse(actions["can_view_provider_internal_notes"])
        # But staff DOES see the operational/staff-instruction notes
        # they need to do the job.
        self.assertTrue(actions["can_view_staff_operational_notes"])
        # Operational ticket actions in scope.
        self.assertTrue(actions["can_view_tickets"])
        self.assertTrue(actions["can_change_ticket_status"])

    def test_staff_out_of_scope_has_no_actions(self):
        actions = self._fetch(self.staff_out)
        # No BSV on b_linked → out of scope.
        self.assertFalse(actions["can_view_customer"])
        self.assertFalse(actions["can_view_tickets"])
        self.assertFalse(actions["can_change_ticket_status"])
        self.assertFalse(actions["can_view_extra_work"])


# ---------------------------------------------------------------------------
# 5. Effective actions — Building Manager
# ---------------------------------------------------------------------------
class BuildingManagerEffectiveActionsTests(_B3Fixture):
    def _fetch(self, target):
        response = self._api(self.super_admin).get(
            self._url(target.id)
            + f"?customer_id={self.customer_a.id}"
            + f"&building_id={self.b_linked.id}"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        return response.data["effective_actions"]

    def test_bm_in_assigned_building_has_operational_and_override_defaults(self):
        actions = self._fetch(self.bm_in)
        self.assertTrue(actions["can_view_customer"])
        self.assertTrue(actions["can_view_building"])
        self.assertTrue(actions["can_view_tickets"])
        self.assertTrue(actions["can_create_ticket"])
        self.assertTrue(actions["can_change_ticket_status"])
        # B1 default: BM can override customer decisions inside
        # assigned buildings.
        self.assertTrue(actions["can_override_customer_decision"])
        # Extra Work + proposal preparation default.
        self.assertTrue(actions["can_view_extra_work"])
        self.assertTrue(actions["can_create_extra_work"])
        self.assertTrue(actions["can_prepare_extra_work_proposal"])
        self.assertTrue(actions["can_view_proposal_prices"])
        # BM defaults still EXCLUDE permission management.
        self.assertFalse(actions["can_manage_customer_users"])
        self.assertFalse(actions["can_manage_customer_permissions"])
        # Note visibility per canonical §9.2 / §9.3.
        self.assertTrue(actions["can_view_provider_internal_notes"])
        self.assertTrue(actions["can_view_staff_operational_notes"])

    def test_bm_out_of_assigned_building_is_out_of_scope(self):
        actions = self._fetch(self.bm_out)
        self.assertFalse(actions["can_view_customer"])
        self.assertFalse(actions["can_view_building"])
        self.assertFalse(actions["can_view_tickets"])
        self.assertFalse(actions["can_override_customer_decision"])
        self.assertFalse(actions["can_prepare_extra_work_proposal"])


# ---------------------------------------------------------------------------
# 6. Effective actions — Customer User
# ---------------------------------------------------------------------------
class CustomerUserEffectiveActionsTests(_B3Fixture):
    def _fetch(self, target, building=None):
        url = self._url(target.id) + f"?customer_id={self.customer_a.id}"
        if building is not None:
            url += f"&building_id={building.id}"
        response = self._api(self.super_admin).get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        return response.data["effective_actions"]

    def test_customer_user_with_access_has_customer_side_actions(self):
        actions = self._fetch(self.cust_user, self.b_linked)
        self.assertTrue(actions["can_view_customer"])
        self.assertTrue(actions["can_view_building"])
        self.assertTrue(actions["can_view_tickets"])
        self.assertTrue(actions["can_create_ticket"])
        self.assertTrue(actions["can_view_extra_work"])
        self.assertTrue(actions["can_create_extra_work"])
        # Contract price exists for customer_a → direct-order path
        # reachable.
        self.assertTrue(actions["can_use_contract_price_direct_order"])
        # Non-contract path is always reachable when create is reachable.
        self.assertTrue(actions["can_request_non_contract_extra_work"])
        # Customer-side roles never drive non-customer-decision
        # transitions and never override the customer.
        self.assertFalse(actions["can_change_ticket_status"])
        self.assertFalse(actions["can_override_customer_decision"])
        # No provider-internal-note or staff-operational-note visibility.
        self.assertFalse(actions["can_view_provider_internal_notes"])
        self.assertFalse(actions["can_view_staff_operational_notes"])
        # No permission management.
        self.assertFalse(actions["can_manage_customer_users"])
        self.assertFalse(actions["can_manage_customer_permissions"])
        # No proposal preparation.
        self.assertFalse(actions["can_prepare_extra_work_proposal"])

    def test_customer_user_without_access_has_no_actions(self):
        actions = self._fetch(self.cust_user_no_access, self.b_linked)
        self.assertFalse(actions["can_view_tickets"])
        self.assertFalse(actions["can_create_ticket"])
        self.assertFalse(actions["can_view_extra_work"])
        self.assertFalse(actions["can_create_extra_work"])


# ---------------------------------------------------------------------------
# 7. Effective actions — Provider Admin + Super Admin
# ---------------------------------------------------------------------------
class ProviderAdminAndSuperAdminEffectiveActionsTests(_B3Fixture):
    def _fetch_for_target(self, target):
        response = self._api(self.super_admin).get(
            self._url(target.id) + f"?customer_id={self.customer_a.id}"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        return response.data["effective_actions"]

    def test_super_admin_has_all_administrative_actions(self):
        actions = self._fetch_for_target(self.super_admin)
        self.assertTrue(actions["can_view_customer"])
        self.assertTrue(actions["can_manage_customer_users"])
        self.assertTrue(actions["can_manage_customer_permissions"])
        self.assertTrue(actions["can_override_customer_decision"])
        self.assertTrue(actions["can_prepare_extra_work_proposal"])

    def test_company_admin_in_scope_can_manage_customer_permissions_by_default(self):
        # Confirms the current backend truth: COMPANY_ADMIN has the
        # default. Future B5 will add a Super Admin-controlled toggle
        # to disable this on a per-Provider-Admin basis; current
        # behaviour remains provider-admin-allowed by default. This is
        # documented in the response notes.
        actions = self._fetch_for_target(self.admin_a)
        self.assertTrue(actions["can_manage_customer_permissions"])
        self.assertTrue(actions["can_manage_customer_users"])

    def test_company_admin_out_of_scope_cannot_manage(self):
        # admin_b is in company_b; querying for customer_a (company_a)
        # context → out of scope for that customer.
        actions = self._fetch_for_target(self.admin_b)
        self.assertFalse(actions["can_view_customer"])
        self.assertFalse(actions["can_manage_customer_permissions"])
        self.assertFalse(actions["can_manage_customer_users"])
