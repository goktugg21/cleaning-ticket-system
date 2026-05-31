"""
Sprint 6B — AUTO_START_AFTER_PRICING operational spawn timing.

Canonical behaviour (Source of Truth §5.3 + §5.10):
  * A customer-side permitted actor (Customer Location Manager /
    Customer Company Admin) — or a provider on the customer's behalf —
    creates an Extra Work request with at least one non-agreed / ad-hoc
    line and `request_intent = AUTO_START_AFTER_PRICING`.
  * NO operational ticket is created at initial submit.
  * The provider enters pricing and SENDs it. On SEND the system
    immediately auto-approves the proposal and spawns EXACTLY ONE
    operational ticket — WITHOUT a customer accept/reject step.
  * This is distinct from REQUEST_QUOTE (still needs a customer
    decision) and from the dangerous quote-bypass / direct-publish
    (which records `is_override=True` + a reason). Auto-start records
    NO override — it is only reachable because the customer
    pre-authorised the intent at creation.

The flows here run end-to-end through the real create serializer, the
real proposal state machine, and the Sprint 6A one-ticket spawn helper.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from accounts.models import UserRole
from buildings.models import Building
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
    ExtraWorkRoutingDecision,
    ExtraWorkStatus,
    ProposalStatus,
    ProposalStatusHistory,
    Service,
    ServiceCategory,
)
from tickets.models import Ticket


User = get_user_model()
PASSWORD = "StrongerTestPassword123!"
EW_URL = "/api/extra-work/"
SPAWN_URL = "/api/extra-work/{ew_id}/spawn/"


def _mk(email: str, role: str, **extra) -> User:
    return User.objects.create_user(
        email=email,
        password=PASSWORD,
        role=role,
        full_name=email.split("@")[0],
        **extra,
    )


class AutoStartFixtureMixin:
    """Provider + customer with a Customer Location Manager (allowed to
    pre-authorise AUTO_START), a basic Customer User (forbidden), a
    contract-priced service, an unpriced service, and the catalog rows
    needed to drive both the AUTO_START and the REQUEST_QUOTE paths."""

    @classmethod
    def _setup_fixture(cls):
        cls.company = Company.objects.create(
            name="Sprint6B Provider", slug="sprint6b"
        )
        cls.building = Building.objects.create(
            company=cls.company, name="Building-6B"
        )
        cls.customer = Customer.objects.create(
            company=cls.company, name="Customer-6B", building=cls.building
        )
        CustomerBuildingMembership.objects.create(
            customer=cls.customer, building=cls.building
        )

        cls.super_admin = _mk(
            "super-6b@example.com",
            UserRole.SUPER_ADMIN,
            is_staff=True,
            is_superuser=True,
        )
        cls.admin = _mk("admin-6b@example.com", UserRole.COMPANY_ADMIN)
        CompanyUserMembership.objects.create(
            user=cls.admin, company=cls.company
        )

        # Customer Location Manager — may pre-authorise AUTO_START.
        cls.cust_loc = _mk("cust-loc-6b@example.com", UserRole.CUSTOMER_USER)
        m_loc = CustomerUserMembership.objects.create(
            customer=cls.customer, user=cls.cust_loc
        )
        CustomerUserBuildingAccess.objects.create(
            membership=m_loc,
            building=cls.building,
            access_role=(
                CustomerUserBuildingAccess.AccessRole.CUSTOMER_LOCATION_MANAGER
            ),
            is_active=True,
        )

        # Basic Customer User — forbidden from AUTO_START.
        cls.cust_user = _mk("cust-basic-6b@example.com", UserRole.CUSTOMER_USER)
        m_user = CustomerUserMembership.objects.create(
            customer=cls.customer, user=cls.cust_user
        )
        CustomerUserBuildingAccess.objects.create(
            membership=m_user,
            building=cls.building,
            access_role=CustomerUserBuildingAccess.AccessRole.CUSTOMER_USER,
            is_active=True,
        )

        cls.cat = ServiceCategory.objects.create(name="Cat-6B")
        cls.service_unpriced = Service.objects.create(
            category=cls.cat,
            company=cls.company,
            name="No-contract service",
            unit_type=ExtraWorkPricingUnitType.HOURS,
            default_unit_price=Decimal("40.00"),
        )
        cls.service_agreed = Service.objects.create(
            category=cls.cat,
            company=cls.company,
            name="Agreed service",
            unit_type=ExtraWorkPricingUnitType.HOURS,
            default_unit_price=Decimal("50.00"),
        )
        CustomerServicePrice.objects.create(
            service=cls.service_agreed,
            customer=cls.customer,
            unit_price=Decimal("48.50"),
            vat_pct=Decimal("21.00"),
            valid_from=date(2026, 1, 1),
            valid_to=None,
            is_active=True,
        )

    def _api(self, user):
        c = APIClient()
        c.force_authenticate(user=user)
        return c

    # -- cart submission --------------------------------------------------
    def _submit(self, *, actor, intent, lines):
        payload = {
            "customer": self.customer.id,
            "building": self.building.id,
            "title": "Sprint6B EW",
            "description": "auto-start cart",
            "category": ExtraWorkCategory.DEEP_CLEANING,
            "request_intent": intent,
            "line_items": lines,
        }
        return self._api(actor).post(EW_URL, payload, format="json")

    def _svc_line(self, service, *, qty="2.00"):
        return {
            "service": service.id,
            "quantity": qty,
            "requested_date": "2026-06-15",
            "customer_note": "",
        }

    def _adhoc_line(self, *, qty="2.00"):
        return {
            "custom_description": "Free-text special task",
            "quantity": qty,
            "requested_date": "2026-06-15",
            "customer_note": "",
        }

    # -- provider pricing finalize (auto-seed + price + SEND) -------------
    def _enter_pricing_and_send(self, ew, *, actor=None):
        """Provider moves the EW to UNDER_REVIEW, auto-seeds a proposal
        from the cart, fills any non-contract (zero-priced) line, and
        SENDs it. Returns (proposal_id, send_response)."""
        actor = actor or self.admin
        api = self._api(actor)

        # REQUESTED -> UNDER_REVIEW.
        resp = api.post(
            f"/api/extra-work/{ew.id}/transition/",
            {"to_status": ExtraWorkStatus.UNDER_REVIEW},
            format="json",
        )
        assert resp.status_code == 200, resp.data

        # Auto-seed a proposal (one line per cart item, contract prices
        # pre-filled, non-contract lines at 0.00).
        resp = api.post(
            f"/api/extra-work/{ew.id}/proposals/", {}, format="json"
        )
        assert resp.status_code == 201, resp.data
        proposal_id = resp.data["id"]

        # Price every non-contract line (>0) so the B2 SEND gate passes.
        lines = api.get(
            f"/api/extra-work/{ew.id}/proposals/{proposal_id}/lines/"
        ).data
        for line in lines:
            if Decimal(str(line["unit_price"])) <= 0:
                body = {"unit_price": "55.00", "vat_pct": "21.00"}
                # Ad-hoc (service-less) lines require a description; the
                # auto-seeded line carries none, so supply one alongside
                # the price the provider is entering.
                if not line.get("service") and not (
                    line.get("description") or ""
                ).strip():
                    body["description"] = "Provider-priced custom line"
                patch = api.patch(
                    f"/api/extra-work/{ew.id}/proposals/"
                    f"{proposal_id}/lines/{line['id']}/",
                    body,
                    format="json",
                )
                assert patch.status_code == 200, patch.data

        send = api.post(
            f"/api/extra-work/{ew.id}/proposals/{proposal_id}/transition/",
            {"to_status": ProposalStatus.SENT},
            format="json",
        )
        return proposal_id, send

    def _ticket_count(self, ew):
        return Ticket.objects.filter(extra_work_request=ew).count()


# ---------------------------------------------------------------------------
# AUTO_START_AFTER_PRICING
# ---------------------------------------------------------------------------
class AutoStartTests(AutoStartFixtureMixin, TestCase):
    @classmethod
    def setUpTestData(cls):
        cls._setup_fixture()

    def test_1_create_auto_start_no_ticket_at_submit(self):
        resp = self._submit(
            actor=self.cust_loc,
            intent=ExtraWorkRequestIntent.AUTO_START_AFTER_PRICING,
            lines=[self._svc_line(self.service_unpriced)],
        )
        self.assertEqual(resp.status_code, 201, resp.data)
        self.assertEqual(
            resp.data["request_intent"],
            ExtraWorkRequestIntent.AUTO_START_AFTER_PRICING,
        )
        self.assertEqual(
            resp.data["routing_decision"],
            ExtraWorkRoutingDecision.PROPOSAL,
        )
        ew = ExtraWorkRequest.objects.get(id=resp.data["id"])
        # No operational ticket at submit time.
        self.assertEqual(self._ticket_count(ew), 0)

    def test_2_pricing_finalize_spawns_exactly_one_ticket(self):
        resp = self._submit(
            actor=self.cust_loc,
            intent=ExtraWorkRequestIntent.AUTO_START_AFTER_PRICING,
            lines=[self._svc_line(self.service_unpriced)],
        )
        ew = ExtraWorkRequest.objects.get(id=resp.data["id"])
        self.assertEqual(self._ticket_count(ew), 0)

        _pid, send = self._enter_pricing_and_send(ew)
        self.assertEqual(send.status_code, 200, send.data)

        # Exactly one operational ticket, linked at request level.
        self.assertEqual(self._ticket_count(ew), 1)
        ticket = Ticket.objects.get(extra_work_request=ew)
        self.assertEqual(ticket.extra_work_request_id, ew.id)

        # Parent EW auto-advanced to CUSTOMER_APPROVED (operational-ready)
        # WITHOUT a customer click.
        ew.refresh_from_db()
        self.assertEqual(ew.status, ExtraWorkStatus.CUSTOMER_APPROVED)

        # Origin payload works and is safe (PROPOSAL routing).
        detail = self._api(self.super_admin).get(
            f"/api/tickets/{ticket.id}/"
        )
        self.assertEqual(detail.status_code, 200, detail.data)
        origin = detail.data.get("extra_work_origin")
        self.assertIsNotNone(origin)
        self.assertEqual(origin["origin"], "PROPOSAL")
        self.assertEqual(origin["extra_work_request_id"], ew.id)

    def test_3_ad_hoc_line_auto_start_spawns_one_ticket(self):
        resp = self._submit(
            actor=self.cust_loc,
            intent=ExtraWorkRequestIntent.AUTO_START_AFTER_PRICING,
            lines=[self._adhoc_line()],
        )
        self.assertEqual(resp.status_code, 201, resp.data)
        ew = ExtraWorkRequest.objects.get(id=resp.data["id"])
        self.assertEqual(self._ticket_count(ew), 0)

        _pid, send = self._enter_pricing_and_send(ew)
        self.assertEqual(send.status_code, 200, send.data)
        self.assertEqual(self._ticket_count(ew), 1)

    def test_4_pricing_finalize_is_idempotent(self):
        resp = self._submit(
            actor=self.cust_loc,
            intent=ExtraWorkRequestIntent.AUTO_START_AFTER_PRICING,
            lines=[self._svc_line(self.service_unpriced)],
        )
        ew = ExtraWorkRequest.objects.get(id=resp.data["id"])
        _pid, send = self._enter_pricing_and_send(ew)
        self.assertEqual(send.status_code, 200, send.data)
        self.assertEqual(self._ticket_count(ew), 1)
        existing = Ticket.objects.get(extra_work_request=ew)

        # Re-firing the retry/spawn endpoint must not duplicate.
        retry = self._api(self.super_admin).post(SPAWN_URL.format(ew_id=ew.id))
        self.assertEqual(retry.status_code, 200, retry.data)
        self.assertTrue(retry.data["already_spawned"])
        self.assertEqual(retry.data["spawned_ticket_ids"], [existing.id])
        self.assertEqual(self._ticket_count(ew), 1)

    def test_8_provider_creates_auto_start_on_behalf_of_customer(self):
        # Provider composes AUTO_START on the customer's behalf.
        resp = self._submit(
            actor=self.admin,
            intent=ExtraWorkRequestIntent.AUTO_START_AFTER_PRICING,
            lines=[self._svc_line(self.service_unpriced)],
        )
        self.assertEqual(resp.status_code, 201, resp.data)
        ew = ExtraWorkRequest.objects.get(id=resp.data["id"])
        # No ticket at submit.
        self.assertEqual(self._ticket_count(ew), 0)

        _pid, send = self._enter_pricing_and_send(ew)
        self.assertEqual(send.status_code, 200, send.data)
        self.assertEqual(self._ticket_count(ew), 1)

    def test_9_auto_start_records_no_override(self):
        resp = self._submit(
            actor=self.cust_loc,
            intent=ExtraWorkRequestIntent.AUTO_START_AFTER_PRICING,
            lines=[self._svc_line(self.service_unpriced)],
        )
        ew = ExtraWorkRequest.objects.get(id=resp.data["id"])
        proposal_id, send = self._enter_pricing_and_send(ew)
        self.assertEqual(send.status_code, 200, send.data)

        # The SENT -> CUSTOMER_APPROVED proposal history row is an
        # auto-start system action, NOT a provider override.
        approve_row = (
            ProposalStatusHistory.objects.filter(
                proposal_id=proposal_id,
                new_status=ProposalStatus.CUSTOMER_APPROVED,
            )
            .order_by("-id")
            .first()
        )
        self.assertIsNotNone(approve_row)
        self.assertFalse(approve_row.is_override)
        self.assertEqual(approve_row.override_reason, "")

        # No override metadata leaked onto the parent EW or the proposal.
        ew.refresh_from_db()
        self.assertIsNone(ew.override_by_id)
        self.assertEqual(ew.override_reason, "")
        from extra_work.models import Proposal

        proposal = Proposal.objects.get(id=proposal_id)
        self.assertIsNone(proposal.override_by_id)
        self.assertEqual(proposal.override_reason, "")

    def test_7_basic_customer_user_cannot_create_auto_start(self):
        resp = self._submit(
            actor=self.cust_user,
            intent=ExtraWorkRequestIntent.AUTO_START_AFTER_PRICING,
            lines=[self._svc_line(self.service_unpriced)],
        )
        self.assertEqual(resp.status_code, 400, resp.data)
        # No EW or ticket created.
        self.assertFalse(
            ExtraWorkRequest.objects.filter(
                created_by=self.cust_user
            ).exists()
        )


# ---------------------------------------------------------------------------
# REQUEST_QUOTE — must remain a real customer decision (no auto-start)
# ---------------------------------------------------------------------------
class RequestQuoteUnchangedTests(AutoStartFixtureMixin, TestCase):
    @classmethod
    def setUpTestData(cls):
        cls._setup_fixture()

    def test_5_quote_send_does_not_auto_start_until_customer_accepts(self):
        resp = self._submit(
            actor=self.cust_loc,
            intent=ExtraWorkRequestIntent.REQUEST_QUOTE,
            lines=[self._svc_line(self.service_unpriced)],
        )
        self.assertEqual(resp.status_code, 201, resp.data)
        ew = ExtraWorkRequest.objects.get(id=resp.data["id"])

        proposal_id, send = self._enter_pricing_and_send(ew)
        self.assertEqual(send.status_code, 200, send.data)
        # Quote SENT — proposal still awaiting the customer, NO ticket.
        self.assertEqual(send.data["status"], ProposalStatus.SENT)
        self.assertEqual(self._ticket_count(ew), 0)

        # Customer accepts -> exactly one ticket.
        approve = self._api(self.cust_loc).post(
            f"/api/extra-work/{ew.id}/proposals/{proposal_id}/transition/",
            {"to_status": ProposalStatus.CUSTOMER_APPROVED},
            format="json",
        )
        self.assertEqual(approve.status_code, 200, approve.data)
        self.assertEqual(self._ticket_count(ew), 1)

    def test_6_quote_rejected_spawns_zero_tickets(self):
        resp = self._submit(
            actor=self.cust_loc,
            intent=ExtraWorkRequestIntent.REQUEST_QUOTE,
            lines=[self._svc_line(self.service_unpriced)],
        )
        ew = ExtraWorkRequest.objects.get(id=resp.data["id"])
        proposal_id, send = self._enter_pricing_and_send(ew)
        self.assertEqual(send.status_code, 200, send.data)
        self.assertEqual(self._ticket_count(ew), 0)

        reject = self._api(self.cust_loc).post(
            f"/api/extra-work/{ew.id}/proposals/{proposal_id}/transition/",
            {
                "to_status": ProposalStatus.CUSTOMER_REJECTED,
                "customer_reject_reason": "not needed",
            },
            format="json",
        )
        self.assertEqual(reject.status_code, 200, reject.data)
        self.assertEqual(self._ticket_count(ew), 0)
