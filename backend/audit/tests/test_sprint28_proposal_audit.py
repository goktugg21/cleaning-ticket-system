"""
Sprint 28 Batch 8 — audit-coverage tests for the proposal models.

Locks the contract:
  * `Proposal` and `ProposalLine` are registered for full CRUD
    (CREATE / UPDATE / DELETE produce AuditLog rows with diff).
  * `ProposalStatusHistory` and `ProposalTimelineEvent` are NOT
    registered (matrix H-11: those history rows are themselves the
    audit trail; double-writing would break the H-11 separation).
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
from companies.models import Company, CompanyUserMembership
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
    ExtraWorkStatus,
    Proposal,
    ProposalLine,
    ProposalStatus,
    Service,
    ServiceCategory,
)


User = get_user_model()
PASSWORD = "StrongerTestPassword123!"


class ProposalAuditFixtureMixin:
    @classmethod
    def _setup_fixture(cls):
        cls.company = Company.objects.create(
            name="Audit B8 Provider", slug="audit-prov-b8"
        )
        cls.building = Building.objects.create(
            company=cls.company, name="Audit-B8-Building"
        )
        cls.customer = Customer.objects.create(
            company=cls.company,
            name="Audit-B8-Cust",
            building=cls.building,
        )
        CustomerBuildingMembership.objects.create(
            customer=cls.customer, building=cls.building
        )
        cls.admin = User.objects.create_user(
            email="audit-admin-b8@example.com",
            password=PASSWORD,
            full_name="audit admin",
            role=UserRole.COMPANY_ADMIN,
        )
        CompanyUserMembership.objects.create(
            user=cls.admin, company=cls.company
        )
        cls.cust_user = User.objects.create_user(
            email="audit-cust-b8@example.com",
            password=PASSWORD,
            full_name="audit cust",
            role=UserRole.CUSTOMER_USER,
        )
        membership = CustomerUserMembership.objects.create(
            customer=cls.customer, user=cls.cust_user
        )
        CustomerUserBuildingAccess.objects.create(
            membership=membership,
            building=cls.building,
            access_role=CustomerUserBuildingAccess.AccessRole.CUSTOMER_USER,
        )
        cls.service_cat = ServiceCategory.objects.create(name="Audit-B8-Cat")
        cls.service = Service.objects.create(
            category=cls.service_cat,
            name="Audit svc",
            unit_type=ExtraWorkPricingUnitType.HOURS,
            default_unit_price=Decimal("50.00"),
        )

    def _make_ew_under_review(self) -> ExtraWorkRequest:
        ew = ExtraWorkRequest.objects.create(
            company=self.company,
            building=self.building,
            customer=self.customer,
            created_by=self.cust_user,
            title="Audit fixture EW",
            description="d",
            category=ExtraWorkCategory.DEEP_CLEANING,
            status=ExtraWorkStatus.UNDER_REVIEW,
        )
        ExtraWorkRequestItem.objects.create(
            extra_work_request=ew,
            service=self.service,
            quantity=Decimal("1.00"),
            unit_type=ExtraWorkPricingUnitType.HOURS,
            requested_date=date(2026, 6, 15),
            customer_note="",
        )
        return ew

    def _create_proposal_via_api(self, ew: ExtraWorkRequest) -> Proposal:
        self.client.force_authenticate(user=self.admin)
        payload = {
            "lines": [
                {
                    "service": self.service.id,
                    "quantity": "2.00",
                    "unit_type": ExtraWorkPricingUnitType.HOURS,
                    "unit_price": "50.00",
                    "vat_pct": "21.00",
                    "customer_explanation": "explainer",
                    "internal_note": "internal",
                }
            ]
        }
        response = self.client.post(
            f"/api/extra-work/{ew.id}/proposals/",
            payload,
            format="json",
        )
        assert response.status_code == status.HTTP_201_CREATED, response.data
        return Proposal.objects.get(pk=response.data["id"])


class ProposalAuditTests(ProposalAuditFixtureMixin, APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls._setup_fixture()

    def setUp(self):
        super().setUp()
        AuditLog.objects.all().delete()

    def test_proposal_create_via_api_writes_audit_log(self):
        ew = self._make_ew_under_review()
        proposal = self._create_proposal_via_api(ew)
        # The create flow writes a CREATE row, then `recompute_totals()`
        # immediately re-saves the row with the computed totals, which
        # surfaces as an additional UPDATE row. We assert on the CREATE
        # row specifically — the UPDATE is incidental and locked in by
        # the dedicated update test below.
        create_logs = AuditLog.objects.filter(
            target_model="extra_work.Proposal",
            target_id=proposal.id,
            action=AuditAction.CREATE,
        )
        self.assertEqual(create_logs.count(), 1)
        log = create_logs.first()
        self.assertEqual(log.actor, self.admin)
        self.assertIn("status", log.changes)
        self.assertEqual(log.changes["status"]["after"], "DRAFT")

    def test_proposal_update_writes_audit_log(self):
        ew = self._make_ew_under_review()
        proposal = self._create_proposal_via_api(ew)
        AuditLog.objects.all().delete()

        proposal.status = ProposalStatus.SENT
        proposal.save(update_fields=["status", "updated_at"])

        log = AuditLog.objects.filter(
            target_model="extra_work.Proposal",
            target_id=proposal.id,
            action=AuditAction.UPDATE,
        ).get()
        self.assertEqual(log.changes["status"]["before"], "DRAFT")
        self.assertEqual(log.changes["status"]["after"], "SENT")

    def test_proposal_delete_writes_audit_log(self):
        ew = self._make_ew_under_review()
        proposal = self._create_proposal_via_api(ew)
        pid = proposal.id
        AuditLog.objects.all().delete()

        proposal.delete()

        log = AuditLog.objects.filter(
            target_model="extra_work.Proposal",
            target_id=pid,
            action=AuditAction.DELETE,
        ).get()
        # DELETE-shape: old values in `before`, None in `after`.
        self.assertEqual(log.changes["status"]["before"], "DRAFT")
        self.assertIsNone(log.changes["status"]["after"])


class ProposalLineAuditTests(ProposalAuditFixtureMixin, APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls._setup_fixture()

    def setUp(self):
        super().setUp()
        AuditLog.objects.all().delete()

    def test_proposal_line_create_via_api_writes_audit_log(self):
        ew = self._make_ew_under_review()
        proposal = self._create_proposal_via_api(ew)
        line = proposal.lines.get()
        logs = AuditLog.objects.filter(
            target_model="extra_work.ProposalLine",
            target_id=line.id,
        )
        self.assertEqual(logs.count(), 1)
        log = logs.first()
        self.assertEqual(log.action, AuditAction.CREATE)
        self.assertEqual(log.actor, self.admin)
        self.assertEqual(
            Decimal(log.changes["quantity"]["after"]), Decimal("2.00")
        )
        self.assertEqual(log.changes["service"]["after"], self.service.id)
        # `internal_note` is in the diff (provider-only data is still
        # auditable — the audit log is provider-internal too).
        self.assertEqual(log.changes["internal_note"]["after"], "internal")

    def test_proposal_line_update_writes_audit_log(self):
        ew = self._make_ew_under_review()
        proposal = self._create_proposal_via_api(ew)
        line = proposal.lines.get()
        AuditLog.objects.all().delete()

        line.customer_explanation = "edited"
        line.quantity = Decimal("3.00")
        line.save()

        log = AuditLog.objects.filter(
            target_model="extra_work.ProposalLine",
            target_id=line.id,
            action=AuditAction.UPDATE,
        ).get()
        # quantity moves and recomputes line_subtotal/line_vat/line_total,
        # so the diff includes those as well — assert at minimum the
        # edited fields land.
        self.assertIn("customer_explanation", log.changes)
        self.assertEqual(
            log.changes["customer_explanation"]["after"], "edited"
        )
        self.assertEqual(
            Decimal(log.changes["quantity"]["before"]), Decimal("2.00")
        )
        self.assertEqual(
            Decimal(log.changes["quantity"]["after"]), Decimal("3.00")
        )

    def test_proposal_line_delete_writes_audit_log(self):
        ew = self._make_ew_under_review()
        proposal = self._create_proposal_via_api(ew)
        line = proposal.lines.get()
        lid = line.id
        AuditLog.objects.all().delete()

        line.delete()

        log = AuditLog.objects.filter(
            target_model="extra_work.ProposalLine",
            target_id=lid,
            action=AuditAction.DELETE,
        ).get()
        self.assertEqual(
            Decimal(log.changes["quantity"]["before"]), Decimal("2.00")
        )


class ProposalTimelineEventNotAuditedTests(
    ProposalAuditFixtureMixin, APITestCase
):
    """H-11: the workflow-override history rows (status_history /
    timeline_event) are the audit trail themselves; they MUST NOT
    write to the generic AuditLog."""

    @classmethod
    def setUpTestData(cls):
        cls._setup_fixture()

    def setUp(self):
        super().setUp()
        AuditLog.objects.all().delete()

    def test_timeline_event_does_not_write_audit_log(self):
        ew = self._make_ew_under_review()
        proposal = self._create_proposal_via_api(ew)
        # Drive a full lifecycle: SEND + customer approve.
        self.client.post(
            f"/api/extra-work/{ew.id}/proposals/{proposal.id}/transition/",
            {"to_status": ProposalStatus.SENT},
            format="json",
        )
        self.client.force_authenticate(user=self.cust_user)
        self.client.post(
            f"/api/extra-work/{ew.id}/proposals/{proposal.id}/transition/",
            {"to_status": ProposalStatus.CUSTOMER_APPROVED},
            format="json",
        )
        # No AuditLog rows for the history / timeline rows.
        self.assertEqual(
            AuditLog.objects.filter(
                target_model="extra_work.ProposalTimelineEvent"
            ).count(),
            0,
        )
        self.assertEqual(
            AuditLog.objects.filter(
                target_model="extra_work.ProposalStatusHistory"
            ).count(),
            0,
        )
