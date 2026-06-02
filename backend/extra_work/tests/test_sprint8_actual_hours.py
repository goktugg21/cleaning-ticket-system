"""
Sprint 8B — actual-hours entry + final-amount finalization for Extra
Work.

Canonical behaviour (Source of Truth §5.12):
  * Provider-only entry of `actual_hours` on HOURS-unit lines.
  * `final_*` recomputed from the active priced-line set, substituting
    `actual_hours` for `quantity` only on hourly lines. `quantity` /
    `snapshot_*` / `unit_price` are NEVER mutated.
  * An EW operational ticket cannot be sent for customer approval
    while any hourly line is missing its actual hours
    (`actual_hours_required`).
  * `final_*` is frozen when the operational ticket reaches APPROVED.
  * Once the operational ticket is APPROVED/CLOSED the final amount is
    locked (`final_amount_locked`).

Flows run end-to-end through the real create serializer, the real
proposal / ticket state machines, and the Sprint 6A one-ticket spawn
helper — mirroring `test_sprint6b_auto_start_after_pricing.py`.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
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
    ExtraWorkRoutingDecision,
    ExtraWorkStatus,
    ExtraWorkStatusHistory,
    ProposalLine,
    ProposalStatus,
    Service,
    ServiceCategory,
)
from tickets.models import Ticket, TicketStatus


User = get_user_model()
PASSWORD = "StrongerTestPassword123!"
EW_URL = "/api/extra-work/"


def _mk(email: str, role: str, **extra) -> User:
    return User.objects.create_user(
        email=email,
        password=PASSWORD,
        role=role,
        full_name=email.split("@")[0],
        **extra,
    )


def _two(x: Decimal) -> Decimal:
    return Decimal(x).quantize(Decimal("0.01"))


class ActualHoursFixtureMixin:
    """Provider company + customer with a Customer Location Manager,
    a basic Customer User, an hourly contract-priced service, an hourly
    unpriced service, and a fixed-price service. A second company +
    out-of-scope BM cover the cross-scope tests."""

    @classmethod
    def _setup_fixture(cls):
        cls.company = Company.objects.create(name="S8B Provider", slug="s8b")
        cls.building = Building.objects.create(
            company=cls.company, name="Building-8B"
        )
        cls.customer = Customer.objects.create(
            company=cls.company, name="Customer-8B", building=cls.building
        )
        CustomerBuildingMembership.objects.create(
            customer=cls.customer, building=cls.building
        )

        cls.super_admin = _mk(
            "super-8b@example.com",
            UserRole.SUPER_ADMIN,
            is_staff=True,
            is_superuser=True,
        )
        cls.admin = _mk("admin-8b@example.com", UserRole.COMPANY_ADMIN)
        CompanyUserMembership.objects.create(
            user=cls.admin, company=cls.company
        )

        cls.bm = _mk("bm-8b@example.com", UserRole.BUILDING_MANAGER)
        BuildingManagerAssignment.objects.create(
            user=cls.bm, building=cls.building
        )

        cls.staff = _mk("staff-8b@example.com", UserRole.STAFF)

        # Customer Location Manager — may pre-authorise AUTO_START /
        # decide on proposals.
        cls.cust_loc = _mk("cust-loc-8b@example.com", UserRole.CUSTOMER_USER)
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

        # Second company + out-of-scope BM + other-company admin.
        cls.other_company = Company.objects.create(
            name="S8B Other", slug="s8b-other"
        )
        cls.other_building = Building.objects.create(
            company=cls.other_company, name="Other-Building-8B"
        )
        cls.other_admin = _mk(
            "other-admin-8b@example.com", UserRole.COMPANY_ADMIN
        )
        CompanyUserMembership.objects.create(
            user=cls.other_admin, company=cls.other_company
        )
        cls.other_bm = _mk("other-bm-8b@example.com", UserRole.BUILDING_MANAGER)
        BuildingManagerAssignment.objects.create(
            user=cls.other_bm, building=cls.other_building
        )

        cls.cat = ServiceCategory.objects.create(name="Cat-8B")
        # Hourly service WITH a customer contract price -> DIRECT route.
        cls.svc_hourly_agreed = Service.objects.create(
            category=cls.cat,
            company=cls.company,
            name="Hourly agreed",
            unit_type=ExtraWorkPricingUnitType.HOURS,
            default_unit_price=Decimal("50.00"),
        )
        cls.csp = CustomerServicePrice.objects.create(
            service=cls.svc_hourly_agreed,
            customer=cls.customer,
            unit_price=Decimal("40.00"),
            vat_pct=Decimal("21.00"),
            valid_from=date(2026, 1, 1),
            valid_to=None,
            is_active=True,
        )
        # Hourly service with NO contract -> PROPOSAL route.
        cls.svc_hourly_unpriced = Service.objects.create(
            category=cls.cat,
            company=cls.company,
            name="Hourly unpriced",
            unit_type=ExtraWorkPricingUnitType.HOURS,
            default_unit_price=Decimal("60.00"),
        )
        # Fixed service WITH a contract price (for mixed / fixed-only).
        cls.svc_fixed_agreed = Service.objects.create(
            category=cls.cat,
            company=cls.company,
            name="Fixed agreed",
            unit_type=ExtraWorkPricingUnitType.FIXED,
            default_unit_price=Decimal("100.00"),
        )
        CustomerServicePrice.objects.create(
            service=cls.svc_fixed_agreed,
            customer=cls.customer,
            unit_price=Decimal("100.00"),
            vat_pct=Decimal("21.00"),
            valid_from=date(2026, 1, 1),
            valid_to=None,
            is_active=True,
        )

    # -- helpers ----------------------------------------------------------
    def _api(self, user):
        c = APIClient()
        c.force_authenticate(user=user)
        return c

    def _submit(self, *, actor, intent, lines):
        payload = {
            "customer": self.customer.id,
            "building": self.building.id,
            "title": "Sprint8B EW",
            "description": "actual hours cart",
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

    def _ticket_for(self, ew):
        return Ticket.objects.get(extra_work_request=ew)

    def _ticket_count(self, ew):
        return Ticket.objects.filter(extra_work_request=ew).count()

    def _enter_pricing_and_send(self, ew, *, actor=None, unit_price="55.00"):
        """Provider -> UNDER_REVIEW, auto-seed proposal, price non-
        contract lines, SEND. Returns (proposal_id, send_response)."""
        actor = actor or self.admin
        api = self._api(actor)

        resp = api.post(
            f"/api/extra-work/{ew.id}/transition/",
            {"to_status": ExtraWorkStatus.UNDER_REVIEW},
            format="json",
        )
        assert resp.status_code == 200, resp.data

        resp = api.post(
            f"/api/extra-work/{ew.id}/proposals/", {}, format="json"
        )
        assert resp.status_code == 201, resp.data
        proposal_id = resp.data["id"]

        lines = api.get(
            f"/api/extra-work/{ew.id}/proposals/{proposal_id}/lines/"
        ).data
        for line in lines:
            if Decimal(str(line["unit_price"])) <= 0:
                body = {"unit_price": unit_price, "vat_pct": "21.00"}
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

    def _drive_ticket(self, ew, *, to_status, actor=None, note="done"):
        actor = actor or self.admin
        ticket = self._ticket_for(ew)
        return self._api(actor).post(
            f"/api/tickets/{ticket.id}/status/",
            {"to_status": to_status, "note": note},
            format="json",
        )

    def _post_hours(self, ew, lines, *, actor=None):
        actor = actor or self.admin
        return self._api(actor).post(
            f"/api/extra-work/{ew.id}/actual-hours/",
            {"lines": lines},
            format="json",
        )


# ---------------------------------------------------------------------------
# Final-amount computation across the three routes
# ---------------------------------------------------------------------------
class FinalAmountComputationTests(ActualHoursFixtureMixin, TestCase):
    @classmethod
    def setUpTestData(cls):
        cls._setup_fixture()

    def test_1_direct_hourly_final_uses_actual_hours(self):
        # DIRECT (instant) route: agreed hourly service.
        resp = self._submit(
            actor=self.cust_loc,
            intent=ExtraWorkRequestIntent.DIRECT_AGREED_PRICE_ORDER,
            lines=[self._svc_line(self.svc_hourly_agreed, qty="2.00")],
        )
        self.assertEqual(resp.status_code, 201, resp.data)
        ew = ExtraWorkRequest.objects.get(id=resp.data["id"])
        self.assertEqual(ew.routing_decision, ExtraWorkRoutingDecision.INSTANT)
        self.assertEqual(self._ticket_count(ew), 1)

        line = ew.line_items.get()
        orig_qty = line.quantity
        orig_snap = line.snapshot_unit_price

        # Enter actual hours != ordered quantity.
        r = self._post_hours(
            ew, [{"line_id": line.id, "actual_hours": "3.50"}]
        )
        self.assertEqual(r.status_code, 200, r.data)

        # final_total = round(3.50 * 40) * (1 + 0.21).
        subtotal = _two(Decimal("3.50") * Decimal("40.00"))  # 140.00
        vat = _two(subtotal * Decimal("21.00") / Decimal("100"))  # 29.40
        ew.refresh_from_db()
        self.assertEqual(ew.final_subtotal_amount, subtotal)
        self.assertEqual(ew.final_vat_amount, vat)
        self.assertEqual(ew.final_total_amount, _two(subtotal + vat))

        # Original quantity + snapshot unchanged.
        line.refresh_from_db()
        self.assertEqual(line.quantity, orig_qty)
        self.assertEqual(line.snapshot_unit_price, orig_snap)
        self.assertEqual(line.actual_hours, Decimal("3.50"))

    def test_2_request_quote_hourly_final_from_proposal(self):
        resp = self._submit(
            actor=self.cust_loc,
            intent=ExtraWorkRequestIntent.REQUEST_QUOTE,
            lines=[self._svc_line(self.svc_hourly_unpriced, qty="2.00")],
        )
        ew = ExtraWorkRequest.objects.get(id=resp.data["id"])
        proposal_id, send = self._enter_pricing_and_send(
            ew, unit_price="55.00"
        )
        self.assertEqual(send.status_code, 200, send.data)
        # Customer accepts -> ticket spawned.
        approve = self._api(self.cust_loc).post(
            f"/api/extra-work/{ew.id}/proposals/{proposal_id}/transition/",
            {"to_status": ProposalStatus.CUSTOMER_APPROVED},
            format="json",
        )
        self.assertEqual(approve.status_code, 200, approve.data)
        self.assertEqual(self._ticket_count(ew), 1)

        pline = ProposalLine.objects.get(proposal_id=proposal_id)
        r = self._post_hours(
            ew, [{"line_id": pline.id, "actual_hours": "5.00"}]
        )
        self.assertEqual(r.status_code, 200, r.data)

        subtotal = _two(Decimal("5.00") * Decimal("55.00"))  # 275.00
        vat = _two(subtotal * Decimal("21.00") / Decimal("100"))
        ew.refresh_from_db()
        self.assertEqual(ew.final_total_amount, _two(subtotal + vat))
        pline.refresh_from_db()
        self.assertEqual(pline.actual_hours, Decimal("5.00"))
        self.assertEqual(pline.quantity, Decimal("2.00"))

    def test_3_auto_start_hourly_final_correct(self):
        resp = self._submit(
            actor=self.cust_loc,
            intent=ExtraWorkRequestIntent.AUTO_START_AFTER_PRICING,
            lines=[self._svc_line(self.svc_hourly_unpriced, qty="2.00")],
        )
        ew = ExtraWorkRequest.objects.get(id=resp.data["id"])
        proposal_id, send = self._enter_pricing_and_send(
            ew, unit_price="70.00"
        )
        self.assertEqual(send.status_code, 200, send.data)
        # AUTO_START spawns immediately on SEND.
        self.assertEqual(self._ticket_count(ew), 1)

        pline = ProposalLine.objects.get(proposal_id=proposal_id)
        r = self._post_hours(
            ew, [{"line_id": pline.id, "actual_hours": "1.25"}]
        )
        self.assertEqual(r.status_code, 200, r.data)
        subtotal = _two(Decimal("1.25") * Decimal("70.00"))  # 87.50
        vat = _two(subtotal * Decimal("21.00") / Decimal("100"))
        ew.refresh_from_db()
        self.assertEqual(ew.final_total_amount, _two(subtotal + vat))

    def test_4_mixed_cart_hourly_plus_fixed(self):
        # Mixed DIRECT cart: hourly agreed + fixed agreed (both contract).
        resp = self._submit(
            actor=self.cust_loc,
            intent=ExtraWorkRequestIntent.DIRECT_AGREED_PRICE_ORDER,
            lines=[
                self._svc_line(self.svc_hourly_agreed, qty="2.00"),
                self._svc_line(self.svc_fixed_agreed, qty="1.00"),
            ],
        )
        self.assertEqual(resp.status_code, 201, resp.data)
        ew = ExtraWorkRequest.objects.get(id=resp.data["id"])
        self.assertEqual(ew.routing_decision, ExtraWorkRoutingDecision.INSTANT)

        hourly_line = ew.line_items.get(service=self.svc_hourly_agreed)
        r = self._post_hours(
            ew, [{"line_id": hourly_line.id, "actual_hours": "4.00"}]
        )
        self.assertEqual(r.status_code, 200, r.data)

        # Hourly: 4.00 * 40 = 160.00. Fixed: 1.00 * 100 = 100.00.
        hourly_sub = _two(Decimal("4.00") * Decimal("40.00"))
        fixed_sub = _two(Decimal("1.00") * Decimal("100.00"))
        subtotal = hourly_sub + fixed_sub  # 260.00
        vat = _two(hourly_sub * Decimal("0.21")) + _two(
            fixed_sub * Decimal("0.21")
        )
        ew.refresh_from_db()
        self.assertEqual(ew.final_subtotal_amount, _two(subtotal))
        self.assertEqual(ew.final_total_amount, _two(subtotal + vat))

    def test_14_snapshot_integrity_after_csp_change(self):
        resp = self._submit(
            actor=self.cust_loc,
            intent=ExtraWorkRequestIntent.DIRECT_AGREED_PRICE_ORDER,
            lines=[self._svc_line(self.svc_hourly_agreed, qty="2.00")],
        )
        ew = ExtraWorkRequest.objects.get(id=resp.data["id"])
        line = ew.line_items.get()
        r = self._post_hours(
            ew, [{"line_id": line.id, "actual_hours": "3.00"}]
        )
        self.assertEqual(r.status_code, 200, r.data)

        # Change the contract rate AFTER entering hours.
        self.csp.unit_price = Decimal("999.00")
        self.csp.save(update_fields=["unit_price"])

        # Re-enter hours; final must still use the snapshot (40.00),
        # not the mutated contract (999.00).
        r2 = self._post_hours(
            ew, [{"line_id": line.id, "actual_hours": "3.00"}]
        )
        self.assertEqual(r2.status_code, 200, r2.data)
        subtotal = _two(Decimal("3.00") * Decimal("40.00"))
        vat = _two(subtotal * Decimal("0.21"))
        ew.refresh_from_db()
        self.assertEqual(ew.final_total_amount, _two(subtotal + vat))


# ---------------------------------------------------------------------------
# Completion gate
# ---------------------------------------------------------------------------
class CompletionGateTests(ActualHoursFixtureMixin, TestCase):
    @classmethod
    def setUpTestData(cls):
        cls._setup_fixture()

    def _drive_to_in_progress(self, ew):
        # OPEN -> IN_PROGRESS via admin.
        r = self._drive_ticket(
            ew, to_status=TicketStatus.IN_PROGRESS, actor=self.admin
        )
        assert r.status_code == 200, r.data

    def test_5_gate_blocks_then_allows_after_hours(self):
        resp = self._submit(
            actor=self.cust_loc,
            intent=ExtraWorkRequestIntent.DIRECT_AGREED_PRICE_ORDER,
            lines=[self._svc_line(self.svc_hourly_agreed, qty="2.00")],
        )
        ew = ExtraWorkRequest.objects.get(id=resp.data["id"])
        self._drive_to_in_progress(ew)

        # Missing actual hours -> blocked.
        blocked = self._drive_ticket(
            ew,
            to_status=TicketStatus.WAITING_CUSTOMER_APPROVAL,
            actor=self.admin,
        )
        self.assertEqual(blocked.status_code, 400, blocked.data)
        self.assertEqual(blocked.data["code"], "actual_hours_required")

        # Enter hours, then the transition succeeds.
        line = ew.line_items.get()
        r = self._post_hours(
            ew, [{"line_id": line.id, "actual_hours": "2.00"}]
        )
        self.assertEqual(r.status_code, 200, r.data)

        ok = self._drive_ticket(
            ew,
            to_status=TicketStatus.WAITING_CUSTOMER_APPROVAL,
            actor=self.admin,
        )
        self.assertEqual(ok.status_code, 200, ok.data)

    def test_6_normal_ticket_unaffected(self):
        # A normal (non-EW) ticket can move to WAITING_CUSTOMER_APPROVAL.
        ticket = Ticket.objects.create(
            company=self.company,
            building=self.building,
            customer=self.customer,
            created_by=self.admin,
            title="Plain ticket",
            description="no EW",
            status=TicketStatus.IN_PROGRESS,
        )
        r = self._api(self.admin).post(
            f"/api/tickets/{ticket.id}/status/",
            {"to_status": TicketStatus.WAITING_CUSTOMER_APPROVAL, "note": "x"},
            format="json",
        )
        self.assertEqual(r.status_code, 200, r.data)

    def test_7_fixed_only_ew_unaffected(self):
        resp = self._submit(
            actor=self.cust_loc,
            intent=ExtraWorkRequestIntent.DIRECT_AGREED_PRICE_ORDER,
            lines=[self._svc_line(self.svc_fixed_agreed, qty="1.00")],
        )
        ew = ExtraWorkRequest.objects.get(id=resp.data["id"])
        self._drive_to_in_progress(ew)
        ok = self._drive_ticket(
            ew,
            to_status=TicketStatus.WAITING_CUSTOMER_APPROVAL,
            actor=self.admin,
        )
        self.assertEqual(ok.status_code, 200, ok.data)


# ---------------------------------------------------------------------------
# Permission / scope
# ---------------------------------------------------------------------------
class PermissionScopeTests(ActualHoursFixtureMixin, TestCase):
    @classmethod
    def setUpTestData(cls):
        cls._setup_fixture()

    def _fresh_ew(self):
        resp = self._submit(
            actor=self.cust_loc,
            intent=ExtraWorkRequestIntent.DIRECT_AGREED_PRICE_ORDER,
            lines=[self._svc_line(self.svc_hourly_agreed, qty="2.00")],
        )
        return ExtraWorkRequest.objects.get(id=resp.data["id"])

    def test_8_customer_user_forbidden(self):
        ew = self._fresh_ew()
        line = ew.line_items.get()
        r = self._post_hours(
            ew,
            [{"line_id": line.id, "actual_hours": "2.00"}],
            actor=self.cust_loc,
        )
        self.assertEqual(r.status_code, 403, r.data)
        self.assertEqual(r.data["code"], "actual_hours_forbidden")

    def test_9_staff_forbidden(self):
        ew = self._fresh_ew()
        line = ew.line_items.get()
        r = self._post_hours(
            ew,
            [{"line_id": line.id, "actual_hours": "2.00"}],
            actor=self.staff,
        )
        self.assertEqual(r.status_code, 403, r.data)
        self.assertEqual(r.data["code"], "actual_hours_forbidden")

    def test_10_provider_scope_matrix(self):
        ew = self._fresh_ew()
        line = ew.line_items.get()

        # SUPER_ADMIN ok.
        r = self._post_hours(
            ew, [{"line_id": line.id, "actual_hours": "2.00"}],
            actor=self.super_admin,
        )
        self.assertEqual(r.status_code, 200, r.data)

        # COMPANY_ADMIN own company ok.
        r = self._post_hours(
            ew, [{"line_id": line.id, "actual_hours": "2.50"}],
            actor=self.admin,
        )
        self.assertEqual(r.status_code, 200, r.data)

        # Scoped BM ok.
        r = self._post_hours(
            ew, [{"line_id": line.id, "actual_hours": "3.00"}],
            actor=self.bm,
        )
        self.assertEqual(r.status_code, 200, r.data)

        # Other-company admin: out of scope -> 404 (scope queryset
        # excludes the EW).
        r = self._post_hours(
            ew, [{"line_id": line.id, "actual_hours": "3.00"}],
            actor=self.other_admin,
        )
        self.assertEqual(r.status_code, 404, r.data)

        # Out-of-scope BM (other building) -> 404.
        r = self._post_hours(
            ew, [{"line_id": line.id, "actual_hours": "3.00"}],
            actor=self.other_bm,
        )
        self.assertEqual(r.status_code, 404, r.data)


# ---------------------------------------------------------------------------
# Validation codes
# ---------------------------------------------------------------------------
class ValidationCodeTests(ActualHoursFixtureMixin, TestCase):
    @classmethod
    def setUpTestData(cls):
        cls._setup_fixture()

    def test_11_not_hourly(self):
        resp = self._submit(
            actor=self.cust_loc,
            intent=ExtraWorkRequestIntent.DIRECT_AGREED_PRICE_ORDER,
            lines=[self._svc_line(self.svc_fixed_agreed, qty="1.00")],
        )
        ew = ExtraWorkRequest.objects.get(id=resp.data["id"])
        line = ew.line_items.get()
        r = self._post_hours(
            ew, [{"line_id": line.id, "actual_hours": "2.00"}]
        )
        self.assertEqual(r.status_code, 400, r.data)
        self.assertEqual(r.data["code"], "actual_hours_not_hourly")

    def test_12_invalid_zero_and_negative(self):
        resp = self._submit(
            actor=self.cust_loc,
            intent=ExtraWorkRequestIntent.DIRECT_AGREED_PRICE_ORDER,
            lines=[self._svc_line(self.svc_hourly_agreed, qty="2.00")],
        )
        ew = ExtraWorkRequest.objects.get(id=resp.data["id"])
        line = ew.line_items.get()

        zero = self._post_hours(
            ew, [{"line_id": line.id, "actual_hours": "0"}]
        )
        self.assertEqual(zero.status_code, 400, zero.data)
        self.assertEqual(zero.data["code"], "actual_hours_invalid")

        neg = self._post_hours(
            ew, [{"line_id": line.id, "actual_hours": "-1.00"}]
        )
        self.assertEqual(neg.status_code, 400, neg.data)
        self.assertEqual(neg.data["code"], "actual_hours_invalid")

    def test_12b_unknown_line_id_invalid(self):
        resp = self._submit(
            actor=self.cust_loc,
            intent=ExtraWorkRequestIntent.DIRECT_AGREED_PRICE_ORDER,
            lines=[self._svc_line(self.svc_hourly_agreed, qty="2.00")],
        )
        ew = ExtraWorkRequest.objects.get(id=resp.data["id"])
        r = self._post_hours(
            ew, [{"line_id": 999999, "actual_hours": "2.00"}]
        )
        self.assertEqual(r.status_code, 400, r.data)
        self.assertEqual(r.data["code"], "actual_hours_invalid")


# ---------------------------------------------------------------------------
# Freeze + lock + audit
# ---------------------------------------------------------------------------
class FreezeLockAuditTests(ActualHoursFixtureMixin, TestCase):
    @classmethod
    def setUpTestData(cls):
        cls._setup_fixture()

    def _approve_operational_ticket(self, ew):
        """OPEN -> IN_PROGRESS -> (hours) -> WAITING_CUSTOMER_APPROVAL
        -> APPROVED. Returns the line used."""
        self._drive_ticket(
            ew, to_status=TicketStatus.IN_PROGRESS, actor=self.admin
        )
        line = ew.line_items.get()
        self._post_hours(
            ew, [{"line_id": line.id, "actual_hours": "2.00"}]
        )
        r = self._drive_ticket(
            ew,
            to_status=TicketStatus.WAITING_CUSTOMER_APPROVAL,
            actor=self.admin,
        )
        assert r.status_code == 200, r.data
        # Customer approves the operational ticket.
        ticket = self._ticket_for(ew)
        a = self._api(self.cust_loc).post(
            f"/api/tickets/{ticket.id}/status/",
            {"to_status": TicketStatus.APPROVED},
            format="json",
        )
        assert a.status_code == 200, a.data
        return line

    def test_16_freeze_at_approval(self):
        resp = self._submit(
            actor=self.cust_loc,
            intent=ExtraWorkRequestIntent.DIRECT_AGREED_PRICE_ORDER,
            lines=[self._svc_line(self.svc_hourly_agreed, qty="2.00")],
        )
        ew = ExtraWorkRequest.objects.get(id=resp.data["id"])
        self._approve_operational_ticket(ew)

        ew.refresh_from_db()
        # 2.00h * 40 = 80.00 subtotal, vat 16.80, total 96.80.
        subtotal = _two(Decimal("2.00") * Decimal("40.00"))
        vat = _two(subtotal * Decimal("0.21"))
        self.assertIsNotNone(ew.final_total_amount)
        self.assertEqual(ew.final_total_amount, _two(subtotal + vat))

    def test_13_lock_after_approval(self):
        resp = self._submit(
            actor=self.cust_loc,
            intent=ExtraWorkRequestIntent.DIRECT_AGREED_PRICE_ORDER,
            lines=[self._svc_line(self.svc_hourly_agreed, qty="2.00")],
        )
        ew = ExtraWorkRequest.objects.get(id=resp.data["id"])
        line = self._approve_operational_ticket(ew)

        # Now POST actual-hours -> locked.
        r = self._post_hours(
            ew, [{"line_id": line.id, "actual_hours": "9.00"}]
        )
        self.assertEqual(r.status_code, 400, r.data)
        self.assertEqual(r.data["code"], "final_amount_locked")

    def test_13b_edit_allowed_after_reopen(self):
        resp = self._submit(
            actor=self.cust_loc,
            intent=ExtraWorkRequestIntent.DIRECT_AGREED_PRICE_ORDER,
            lines=[self._svc_line(self.svc_hourly_agreed, qty="2.00")],
        )
        ew = ExtraWorkRequest.objects.get(id=resp.data["id"])
        line = self._approve_operational_ticket(ew)
        ticket = self._ticket_for(ew)

        # APPROVED -> CLOSED -> REOPENED_BY_ADMIN -> IN_PROGRESS.
        for to in (
            TicketStatus.CLOSED,
            TicketStatus.REOPENED_BY_ADMIN,
            TicketStatus.IN_PROGRESS,
        ):
            r = self._api(self.super_admin).post(
                f"/api/tickets/{ticket.id}/status/",
                {"to_status": to, "note": "reopen"},
                format="json",
            )
            self.assertEqual(r.status_code, 200, r.data)

        # No longer locked (no ticket in APPROVED/CLOSED).
        r = self._post_hours(
            ew, [{"line_id": line.id, "actual_hours": "6.00"}]
        )
        self.assertEqual(r.status_code, 200, r.data)
        ew.refresh_from_db()
        subtotal = _two(Decimal("6.00") * Decimal("40.00"))
        vat = _two(subtotal * Decimal("0.21"))
        self.assertEqual(ew.final_total_amount, _two(subtotal + vat))

    def test_15_audit_history_row_written(self):
        resp = self._submit(
            actor=self.cust_loc,
            intent=ExtraWorkRequestIntent.DIRECT_AGREED_PRICE_ORDER,
            lines=[self._svc_line(self.svc_hourly_agreed, qty="2.00")],
        )
        ew = ExtraWorkRequest.objects.get(id=resp.data["id"])
        line = ew.line_items.get()
        before = ExtraWorkStatusHistory.objects.filter(extra_work=ew).count()
        r = self._post_hours(
            ew, [{"line_id": line.id, "actual_hours": "3.00"}]
        )
        self.assertEqual(r.status_code, 200, r.data)
        rows = ExtraWorkStatusHistory.objects.filter(extra_work=ew)
        self.assertEqual(rows.count(), before + 1)
        latest = rows.order_by("-id").first()
        # No-transition annotation row: old == new == current status.
        self.assertEqual(latest.old_status, latest.new_status)
        self.assertEqual(latest.old_status, ew.status)
        self.assertEqual(latest.changed_by_id, self.admin.id)
        self.assertIn(str(line.id), latest.note)
        self.assertIn("final_total_amount", latest.note)
        self.assertFalse(latest.is_override)
