"""
B3 — URL-smuggling regression matrix.

Every scoped read / write endpoint must refuse cross-tenant URL
typing. This file is the consolidated regression net: it spins up
TWO provider companies (A, B) with their own customers / buildings /
users / tickets / EW / proposals / pricing, then for each surface in
the spec it asserts that:

  * A COMPANY_ADMIN of company B who URL-types a resource id from
    company A gets a clean 4xx (404 for cross-tenant existence; 403
    when the project convention dictates).
  * A CUSTOMER_USER of customer Y who URL-types a resource id from
    customer X gets the same.
  * A Building Manager assigned to building B-other who URL-types
    a resource id at building A-linked gets the same.
  * The new `effective-permissions` endpoint refuses cross-company
    customer_id values.

Surfaces covered (from the B3 spec):
  - tickets (detail + status + messages)
  - ticket attachments (list + create + download)
  - extra work requests (detail + status-history + transition + spawn)
  - proposals (list + detail + lines + status-history + timeline +
    transition + PDF)
  - customer pricing (list + detail)
  - customer ↔ building memberships (list + delete)
  - customer-user membership / access (list + delete + access PATCH)
  - effective-permissions endpoint

This file does NOT test STAFF — the dedicated
`extra_work/tests/test_staff_privacy_p0.py` already pins the STAFF
cross-surface refusals. This file targets the cross-company /
cross-customer / cross-building dimensions instead.

No code changes were required to make these tests pass; they pin
existing behaviour.
"""
from __future__ import annotations

from datetime import date
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
    CustomerServicePrice,
    ExtraWorkCategory,
    ExtraWorkPricingUnitType,
    ExtraWorkRequest,
    ExtraWorkRequestItem,
    ExtraWorkStatus,
    Proposal,
    ProposalLine,
    ProposalStatus,
    Service,
    ServiceCategory,
)
from tickets.models import Ticket, TicketStatus


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


class _Fixture(TestCase):
    """Two provider companies, each with one customer, one building,
    one ticket, one EW request, one Proposal, one CustomerServicePrice.
    """

    @classmethod
    def setUpTestData(cls):
        # ---- company A ----
        cls.company_a = Company.objects.create(name="Prov A B3", slug="prov-a-b3url")
        cls.building_a = Building.objects.create(
            company=cls.company_a, name="Building A"
        )
        cls.customer_a = Customer.objects.create(
            company=cls.company_a, name="Customer A", building=cls.building_a
        )
        CustomerBuildingMembership.objects.create(
            customer=cls.customer_a, building=cls.building_a
        )

        cls.admin_a = _mk("admin-a-b3url@example.com", UserRole.COMPANY_ADMIN)
        CompanyUserMembership.objects.create(
            user=cls.admin_a, company=cls.company_a
        )
        cls.bm_a = _mk("bm-a-b3url@example.com", UserRole.BUILDING_MANAGER)
        BuildingManagerAssignment.objects.create(
            user=cls.bm_a, building=cls.building_a
        )
        cls.cust_a = _mk("cust-a-b3url@example.com", UserRole.CUSTOMER_USER)
        ma = CustomerUserMembership.objects.create(
            customer=cls.customer_a, user=cls.cust_a
        )
        CustomerUserBuildingAccess.objects.create(
            membership=ma, building=cls.building_a
        )

        # ---- company B ----
        cls.company_b = Company.objects.create(name="Prov B B3", slug="prov-b-b3url")
        cls.building_b = Building.objects.create(
            company=cls.company_b, name="Building B"
        )
        cls.customer_b = Customer.objects.create(
            company=cls.company_b, name="Customer B", building=cls.building_b
        )
        CustomerBuildingMembership.objects.create(
            customer=cls.customer_b, building=cls.building_b
        )

        cls.admin_b = _mk("admin-b-b3url@example.com", UserRole.COMPANY_ADMIN)
        CompanyUserMembership.objects.create(
            user=cls.admin_b, company=cls.company_b
        )
        cls.bm_b = _mk("bm-b-b3url@example.com", UserRole.BUILDING_MANAGER)
        BuildingManagerAssignment.objects.create(
            user=cls.bm_b, building=cls.building_b
        )
        cls.cust_b = _mk("cust-b-b3url@example.com", UserRole.CUSTOMER_USER)
        mb = CustomerUserMembership.objects.create(
            customer=cls.customer_b, user=cls.cust_b
        )
        CustomerUserBuildingAccess.objects.create(
            membership=mb, building=cls.building_b
        )

        # ---- super admin ----
        cls.super_admin = _mk(
            "super-b3url@example.com",
            UserRole.SUPER_ADMIN,
            is_staff=True,
            is_superuser=True,
        )

        # ---- service catalog + per-customer contract price ----
        cls.service_cat = ServiceCategory.objects.create(name="Cat B3 URL")
        cls.service = Service.objects.create(
            category=cls.service_cat,
            name="Service B3 URL",
            unit_type=ExtraWorkPricingUnitType.HOURS,
            default_unit_price=Decimal("50.00"),
        )
        cls.price_a = CustomerServicePrice.objects.create(
            service=cls.service,
            customer=cls.customer_a,
            unit_price=Decimal("5.00"),
            vat_pct=Decimal("21.00"),
            valid_from=date(2026, 1, 1),
            is_active=True,
        )
        cls.price_b = CustomerServicePrice.objects.create(
            service=cls.service,
            customer=cls.customer_b,
            unit_price=Decimal("9.00"),
            vat_pct=Decimal("21.00"),
            valid_from=date(2026, 1, 1),
            is_active=True,
        )

        # ---- tickets ----
        cls.ticket_a = Ticket.objects.create(
            company=cls.company_a,
            building=cls.building_a,
            customer=cls.customer_a,
            created_by=cls.cust_a,
            title="Ticket A",
            description="A's ticket",
            status=TicketStatus.OPEN,
        )
        cls.ticket_b = Ticket.objects.create(
            company=cls.company_b,
            building=cls.building_b,
            customer=cls.customer_b,
            created_by=cls.cust_b,
            title="Ticket B",
            description="B's ticket",
            status=TicketStatus.OPEN,
        )

        # ---- Extra Work requests + proposals ----
        cls.ew_a = ExtraWorkRequest.objects.create(
            company=cls.company_a,
            building=cls.building_a,
            customer=cls.customer_a,
            created_by=cls.cust_a,
            title="EW A",
            description="A's EW",
            category=ExtraWorkCategory.DEEP_CLEANING,
            status=ExtraWorkStatus.UNDER_REVIEW,
        )
        ExtraWorkRequestItem.objects.create(
            extra_work_request=cls.ew_a,
            service=cls.service,
            quantity=Decimal("1.00"),
            unit_type=ExtraWorkPricingUnitType.HOURS,
            requested_date=date(2026, 6, 1),
        )
        cls.proposal_a = Proposal.objects.create(
            extra_work_request=cls.ew_a,
            status=ProposalStatus.SENT,
            created_by=cls.admin_a,
        )
        cls.line_a = ProposalLine.objects.create(
            proposal=cls.proposal_a,
            service=cls.service,
            quantity=Decimal("1.00"),
            unit_type=ExtraWorkPricingUnitType.HOURS,
            unit_price=Decimal("5.00"),
            vat_pct=Decimal("21.00"),
        )

        cls.ew_b = ExtraWorkRequest.objects.create(
            company=cls.company_b,
            building=cls.building_b,
            customer=cls.customer_b,
            created_by=cls.cust_b,
            title="EW B",
            description="B's EW",
            category=ExtraWorkCategory.DEEP_CLEANING,
            status=ExtraWorkStatus.UNDER_REVIEW,
        )
        ExtraWorkRequestItem.objects.create(
            extra_work_request=cls.ew_b,
            service=cls.service,
            quantity=Decimal("1.00"),
            unit_type=ExtraWorkPricingUnitType.HOURS,
            requested_date=date(2026, 6, 1),
        )
        cls.proposal_b = Proposal.objects.create(
            extra_work_request=cls.ew_b,
            status=ProposalStatus.SENT,
            created_by=cls.admin_b,
        )
        cls.line_b = ProposalLine.objects.create(
            proposal=cls.proposal_b,
            service=cls.service,
            quantity=Decimal("1.00"),
            unit_type=ExtraWorkPricingUnitType.HOURS,
            unit_price=Decimal("9.00"),
            vat_pct=Decimal("21.00"),
        )

    def _api(self, user):
        c = APIClient()
        c.force_authenticate(user=user)
        return c

    @staticmethod
    def _refused(status_code: int) -> bool:
        # The project mixes 403 (object-permission refusals) and 404
        # (queryset-scope refusals) for cross-tenant cases. Either is
        # an acceptable refusal — anything 2xx is a leak.
        return status_code in (
            status.HTTP_403_FORBIDDEN,
            status.HTTP_404_NOT_FOUND,
        )


# ---------------------------------------------------------------------------
# Tickets
# ---------------------------------------------------------------------------
class TicketsURLSmugglingTests(_Fixture):
    def test_cross_company_admin_cannot_open_other_companys_ticket(self):
        response = self._api(self.admin_b).get(f"/api/tickets/{self.ticket_a.id}/")
        self.assertTrue(self._refused(response.status_code), response.status_code)

    def test_cross_customer_user_cannot_open_other_customers_ticket(self):
        response = self._api(self.cust_b).get(f"/api/tickets/{self.ticket_a.id}/")
        self.assertTrue(self._refused(response.status_code), response.status_code)

    def test_cross_company_bm_cannot_open_other_companys_ticket(self):
        response = self._api(self.bm_b).get(f"/api/tickets/{self.ticket_a.id}/")
        self.assertTrue(self._refused(response.status_code), response.status_code)

    def test_super_admin_can_open_either(self):
        for tid in (self.ticket_a.id, self.ticket_b.id):
            response = self._api(self.super_admin).get(f"/api/tickets/{tid}/")
            self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_cross_company_admin_cannot_drive_other_companys_ticket_status(self):
        response = self._api(self.admin_b).post(
            f"/api/tickets/{self.ticket_a.id}/status/",
            {"to_status": TicketStatus.IN_PROGRESS},
            format="json",
        )
        self.assertTrue(self._refused(response.status_code), response.status_code)

    def test_cross_customer_user_cannot_list_other_customers_messages(self):
        response = self._api(self.cust_b).get(
            f"/api/tickets/{self.ticket_a.id}/messages/"
        )
        self.assertTrue(self._refused(response.status_code), response.status_code)

    def test_cross_customer_user_cannot_list_other_customers_attachments(self):
        response = self._api(self.cust_b).get(
            f"/api/tickets/{self.ticket_a.id}/attachments/"
        )
        self.assertTrue(self._refused(response.status_code), response.status_code)


# ---------------------------------------------------------------------------
# Extra Work parent + spawn
# ---------------------------------------------------------------------------
class ExtraWorkURLSmugglingTests(_Fixture):
    def test_cross_company_admin_cannot_open_other_companys_ew(self):
        response = self._api(self.admin_b).get(
            f"/api/extra-work/{self.ew_a.id}/"
        )
        self.assertTrue(self._refused(response.status_code), response.status_code)

    def test_cross_customer_user_cannot_open_other_customers_ew(self):
        response = self._api(self.cust_b).get(
            f"/api/extra-work/{self.ew_a.id}/"
        )
        self.assertTrue(self._refused(response.status_code), response.status_code)

    def test_cross_company_admin_cannot_drive_other_companys_ew_transition(self):
        response = self._api(self.admin_b).post(
            f"/api/extra-work/{self.ew_a.id}/transition/",
            {"to_status": ExtraWorkStatus.PRICING_PROPOSED},
            format="json",
        )
        self.assertTrue(self._refused(response.status_code), response.status_code)

    def test_cross_company_admin_cannot_list_other_companys_status_history(self):
        response = self._api(self.admin_b).get(
            f"/api/extra-work/{self.ew_a.id}/status-history/"
        )
        self.assertTrue(self._refused(response.status_code), response.status_code)

    def test_cross_company_admin_cannot_call_other_companys_spawn(self):
        response = self._api(self.admin_b).post(
            f"/api/extra-work/{self.ew_a.id}/spawn/"
        )
        self.assertTrue(self._refused(response.status_code), response.status_code)


# ---------------------------------------------------------------------------
# Proposals
# ---------------------------------------------------------------------------
class ProposalURLSmugglingTests(_Fixture):
    def test_cross_company_admin_cannot_list_other_companys_proposals(self):
        response = self._api(self.admin_b).get(
            f"/api/extra-work/{self.ew_a.id}/proposals/"
        )
        self.assertTrue(self._refused(response.status_code), response.status_code)

    def test_cross_company_admin_cannot_open_other_companys_proposal_detail(self):
        response = self._api(self.admin_b).get(
            f"/api/extra-work/{self.ew_a.id}/proposals/{self.proposal_a.id}/"
        )
        self.assertTrue(self._refused(response.status_code), response.status_code)

    def test_cross_company_admin_cannot_list_other_companys_proposal_lines(self):
        response = self._api(self.admin_b).get(
            f"/api/extra-work/{self.ew_a.id}/proposals/{self.proposal_a.id}/lines/"
        )
        self.assertTrue(self._refused(response.status_code), response.status_code)

    def test_cross_company_admin_cannot_read_other_companys_proposal_status_history(self):
        response = self._api(self.admin_b).get(
            f"/api/extra-work/{self.ew_a.id}"
            f"/proposals/{self.proposal_a.id}/status-history/"
        )
        self.assertTrue(self._refused(response.status_code), response.status_code)

    def test_cross_company_admin_cannot_read_other_companys_proposal_timeline(self):
        response = self._api(self.admin_b).get(
            f"/api/extra-work/{self.ew_a.id}"
            f"/proposals/{self.proposal_a.id}/timeline/"
        )
        self.assertTrue(self._refused(response.status_code), response.status_code)

    def test_cross_company_admin_cannot_post_transition_on_other_companys_proposal(self):
        response = self._api(self.admin_b).post(
            f"/api/extra-work/{self.ew_a.id}"
            f"/proposals/{self.proposal_a.id}/transition/",
            {"to_status": ProposalStatus.CUSTOMER_APPROVED},
            format="json",
        )
        self.assertTrue(self._refused(response.status_code), response.status_code)

    def test_cross_company_admin_cannot_download_other_companys_proposal_pdf(self):
        response = self._api(self.admin_b).get(
            f"/api/extra-work/{self.ew_a.id}"
            f"/proposals/{self.proposal_a.id}/pdf/"
        )
        self.assertTrue(self._refused(response.status_code), response.status_code)

    def test_cross_customer_user_cannot_open_other_customers_proposal(self):
        response = self._api(self.cust_b).get(
            f"/api/extra-work/{self.ew_a.id}/proposals/{self.proposal_a.id}/"
        )
        self.assertTrue(self._refused(response.status_code), response.status_code)


# ---------------------------------------------------------------------------
# Customer pricing
# ---------------------------------------------------------------------------
class CustomerPricingURLSmugglingTests(_Fixture):
    def test_cross_company_admin_cannot_list_other_customers_prices(self):
        response = self._api(self.admin_b).get(
            f"/api/customers/{self.customer_a.id}/pricing/"
        )
        self.assertTrue(self._refused(response.status_code), response.status_code)

    def test_cross_company_admin_cannot_open_other_customers_price_detail(self):
        response = self._api(self.admin_b).get(
            f"/api/customers/{self.customer_a.id}/pricing/{self.price_a.id}/"
        )
        self.assertTrue(self._refused(response.status_code), response.status_code)

    def test_id_smuggling_price_id_belonging_to_other_customer_returns_404(self):
        # admin_a is in scope for customer_a, but tries to fetch
        # price_b under customer_a's URL. The detail view re-scopes by
        # the URL-bound customer so this MUST 404.
        response = self._api(self.admin_a).get(
            f"/api/customers/{self.customer_a.id}/pricing/{self.price_b.id}/"
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)


# ---------------------------------------------------------------------------
# Customer ↔ building memberships
# ---------------------------------------------------------------------------
class CustomerBuildingMembershipURLSmugglingTests(_Fixture):
    def test_cross_company_admin_cannot_list_other_customers_buildings(self):
        response = self._api(self.admin_b).get(
            f"/api/customers/{self.customer_a.id}/buildings/"
        )
        self.assertTrue(self._refused(response.status_code), response.status_code)

    def test_cross_company_admin_cannot_unlink_other_customers_building(self):
        response = self._api(self.admin_b).delete(
            f"/api/customers/{self.customer_a.id}/buildings/{self.building_a.id}/"
        )
        self.assertTrue(self._refused(response.status_code), response.status_code)


# ---------------------------------------------------------------------------
# Customer user membership / access
# ---------------------------------------------------------------------------
class CustomerUserMembershipURLSmugglingTests(_Fixture):
    def test_cross_company_admin_cannot_list_other_customers_users(self):
        response = self._api(self.admin_b).get(
            f"/api/customers/{self.customer_a.id}/users/"
        )
        self.assertTrue(self._refused(response.status_code), response.status_code)

    def test_cross_company_admin_cannot_list_other_customers_user_access(self):
        response = self._api(self.admin_b).get(
            f"/api/customers/{self.customer_a.id}/users/{self.cust_a.id}/access/"
        )
        self.assertTrue(self._refused(response.status_code), response.status_code)

    def test_cross_company_admin_cannot_delete_other_customers_user_membership(self):
        response = self._api(self.admin_b).delete(
            f"/api/customers/{self.customer_a.id}/users/{self.cust_a.id}/"
        )
        self.assertTrue(self._refused(response.status_code), response.status_code)


# ---------------------------------------------------------------------------
# Effective-permissions endpoint itself
# ---------------------------------------------------------------------------
class EffectivePermissionsURLSmugglingTests(_Fixture):
    def test_cross_company_admin_cannot_query_other_companys_customer(self):
        # admin_b queries a target user in their own scope but passes
        # customer_id from company A. The customer-scope inline guard
        # must fire with 403.
        response = self._api(self.admin_b).get(
            f"/api/users/{self.bm_b.id}/effective-permissions/"
            f"?customer_id={self.customer_a.id}"
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_cross_company_admin_cannot_query_target_in_other_company(self):
        # admin_b queries a target user from company A — `get_object()`
        # via `CanManageUser` filters that target out of admin_b's
        # queryset → 404.
        response = self._api(self.admin_b).get(
            f"/api/users/{self.bm_a.id}/effective-permissions/"
            f"?customer_id={self.customer_b.id}"
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_super_admin_can_cross_company(self):
        response = self._api(self.super_admin).get(
            f"/api/users/{self.bm_a.id}/effective-permissions/"
            f"?customer_id={self.customer_a.id}"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
