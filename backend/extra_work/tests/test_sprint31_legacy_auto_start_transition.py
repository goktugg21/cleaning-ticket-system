"""
Sprint 31 — AUTO_START_AFTER_PRICING on the LEGACY EW state machine.

The proposal flow (`extra_work.proposal_state_machine`) already auto-
starts an AUTO_START_AFTER_PRICING request on proposal SEND (Sprint 6B,
`_auto_start_after_pricing`). This file pins the parallel behaviour on
the LEGACY `extra_work.state_machine.apply_transition` path, which is
the code the public `POST /api/extra-work/<id>/transition/` endpoint
takes when a provider drives `PRICING_PROPOSED -> CUSTOMER_APPROVED`
directly on the EW (no Proposal row involved).

Documented intent (system-business-logic-and-workflows.md §5.3 +
ExtraWorkRequestIntent docstring):
  * When `request_intent == AUTO_START_AFTER_PRICING` and a provider-
    operator (SA / CA-in-scope / BM-in-scope) drives PRICING_PROPOSED
    -> CUSTOMER_APPROVED, the customer PRE-AUTHORISED the start at
    creation. This is NOT a provider override:
        - is_override stays False on the history row,
        - override_reason is NOT required (no HTTP 400),
        - the ticket-spawn hook still fires.
  * For DIRECT_AGREED_PRICE_ORDER / REQUEST_QUOTE / null intent the
    provider-driven approval is STILL an override requiring a reason
    (unchanged — H-11).
  * PRICING_PROPOSED -> CUSTOMER_REJECTED is ALWAYS an override
    requiring a reason, even for AUTO_START (rejection is never auto).
  * STAFF and plain CUSTOMER_USER can never drive the auto-start start
    (H-5).

The `can_auto_start` action boolean on the detail serializer is also
pinned here (True only when status == PRICING_PROPOSED AND intent ==
AUTO_START_AFTER_PRICING AND viewer is a provider-operator in scope).
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
    ExtraWorkCategory,
    ExtraWorkPricingLineItem,
    ExtraWorkPricingUnitType,
    ExtraWorkRequest,
    ExtraWorkRequestIntent,
    ExtraWorkRequestItem,
    ExtraWorkRoutingDecision,
    ExtraWorkStatus,
    ExtraWorkStatusHistory,
    Service,
    ServiceCategory,
)
from extra_work.state_machine import TransitionError, apply_transition
from tickets.models import Ticket


User = get_user_model()
PASSWORD = "StrongerTestPassword123!"
TRANSITION_URL = "/api/extra-work/{ew_id}/transition/"
DETAIL_URL = "/api/extra-work/{ew_id}/"


def _mk(email: str, role: str, **extra) -> User:
    return User.objects.create_user(
        email=email,
        password=PASSWORD,
        role=role,
        full_name=email.split("@")[0],
        **extra,
    )


class LegacyAutoStartFixtureMixin:
    """Provider (SA / CA / BM in scope) + a customer with a plain
    CUSTOMER_USER and a STAFF user. Helper builds an EW directly in
    PRICING_PROPOSED with a chosen `request_intent`."""

    @classmethod
    def _setup_fixture(cls):
        cls.company = Company.objects.create(
            name="Sprint31 Provider", slug="sprint31-auto-start"
        )
        cls.building = Building.objects.create(
            company=cls.company, name="Building-31"
        )
        cls.customer = Customer.objects.create(
            company=cls.company,
            name="Customer-31",
            building=cls.building,
        )
        CustomerBuildingMembership.objects.create(
            customer=cls.customer, building=cls.building
        )

        cls.super_admin = _mk(
            "super-31@example.com",
            UserRole.SUPER_ADMIN,
            is_staff=True,
            is_superuser=True,
        )
        cls.admin = _mk("admin-31@example.com", UserRole.COMPANY_ADMIN)
        CompanyUserMembership.objects.create(
            user=cls.admin, company=cls.company
        )
        cls.manager = _mk("mgr-31@example.com", UserRole.BUILDING_MANAGER)
        BuildingManagerAssignment.objects.create(
            user=cls.manager, building=cls.building
        )

        cls.staff = _mk("staff-31@example.com", UserRole.STAFF)

        cls.cust_user = _mk("cust-31@example.com", UserRole.CUSTOMER_USER)
        membership = CustomerUserMembership.objects.create(
            customer=cls.customer, user=cls.cust_user
        )
        CustomerUserBuildingAccess.objects.create(
            membership=membership,
            building=cls.building,
            access_role=CustomerUserBuildingAccess.AccessRole.CUSTOMER_USER,
        )

        cls.service_cat = ServiceCategory.objects.create(name="Sprint31-Cat")
        cls.service = Service.objects.create(
            category=cls.service_cat,
            company=cls.company,
            name="Sprint31-Service",
            unit_type=ExtraWorkPricingUnitType.HOURS,
            default_unit_price=Decimal("50.00"),
        )

    @classmethod
    def _make_ew(
        cls,
        *,
        intent,
        status: str = ExtraWorkStatus.PRICING_PROPOSED,
        n_cart_items: int = 1,
        title: str = "Legacy auto-start EW",
    ) -> ExtraWorkRequest:
        ew = ExtraWorkRequest.objects.create(
            company=cls.company,
            building=cls.building,
            customer=cls.customer,
            created_by=cls.cust_user,
            title=title,
            description="legacy pricing flow",
            category=ExtraWorkCategory.DEEP_CLEANING,
            status=status,
            routing_decision=ExtraWorkRoutingDecision.PROPOSAL,
            request_intent=intent,
        )
        for i in range(n_cart_items):
            ExtraWorkRequestItem.objects.create(
                extra_work_request=ew,
                service=cls.service,
                quantity=Decimal("2.00"),
                unit_type=ExtraWorkPricingUnitType.HOURS,
                requested_date=date(2026, 6, 15),
                customer_note=f"line {i}",
            )
        # A pricing line item is required for the UNDER_REVIEW ->
        # PRICING_PROPOSED precondition; harmless to seed it here so the
        # row is shaped exactly like a real legacy-flow EW.
        ExtraWorkPricingLineItem.objects.create(
            extra_work=ew,
            description="Cleaning quote",
            unit_type=ExtraWorkPricingUnitType.FIXED,
            quantity=Decimal("1.00"),
            unit_price=Decimal("100.00"),
            vat_rate=Decimal("21.00"),
        )
        return ew

    def _api(self, user):
        c = APIClient()
        c.force_authenticate(user=user)
        return c

    def _ticket_count(self, ew):
        return Ticket.objects.filter(extra_work_request=ew).count()


# ---------------------------------------------------------------------------
# AUTO_START — provider approval is NOT an override
# ---------------------------------------------------------------------------
class LegacyAutoStartApprovalTests(LegacyAutoStartFixtureMixin, TestCase):
    @classmethod
    def setUpTestData(cls):
        cls._setup_fixture()

    def _assert_auto_start_approval(self, actor):
        ew = self._make_ew(
            intent=ExtraWorkRequestIntent.AUTO_START_AFTER_PRICING
        )
        self.assertEqual(self._ticket_count(ew), 0)

        resp = self._api(actor).post(
            TRANSITION_URL.format(ew_id=ew.id),
            {"to_status": ExtraWorkStatus.CUSTOMER_APPROVED},
            format="json",
        )
        self.assertEqual(resp.status_code, 200, resp.data)

        ew.refresh_from_db()
        self.assertEqual(ew.status, ExtraWorkStatus.CUSTOMER_APPROVED)

        # The status-history row is NOT an override.
        row = (
            ExtraWorkStatusHistory.objects.filter(
                extra_work=ew,
                new_status=ExtraWorkStatus.CUSTOMER_APPROVED,
            )
            .order_by("-id")
            .first()
        )
        self.assertIsNotNone(row)
        self.assertFalse(row.is_override)
        self.assertEqual(row.changed_by_id, actor.id)

        # No override metadata leaked onto the parent EW.
        self.assertIsNone(ew.override_by_id)
        self.assertEqual(ew.override_reason, "")
        self.assertIsNone(ew.override_at)

        # Ticket-spawn hook still fired (legacy path: one ticket per
        # request, summarising all cart lines — Sprint 6A contract).
        self.assertEqual(self._ticket_count(ew), 1)
        return ew

    def test_super_admin_auto_start_no_reason_ok(self):
        self._assert_auto_start_approval(self.super_admin)

    def test_company_admin_in_scope_auto_start_no_reason_ok(self):
        self._assert_auto_start_approval(self.admin)

    def test_building_manager_in_scope_auto_start_no_reason_ok(self):
        # BM-scope decision: the auto-start start is NOT an override, so
        # the BM only needs building scope (view_building, already gated
        # by _user_can_drive_transition). The
        # `osius.building_manager.override_customer_decision` revocation
        # gate is intentionally NOT consulted on the auto-start path.
        self._assert_auto_start_approval(self.manager)

    def test_building_manager_with_override_disabled_still_auto_starts(self):
        # Even when the BM's override key is revoked for this building,
        # the auto-start start succeeds — it is not an override.
        assignment = BuildingManagerAssignment.objects.get(
            user=self.manager, building=self.building
        )
        assignment.permission_overrides = {
            "osius.building_manager.override_customer_decision": False
        }
        assignment.save(update_fields=["permission_overrides"])

        self._assert_auto_start_approval(self.manager)

    def test_auto_start_spawns_one_ticket_for_multi_line_cart(self):
        # Legacy spawn helper is one-ticket-per-request even for an N-line
        # cart (Sprint 6A). Assert the hook fired regardless of line count.
        ew = self._make_ew(
            intent=ExtraWorkRequestIntent.AUTO_START_AFTER_PRICING,
            n_cart_items=3,
        )
        resp = self._api(self.super_admin).post(
            TRANSITION_URL.format(ew_id=ew.id),
            {"to_status": ExtraWorkStatus.CUSTOMER_APPROVED},
            format="json",
        )
        self.assertEqual(resp.status_code, 200, resp.data)
        self.assertEqual(self._ticket_count(ew), 1)


# ---------------------------------------------------------------------------
# Non-AUTO_START intents — provider approval STILL requires a reason
# ---------------------------------------------------------------------------
class LegacyNonAutoStartStillOverrideTests(
    LegacyAutoStartFixtureMixin, TestCase
):
    @classmethod
    def setUpTestData(cls):
        cls._setup_fixture()

    def _assert_requires_reason(self, intent):
        ew = self._make_ew(intent=intent)
        resp = self._api(self.super_admin).post(
            TRANSITION_URL.format(ew_id=ew.id),
            {"to_status": ExtraWorkStatus.CUSTOMER_APPROVED},
            format="json",
        )
        self.assertEqual(resp.status_code, 400, resp.data)
        self.assertEqual(resp.data["code"], "override_reason_required")
        ew.refresh_from_db()
        self.assertEqual(ew.status, ExtraWorkStatus.PRICING_PROPOSED)
        self.assertEqual(self._ticket_count(ew), 0)

    def test_request_quote_provider_approval_requires_reason(self):
        self._assert_requires_reason(ExtraWorkRequestIntent.REQUEST_QUOTE)

    def test_direct_order_provider_approval_requires_reason(self):
        self._assert_requires_reason(
            ExtraWorkRequestIntent.DIRECT_AGREED_PRICE_ORDER
        )

    def test_null_intent_provider_approval_requires_reason(self):
        # Legacy pre-Sprint-2A rows carry a null intent. Provider
        # approval on those is still an override requiring a reason.
        self._assert_requires_reason(None)

    def test_non_auto_start_with_reason_succeeds_as_override(self):
        # Sanity: the same provider approval WITH a reason succeeds and
        # is recorded as an override (unchanged behaviour).
        ew = self._make_ew(intent=ExtraWorkRequestIntent.REQUEST_QUOTE)
        resp = self._api(self.super_admin).post(
            TRANSITION_URL.format(ew_id=ew.id),
            {
                "to_status": ExtraWorkStatus.CUSTOMER_APPROVED,
                "override_reason": "customer agreed by phone",
            },
            format="json",
        )
        self.assertEqual(resp.status_code, 200, resp.data)
        ew.refresh_from_db()
        self.assertEqual(ew.status, ExtraWorkStatus.CUSTOMER_APPROVED)
        row = (
            ExtraWorkStatusHistory.objects.filter(
                extra_work=ew,
                new_status=ExtraWorkStatus.CUSTOMER_APPROVED,
            )
            .order_by("-id")
            .first()
        )
        self.assertTrue(row.is_override)


# ---------------------------------------------------------------------------
# AUTO_START rejection is NEVER auto — still an override
# ---------------------------------------------------------------------------
class LegacyAutoStartRejectionStillOverrideTests(
    LegacyAutoStartFixtureMixin, TestCase
):
    @classmethod
    def setUpTestData(cls):
        cls._setup_fixture()

    def test_auto_start_reject_by_provider_requires_reason(self):
        ew = self._make_ew(
            intent=ExtraWorkRequestIntent.AUTO_START_AFTER_PRICING
        )
        resp = self._api(self.super_admin).post(
            TRANSITION_URL.format(ew_id=ew.id),
            {"to_status": ExtraWorkStatus.CUSTOMER_REJECTED},
            format="json",
        )
        self.assertEqual(resp.status_code, 400, resp.data)
        self.assertEqual(resp.data["code"], "override_reason_required")
        ew.refresh_from_db()
        self.assertEqual(ew.status, ExtraWorkStatus.PRICING_PROPOSED)
        self.assertEqual(self._ticket_count(ew), 0)

    def test_auto_start_reject_with_reason_is_override(self):
        ew = self._make_ew(
            intent=ExtraWorkRequestIntent.AUTO_START_AFTER_PRICING
        )
        resp = self._api(self.super_admin).post(
            TRANSITION_URL.format(ew_id=ew.id),
            {
                "to_status": ExtraWorkStatus.CUSTOMER_REJECTED,
                "override_reason": "duplicate request",
            },
            format="json",
        )
        self.assertEqual(resp.status_code, 200, resp.data)
        ew.refresh_from_db()
        self.assertEqual(ew.status, ExtraWorkStatus.CUSTOMER_REJECTED)
        row = (
            ExtraWorkStatusHistory.objects.filter(
                extra_work=ew,
                new_status=ExtraWorkStatus.CUSTOMER_REJECTED,
            )
            .order_by("-id")
            .first()
        )
        self.assertTrue(row.is_override)
        self.assertEqual(self._ticket_count(ew), 0)


# ---------------------------------------------------------------------------
# H-5 — STAFF and plain CUSTOMER_USER cannot drive the auto-start start
# ---------------------------------------------------------------------------
class LegacyAutoStartForbiddenActorsTests(
    LegacyAutoStartFixtureMixin, TestCase
):
    @classmethod
    def setUpTestData(cls):
        cls._setup_fixture()

    def test_staff_cannot_auto_start(self):
        ew = self._make_ew(
            intent=ExtraWorkRequestIntent.AUTO_START_AFTER_PRICING
        )
        # STAFF scopes EW to .none(), so the HTTP endpoint 404s before
        # the state machine. Assert the state machine itself also
        # refuses (defence in depth) — forbidden_transition, not a
        # silent approval.
        with self.assertRaises(TransitionError) as ctx:
            apply_transition(
                ew, self.staff, ExtraWorkStatus.CUSTOMER_APPROVED
            )
        self.assertEqual(ctx.exception.code, "forbidden_transition")
        ew.refresh_from_db()
        self.assertEqual(ew.status, ExtraWorkStatus.PRICING_PROPOSED)
        self.assertEqual(self._ticket_count(ew), 0)

    def test_plain_customer_user_without_approve_key_cannot_auto_start(self):
        # A CUSTOMER_USER with NO approve rights cannot drive the
        # decision — and AUTO_START gives customers no bypass (it only
        # changes the PROVIDER override path). The default CUSTOMER_USER
        # access role DOES grant `customer.extra_work.approve_own`, so we
        # explicitly revoke both approve keys here to model a keyless
        # customer; otherwise the creator could legitimately self-approve
        # via the normal customer-approval path (unrelated to auto-start).
        access = CustomerUserBuildingAccess.objects.get(
            membership__user=self.cust_user, building=self.building
        )
        access.permission_overrides = {
            "customer.extra_work.approve_own": False,
            "customer.extra_work.approve_location": False,
        }
        access.save(update_fields=["permission_overrides"])

        ew = self._make_ew(
            intent=ExtraWorkRequestIntent.AUTO_START_AFTER_PRICING
        )
        with self.assertRaises(TransitionError) as ctx:
            apply_transition(
                ew, self.cust_user, ExtraWorkStatus.CUSTOMER_APPROVED
            )
        self.assertEqual(ctx.exception.code, "forbidden_transition")
        ew.refresh_from_db()
        self.assertEqual(ew.status, ExtraWorkStatus.PRICING_PROPOSED)
        self.assertEqual(self._ticket_count(ew), 0)


# ---------------------------------------------------------------------------
# Wire contract: get_actions.can_auto_start
# ---------------------------------------------------------------------------
class CanAutoStartActionTests(LegacyAutoStartFixtureMixin, TestCase):
    @classmethod
    def setUpTestData(cls):
        cls._setup_fixture()

    def _actions(self, ew, actor):
        resp = self._api(actor).get(DETAIL_URL.format(ew_id=ew.id))
        self.assertEqual(resp.status_code, 200, resp.data)
        return resp.data["actions"]

    def test_can_auto_start_true_for_provider_in_scope(self):
        ew = self._make_ew(
            intent=ExtraWorkRequestIntent.AUTO_START_AFTER_PRICING
        )
        for actor in (self.super_admin, self.admin, self.manager):
            actions = self._actions(ew, actor)
            self.assertIn("can_auto_start", actions)
            self.assertTrue(
                actions["can_auto_start"],
                f"can_auto_start should be True for {actor.email}",
            )
            # can_override_customer_decision semantics unchanged: still
            # True for provider operators at PRICING_PROPOSED.
            self.assertTrue(actions["can_override_customer_decision"])

    def test_can_auto_start_false_wrong_status(self):
        ew = self._make_ew(
            intent=ExtraWorkRequestIntent.AUTO_START_AFTER_PRICING,
            status=ExtraWorkStatus.UNDER_REVIEW,
        )
        actions = self._actions(ew, self.super_admin)
        self.assertFalse(actions["can_auto_start"])

    def test_can_auto_start_false_wrong_intent(self):
        ew = self._make_ew(intent=ExtraWorkRequestIntent.REQUEST_QUOTE)
        actions = self._actions(ew, self.super_admin)
        self.assertFalse(actions["can_auto_start"])
        # But the override action is still available for a quote.
        self.assertTrue(actions["can_override_customer_decision"])

    def test_can_auto_start_false_null_intent(self):
        ew = self._make_ew(intent=None)
        actions = self._actions(ew, self.super_admin)
        self.assertFalse(actions["can_auto_start"])

    def test_can_auto_start_false_for_customer_viewer(self):
        ew = self._make_ew(
            intent=ExtraWorkRequestIntent.AUTO_START_AFTER_PRICING
        )
        actions = self._actions(ew, self.cust_user)
        self.assertFalse(actions["can_auto_start"])

    def test_request_intent_serialized_on_detail(self):
        # Frontend reads `request_intent` from the detail payload.
        ew = self._make_ew(
            intent=ExtraWorkRequestIntent.AUTO_START_AFTER_PRICING
        )
        resp = self._api(self.super_admin).get(
            DETAIL_URL.format(ew_id=ew.id)
        )
        self.assertEqual(resp.status_code, 200, resp.data)
        self.assertEqual(
            resp.data["request_intent"],
            ExtraWorkRequestIntent.AUTO_START_AFTER_PRICING,
        )
