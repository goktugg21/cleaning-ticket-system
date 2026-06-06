"""
M1 — Notification / message center, phase B4 (BACKEND).

Extra Work LIFECYCLE in-app notifications (no EW message thread, no email):

  * NEW REQUEST            -> provider management (action needed)
  * QUOTE / PROPOSAL SENT  -> customer side (decision needed)
  * CUSTOMER DECISION      -> provider management (approved / rejected)

These tests drive the real HTTP surfaces (cart-create + the proposal
transition endpoint), because the emit hooks live at the VIEW layer:
  * NEW REQUEST  -> ExtraWorkRequestViewSet.create
  * QUOTE SENT + DECISION -> ProposalTransitionView.post

They assert recipient DIRECTION (provider vs customer), cross-tenant
isolation, minus-actor, the Notification shape (extra_work set / ticket null /
event_type), the recipient-facing feed + unread count, the B1 scope gate
(a customer-org member without building access for the EW's building is NOT
notified about a quote they cannot open), and the intent fall-out (instant /
auto-start EWs never trigger the QUOTE / DECISION hooks).

In-app ONLY — no email assertions (there is no EW email path).
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
    ExtraWorkRequestItem,
    ExtraWorkRequestIntent,
    ExtraWorkStatus,
    Proposal,
    ProposalStatus,
    Service,
    ServiceCategory,
)
from notifications.models import Notification, NotificationType


User = get_user_model()
PASSWORD = "StrongerTestPassword123!"
URL = "/api/extra-work/"

AccessRole = CustomerUserBuildingAccess.AccessRole


def _mk(email: str, role: str, **extra) -> User:
    return User.objects.create_user(
        email=email,
        password=PASSWORD,
        role=role,
        full_name=email.split("@")[0],
        **extra,
    )


class B4FixtureMixin:
    """Two-tenant fixture.

    Provider A (company_a / building_a / customer_a) with:
      * provider mgmt: admin_a (CA), bm_a (BM of building_a)
      * customer side of customer_a:
          - cust_a            CUSTOMER_USER, the requester/creator (view_own)
          - cust_a_mgr        CUSTOMER_LOCATION_MANAGER (view_location)
          - cust_a_noview     CUSTOMER_USER, NOT the creator (view_own only) —
                              cannot see another user's EW -> scope-gate prunes
      * service catalog with one priced (contract) + one unpriced service.

    Provider B (company_b / building_b / customer_b) is the cross-tenant foil:
      * admin_b (CA), bm_b (BM), cust_b (CUSTOMER_USER) — NONE may ever be
        notified about a Provider-A EW.

    Plus a SUPER_ADMIN (never auto-notified) and a STAFF (never notified).
    """

    @classmethod
    def _setup_fixture(cls):
        cls.company_a = Company.objects.create(name="Provider A", slug="b4-a")
        cls.company_b = Company.objects.create(name="Provider B", slug="b4-b")
        cls.building_a = Building.objects.create(
            company=cls.company_a, name="B4-A"
        )
        cls.building_b = Building.objects.create(
            company=cls.company_b, name="B4-B"
        )
        cls.customer_a = Customer.objects.create(
            company=cls.company_a, name="Customer-A", building=cls.building_a
        )
        cls.customer_b = Customer.objects.create(
            company=cls.company_b, name="Customer-B", building=cls.building_b
        )
        CustomerBuildingMembership.objects.create(
            customer=cls.customer_a, building=cls.building_a
        )
        CustomerBuildingMembership.objects.create(
            customer=cls.customer_b, building=cls.building_b
        )

        # Provider users.
        cls.super_admin = _mk(
            "b4-super@example.com",
            UserRole.SUPER_ADMIN,
            is_staff=True,
            is_superuser=True,
        )
        cls.admin_a = _mk("b4-admin-a@example.com", UserRole.COMPANY_ADMIN)
        CompanyUserMembership.objects.create(
            user=cls.admin_a, company=cls.company_a
        )
        cls.bm_a = _mk("b4-bm-a@example.com", UserRole.BUILDING_MANAGER)
        BuildingManagerAssignment.objects.create(
            user=cls.bm_a, building=cls.building_a
        )
        cls.admin_b = _mk("b4-admin-b@example.com", UserRole.COMPANY_ADMIN)
        CompanyUserMembership.objects.create(
            user=cls.admin_b, company=cls.company_b
        )
        cls.bm_b = _mk("b4-bm-b@example.com", UserRole.BUILDING_MANAGER)
        BuildingManagerAssignment.objects.create(
            user=cls.bm_b, building=cls.building_b
        )
        cls.staff = _mk("b4-staff@example.com", UserRole.STAFF)

        # Customer-A side users.
        cls.cust_a = _mk("b4-cust-a@example.com", UserRole.CUSTOMER_USER)
        cls._grant_customer_access(
            cls.cust_a, cls.customer_a, cls.building_a, AccessRole.CUSTOMER_USER
        )
        cls.cust_a_mgr = _mk(
            "b4-cust-a-mgr@example.com", UserRole.CUSTOMER_USER
        )
        cls._grant_customer_access(
            cls.cust_a_mgr,
            cls.customer_a,
            cls.building_a,
            AccessRole.CUSTOMER_LOCATION_MANAGER,
        )
        cls.cust_a_noview = _mk(
            "b4-cust-a-noview@example.com", UserRole.CUSTOMER_USER
        )
        cls._grant_customer_access(
            cls.cust_a_noview,
            cls.customer_a,
            cls.building_a,
            AccessRole.CUSTOMER_USER,
        )

        # Customer-B side user (cross-tenant).
        cls.cust_b = _mk("b4-cust-b@example.com", UserRole.CUSTOMER_USER)
        cls._grant_customer_access(
            cls.cust_b, cls.customer_b, cls.building_b, AccessRole.CUSTOMER_USER
        )

        # Service catalog.
        cls.service_cat = ServiceCategory.objects.create(name="B4-Cat")
        cls.service_priced = Service.objects.create(
            category=cls.service_cat,
            company=cls.company_a,
            name="Window cleaning",
            unit_type=ExtraWorkPricingUnitType.HOURS,
            default_unit_price=Decimal("50.00"),
        )
        cls.service_unpriced = Service.objects.create(
            category=cls.service_cat,
            company=cls.company_a,
            name="Floor maintenance",
            unit_type=ExtraWorkPricingUnitType.SQUARE_METERS,
            default_unit_price=Decimal("3.50"),
        )
        # Active contract price for customer_a + service_priced -> an
        # all-agreed cart routes to DIRECT_AGREED_PRICE_ORDER (instant).
        CustomerServicePrice.objects.create(
            service=cls.service_priced,
            customer=cls.customer_a,
            unit_price=Decimal("48.50"),
            vat_pct=Decimal("21.00"),
            valid_from=date(2026, 1, 1),
            valid_to=None,
            is_active=True,
        )

    @classmethod
    def _grant_customer_access(cls, user, customer, building, access_role):
        membership, _ = CustomerUserMembership.objects.get_or_create(
            user=user, customer=customer
        )
        CustomerUserBuildingAccess.objects.create(
            membership=membership,
            building=building,
            access_role=access_role,
        )

    # -- HTTP helpers ----------------------------------------------------
    def _api(self, user):
        c = APIClient()
        c.force_authenticate(user=user)
        return c

    def _proposals_url(self, ew_id):
        return f"/api/extra-work/{ew_id}/proposals/"

    def _transition_url(self, ew_id, pid):
        return f"/api/extra-work/{ew_id}/proposals/{pid}/transition/"

    def _line_payload(self, **overrides):
        payload = {
            "service": self.service_priced.id,
            "quantity": "2.00",
            "unit_type": ExtraWorkPricingUnitType.HOURS,
            "unit_price": "50.00",
            "vat_pct": "21.00",
            "customer_explanation": "Customer-visible explanation",
            "internal_note": "Provider-only note",
        }
        payload.update(overrides)
        return payload

    def _make_ew(self, *, status=ExtraWorkStatus.UNDER_REVIEW, intent=None):
        ew = ExtraWorkRequest.objects.create(
            company=self.company_a,
            building=self.building_a,
            customer=self.customer_a,
            created_by=self.cust_a,
            title="B4 fixture EW",
            description="parent description",
            category=ExtraWorkCategory.DEEP_CLEANING,
            status=status,
            request_intent=intent,
        )
        ExtraWorkRequestItem.objects.create(
            extra_work_request=ew,
            service=self.service_priced,
            quantity=Decimal("2.00"),
            unit_type=ExtraWorkPricingUnitType.HOURS,
            requested_date=date(2026, 6, 15),
            customer_note="",
        )
        return ew

    def _create_draft_proposal(self, ew, *, actor=None):
        actor = actor or self.admin_a
        resp = self._api(actor).post(
            self._proposals_url(ew.id),
            {"lines": [self._line_payload()]},
            format="json",
        )
        assert resp.status_code == 201, resp.data
        return Proposal.objects.get(pk=resp.data["id"])

    def _send_proposal(self, ew, proposal, *, actor=None):
        actor = actor or self.admin_a
        return self._api(actor).post(
            self._transition_url(ew.id, proposal.id),
            {"to_status": ProposalStatus.SENT},
            format="json",
        )

    def _cart_payload(self, **extra):
        payload = {
            "customer": self.customer_a.id,
            "building": self.building_a.id,
            "title": "Cart submission",
            "description": "shopping cart",
            "category": ExtraWorkCategory.DEEP_CLEANING,
            "line_items": [
                {
                    "service": self.service_priced.id,
                    "quantity": "2.00",
                    "requested_date": "2026-06-15",
                    "customer_note": "Top floor",
                }
            ],
        }
        payload.update(extra)
        return payload

    # -- assertion helpers ----------------------------------------------
    def _recipients(self, event_type, extra_work=None):
        qs = Notification.objects.filter(event_type=event_type)
        if extra_work is not None:
            qs = qs.filter(extra_work=extra_work)
        return set(qs.values_list("recipient_id", flat=True))


# ---------------------------------------------------------------------------
# NEW REQUEST -> provider management
# ---------------------------------------------------------------------------
class ExtraWorkRequestedNotificationTests(B4FixtureMixin, TestCase):
    @classmethod
    def setUpTestData(cls):
        cls._setup_fixture()

    def test_new_request_notifies_provider_management_only(self):
        resp = self._api(self.cust_a).post(URL, self._cart_payload(), format="json")
        self.assertEqual(resp.status_code, 201, resp.data)
        ew_id = resp.data["id"]

        recipients = self._recipients(NotificationType.EXTRA_WORK_REQUESTED)
        # Provider management of Provider A: the CA + the building's BM.
        self.assertIn(self.admin_a.id, recipients)
        self.assertIn(self.bm_a.id, recipients)
        # The requester is never notified about their own request.
        self.assertNotIn(self.cust_a.id, recipients)
        # No customer-side user is notified about a NEW REQUEST.
        self.assertNotIn(self.cust_a_mgr.id, recipients)
        self.assertNotIn(self.cust_a_noview.id, recipients)
        # Cross-tenant provider users are never notified.
        self.assertNotIn(self.admin_b.id, recipients)
        self.assertNotIn(self.bm_b.id, recipients)
        # SUPER_ADMIN is not auto-notified; STAFF never is.
        self.assertNotIn(self.super_admin.id, recipients)
        self.assertNotIn(self.staff.id, recipients)
        # Exactly the two provider-mgmt users, nobody else.
        self.assertEqual(recipients, {self.admin_a.id, self.bm_a.id})

    def test_new_request_notification_shape(self):
        resp = self._api(self.cust_a).post(URL, self._cart_payload(), format="json")
        self.assertEqual(resp.status_code, 201, resp.data)
        ew_id = resp.data["id"]

        notif = Notification.objects.get(
            event_type=NotificationType.EXTRA_WORK_REQUESTED,
            recipient=self.admin_a,
        )
        self.assertEqual(notif.extra_work_id, ew_id)
        self.assertIsNone(notif.ticket_id)
        self.assertFalse(notif.is_directed)
        self.assertIsNone(notif.read_at)
        self.assertEqual(notif.actor_id, self.cust_a.id)
        self.assertIn("Cart submission", notif.summary)


# ---------------------------------------------------------------------------
# QUOTE / PROPOSAL SENT -> customer side
# ---------------------------------------------------------------------------
class ExtraWorkProposalSentNotificationTests(B4FixtureMixin, TestCase):
    @classmethod
    def setUpTestData(cls):
        cls._setup_fixture()

    def test_quote_sent_notifies_customer_side_only(self):
        ew = self._make_ew()
        proposal = self._create_draft_proposal(ew)
        resp = self._send_proposal(ew, proposal)
        self.assertEqual(resp.status_code, 200, resp.data)

        recipients = self._recipients(
            NotificationType.EXTRA_WORK_PROPOSAL_SENT, extra_work=ew
        )
        # The requester (created_by) is notified the quote is ready.
        self.assertIn(self.cust_a.id, recipients)
        # A customer LOCATION MANAGER (view_location) can open the EW and IS
        # notified even though they did not create it.
        self.assertIn(self.cust_a_mgr.id, recipients)
        # SCOPE GATE: a plain CUSTOMER_USER who did NOT create the EW has
        # view_own only -> cannot open it -> must NOT be notified (B1 parity).
        self.assertNotIn(self.cust_a_noview.id, recipients)
        # Provider management is NOT notified on QUOTE SENT.
        self.assertNotIn(self.admin_a.id, recipients)
        self.assertNotIn(self.bm_a.id, recipients)
        # The sender (provider operator) is not a recipient.
        self.assertNotIn(self.admin_a.id, recipients)
        # Cross-tenant customer is never notified.
        self.assertNotIn(self.cust_b.id, recipients)
        # SUPER_ADMIN / STAFF never.
        self.assertNotIn(self.super_admin.id, recipients)
        self.assertNotIn(self.staff.id, recipients)
        self.assertEqual(recipients, {self.cust_a.id, self.cust_a_mgr.id})

    def test_quote_sent_notification_shape(self):
        ew = self._make_ew()
        proposal = self._create_draft_proposal(ew)
        self.assertEqual(self._send_proposal(ew, proposal).status_code, 200)

        notif = Notification.objects.get(
            event_type=NotificationType.EXTRA_WORK_PROPOSAL_SENT,
            recipient=self.cust_a,
        )
        self.assertEqual(notif.extra_work_id, ew.id)
        self.assertIsNone(notif.ticket_id)
        self.assertFalse(notif.is_directed)
        self.assertEqual(notif.actor_id, self.admin_a.id)
        self.assertIn("B4 fixture EW", notif.summary)


# ---------------------------------------------------------------------------
# CUSTOMER DECISION -> provider management
# ---------------------------------------------------------------------------
class ExtraWorkDecisionNotificationTests(B4FixtureMixin, TestCase):
    @classmethod
    def setUpTestData(cls):
        cls._setup_fixture()

    def _sent(self):
        ew = self._make_ew()
        proposal = self._create_draft_proposal(ew)
        self.assertEqual(self._send_proposal(ew, proposal).status_code, 200)
        return ew, proposal

    def test_customer_approve_notifies_provider_management_only(self):
        ew, proposal = self._sent()
        resp = self._api(self.cust_a).post(
            self._transition_url(ew.id, proposal.id),
            {"to_status": ProposalStatus.CUSTOMER_APPROVED},
            format="json",
        )
        self.assertEqual(resp.status_code, 200, resp.data)

        recipients = self._recipients(
            NotificationType.EXTRA_WORK_DECISION, extra_work=ew
        )
        self.assertEqual(recipients, {self.admin_a.id, self.bm_a.id})
        # The decider (customer) is not notified; no customer side at all.
        self.assertNotIn(self.cust_a.id, recipients)
        self.assertNotIn(self.cust_a_mgr.id, recipients)
        # Cross-tenant + SA + STAFF excluded.
        self.assertNotIn(self.admin_b.id, recipients)
        self.assertNotIn(self.bm_b.id, recipients)
        self.assertNotIn(self.super_admin.id, recipients)

        notif = Notification.objects.get(
            event_type=NotificationType.EXTRA_WORK_DECISION,
            recipient=self.admin_a,
        )
        self.assertEqual(notif.extra_work_id, ew.id)
        self.assertIsNone(notif.ticket_id)
        self.assertEqual(notif.actor_id, self.cust_a.id)
        self.assertIn("approved", notif.summary)
        self.assertNotIn("rejected", notif.summary)

    def test_customer_reject_notifies_provider_management_with_rejected_summary(self):
        ew, proposal = self._sent()
        resp = self._api(self.cust_a).post(
            self._transition_url(ew.id, proposal.id),
            {"to_status": ProposalStatus.CUSTOMER_REJECTED},
            format="json",
        )
        self.assertEqual(resp.status_code, 200, resp.data)

        recipients = self._recipients(
            NotificationType.EXTRA_WORK_DECISION, extra_work=ew
        )
        self.assertEqual(recipients, {self.admin_a.id, self.bm_a.id})
        notif = Notification.objects.get(
            event_type=NotificationType.EXTRA_WORK_DECISION,
            recipient=self.bm_a,
        )
        self.assertIn("rejected", notif.summary)
        self.assertNotIn("approved", notif.summary)

    def test_provider_override_decision_excludes_the_overriding_actor(self):
        # A provider operator (admin_a) drives the customer decision with a
        # mandatory reason. The DECISION notification still goes to provider
        # management, but minus the actor (admin_a) -> only bm_a is notified.
        ew, proposal = self._sent()
        resp = self._api(self.admin_a).post(
            self._transition_url(ew.id, proposal.id),
            {
                "to_status": ProposalStatus.CUSTOMER_APPROVED,
                "override_reason": "Customer agreed on the phone.",
            },
            format="json",
        )
        self.assertEqual(resp.status_code, 200, resp.data)

        recipients = self._recipients(
            NotificationType.EXTRA_WORK_DECISION, extra_work=ew
        )
        self.assertEqual(recipients, {self.bm_a.id})
        self.assertNotIn(self.admin_a.id, recipients)


# ---------------------------------------------------------------------------
# Recipient-facing feed + unread count
# ---------------------------------------------------------------------------
class ExtraWorkNotificationFeedTests(B4FixtureMixin, TestCase):
    @classmethod
    def setUpTestData(cls):
        cls._setup_fixture()

    def test_quote_sent_surfaces_in_recipient_feed_with_deeplink_source(self):
        ew = self._make_ew()
        proposal = self._create_draft_proposal(ew)
        self.assertEqual(self._send_proposal(ew, proposal).status_code, 200)

        # The requester's feed includes the EW row with the extra_work
        # deep-link source set (and no ticket source).
        resp = self._api(self.cust_a).get("/api/notifications/")
        self.assertEqual(resp.status_code, 200, resp.data)
        rows = resp.data["results"]
        ew_rows = [
            r
            for r in rows
            if r["event_type"] == NotificationType.EXTRA_WORK_PROPOSAL_SENT
        ]
        self.assertEqual(len(ew_rows), 1)
        self.assertEqual(ew_rows[0]["extra_work"], ew.id)
        self.assertIsNone(ew_rows[0]["ticket"])
        # unread_count is injected and reflects the new unread row.
        self.assertGreaterEqual(resp.data["unread_count"], 1)

    def test_unread_count_moves_for_provider_on_decision(self):
        ew = self._make_ew()
        proposal = self._create_draft_proposal(ew)
        self.assertEqual(self._send_proposal(ew, proposal).status_code, 200)

        before = self._api(self.admin_a).get(
            "/api/notifications/unread-count/"
        ).data["unread_count"]

        resp = self._api(self.cust_a).post(
            self._transition_url(ew.id, proposal.id),
            {"to_status": ProposalStatus.CUSTOMER_APPROVED},
            format="json",
        )
        self.assertEqual(resp.status_code, 200, resp.data)

        after = self._api(self.admin_a).get(
            "/api/notifications/unread-count/"
        ).data["unread_count"]
        self.assertEqual(after, before + 1)


# ---------------------------------------------------------------------------
# Intent fall-out — instant / auto-start never hit the QUOTE / DECISION hooks
# ---------------------------------------------------------------------------
class ExtraWorkIntentNotificationTests(B4FixtureMixin, TestCase):
    @classmethod
    def setUpTestData(cls):
        cls._setup_fixture()

    def test_instant_request_produces_new_request_and_no_quote_or_decision(self):
        # An all-agreed cart routes to DIRECT_AGREED_PRICE_ORDER (instant):
        # tickets spawn immediately, no proposal loop.
        resp = self._api(self.cust_a).post(URL, self._cart_payload(), format="json")
        self.assertEqual(resp.status_code, 201, resp.data)
        self.assertEqual(
            resp.data["request_intent"],
            ExtraWorkRequestIntent.DIRECT_AGREED_PRICE_ORDER,
        )

        self.assertTrue(
            Notification.objects.filter(
                event_type=NotificationType.EXTRA_WORK_REQUESTED
            ).exists()
        )
        self.assertFalse(
            Notification.objects.filter(
                event_type=NotificationType.EXTRA_WORK_PROPOSAL_SENT
            ).exists()
        )
        self.assertFalse(
            Notification.objects.filter(
                event_type=NotificationType.EXTRA_WORK_DECISION
            ).exists()
        )

    def test_auto_start_send_does_not_notify_customer_or_record_decision(self):
        # AUTO_START_AFTER_PRICING: a provider SEND auto-approves + spawns
        # inside apply_proposal_transition (the customer pre-authorised). The
        # proposal collapses to CUSTOMER_APPROVED on the SEND, so the view's
        # `updated.status != SENT` guard suppresses the QUOTE-SENT notify, and
        # there is no CUSTOMER_* transition request, so no DECISION notify.
        ew = self._make_ew(intent=ExtraWorkRequestIntent.AUTO_START_AFTER_PRICING)
        proposal = self._create_draft_proposal(ew)
        resp = self._send_proposal(ew, proposal)
        self.assertEqual(resp.status_code, 200, resp.data)
        proposal.refresh_from_db()
        self.assertEqual(proposal.status, ProposalStatus.CUSTOMER_APPROVED)

        self.assertFalse(
            Notification.objects.filter(
                event_type=NotificationType.EXTRA_WORK_PROPOSAL_SENT,
                extra_work=ew,
            ).exists()
        )
        self.assertFalse(
            Notification.objects.filter(
                event_type=NotificationType.EXTRA_WORK_DECISION,
                extra_work=ew,
            ).exists()
        )
