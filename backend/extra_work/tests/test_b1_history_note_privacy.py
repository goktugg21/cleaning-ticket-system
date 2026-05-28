"""
B1 — Extra Work + Proposal status-history note privacy.

Pins the customer-side redaction added in B1.3:

  * `ExtraWorkStatusHistorySerializer.note` is empty for CUSTOMER_USER
    readers when `changed_by` is a provider-side actor.

  * `ProposalStatusHistorySerializer.note` is empty for CUSTOMER_USER
    readers when `changed_by` is a provider-side actor.

  * `ProposalStatusHistorySerializer.override_reason` is always empty
    for CUSTOMER_USER readers (provider-only context by definition).

  * Customer-authored history rows keep their notes visible to the
    same customer reading the timeline.

  * Provider readers (SUPER_ADMIN / COMPANY_ADMIN / BUILDING_MANAGER)
    see every field unchanged.

No new permission keys. No migration. STAFF cannot reach either
endpoint at all (P0 staff-privacy patch) — so STAFF refusal stays
covered by `test_staff_privacy_p0.py`, not duplicated here.
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
    ExtraWorkCategory,
    ExtraWorkPricingLineItem,
    ExtraWorkPricingUnitType,
    ExtraWorkRequest,
    ExtraWorkStatus,
    ExtraWorkStatusHistory,
    Proposal,
    ProposalLine,
    ProposalStatus,
    ProposalStatusHistory,
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


class _Fixture(TestCase):
    """Provider + customer + EW + Proposal, with both kinds of
    status-history rows:
      * provider-authored note + override_reason (must be redacted
        for customer readers),
      * customer-authored note (must stay visible to the customer).
    """

    @classmethod
    def setUpTestData(cls):
        suffix = "b1np"
        cls.company = Company.objects.create(
            name=f"Provider {suffix}", slug=f"prov-{suffix}"
        )
        cls.building = Building.objects.create(
            company=cls.company, name=f"Building {suffix}"
        )
        cls.customer = Customer.objects.create(
            company=cls.company,
            name=f"Customer {suffix}",
            building=cls.building,
        )
        CustomerBuildingMembership.objects.create(
            customer=cls.customer, building=cls.building
        )

        cls.admin = _mk(f"admin-{suffix}@example.com", UserRole.COMPANY_ADMIN)
        CompanyUserMembership.objects.create(
            user=cls.admin, company=cls.company
        )
        cls.bm = _mk(f"bm-{suffix}@example.com", UserRole.BUILDING_MANAGER)
        BuildingManagerAssignment.objects.create(
            user=cls.bm, building=cls.building
        )

        cls.cust_user = _mk(
            f"cust-{suffix}@example.com", UserRole.CUSTOMER_USER
        )
        membership = CustomerUserMembership.objects.create(
            customer=cls.customer, user=cls.cust_user
        )
        CustomerUserBuildingAccess.objects.create(
            membership=membership, building=cls.building
        )

        # EW + a couple of history rows in deliberate states.
        cls.ew = ExtraWorkRequest.objects.create(
            company=cls.company,
            building=cls.building,
            customer=cls.customer,
            created_by=cls.cust_user,
            title=f"EW {suffix}",
            description="seed",
            category=ExtraWorkCategory.DEEP_CLEANING,
            status=ExtraWorkStatus.CUSTOMER_REJECTED,
        )
        # Provider-authored note (the row that must be redacted for
        # customer readers).
        cls.ew_provider_row = ExtraWorkStatusHistory.objects.create(
            extra_work=cls.ew,
            old_status=ExtraWorkStatus.UNDER_REVIEW,
            new_status=ExtraWorkStatus.PRICING_PROPOSED,
            changed_by=cls.admin,
            note="Internal: margin tight — flag if approved.",
            is_override=False,
        )
        # Customer-authored note (must stay visible to the same customer).
        cls.ew_customer_row = ExtraWorkStatusHistory.objects.create(
            extra_work=cls.ew,
            old_status=ExtraWorkStatus.PRICING_PROPOSED,
            new_status=ExtraWorkStatus.CUSTOMER_REJECTED,
            changed_by=cls.cust_user,
            note="[Reject reason] Too expensive for our budget.",
            is_override=False,
        )

        # Proposal + history rows mirroring the same shape.
        cls.service_cat = ServiceCategory.objects.create(name=f"Cat {suffix}")
        cls.service = Service.objects.create(
            category=cls.service_cat,
            name=f"Service {suffix}",
            unit_type=ExtraWorkPricingUnitType.HOURS,
            default_unit_price=Decimal("50.00"),
        )
        cls.proposal = Proposal.objects.create(
            extra_work_request=cls.ew,
            status=ProposalStatus.CUSTOMER_REJECTED,
            created_by=cls.admin,
        )
        ProposalLine.objects.create(
            proposal=cls.proposal,
            service=cls.service,
            quantity=Decimal("1.00"),
            unit_type=ExtraWorkPricingUnitType.HOURS,
            unit_price=Decimal("50.00"),
            vat_pct=Decimal("21.00"),
        )
        cls.prop_provider_row = ProposalStatusHistory.objects.create(
            proposal=cls.proposal,
            old_status=ProposalStatus.DRAFT,
            new_status=ProposalStatus.SENT,
            changed_by=cls.admin,
            note="Internal: prepared by night-shift admin.",
            is_override=False,
            override_reason="",
        )
        cls.prop_override_row = ProposalStatusHistory.objects.create(
            proposal=cls.proposal,
            old_status=ProposalStatus.SENT,
            new_status=ProposalStatus.CUSTOMER_REJECTED,
            changed_by=cls.bm,
            note="Internal: BM acting on phone call from customer.",
            is_override=True,
            override_reason="Customer rejected by phone, BM acting.",
        )

    def _api(self, user):
        c = APIClient()
        c.force_authenticate(user=user)
        return c

    def _ew_history_url(self):
        return f"/api/extra-work/{self.ew.id}/status-history/"

    def _proposal_history_url(self):
        return f"/api/extra-work/{self.ew.id}/proposals/{self.proposal.id}/status-history/"


# ---------------------------------------------------------------------------
# ExtraWorkStatusHistory — customer redaction.
# ---------------------------------------------------------------------------
class ExtraWorkHistoryNoteRedactionTests(_Fixture):
    def _rows_by_new_status(self, response):
        return {row["new_status"]: row for row in response.data}

    def test_customer_provider_authored_note_is_redacted(self):
        response = self._api(self.cust_user).get(self._ew_history_url())
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        rows = self._rows_by_new_status(response)
        provider_row = rows[ExtraWorkStatus.PRICING_PROPOSED]
        self.assertEqual(provider_row["note"], "")

    def test_customer_own_note_is_preserved(self):
        response = self._api(self.cust_user).get(self._ew_history_url())
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        rows = self._rows_by_new_status(response)
        own_row = rows[ExtraWorkStatus.CUSTOMER_REJECTED]
        self.assertEqual(
            own_row["note"], "[Reject reason] Too expensive for our budget."
        )

    def test_provider_admin_sees_all_notes(self):
        response = self._api(self.admin).get(self._ew_history_url())
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        rows = self._rows_by_new_status(response)
        self.assertEqual(
            rows[ExtraWorkStatus.PRICING_PROPOSED]["note"],
            "Internal: margin tight — flag if approved.",
        )
        self.assertEqual(
            rows[ExtraWorkStatus.CUSTOMER_REJECTED]["note"],
            "[Reject reason] Too expensive for our budget.",
        )

    def test_building_manager_sees_all_notes(self):
        response = self._api(self.bm).get(self._ew_history_url())
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        rows = self._rows_by_new_status(response)
        self.assertEqual(
            rows[ExtraWorkStatus.PRICING_PROPOSED]["note"],
            "Internal: margin tight — flag if approved.",
        )


# ---------------------------------------------------------------------------
# ProposalStatusHistory — customer redaction (note + override_reason).
# ---------------------------------------------------------------------------
class ProposalHistoryNoteRedactionTests(_Fixture):
    def _rows_by_new_status(self, response):
        return {row["new_status"]: row for row in response.data}

    def test_customer_provider_authored_note_is_redacted(self):
        response = self._api(self.cust_user).get(self._proposal_history_url())
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        rows = self._rows_by_new_status(response)
        self.assertEqual(rows[ProposalStatus.SENT]["note"], "")

    def test_customer_override_reason_is_redacted_on_provider_override(self):
        response = self._api(self.cust_user).get(self._proposal_history_url())
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        rows = self._rows_by_new_status(response)
        override_row = rows[ProposalStatus.CUSTOMER_REJECTED]
        # Note redacted (provider-authored)
        self.assertEqual(override_row["note"], "")
        # Override reason redacted (provider-only context by definition)
        self.assertEqual(override_row["override_reason"], "")
        # The override flag itself stays visible — the customer should
        # see THAT an override happened, just not the free-text content.
        self.assertTrue(override_row["is_override"])

    def test_provider_admin_sees_all_notes_and_override_reason(self):
        response = self._api(self.admin).get(self._proposal_history_url())
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        rows = self._rows_by_new_status(response)
        self.assertEqual(
            rows[ProposalStatus.SENT]["note"],
            "Internal: prepared by night-shift admin.",
        )
        override_row = rows[ProposalStatus.CUSTOMER_REJECTED]
        self.assertEqual(
            override_row["note"],
            "Internal: BM acting on phone call from customer.",
        )
        self.assertEqual(
            override_row["override_reason"],
            "Customer rejected by phone, BM acting.",
        )

    def test_building_manager_sees_all_notes_and_override_reason(self):
        response = self._api(self.bm).get(self._proposal_history_url())
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        rows = self._rows_by_new_status(response)
        override_row = rows[ProposalStatus.CUSTOMER_REJECTED]
        self.assertEqual(
            override_row["override_reason"],
            "Customer rejected by phone, BM acting.",
        )
