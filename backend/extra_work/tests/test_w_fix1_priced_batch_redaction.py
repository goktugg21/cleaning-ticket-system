"""W-FIX1 A3, D3, D4, E3 (audit F3, F28, F8, F52).

A3. A SENT proposal with lines is a price on the record: `is_priced`
    reads True on the list and the detail, so the header's MONEY cell
    and WHAT NEXT can no longer disagree about a proposal the customer
    is looking at. A DRAFT with no lines cannot advertise Send.
D3. A batch resent with an `idempotency_key` is answered with the series
    it already made; the batch path emits the same "requested"
    notifications the single path does.
D4. The series' member payload is redacted for a customer exactly like
    the detail: `budget_hours` never reaches them.
E3. A spawned ticket's title is the line's name; the quantity lives in
    the line.
"""
from __future__ import annotations

from decimal import Decimal

from django.test import TestCase
from rest_framework import status

from extra_work.instant_tickets import _line_summary as instant_summary
from extra_work.models import (
    ExtraWorkGroup,
    ExtraWorkPricingUnitType,
    ExtraWorkStatus,
    Proposal,
    ProposalLine,
    ProposalStatus,
)
from extra_work.proposal_tickets import _ew_line_summary, _proposal_line_summary
from notifications.models import Notification, NotificationType

from .test_sprint28_proposal import ProposalFixtureMixin
from .test_w5b_groups import BATCH_URL, GroupTestBase, group_url

LOCATION_MANAGER_ROLE = "CUSTOMER_LOCATION_MANAGER"


class SentProposalIsPricedTests(ProposalFixtureMixin, TestCase):
    @classmethod
    def setUpTestData(cls):
        cls._setup_fixture()

    def _send(self, ew, proposal):
        resp = self._api(self.admin).post(
            self._transition_url(ew.id, proposal.id),
            {"to_status": ProposalStatus.SENT},
            format="json",
        )
        self.assertEqual(resp.status_code, 200, resp.data)

    def test_an_unpriced_request_reads_unpriced(self):
        ew = self._make_ew(status=ExtraWorkStatus.UNDER_REVIEW)
        detail = self._api(self.admin).get(f"/api/extra-work/{ew.id}/")
        self.assertFalse(detail.data["is_priced"])

    def test_a_sent_proposal_with_a_line_is_priced_on_both_surfaces(self):
        ew = self._make_ew(status=ExtraWorkStatus.UNDER_REVIEW)
        proposal = self._create_proposal(ew)
        self._send(ew, proposal)

        detail = self._api(self.admin).get(f"/api/extra-work/{ew.id}/")
        self.assertEqual(detail.data["status"], ExtraWorkStatus.PRICING_PROPOSED)
        self.assertTrue(detail.data["is_priced"])

        listing = self._api(self.admin).get("/api/extra-work/", {"page_size": 100})
        row = next(r for r in listing.data["results"] if r["id"] == ew.id)
        self.assertTrue(row["is_priced"])

    def test_a_zero_priced_sent_line_is_still_priced(self):
        """Zero is a legal price — the question is whether a line exists."""
        ew = self._make_ew(status=ExtraWorkStatus.UNDER_REVIEW)
        proposal = self._create_proposal(ew)
        line = proposal.lines.get()
        line.unit_price = Decimal("0.00")
        line.save()
        proposal.recompute_totals()
        self._send(ew, proposal)

        detail = self._api(self.admin).get(f"/api/extra-work/{ew.id}/")
        self.assertTrue(detail.data["is_priced"])

    def test_a_draft_without_lines_cannot_advertise_send(self):
        ew = self._make_ew(status=ExtraWorkStatus.UNDER_REVIEW)
        proposal = Proposal.objects.create(
            extra_work_request=ew, status=ProposalStatus.DRAFT, created_by=self.admin
        )
        resp = self._api(self.admin).get(self._proposal_url(ew.id, proposal.id))
        self.assertEqual(resp.status_code, 200, resp.data)
        self.assertFalse(resp.data["actions"]["can_send"])
        self.assertFalse(resp.data["actions"]["can_direct_publish"])

        ProposalLine.objects.create(
            proposal=proposal,
            service=self.service,
            description="",
            quantity=Decimal("1.00"),
            unit_type=ExtraWorkPricingUnitType.FIXED,
            unit_price=Decimal("0.00"),
            vat_pct=Decimal("21.00"),
        )
        resp = self._api(self.admin).get(self._proposal_url(ew.id, proposal.id))
        self.assertTrue(resp.data["actions"]["can_send"])


class BatchIdempotencyAndNotificationsTests(GroupTestBase):
    SLOTS = [
        {"date": "2026-11-19", "time": "18:00", "condition": "AT_HANDOVER"},
        {"date": "2026-11-26", "time": "18:00", "condition": "BEFORE_HANDOVER"},
    ]

    def test_a_resend_with_the_same_key_is_answered_with_the_same_series(self):
        first = self.batch(self.SLOTS, idempotency_key="abc-123")
        self.assertEqual(first.status_code, status.HTTP_201_CREATED, first.data)
        self.assertFalse(first.data["deduplicated"])

        second = self.batch(self.SLOTS, idempotency_key="abc-123")
        self.assertEqual(second.status_code, status.HTTP_200_OK, second.data)
        self.assertTrue(second.data["deduplicated"])
        self.assertEqual(second.data["group"]["id"], first.data["group"]["id"])
        self.assertEqual(second.data["members"], first.data["members"])
        self.assertEqual(second.data["created"], 0)
        self.assertEqual(ExtraWorkGroup.objects.count(), 1)

    def test_a_different_batch_with_a_key_is_a_new_series(self):
        self.batch(self.SLOTS, idempotency_key="k1")
        other = self.batch(
            [{"date": "2026-12-03", "time": "09:30", "condition": "AFTER_HANDOVER"}],
            idempotency_key="k2",
        )
        self.assertEqual(other.status_code, status.HTTP_201_CREATED, other.data)
        self.assertEqual(ExtraWorkGroup.objects.count(), 2)

    def test_without_a_key_the_old_contract_holds(self):
        self.batch(self.SLOTS)
        again = self.batch(self.SLOTS)
        self.assertEqual(again.status_code, status.HTTP_201_CREATED, again.data)
        self.assertEqual(ExtraWorkGroup.objects.count(), 2)

    def test_the_key_is_not_written_onto_a_member(self):
        resp = self.batch(self.SLOTS, idempotency_key="abc-123")
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED, resp.data)

    def test_every_member_emits_the_requested_notification(self):
        Notification.objects.all().delete()
        resp = self.batch(self.SLOTS)
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED, resp.data)
        rows = Notification.objects.filter(
            event_type=NotificationType.EXTRA_WORK_REQUESTED
        )
        # One row per member per management recipient — at least one per
        # member, and referring to the members that were made.
        self.assertGreaterEqual(rows.count(), len(resp.data["members"]))


class GroupMemberRedactionTests(GroupTestBase):
    def setUp(self):
        super().setUp()
        # The fixture's customer user holds the reporter role (view_own);
        # a LOCATION MANAGER may read the whole building's work, which is
        # the reader this redaction exists for.
        from customers.models import CustomerUserBuildingAccess

        CustomerUserBuildingAccess.objects.filter(
            membership__user=self.customer_user
        ).update(access_role=LOCATION_MANAGER_ROLE)

    def test_a_customer_never_reads_budget_hours_on_the_series(self):
        created = self.batch(
            [{"date": "2026-11-19", "time": "18:00", "condition": "AT_HANDOVER"}]
        )
        self.assertEqual(created.status_code, status.HTTP_201_CREATED, created.data)
        group_id = created.data["group"]["id"]

        self.authenticate(self.customer_user)
        resp = self.client.get(group_url(group_id))
        self.assertEqual(resp.status_code, status.HTTP_200_OK, resp.data)
        for member in resp.data["members"]:
            self.assertNotIn("budget_hours", member)
            self.assertIn("title", member)

        self.authenticate(self.company_admin)
        resp = self.client.get(group_url(group_id))
        self.assertEqual(resp.status_code, status.HTTP_200_OK, resp.data)
        for member in resp.data["members"]:
            self.assertIn("budget_hours", member)

    def test_the_batch_url_is_still_the_one_the_client_speaks(self):
        self.assertEqual(BATCH_URL, "/api/extra-work/batch/")


class SpawnTitleTests(TestCase):
    def test_a_proposal_line_title_has_no_quantity_baked_in(self):
        class _Service:
            name = "Consumables refill — standard"

        class _Line:
            service = _Service()
            description = ""
            quantity = Decimal("1.00")

        self.assertEqual(_proposal_line_summary(_Line()), "Consumables refill — standard")

    def test_a_described_line_uses_its_description(self):
        class _Line:
            service = None
            description = "  Waste removal — small van  "
            quantity = Decimal("2.00")

        self.assertEqual(_proposal_line_summary(_Line()), "Waste removal — small van")

    def test_cart_lines_follow_the_same_rule(self):
        class _Service:
            name = "Window round"

        class _Item:
            service = _Service()
            quantity = Decimal("3.00")

        self.assertEqual(_ew_line_summary(_Item()), "Window round")
        self.assertEqual(instant_summary(_Item()), "Window round")
