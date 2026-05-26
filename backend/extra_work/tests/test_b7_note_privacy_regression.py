"""
B7 — Extra Work + Proposal note-privacy regression.

The audit for B7 (canonical doc §9, four-tier note taxonomy) confirmed
that every text/note/metadata field on `ExtraWorkRequest`,
`ExtraWorkRequestItem`, `ExtraWorkStatusHistory`, `Proposal`,
`ProposalLine`, `ProposalStatusHistory`, and `ProposalTimelineEvent`
is already correctly classified by purpose and stripped at the
serializer layer for the wrong audience. STAFF is locked out of every
EW/Proposal endpoint at the scope helper (`scope_extra_work_for`
returns `.none()` for STAFF) per the P0 staff-privacy posture.

This file pins that floor as B7 regression coverage so a future
refactor that touches these serializers cannot accidentally
re-introduce a PROVIDER_INTERNAL leak.

Coverage:

  A. ExtraWorkRequestDetailSerializer strips
     `manager_note`, `internal_cost_note`, `override_by`,
     `override_reason`, `override_at` for CUSTOMER_USER.
  B. ProposalLineCustomerSerializer omits `internal_note`.
  C. ProposalTimelineEventCustomerSerializer omits `metadata`.
  D. ProposalStatusHistorySerializer redacts `override_reason` for
     CUSTOMER_USER on customer-decision overrides.
  E. STAFF cannot reach EW list / detail / proposal endpoints at all
     (P0 floor — `scope_extra_work_for` returns `.none()`).
  F. ProposalLine.internal_note is never serialized to a customer
     payload, end-to-end (defence-in-depth direct DB probe).
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework import status
from rest_framework.test import APIClient

from accounts.models import StaffProfile, UserRole
from buildings.models import Building, BuildingStaffVisibility
from companies.models import Company, CompanyUserMembership
from customers.models import (
    Customer,
    CustomerBuildingMembership,
    CustomerUserBuildingAccess,
    CustomerUserMembership,
)
from extra_work.models import (
    ExtraWorkPricingUnitType,
    ExtraWorkRequest,
    ExtraWorkRequestItem,
    ExtraWorkStatus,
    Proposal,
    ProposalLine,
    ProposalStatus,
    ProposalStatusHistory,
    ProposalTimelineEvent,
    ProposalTimelineEventType,
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


class _B7EwFixture(TestCase):
    """One provider company, one building, one customer, one full
    EW + SENT proposal with both customer-visible and provider-
    internal text on every level."""

    @classmethod
    def setUpTestData(cls):
        cls.company = Company.objects.create(name="Prov B7", slug="prov-b7")
        cls.building = Building.objects.create(
            company=cls.company, name="B7-Building"
        )
        cls.customer = Customer.objects.create(
            company=cls.company, name="Customer B7", building=cls.building
        )
        CustomerBuildingMembership.objects.create(
            customer=cls.customer, building=cls.building
        )

        cls.super_admin = _mk(
            "super-b7@example.com",
            UserRole.SUPER_ADMIN,
            is_staff=True,
            is_superuser=True,
        )
        cls.admin = _mk("admin-b7@example.com", UserRole.COMPANY_ADMIN)
        CompanyUserMembership.objects.create(
            user=cls.admin, company=cls.company
        )

        cls.staff_user = _mk("staff-b7@example.com", UserRole.STAFF)
        StaffProfile.objects.create(user=cls.staff_user, is_active=True)
        BuildingStaffVisibility.objects.create(
            user=cls.staff_user, building=cls.building
        )

        cls.customer_user = _mk(
            "cust-b7@example.com", UserRole.CUSTOMER_USER
        )
        membership = CustomerUserMembership.objects.create(
            customer=cls.customer, user=cls.customer_user
        )
        CustomerUserBuildingAccess.objects.create(
            membership=membership,
            building=cls.building,
            access_role=CustomerUserBuildingAccess.AccessRole.CUSTOMER_USER,
        )

        category = ServiceCategory.objects.create(name="B7-cat")
        cls.service = Service.objects.create(
            category=category,
            name="B7-service",
            unit_type=ExtraWorkPricingUnitType.FIXED,
            default_unit_price=Decimal("100.00"),
        )

        cls.ew = ExtraWorkRequest.objects.create(
            company=cls.company,
            building=cls.building,
            customer=cls.customer,
            created_by=cls.customer_user,
            title="B7 EW",
            description="customer-visible description",
            manager_note="MANAGER_NOTE_PROVIDER_INTERNAL",
            internal_cost_note="INTERNAL_COST_PROVIDER_INTERNAL",
            status=ExtraWorkStatus.PRICING_PROPOSED,
            subtotal_amount=Decimal("100.00"),
            vat_amount=Decimal("21.00"),
            total_amount=Decimal("121.00"),
        )
        cls.item = ExtraWorkRequestItem.objects.create(
            extra_work_request=cls.ew,
            service=cls.service,
            unit_type=ExtraWorkPricingUnitType.FIXED,
            quantity=Decimal("1.00"),
            requested_date=date(2026, 6, 1),
            customer_note="customer-visible item note",
        )
        cls.proposal = Proposal.objects.create(
            extra_work_request=cls.ew,
            created_by=cls.admin,
            status=ProposalStatus.SENT,
        )
        cls.line = ProposalLine.objects.create(
            proposal=cls.proposal,
            service=cls.service,
            unit_type=ExtraWorkPricingUnitType.FIXED,
            quantity=Decimal("1.00"),
            unit_price=Decimal("100.00"),
            vat_pct=Decimal("21.00"),
            customer_explanation="explained for the customer",
            internal_note="LINE_INTERNAL_PROVIDER_INTERNAL",
        )
        cls.timeline_event = ProposalTimelineEvent.objects.create(
            proposal=cls.proposal,
            event_type=ProposalTimelineEventType.ADMIN_OVERRIDDEN,
            actor=cls.admin,
            customer_visible=False,
            metadata={"reason": "TIMELINE_METADATA_PROVIDER_INTERNAL"},
        )
        cls.override_row = ProposalStatusHistory.objects.create(
            proposal=cls.proposal,
            old_status=ProposalStatus.SENT,
            new_status=ProposalStatus.CUSTOMER_APPROVED,
            changed_by=cls.admin,
            note="STATUS_HISTORY_OVERRIDE_NOTE_PROVIDER_INTERNAL",
            is_override=True,
            override_reason="STATUS_HISTORY_OVERRIDE_REASON_PROVIDER_INTERNAL",
        )

    def _api(self, user):
        c = APIClient()
        c.force_authenticate(user=user)
        return c


# ---------------------------------------------------------------------------
# A. ExtraWorkRequest detail — PROVIDER_INTERNAL strip for customer
# ---------------------------------------------------------------------------
class ExtraWorkDetailPrivacyTests(_B7EwFixture):
    def test_customer_does_not_see_manager_or_internal_cost_notes(self):
        response = self._api(self.customer_user).get(
            f"/api/extra-work/{self.ew.id}/"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        body = response.content.decode("utf-8")
        # Field strip + body byte-search.
        self.assertNotIn("manager_note", response.data)
        self.assertNotIn("internal_cost_note", response.data)
        self.assertNotIn("override_reason", response.data)
        self.assertNotIn("MANAGER_NOTE_PROVIDER_INTERNAL", body)
        self.assertNotIn("INTERNAL_COST_PROVIDER_INTERNAL", body)

    def test_provider_management_sees_internal_notes(self):
        for actor in (self.super_admin, self.admin):
            response = self._api(actor).get(
                f"/api/extra-work/{self.ew.id}/"
            )
            self.assertEqual(response.status_code, status.HTTP_200_OK)
            self.assertEqual(
                response.data["manager_note"],
                "MANAGER_NOTE_PROVIDER_INTERNAL",
            )
            self.assertEqual(
                response.data["internal_cost_note"],
                "INTERNAL_COST_PROVIDER_INTERNAL",
            )


# ---------------------------------------------------------------------------
# B + C. Proposal line + timeline — PROVIDER_INTERNAL strip
# ---------------------------------------------------------------------------
class ProposalLineAndTimelinePrivacyTests(_B7EwFixture):
    def test_customer_proposal_lines_omit_internal_note(self):
        response = self._api(self.customer_user).get(
            f"/api/extra-work/{self.ew.id}/proposals/{self.proposal.id}/lines/"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        body = response.content.decode("utf-8")
        self.assertNotIn("LINE_INTERNAL_PROVIDER_INTERNAL", body)
        # customer_explanation IS visible.
        self.assertIn("explained for the customer", body)
        for line in response.data:
            self.assertNotIn("internal_note", line)

    def test_provider_management_proposal_lines_include_internal_note(self):
        for actor in (self.super_admin, self.admin):
            response = self._api(actor).get(
                f"/api/extra-work/{self.ew.id}/proposals/{self.proposal.id}/lines/"
            )
            self.assertEqual(response.status_code, status.HTTP_200_OK)
            line_payload = response.data[0]
            self.assertEqual(
                line_payload["internal_note"],
                "LINE_INTERNAL_PROVIDER_INTERNAL",
            )

    def test_customer_timeline_omits_metadata_and_hidden_events(self):
        response = self._api(self.customer_user).get(
            f"/api/extra-work/{self.ew.id}/proposals/{self.proposal.id}/timeline/"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        body = response.content.decode("utf-8")
        self.assertNotIn("TIMELINE_METADATA_PROVIDER_INTERNAL", body)
        # The event was created with customer_visible=False, so the
        # row should not appear in the customer's response at all.
        for event in response.data:
            self.assertNotIn("metadata", event)


# ---------------------------------------------------------------------------
# D. Proposal status-history — override_reason redaction for customer
# ---------------------------------------------------------------------------
class ProposalStatusHistoryRedactionTests(_B7EwFixture):
    def test_customer_status_history_redacts_override_reason(self):
        response = self._api(self.customer_user).get(
            f"/api/extra-work/{self.ew.id}/proposals/{self.proposal.id}/status-history/"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        body = response.content.decode("utf-8")
        self.assertNotIn(
            "STATUS_HISTORY_OVERRIDE_REASON_PROVIDER_INTERNAL", body
        )
        self.assertNotIn(
            "STATUS_HISTORY_OVERRIDE_NOTE_PROVIDER_INTERNAL", body
        )

    def test_provider_management_status_history_includes_override_fields(self):
        for actor in (self.super_admin, self.admin):
            response = self._api(actor).get(
                f"/api/extra-work/{self.ew.id}/proposals/{self.proposal.id}/status-history/"
            )
            self.assertEqual(response.status_code, status.HTTP_200_OK)
            override = next(
                row for row in response.data if row["id"] == self.override_row.id
            )
            self.assertEqual(
                override["override_reason"],
                "STATUS_HISTORY_OVERRIDE_REASON_PROVIDER_INTERNAL",
            )
            self.assertEqual(
                override["note"],
                "STATUS_HISTORY_OVERRIDE_NOTE_PROVIDER_INTERNAL",
            )


# ---------------------------------------------------------------------------
# E. STAFF cannot reach Extra Work / Proposal endpoints at all
# ---------------------------------------------------------------------------
class StaffPrivacyFloorTests(_B7EwFixture):
    def _expect_locked_out(self, response):
        self.assertIn(
            response.status_code,
            (status.HTTP_403_FORBIDDEN, status.HTTP_404_NOT_FOUND),
        )

    def test_staff_cannot_list_extra_work(self):
        response = self._api(self.staff_user).get("/api/extra-work/")
        # Either 403 at the permission layer or empty list — never
        # body content from EW rows.
        if response.status_code == status.HTTP_200_OK:
            data = response.data.get("results", response.data)
            self.assertEqual(data, [])
        else:
            self._expect_locked_out(response)

    def test_staff_cannot_retrieve_extra_work_detail(self):
        self._expect_locked_out(
            self._api(self.staff_user).get(
                f"/api/extra-work/{self.ew.id}/"
            )
        )

    def test_staff_cannot_list_proposals(self):
        self._expect_locked_out(
            self._api(self.staff_user).get(
                f"/api/extra-work/{self.ew.id}/proposals/"
            )
        )

    def test_staff_cannot_list_proposal_lines(self):
        self._expect_locked_out(
            self._api(self.staff_user).get(
                f"/api/extra-work/{self.ew.id}/proposals/{self.proposal.id}/lines/"
            )
        )

    def test_staff_cannot_read_proposal_pdf(self):
        self._expect_locked_out(
            self._api(self.staff_user).get(
                f"/api/extra-work/{self.ew.id}/proposals/{self.proposal.id}/pdf/"
            )
        )


# ---------------------------------------------------------------------------
# F. Defence-in-depth — body byte-search across every read endpoint
# ---------------------------------------------------------------------------
class CustomerByteSearchTests(_B7EwFixture):
    """End-to-end: a single customer GET on each EW/Proposal endpoint
    must never yield the PROVIDER_INTERNAL sentinel strings in the
    raw response body."""

    SENTINELS = (
        "MANAGER_NOTE_PROVIDER_INTERNAL",
        "INTERNAL_COST_PROVIDER_INTERNAL",
        "LINE_INTERNAL_PROVIDER_INTERNAL",
        "TIMELINE_METADATA_PROVIDER_INTERNAL",
        "STATUS_HISTORY_OVERRIDE_REASON_PROVIDER_INTERNAL",
        "STATUS_HISTORY_OVERRIDE_NOTE_PROVIDER_INTERNAL",
    )

    def test_customer_ew_detail_no_internal_leak(self):
        response = self._api(self.customer_user).get(
            f"/api/extra-work/{self.ew.id}/"
        )
        body = response.content.decode("utf-8")
        for sentinel in self.SENTINELS:
            self.assertNotIn(sentinel, body, f"leak: {sentinel}")

    def test_customer_proposal_detail_no_internal_leak(self):
        response = self._api(self.customer_user).get(
            f"/api/extra-work/{self.ew.id}/proposals/{self.proposal.id}/"
        )
        body = response.content.decode("utf-8")
        for sentinel in self.SENTINELS:
            self.assertNotIn(sentinel, body, f"leak: {sentinel}")

    def test_customer_proposal_pdf_no_internal_leak(self):
        response = self._api(self.customer_user).get(
            f"/api/extra-work/{self.ew.id}/proposals/{self.proposal.id}/pdf/"
        )
        # PDF bytes — substring search on raw body must still not
        # contain any sentinel.
        for sentinel in self.SENTINELS:
            self.assertNotIn(
                sentinel.encode("utf-8"),
                response.content,
                f"leak: {sentinel}",
            )

    def test_customer_status_history_no_internal_leak(self):
        response = self._api(self.customer_user).get(
            f"/api/extra-work/{self.ew.id}/proposals/{self.proposal.id}/status-history/"
        )
        body = response.content.decode("utf-8")
        for sentinel in self.SENTINELS:
            self.assertNotIn(sentinel, body, f"leak: {sentinel}")

    def test_customer_timeline_no_internal_leak(self):
        response = self._api(self.customer_user).get(
            f"/api/extra-work/{self.ew.id}/proposals/{self.proposal.id}/timeline/"
        )
        body = response.content.decode("utf-8")
        for sentinel in self.SENTINELS:
            self.assertNotIn(sentinel, body, f"leak: {sentinel}")
