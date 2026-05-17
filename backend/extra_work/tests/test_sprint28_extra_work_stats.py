"""
Sprint 28 Batch 9 — Extra Work stats endpoints tests.

Two endpoints exercised:
  * GET /api/extra-work/stats/
  * GET /api/extra-work/stats/by-building/

Both go through `scope_extra_work_for(request.user)`, so the per-role
scope is the same shape that protects the list / detail endpoints.

Test classes (per PM Q8):
  * ExtraWorkStatsScopeTests           — per-role scoping including
                                          STAFF zero-row + customer
                                          access-row matching.
  * ExtraWorkStatsBucketsTests         — bucket definitions: by_status,
                                          by_routing, by_urgency, active,
                                          awaiting_pricing,
                                          awaiting_customer_approval,
                                          urgent.
  * ExtraWorkStatsByBuildingTests      — by-building ordering + zero-row
                                          skip + per-bucket aggregation.
  * ExtraWorkStatsCrossTenantIsolation — defence-in-depth cross-tenant
                                          isolation (provider + customer).
  * ExtraWorkStatsSoftDeletedExcluded  — soft-deleted rows are filtered
                                          out by the scope helper and
                                          therefore by the stats endpoint.
"""
from __future__ import annotations

from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone
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
    ExtraWorkRequest,
    ExtraWorkRoutingDecision,
    ExtraWorkStatus,
    ExtraWorkUrgency,
)


User = get_user_model()
PASSWORD = "StrongerTestPassword123!"

STATS_URL = "/api/extra-work/stats/"
STATS_BY_BUILDING_URL = "/api/extra-work/stats/by-building/"


def _mk(email: str, role: str, **extra) -> User:
    return User.objects.create_user(
        email=email,
        password=PASSWORD,
        role=role,
        full_name=email.split("@")[0],
        **extra,
    )


class _StatsFixtureMixin:
    """
    Two-provider, two-customer fixture covering the scope shapes the
    stats endpoints need. Per-class additions seed specific bucket
    combinations on top of this base.
    """

    @classmethod
    def _setup_fixture(cls, *, suffix: str = "b9"):
        cls.provider_a = Company.objects.create(
            name=f"Provider A {suffix}", slug=f"prov-a-{suffix}"
        )
        cls.provider_b = Company.objects.create(
            name=f"Provider B {suffix}", slug=f"prov-b-{suffix}"
        )

        cls.building_a1 = Building.objects.create(
            company=cls.provider_a, name="Aardenburg"
        )
        cls.building_a2 = Building.objects.create(
            company=cls.provider_a, name="Breda"
        )
        cls.building_b = Building.objects.create(
            company=cls.provider_b, name="Coevorden"
        )

        cls.customer_a = Customer.objects.create(
            company=cls.provider_a,
            name="Customer A",
            building=cls.building_a1,
        )
        cls.customer_a_alt = Customer.objects.create(
            company=cls.provider_a,
            name="Customer A-alt",
            building=cls.building_a1,
        )
        cls.customer_b = Customer.objects.create(
            company=cls.provider_b,
            name="Customer B",
            building=cls.building_b,
        )

        for c, b in [
            (cls.customer_a, cls.building_a1),
            (cls.customer_a, cls.building_a2),
            (cls.customer_a_alt, cls.building_a1),
            (cls.customer_b, cls.building_b),
        ]:
            CustomerBuildingMembership.objects.create(customer=c, building=b)

        cls.super_admin = _mk(
            f"super-{suffix}@example.com",
            UserRole.SUPER_ADMIN,
            is_staff=True,
            is_superuser=True,
        )
        cls.admin_a = _mk(
            f"admin-a-{suffix}@example.com", UserRole.COMPANY_ADMIN
        )
        CompanyUserMembership.objects.create(
            user=cls.admin_a, company=cls.provider_a
        )
        cls.admin_b = _mk(
            f"admin-b-{suffix}@example.com", UserRole.COMPANY_ADMIN
        )
        CompanyUserMembership.objects.create(
            user=cls.admin_b, company=cls.provider_b
        )

        cls.manager_a1 = _mk(
            f"mgr-a1-{suffix}@example.com", UserRole.BUILDING_MANAGER
        )
        BuildingManagerAssignment.objects.create(
            user=cls.manager_a1, building=cls.building_a1
        )

        cls.staff = _mk(f"staff-{suffix}@example.com", UserRole.STAFF)

        # CUSTOMER_USER with access on (customer_a, building_a1).
        cls.cust_a = _mk(
            f"cust-a-{suffix}@example.com", UserRole.CUSTOMER_USER
        )
        membership = CustomerUserMembership.objects.create(
            customer=cls.customer_a, user=cls.cust_a
        )
        CustomerUserBuildingAccess.objects.create(
            membership=membership,
            building=cls.building_a1,
            access_role=CustomerUserBuildingAccess.AccessRole.CUSTOMER_USER,
        )

        # CUSTOMER_USER on (customer_a_alt, building_a1) — used for
        # cross-customer isolation checks.
        cls.cust_alt = _mk(
            f"cust-alt-{suffix}@example.com", UserRole.CUSTOMER_USER
        )
        alt_membership = CustomerUserMembership.objects.create(
            customer=cls.customer_a_alt, user=cls.cust_alt
        )
        CustomerUserBuildingAccess.objects.create(
            membership=alt_membership,
            building=cls.building_a1,
            access_role=CustomerUserBuildingAccess.AccessRole.CUSTOMER_USER,
        )

    def _api(self, user):
        c = APIClient()
        c.force_authenticate(user=user)
        return c

    @staticmethod
    def _make_ew(
        *,
        customer,
        building,
        created_by,
        status_value=ExtraWorkStatus.REQUESTED,
        urgency=ExtraWorkUrgency.NORMAL,
        routing=ExtraWorkRoutingDecision.PROPOSAL,
        company=None,
    ) -> ExtraWorkRequest:
        return ExtraWorkRequest.objects.create(
            company=company or customer.company,
            building=building,
            customer=customer,
            created_by=created_by,
            title=f"EW for {customer.name} @ {building.name}",
            description="seed",
            category=ExtraWorkCategory.DEEP_CLEANING,
            status=status_value,
            urgency=urgency,
            routing_decision=routing,
        )


# ---------------------------------------------------------------------------
# Per-role scoping
# ---------------------------------------------------------------------------
class ExtraWorkStatsScopeTests(_StatsFixtureMixin, TestCase):
    @classmethod
    def setUpTestData(cls):
        cls._setup_fixture(suffix="b9-scope")
        # Provider-A rows: three across building_a1 and building_a2.
        cls.ew_a1_one = cls._make_ew(
            customer=cls.customer_a,
            building=cls.building_a1,
            created_by=cls.cust_a,
        )
        cls.ew_a1_two = cls._make_ew(
            customer=cls.customer_a,
            building=cls.building_a1,
            created_by=cls.admin_a,
        )
        cls.ew_a2 = cls._make_ew(
            customer=cls.customer_a,
            building=cls.building_a2,
            created_by=cls.admin_a,
        )
        # Cross-customer same provider — visible to admin_a, NOT to cust_a.
        cls.ew_a_alt = cls._make_ew(
            customer=cls.customer_a_alt,
            building=cls.building_a1,
            created_by=cls.cust_alt,
        )
        # Provider B row — only super_admin + admin_b should see it.
        cls.ew_b = cls._make_ew(
            customer=cls.customer_b,
            building=cls.building_b,
            created_by=cls.admin_b,
        )

    def test_super_admin_sees_all_rows(self):
        response = self._api(self.super_admin).get(STATS_URL)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["total"], 5)

    def test_company_admin_only_counts_own_company(self):
        response = self._api(self.admin_a).get(STATS_URL)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        # Four provider-A rows (ew_a1_one, ew_a1_two, ew_a2, ew_a_alt).
        self.assertEqual(response.data["total"], 4)

        response_b = self._api(self.admin_b).get(STATS_URL)
        self.assertEqual(response_b.status_code, status.HTTP_200_OK)
        self.assertEqual(response_b.data["total"], 1)

    def test_building_manager_only_counts_assigned_buildings(self):
        # manager_a1 is assigned only to building_a1 — sees ew_a1_one,
        # ew_a1_two, ew_a_alt (all on building_a1), NOT ew_a2.
        response = self._api(self.manager_a1).get(STATS_URL)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["total"], 3)

    def test_customer_user_only_counts_own_access(self):
        # cust_a has CUSTOMER_USER access on (customer_a, building_a1).
        # That access role's default permission key is
        # `customer.extra_work.view_own` — sees only rows it created.
        response = self._api(self.cust_a).get(STATS_URL)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        # Only ew_a1_one (cust_a is creator).
        self.assertEqual(response.data["total"], 1)

    def test_staff_gets_all_zeros(self):
        response = self._api(self.staff).get(STATS_URL)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["total"], 0)
        self.assertEqual(response.data["by_status"], {})
        self.assertEqual(response.data["by_routing"], {})
        self.assertEqual(response.data["by_urgency"], {})
        self.assertEqual(response.data["active"], 0)
        self.assertEqual(response.data["awaiting_pricing"], 0)
        self.assertEqual(response.data["awaiting_customer_approval"], 0)
        self.assertEqual(response.data["urgent"], 0)


# ---------------------------------------------------------------------------
# Bucket definitions
# ---------------------------------------------------------------------------
class ExtraWorkStatsBucketsTests(_StatsFixtureMixin, TestCase):
    """
    Seed one row per (status × routing × urgency) combination needed
    to pin every bucket definition. As SUPER_ADMIN to side-step
    scoping noise — scoping is exercised in the class above.
    """

    @classmethod
    def setUpTestData(cls):
        cls._setup_fixture(suffix="b9-buckets")
        # REQUESTED + PROPOSAL + NORMAL → awaiting_pricing + active.
        cls.ew_req_proposal = cls._make_ew(
            customer=cls.customer_a,
            building=cls.building_a1,
            created_by=cls.admin_a,
            status_value=ExtraWorkStatus.REQUESTED,
            routing=ExtraWorkRoutingDecision.PROPOSAL,
            urgency=ExtraWorkUrgency.NORMAL,
        )
        # UNDER_REVIEW + PROPOSAL → awaiting_pricing + active.
        cls.ew_under_review = cls._make_ew(
            customer=cls.customer_a,
            building=cls.building_a1,
            created_by=cls.admin_a,
            status_value=ExtraWorkStatus.UNDER_REVIEW,
            routing=ExtraWorkRoutingDecision.PROPOSAL,
            urgency=ExtraWorkUrgency.HIGH,
        )
        # REQUESTED + INSTANT → NOT awaiting_pricing (INSTANT route);
        # still active.
        cls.ew_req_instant = cls._make_ew(
            customer=cls.customer_a,
            building=cls.building_a2,
            created_by=cls.admin_a,
            status_value=ExtraWorkStatus.REQUESTED,
            routing=ExtraWorkRoutingDecision.INSTANT,
            urgency=ExtraWorkUrgency.NORMAL,
        )
        # PRICING_PROPOSED → awaiting_customer_approval + active.
        cls.ew_pricing_proposed = cls._make_ew(
            customer=cls.customer_a,
            building=cls.building_a1,
            created_by=cls.admin_a,
            status_value=ExtraWorkStatus.PRICING_PROPOSED,
            routing=ExtraWorkRoutingDecision.PROPOSAL,
            urgency=ExtraWorkUrgency.NORMAL,
        )
        # CUSTOMER_APPROVED → terminal; NOT active.
        cls.ew_approved = cls._make_ew(
            customer=cls.customer_a,
            building=cls.building_a1,
            created_by=cls.admin_a,
            status_value=ExtraWorkStatus.CUSTOMER_APPROVED,
            routing=ExtraWorkRoutingDecision.PROPOSAL,
            urgency=ExtraWorkUrgency.NORMAL,
        )
        # CUSTOMER_REJECTED → terminal.
        cls.ew_rejected = cls._make_ew(
            customer=cls.customer_a,
            building=cls.building_a1,
            created_by=cls.admin_a,
            status_value=ExtraWorkStatus.CUSTOMER_REJECTED,
            routing=ExtraWorkRoutingDecision.PROPOSAL,
            urgency=ExtraWorkUrgency.NORMAL,
        )
        # CANCELLED + URGENT → terminal, MUST NOT count in urgent
        # bucket (urgent excludes terminal).
        cls.ew_cancelled_urgent = cls._make_ew(
            customer=cls.customer_a,
            building=cls.building_a1,
            created_by=cls.admin_a,
            status_value=ExtraWorkStatus.CANCELLED,
            routing=ExtraWorkRoutingDecision.PROPOSAL,
            urgency=ExtraWorkUrgency.URGENT,
        )
        # URGENT + UNDER_REVIEW → active + urgent.
        cls.ew_urgent_under_review = cls._make_ew(
            customer=cls.customer_a,
            building=cls.building_a2,
            created_by=cls.admin_a,
            status_value=ExtraWorkStatus.UNDER_REVIEW,
            routing=ExtraWorkRoutingDecision.INSTANT,
            urgency=ExtraWorkUrgency.URGENT,
        )

    def _stats(self):
        response = self._api(self.super_admin).get(STATS_URL)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        return response.data

    def test_total_matches_seed(self):
        self.assertEqual(self._stats()["total"], 8)

    def test_by_status_counts(self):
        by_status = self._stats()["by_status"]
        self.assertEqual(by_status.get("REQUESTED"), 2)
        self.assertEqual(by_status.get("UNDER_REVIEW"), 2)
        self.assertEqual(by_status.get("PRICING_PROPOSED"), 1)
        self.assertEqual(by_status.get("CUSTOMER_APPROVED"), 1)
        self.assertEqual(by_status.get("CUSTOMER_REJECTED"), 1)
        self.assertEqual(by_status.get("CANCELLED"), 1)

    def test_by_routing_counts(self):
        data = self._stats()
        by_routing = data["by_routing"]
        # 6 PROPOSAL: req_proposal, under_review, pricing_proposed,
        # approved, rejected, cancelled_urgent.
        # 2 INSTANT: req_instant, urgent_under_review.
        self.assertEqual(by_routing.get("PROPOSAL"), 6)
        self.assertEqual(by_routing.get("INSTANT"), 2)
        self.assertEqual(sum(by_routing.values()), data["total"])

    def test_by_urgency_counts(self):
        data = self._stats()
        by_urgency = data["by_urgency"]
        # NORMAL: req_proposal, req_instant, pricing_proposed,
        #         approved, rejected → 5
        # HIGH:   under_review → 1
        # URGENT: cancelled_urgent, urgent_under_review → 2
        self.assertEqual(by_urgency.get("NORMAL"), 5)
        self.assertEqual(by_urgency.get("HIGH"), 1)
        self.assertEqual(by_urgency.get("URGENT"), 2)
        self.assertEqual(sum(by_urgency.values()), data["total"])

    def test_active_excludes_terminal_states(self):
        # 8 total - 3 terminal (approved, rejected, cancelled_urgent)
        # = 5 active.
        self.assertEqual(self._stats()["active"], 5)

    def test_awaiting_pricing_definition(self):
        # PROPOSAL + REQUESTED/UNDER_REVIEW only:
        # req_proposal (REQUESTED + PROPOSAL),
        # under_review (UNDER_REVIEW + PROPOSAL).
        # NOT req_instant (INSTANT routing) and NOT
        # urgent_under_review (INSTANT routing).
        self.assertEqual(self._stats()["awaiting_pricing"], 2)

    def test_awaiting_customer_approval_definition(self):
        # Only ew_pricing_proposed.
        self.assertEqual(self._stats()["awaiting_customer_approval"], 1)

    def test_urgent_excludes_terminal_states(self):
        # URGENT urgency rows: cancelled_urgent (CANCELLED — terminal),
        # urgent_under_review (UNDER_REVIEW — active). Bucket counts
        # only the second.
        self.assertEqual(self._stats()["urgent"], 1)


# ---------------------------------------------------------------------------
# Per-building stats
# ---------------------------------------------------------------------------
class ExtraWorkStatsByBuildingTests(_StatsFixtureMixin, TestCase):
    @classmethod
    def setUpTestData(cls):
        cls._setup_fixture(suffix="b9-by-bld")
        # Building A1: three rows of varied buckets.
        cls.ew_a1_active = cls._make_ew(
            customer=cls.customer_a,
            building=cls.building_a1,
            created_by=cls.admin_a,
            status_value=ExtraWorkStatus.REQUESTED,
            routing=ExtraWorkRoutingDecision.PROPOSAL,
            urgency=ExtraWorkUrgency.URGENT,
        )
        cls.ew_a1_pricing = cls._make_ew(
            customer=cls.customer_a,
            building=cls.building_a1,
            created_by=cls.admin_a,
            status_value=ExtraWorkStatus.PRICING_PROPOSED,
            routing=ExtraWorkRoutingDecision.PROPOSAL,
            urgency=ExtraWorkUrgency.NORMAL,
        )
        cls.ew_a1_terminal = cls._make_ew(
            customer=cls.customer_a,
            building=cls.building_a1,
            created_by=cls.admin_a,
            status_value=ExtraWorkStatus.CUSTOMER_APPROVED,
            routing=ExtraWorkRoutingDecision.PROPOSAL,
            urgency=ExtraWorkUrgency.NORMAL,
        )
        # Building A2: one row.
        cls.ew_a2 = cls._make_ew(
            customer=cls.customer_a,
            building=cls.building_a2,
            created_by=cls.admin_a,
            status_value=ExtraWorkStatus.UNDER_REVIEW,
            routing=ExtraWorkRoutingDecision.PROPOSAL,
            urgency=ExtraWorkUrgency.NORMAL,
        )
        # building_b: in scope only for super_admin / admin_b, NOT
        # admin_a — admin_a's response must NOT list it.
        cls.ew_b = cls._make_ew(
            customer=cls.customer_b,
            building=cls.building_b,
            created_by=cls.admin_b,
        )
        # provider-A also owns a brand-new empty building — must NOT
        # appear in the response (zero-row skip).
        cls.building_a_empty = Building.objects.create(
            company=cls.provider_a, name="Zwolle"
        )

    def test_by_building_orders_by_name(self):
        response = self._api(self.super_admin).get(STATS_BY_BUILDING_URL)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        names = [row["building_name"] for row in response.data]
        # Buildings with rows: Aardenburg (A1), Breda (A2), Coevorden (B).
        # Sorted alphabetically.
        self.assertEqual(names, sorted(names))
        self.assertEqual(
            names,
            ["Aardenburg", "Breda", "Coevorden"],
        )

    def test_by_building_excludes_zero_row_buildings(self):
        response = self._api(self.super_admin).get(STATS_BY_BUILDING_URL)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        names = [row["building_name"] for row in response.data]
        self.assertNotIn("Zwolle", names)
        # admin_a doesn't see building_b → it must be absent too.
        admin_resp = self._api(self.admin_a).get(STATS_BY_BUILDING_URL)
        admin_names = [row["building_name"] for row in admin_resp.data]
        self.assertNotIn("Coevorden", admin_names)
        # And the empty A building is still absent.
        self.assertNotIn("Zwolle", admin_names)

    def test_by_building_aggregates_match_per_row(self):
        response = self._api(self.super_admin).get(STATS_BY_BUILDING_URL)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        by_name = {row["building_name"]: row for row in response.data}

        aardenburg = by_name["Aardenburg"]
        self.assertEqual(aardenburg["building_id"], self.building_a1.id)
        self.assertEqual(aardenburg["total"], 3)
        # active = 3 total - 1 CUSTOMER_APPROVED = 2.
        self.assertEqual(aardenburg["active"], 2)
        # awaiting_pricing = REQUESTED+PROPOSAL row → 1.
        self.assertEqual(aardenburg["awaiting_pricing"], 1)
        # awaiting_customer_approval = PRICING_PROPOSED row → 1.
        self.assertEqual(aardenburg["awaiting_customer_approval"], 1)
        # urgent = URGENT urgency, not terminal → 1 (ew_a1_active).
        self.assertEqual(aardenburg["urgent"], 1)

        breda = by_name["Breda"]
        self.assertEqual(breda["building_id"], self.building_a2.id)
        self.assertEqual(breda["total"], 1)
        self.assertEqual(breda["active"], 1)
        # UNDER_REVIEW + PROPOSAL → awaiting_pricing = 1.
        self.assertEqual(breda["awaiting_pricing"], 1)
        self.assertEqual(breda["awaiting_customer_approval"], 0)
        self.assertEqual(breda["urgent"], 0)


# ---------------------------------------------------------------------------
# Cross-tenant isolation (defence-in-depth)
# ---------------------------------------------------------------------------
class ExtraWorkStatsCrossTenantIsolationTests(_StatsFixtureMixin, TestCase):
    @classmethod
    def setUpTestData(cls):
        cls._setup_fixture(suffix="b9-iso")
        # Provider A owns 2 rows.
        cls._make_ew(
            customer=cls.customer_a,
            building=cls.building_a1,
            created_by=cls.admin_a,
            status_value=ExtraWorkStatus.REQUESTED,
        )
        cls._make_ew(
            customer=cls.customer_a,
            building=cls.building_a2,
            created_by=cls.admin_a,
            status_value=ExtraWorkStatus.REQUESTED,
        )
        # Provider B owns 3 rows (must not leak to admin_a / cust_a).
        for _ in range(3):
            cls._make_ew(
                customer=cls.customer_b,
                building=cls.building_b,
                created_by=cls.admin_b,
                status_value=ExtraWorkStatus.REQUESTED,
            )
        # Customer A-alt owns 1 row (must not leak to cust_a).
        cls._make_ew(
            customer=cls.customer_a_alt,
            building=cls.building_a1,
            created_by=cls.cust_alt,
            status_value=ExtraWorkStatus.REQUESTED,
        )

    def test_provider_in_company_a_cannot_see_company_b_totals(self):
        # admin_a sees only provider-A rows: 2 own + 1 customer A-alt
        # (same provider, no customer-org isolation at provider level).
        response = self._api(self.admin_a).get(STATS_URL)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["total"], 3)
        # admin_b sees 3 (provider-B only).
        response_b = self._api(self.admin_b).get(STATS_URL)
        self.assertEqual(response_b.status_code, status.HTTP_200_OK)
        self.assertEqual(response_b.data["total"], 3)
        # Cross-check by_status — admin_a sees only the REQUESTED rows
        # of provider A, never the provider-B rows.
        self.assertEqual(
            response.data["by_status"].get("REQUESTED"), 3
        )

    def test_customer_user_cannot_see_other_customer_totals(self):
        # cust_a has CUSTOMER_USER (view_own) on (customer_a,
        # building_a1) and is NOT the creator of the seeded rows.
        # Total should be zero — admin_a was the creator.
        response = self._api(self.cust_a).get(STATS_URL)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["total"], 0)
        # cust_alt has CUSTOMER_USER (view_own) on (customer_a_alt,
        # building_a1) and is the creator of one row.
        response_alt = self._api(self.cust_alt).get(STATS_URL)
        self.assertEqual(response_alt.status_code, status.HTTP_200_OK)
        self.assertEqual(response_alt.data["total"], 1)


# ---------------------------------------------------------------------------
# Soft-deleted rows
# ---------------------------------------------------------------------------
class ExtraWorkStatsSoftDeletedExcludedTests(_StatsFixtureMixin, TestCase):
    @classmethod
    def setUpTestData(cls):
        cls._setup_fixture(suffix="b9-soft")

    def test_soft_deleted_row_not_in_total(self):
        # Baseline: zero rows.
        response = self._api(self.super_admin).get(STATS_URL)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["total"], 0)

        ew = self._make_ew(
            customer=self.customer_a,
            building=self.building_a1,
            created_by=self.admin_a,
        )
        response = self._api(self.super_admin).get(STATS_URL)
        self.assertEqual(response.data["total"], 1)

        # Soft-delete: scope helper filters out deleted_at IS NOT NULL.
        ew.deleted_at = timezone.now()
        ew.deleted_by = self.super_admin
        ew.save(update_fields=["deleted_at", "deleted_by"])

        response = self._api(self.super_admin).get(STATS_URL)
        self.assertEqual(response.data["total"], 0)
        self.assertEqual(response.data["by_status"], {})
        # The by-building endpoint should likewise drop the building.
        by_bld = self._api(self.super_admin).get(STATS_BY_BUILDING_URL)
        self.assertEqual(by_bld.status_code, status.HTTP_200_OK)
        building_ids = [row["building_id"] for row in by_bld.data]
        self.assertNotIn(self.building_a1.id, building_ids)
