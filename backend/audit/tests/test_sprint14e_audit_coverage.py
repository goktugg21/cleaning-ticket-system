"""
Sprint 14E — generic audit coverage for ticket notes, attachments, and
dated staff-assignment slots, plus the no-double-write guarantee for the
ticket lifecycle (TicketStatusHistory stays the H-11 status trail).

Audit reads are SUPER_ADMIN-only (AuditLogViewSet) / provider-only
(ticket timeline); there is no customer-visible audit endpoint, so
internal note bodies never leak. GET endpoints write no audit.
"""
from __future__ import annotations

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from rest_framework.test import APIClient

from accounts.models import StaffProfile, UserRole
from audit.models import AuditAction, AuditLog
from buildings.models import (
    Building,
    BuildingManagerAssignment,
    BuildingStaffVisibility,
)
from companies.models import Company, CompanyUserMembership
from customers.models import (
    Customer,
    CustomerBuildingMembership,
    CustomerUserBuildingAccess,
    CustomerUserMembership,
)
from tickets.models import (
    StaffAssignmentSlotStatus,
    Ticket,
    TicketStaffAssignment,
    TicketStatusHistory,
)


User = get_user_model()
PASSWORD = "StrongerTestPassword123!"


def _mk(email, role, **extra):
    return User.objects.create_user(
        email=email, password=PASSWORD, role=role,
        full_name=email.split("@")[0], **extra,
    )


class _AuditFixture(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.company = Company.objects.create(name="Prov AC", slug="prov-ac-14e")
        cls.building = Building.objects.create(company=cls.company, name="B-ac")
        cls.customer = Customer.objects.create(
            company=cls.company, name="Cust-ac", building=cls.building
        )
        CustomerBuildingMembership.objects.create(
            customer=cls.customer, building=cls.building
        )

        cls.super_admin = _mk(
            "sa-ac@example.com", UserRole.SUPER_ADMIN,
            is_staff=True, is_superuser=True,
        )
        cls.admin = _mk("ca-ac@example.com", UserRole.COMPANY_ADMIN)
        CompanyUserMembership.objects.create(user=cls.admin, company=cls.company)

        cls.staff = _mk("staff-ac@example.com", UserRole.STAFF)
        StaffProfile.objects.create(user=cls.staff)
        BuildingStaffVisibility.objects.create(user=cls.staff, building=cls.building)

        cls.cust_user = _mk("cust-ac@example.com", UserRole.CUSTOMER_USER)
        m = CustomerUserMembership.objects.create(
            customer=cls.customer, user=cls.cust_user
        )
        CustomerUserBuildingAccess.objects.create(
            membership=m,
            building=cls.building,
            access_role=CustomerUserBuildingAccess.AccessRole.CUSTOMER_COMPANY_ADMIN,
        )

        # Out-of-scope provider for the scope test.
        cls.other_company = Company.objects.create(
            name="Other AC", slug="other-ac-14e"
        )
        cls.other_building = Building.objects.create(
            company=cls.other_company, name="B-other-ac"
        )
        cls.other_bm = _mk("bm-other-ac@example.com", UserRole.BUILDING_MANAGER)
        BuildingManagerAssignment.objects.create(
            user=cls.other_bm, building=cls.other_building
        )

        cls.ticket = Ticket.objects.create(
            company=cls.company,
            building=cls.building,
            customer=cls.customer,
            created_by=cls.admin,
            title="Audit ticket",
            description="desc",
            status="OPEN",
        )

    def _api(self, user):
        c = APIClient()
        c.force_authenticate(user=user)
        return c

    def _ticket_audit(self, model, action=None, target_id=None):
        qs = AuditLog.objects.filter(target_model=model)
        if action is not None:
            qs = qs.filter(action=action)
        if target_id is not None:
            qs = qs.filter(target_id=target_id)
        return qs


class TicketCreateAuditTests(_AuditFixture):
    def test_ticket_create_via_api_writes_one_audit_row(self):
        before = self._ticket_audit(
            "tickets.Ticket", action=AuditAction.CREATE
        ).count()
        resp = self._api(self.super_admin).post(
            "/api/tickets/",
            {
                "title": "New audited ticket",
                "description": "body",
                "building": self.building.id,
                "customer": self.customer.id,
            },
            format="json",
        )
        self.assertEqual(resp.status_code, 201, resp.data)
        new_id = resp.data["id"]
        rows = self._ticket_audit(
            "tickets.Ticket", action=AuditAction.CREATE, target_id=new_id
        )
        self.assertEqual(rows.count(), 1)
        self.assertEqual(rows.first().changes["title"]["after"], "New audited ticket")
        self.assertEqual(rows.first().actor_id, self.super_admin.id)


class NoteAuditTests(_AuditFixture):
    def test_note_added_writes_one_audit_row_with_type(self):
        resp = self._api(self.super_admin).post(
            f"/api/tickets/{self.ticket.id}/messages/",
            {"message": "Public note", "message_type": "PUBLIC_REPLY"},
            format="json",
        )
        self.assertEqual(resp.status_code, 201, resp.data)
        note_id = resp.data["id"]
        rows = self._ticket_audit(
            "tickets.TicketMessage", action=AuditAction.CREATE, target_id=note_id
        )
        self.assertEqual(rows.count(), 1)
        self.assertEqual(
            rows.first().changes["message_type"]["after"], "PUBLIC_REPLY"
        )


class AttachmentAuditTests(_AuditFixture):
    def test_attachment_upload_writes_one_audit_row(self):
        upload = SimpleUploadedFile(
            "evidence.png", b"\x89PNG\r\n\x1a\n", content_type="image/png"
        )
        resp = self._api(self.super_admin).post(
            f"/api/tickets/{self.ticket.id}/attachments/",
            {"file": upload},
            format="multipart",
        )
        self.assertEqual(resp.status_code, 201, resp.data)
        att_id = resp.data["id"]
        rows = self._ticket_audit(
            "tickets.TicketAttachment",
            action=AuditAction.CREATE,
            target_id=att_id,
        )
        self.assertEqual(rows.count(), 1)


class SlotAuditTests(_AuditFixture):
    def test_slot_create_update_delete_each_one_row(self):
        url = f"/api/tickets/{self.ticket.id}/staff-assignments/"

        # CREATE -> one membership CREATE row.
        r = self._api(self.admin).post(
            url, {"user_id": self.staff.id, "time_window_label": "morning"},
            format="json",
        )
        self.assertEqual(r.status_code, 201, r.data)
        slot_id = TicketStaffAssignment.objects.get(
            ticket=self.ticket, user=self.staff
        ).id
        # Multi-slot per staff — PATCH / DELETE are keyed by the slot id.
        detail = f"{url}{slot_id}/"
        self.assertEqual(
            self._ticket_audit(
                "tickets.TicketStaffAssignment",
                action=AuditAction.CREATE,
                target_id=slot_id,
            ).count(),
            1,
        )

        # UPDATE (complete) -> EXACTLY one UPDATE row (no double write
        # from the completed_at side-effect).
        r = self._api(self.admin).patch(
            detail,
            {
                "slot_status": StaffAssignmentSlotStatus.COMPLETED,
                "completion_note": "done",
            },
            format="json",
        )
        self.assertEqual(r.status_code, 200, r.data)
        update_rows = self._ticket_audit(
            "tickets.TicketStaffAssignment",
            action=AuditAction.UPDATE,
            target_id=slot_id,
        )
        self.assertEqual(update_rows.count(), 1)
        self.assertIn("slot_status", update_rows.first().changes)

        # DELETE -> one DELETE row.
        r = self._api(self.admin).delete(detail)
        self.assertEqual(r.status_code, 204)
        self.assertEqual(
            self._ticket_audit(
                "tickets.TicketStaffAssignment",
                action=AuditAction.DELETE,
                target_id=slot_id,
            ).count(),
            1,
        )


class NoDoubleWriteStatusTests(_AuditFixture):
    def test_status_transition_writes_history_not_generic_ticket_audit(self):
        before_hist = TicketStatusHistory.objects.filter(
            ticket=self.ticket
        ).count()
        resp = self._api(self.super_admin).post(
            f"/api/tickets/{self.ticket.id}/status/",
            {"to_status": "IN_PROGRESS"},
            format="json",
        )
        self.assertEqual(resp.status_code, 200, resp.data)
        # The H-11 status trail row was written.
        self.assertEqual(
            TicketStatusHistory.objects.filter(ticket=self.ticket).count(),
            before_hist + 1,
        )
        # No generic tickets.Ticket UPDATE audit row for the status
        # change (Ticket is intentionally NOT in the generic CRUD trio).
        self.assertEqual(
            self._ticket_audit(
                "tickets.Ticket",
                action=AuditAction.UPDATE,
                target_id=self.ticket.id,
            ).count(),
            0,
        )


class TimelineTests(_AuditFixture):
    def _make_note_and_attachment(self):
        self._api(self.super_admin).post(
            f"/api/tickets/{self.ticket.id}/messages/",
            {"message": "n", "message_type": "PUBLIC_REPLY"},
            format="json",
        )
        upload = SimpleUploadedFile(
            "a.png", b"\x89PNG\r\n\x1a\n", content_type="image/png"
        )
        self._api(self.super_admin).post(
            f"/api/tickets/{self.ticket.id}/attachments/",
            {"file": upload},
            format="multipart",
        )

    def _timeline_url(self, ticket_id=None):
        tid = ticket_id or self.ticket.id
        return f"/api/audit/tickets/{tid}/timeline/"

    def test_timeline_includes_note_and_attachment_audit_rows(self):
        self._make_note_and_attachment()
        resp = self._api(self.super_admin).get(self._timeline_url())
        self.assertEqual(resp.status_code, 200, resp.data)
        models_seen = {
            e.get("target_model")
            for e in resp.data["timeline"]
            if e.get("source") == "audit_log"
        }
        self.assertIn("tickets.TicketMessage", models_seen)
        self.assertIn("tickets.TicketAttachment", models_seen)

    def test_timeline_get_writes_no_audit(self):
        self._make_note_and_attachment()
        before = AuditLog.objects.count()
        self._api(self.super_admin).get(self._timeline_url())
        self.assertEqual(AuditLog.objects.count(), before)

    def test_timeline_forbidden_for_customer_and_staff(self):
        self.assertEqual(
            self._api(self.cust_user).get(self._timeline_url()).status_code, 403
        )
        self.assertEqual(
            self._api(self.staff).get(self._timeline_url()).status_code, 403
        )

    def test_out_of_scope_provider_gets_404(self):
        resp = self._api(self.other_bm).get(self._timeline_url())
        self.assertEqual(resp.status_code, 404, getattr(resp, "data", None))


class AuditFeedAccessTests(_AuditFixture):
    def test_customer_cannot_read_audit_log_feed(self):
        # AuditLogViewSet is SUPER_ADMIN-only.
        self.assertEqual(
            self._api(self.cust_user).get("/api/audit-logs/").status_code, 403
        )
        self.assertEqual(
            self._api(self.staff).get("/api/audit-logs/").status_code, 403
        )
        self.assertEqual(
            self._api(self.admin).get("/api/audit-logs/").status_code, 403
        )
        self.assertEqual(
            self._api(self.super_admin).get("/api/audit-logs/").status_code, 200
        )
