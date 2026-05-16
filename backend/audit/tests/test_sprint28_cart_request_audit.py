"""
Sprint 28 Batch 6 — audit-coverage tests for the new
ExtraWorkRequestItem model.

ExtraWorkRequestItem is registered with the full-CRUD signal trio
(`_on_pre_save` / `_on_post_save` / `_on_post_delete`) in
`backend/audit/signals.py`. The tests below drive the create path
end-to-end through the cart-submission API and then exercise the
model directly for UPDATE / DELETE (the line-item editor surface
ships in a later sprint; for Batch 6 the model-level audit shape is
what we need to lock).

The parent `ExtraWorkRequest.routing_decision` field is set by the
serializer's `create()` flow. Because `ExtraWorkRequest` is not yet
registered for audit (a deliberate Batch 6 scope decision — registering
the request itself is its own future sprint), there is no AuditLog row
for the field write; this module pins that contract so a future sprint
that DOES register the model can pick up the change with an explicit
assertion update rather than an unexplained empty diff.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from rest_framework import status
from rest_framework.test import APITestCase

from accounts.models import UserRole
from audit.models import AuditAction, AuditLog
from buildings.models import Building
from companies.models import Company
from customers.models import (
    Customer,
    CustomerBuildingMembership,
    CustomerUserBuildingAccess,
    CustomerUserMembership,
)
from extra_work.models import (
    ExtraWorkCategory,
    ExtraWorkPricingUnitType,
    ExtraWorkRequest,
    ExtraWorkRequestItem,
    ExtraWorkRoutingDecision,
    Service,
    ServiceCategory,
)


User = get_user_model()
PASSWORD = "StrongerTestPassword123!"
URL = "/api/extra-work/"


class CartAuditFixtureMixin:
    @classmethod
    def _setup_fixture(cls):
        cls.company = Company.objects.create(
            name="Audit Provider", slug="audit-prov-b6"
        )
        cls.building = Building.objects.create(
            company=cls.company, name="A1"
        )
        cls.customer = Customer.objects.create(
            company=cls.company, name="Audit Cust", building=cls.building
        )
        CustomerBuildingMembership.objects.create(
            customer=cls.customer, building=cls.building
        )
        cls.super_admin = User.objects.create_user(
            email="super-audit-b6@example.com",
            password=PASSWORD,
            full_name="super",
            role=UserRole.SUPER_ADMIN,
            is_staff=True,
            is_superuser=True,
        )
        cls.customer_user = User.objects.create_user(
            email="cust-audit-b6@example.com",
            password=PASSWORD,
            full_name="cust",
            role=UserRole.CUSTOMER_USER,
        )
        membership = CustomerUserMembership.objects.create(
            customer=cls.customer, user=cls.customer_user
        )
        CustomerUserBuildingAccess.objects.create(
            membership=membership,
            building=cls.building,
            access_role=CustomerUserBuildingAccess.AccessRole.CUSTOMER_USER,
        )
        cls.service_cat = ServiceCategory.objects.create(
            name="Audit Cat"
        )
        cls.service = Service.objects.create(
            category=cls.service_cat,
            name="Audit svc",
            unit_type=ExtraWorkPricingUnitType.HOURS,
            default_unit_price=Decimal("50.00"),
        )

    def _create_request_with_one_line(self) -> ExtraWorkRequest:
        """Drive an end-to-end cart submission via the API so the
        AuditLog rows the test asserts on come from the real
        signal chain, not a backdoored .objects.create()."""
        self.client.force_authenticate(user=self.super_admin)
        payload = {
            "customer": self.customer.id,
            "building": self.building.id,
            "title": "Cart for audit",
            "description": "cart",
            "category": ExtraWorkCategory.DEEP_CLEANING,
            "line_items": [
                {
                    "service": self.service.id,
                    "quantity": "1.00",
                    "requested_date": "2026-06-15",
                    "customer_note": "",
                }
            ],
        }
        response = self.client.post(URL, payload, format="json")
        assert response.status_code == status.HTTP_201_CREATED, response.data
        return ExtraWorkRequest.objects.get(id=response.data["id"])


class ExtraWorkRequestItemAuditTests(CartAuditFixtureMixin, APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls._setup_fixture()

    def setUp(self):
        super().setUp()
        # Fresh AuditLog slate for every test — fixture setUpTestData
        # already wrote a bunch of CREATE rows for tenancy fixture
        # objects (companies / buildings / customers / users) that
        # are irrelevant to the line-item assertions below.
        AuditLog.objects.all().delete()

    def test_line_item_create_via_cart_submission_emits_audit_log(self):
        request = self._create_request_with_one_line()
        line = request.line_items.get()

        logs = AuditLog.objects.filter(
            target_model="extra_work.ExtraWorkRequestItem",
            target_id=line.id,
        )
        self.assertEqual(logs.count(), 1)
        log = logs.first()
        self.assertEqual(log.action, AuditAction.CREATE)
        self.assertEqual(log.actor, self.super_admin)
        # CREATE-shape diff: new values in `after`, None in `before`.
        self.assertIn("quantity", log.changes)
        self.assertEqual(
            Decimal(log.changes["quantity"]["after"]), Decimal("1.00")
        )
        self.assertIsNone(log.changes["quantity"]["before"])
        # service FK captured as the pk.
        self.assertEqual(
            log.changes["service"]["after"], self.service.id
        )
        self.assertEqual(log.changes["unit_type"]["after"], "HOURS")
        self.assertEqual(
            log.changes["requested_date"]["after"], "2026-06-15"
        )

    def test_line_item_update_emits_audit_log(self):
        request = self._create_request_with_one_line()
        line = request.line_items.get()
        AuditLog.objects.all().delete()

        line.quantity = Decimal("5.00")
        line.customer_note = "after edit"
        line.save()

        log = AuditLog.objects.filter(
            target_model="extra_work.ExtraWorkRequestItem",
            target_id=line.id,
            action=AuditAction.UPDATE,
        ).get()
        # Only the edited fields land in the diff.
        self.assertEqual(
            set(log.changes.keys()), {"quantity", "customer_note"}
        )
        self.assertEqual(
            Decimal(log.changes["quantity"]["before"]), Decimal("1.00")
        )
        self.assertEqual(
            Decimal(log.changes["quantity"]["after"]), Decimal("5.00")
        )
        self.assertEqual(log.changes["customer_note"]["before"], "")
        self.assertEqual(log.changes["customer_note"]["after"], "after edit")

    def test_line_item_delete_emits_audit_log(self):
        request = self._create_request_with_one_line()
        line = request.line_items.get()
        line_id = line.id
        AuditLog.objects.all().delete()

        line.delete()

        log = AuditLog.objects.filter(
            target_model="extra_work.ExtraWorkRequestItem",
            target_id=line_id,
            action=AuditAction.DELETE,
        ).get()
        # DELETE-shape diff: old values in `before`, None in `after`.
        self.assertEqual(
            Decimal(log.changes["quantity"]["before"]), Decimal("1.00")
        )
        self.assertIsNone(log.changes["quantity"]["after"])
        self.assertEqual(log.changes["service"]["before"], self.service.id)


class ExtraWorkRequestRoutingDecisionAuditTests(
    CartAuditFixtureMixin, APITestCase
):
    """
    The parent `ExtraWorkRequest` is intentionally NOT registered for
    audit in Batch 6. This test class pins the contract: writing the
    routing_decision field through the create serializer must NOT
    cause a parent-row AuditLog row in this sprint. When a future
    sprint registers the request model, the assertion below should be
    flipped (and the diff shape captured) in a single deliberate edit.
    """

    @classmethod
    def setUpTestData(cls):
        cls._setup_fixture()

    def setUp(self):
        super().setUp()
        AuditLog.objects.all().delete()

    def test_request_routing_decision_write_is_not_audited_yet(self):
        request = self._create_request_with_one_line()
        # No AuditLog rows for the parent request itself (the model is
        # not registered for audit in Batch 6).
        self.assertFalse(
            AuditLog.objects.filter(
                target_model="extra_work.ExtraWorkRequest",
                target_id=request.id,
            ).exists()
        )

    def test_request_routing_decision_value_is_stored(self):
        # Sanity belt: even without an audit row, the routing_decision
        # IS persisted (so a future sprint that wires up the audit
        # column will diff against the real value).
        request = self._create_request_with_one_line()
        self.assertEqual(
            request.routing_decision,
            ExtraWorkRoutingDecision.PROPOSAL,
        )
