"""
Sprint 12 — soft-delete coverage for tickets.

The DELETE action on /api/tickets/<id>/ never hard-removes a row. It
sets deleted_at + deleted_by, leaves messages / attachments /
status_history alone, and writes one AuditLog row.

These tests pin:

  - permission rules:
      SUPER_ADMIN can delete any in-scope ticket;
      COMPANY_ADMIN can delete any ticket in their company;
      BUILDING_MANAGER can only delete tickets they themselves opened;
      CUSTOMER_USER can only delete tickets they themselves opened;
      cross-tenant deletion returns 404 (queryset gate fires before
      the role gate);
      a non-creator customer-user with the same customer-membership as
      the creator is NOT allowed to delete (defence in depth).

  - hidden-from-list behaviour: a soft-deleted ticket disappears from
    GET /api/tickets/, GET /api/tickets/<id>/, GET /api/tickets/stats/,
    GET /api/tickets/stats/by-building/, and the reports module
    (status-distribution as a representative).

  - related-data preservation: messages, attachments, and
    TicketStatusHistory rows still exist in the DB after delete.

  - audit log behaviour: exactly one AuditLog row written, with the
    correct actor, target_model, target_id, and a rich changes
    payload (ticket_no, title, deleted_by_email).
"""
from datetime import datetime
from io import BytesIO

from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework import status
from rest_framework.test import APITestCase

from accounts.models import UserRole
from audit.models import AuditAction, AuditLog
from customers.models import CustomerUserMembership
from test_utils import TenantFixtureMixin
from tickets.models import (
    Ticket,
    TicketAttachment,
    TicketMessage,
    TicketMessageType,
    TicketStatus,
    TicketStatusHistory,
)


class _TicketDeleteBase(TenantFixtureMixin, APITestCase):
    def setUp(self):
        super().setUp()
        # Wipe audit rows so the count assertions below are deterministic
        # — TenantFixtureMixin's setUp creates membership rows that the
        # audit signals already log.
        AuditLog.objects.all().delete()


# ===========================================================================
# Permission matrix
# ===========================================================================


class TicketSoftDeletePermissionTests(_TicketDeleteBase):
    def test_super_admin_can_delete_any_ticket(self):
        self.authenticate(self.super_admin)
        response = self.client.delete(f"/api/tickets/{self.other_ticket.id}/")
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)

        self.other_ticket.refresh_from_db()
        self.assertIsNotNone(self.other_ticket.deleted_at)
        self.assertEqual(self.other_ticket.deleted_by, self.super_admin)

    def test_company_admin_can_delete_in_scope_ticket(self):
        self.authenticate(self.company_admin)
        response = self.client.delete(f"/api/tickets/{self.ticket.id}/")
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)

        self.ticket.refresh_from_db()
        self.assertIsNotNone(self.ticket.deleted_at)
        self.assertEqual(self.ticket.deleted_by, self.company_admin)

    def test_company_admin_cannot_delete_cross_company_ticket(self):
        # company_admin belongs to self.company; self.other_ticket lives
        # in self.other_company. The queryset gate fires first → 404.
        self.authenticate(self.company_admin)
        response = self.client.delete(f"/api/tickets/{self.other_ticket.id}/")
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

        self.other_ticket.refresh_from_db()
        self.assertIsNone(self.other_ticket.deleted_at)

    def test_creator_customer_can_delete_own_ticket(self):
        # self.ticket.created_by == self.customer_user (per
        # TenantFixtureMixin), so the customer-user is the creator.
        self.authenticate(self.customer_user)
        response = self.client.delete(f"/api/tickets/{self.ticket.id}/")
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)

        self.ticket.refresh_from_db()
        self.assertIsNotNone(self.ticket.deleted_at)
        self.assertEqual(self.ticket.deleted_by, self.customer_user)

    def test_non_creator_customer_user_cannot_delete(self):
        # A second customer-user shares the same customer with the
        # ticket creator but DID NOT open the ticket. Sprint 12's
        # conservative permission rule blocks them with 403 — even
        # though the ticket is technically in their scope.
        sibling = self.make_user(
            "customer-a-sibling@example.com", UserRole.CUSTOMER_USER
        )
        CustomerUserMembership.objects.create(user=sibling, customer=self.customer)

        self.authenticate(sibling)
        response = self.client.delete(f"/api/tickets/{self.ticket.id}/")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

        self.ticket.refresh_from_db()
        self.assertIsNone(self.ticket.deleted_at)

    def test_building_manager_cannot_delete_other_users_ticket(self):
        # self.manager is assigned to self.building (where self.ticket
        # lives) but did NOT create self.ticket — created_by is the
        # customer_user. The 403 fires AFTER the queryset gate (the
        # ticket IS in scope), proving the role-narrow rule kicks in.
        self.authenticate(self.manager)
        response = self.client.delete(f"/api/tickets/{self.ticket.id}/")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

        self.ticket.refresh_from_db()
        self.assertIsNone(self.ticket.deleted_at)

    def test_building_manager_can_delete_own_ticket(self):
        manager_ticket = Ticket.objects.create(
            company=self.company,
            building=self.building,
            customer=self.customer,
            created_by=self.manager,
            title="Manager-opened ticket",
            description="Opened by a manager who wants to roll it back",
        )
        self.authenticate(self.manager)
        response = self.client.delete(f"/api/tickets/{manager_ticket.id}/")
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)

        manager_ticket.refresh_from_db()
        self.assertIsNotNone(manager_ticket.deleted_at)


# ===========================================================================
# Hidden-from-list behaviour
# ===========================================================================


class TicketSoftDeleteVisibilityTests(_TicketDeleteBase):
    def setUp(self):
        super().setUp()
        # Soft-delete self.ticket (Company A's ticket) up front so each
        # test exercises the hidden-row guarantee.
        self.authenticate(self.super_admin)
        response = self.client.delete(f"/api/tickets/{self.ticket.id}/")
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)

    def test_deleted_ticket_hidden_from_list_for_super_admin(self):
        self.authenticate(self.super_admin)
        response = self.client.get("/api/tickets/")
        ids = self.response_ids(response)
        self.assertNotIn(self.ticket.id, ids)
        self.assertIn(self.other_ticket.id, ids)

    def test_deleted_ticket_hidden_from_list_for_company_admin(self):
        self.authenticate(self.company_admin)
        response = self.client.get("/api/tickets/")
        ids = self.response_ids(response)
        self.assertNotIn(self.ticket.id, ids)
        # company_admin only ever sees company A; with self.ticket gone
        # the list is now empty.
        self.assertEqual(ids, set())

    def test_deleted_ticket_hidden_from_detail(self):
        # Even a SUPER_ADMIN cannot read a soft-deleted ticket through
        # the public detail endpoint. (Hard SQL access in admin or a
        # dedicated archive endpoint can still see it.)
        self.authenticate(self.super_admin)
        response = self.client.get(f"/api/tickets/{self.ticket.id}/")
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_deleted_ticket_dropped_from_stats(self):
        self.authenticate(self.company_admin)
        response = self.client.get("/api/tickets/stats/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        # Company A only had self.ticket; deleting it leaves total=0.
        self.assertEqual(response.data["total"], 0)

    def test_deleted_ticket_dropped_from_reports(self):
        self.authenticate(self.company_admin)
        response = self.client.get("/api/reports/status-distribution/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["total"], 0)


# ===========================================================================
# Related-data preservation
# ===========================================================================


class TicketSoftDeletePreservesRelatedDataTests(_TicketDeleteBase):
    def test_messages_attachments_history_survive_soft_delete(self):
        # Build a message + attachment + status-history row attached to
        # the ticket BEFORE deleting it.
        message = TicketMessage.objects.create(
            ticket=self.ticket,
            author=self.manager,
            message="hello",
            message_type=TicketMessageType.PUBLIC_REPLY,
        )
        attachment = TicketAttachment.objects.create(
            ticket=self.ticket,
            uploaded_by=self.manager,
            file=SimpleUploadedFile("a.pdf", b"%PDF-1.4", content_type="application/pdf"),
            original_filename="a.pdf",
            mime_type="application/pdf",
            file_size=8,
        )
        history = TicketStatusHistory.objects.create(
            ticket=self.ticket,
            old_status="OPEN",
            new_status="IN_PROGRESS",
            changed_by=self.manager,
        )

        self.authenticate(self.super_admin)
        response = self.client.delete(f"/api/tickets/{self.ticket.id}/")
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)

        # Ticket row still in DB with deleted_at set.
        self.assertTrue(Ticket.objects.filter(pk=self.ticket.pk).exists())

        # Related rows untouched.
        self.assertTrue(TicketMessage.objects.filter(pk=message.pk).exists())
        self.assertTrue(TicketAttachment.objects.filter(pk=attachment.pk).exists())
        self.assertTrue(TicketStatusHistory.objects.filter(pk=history.pk).exists())


# ===========================================================================
# Audit log
# ===========================================================================


class TicketSoftDeleteAuditTests(_TicketDeleteBase):
    def test_soft_delete_writes_one_audit_log_with_actor_and_metadata(self):
        ticket_no = self.ticket.ticket_no
        ticket_title = self.ticket.title

        self.authenticate(self.super_admin)
        response = self.client.delete(f"/api/tickets/{self.ticket.id}/")
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)

        logs = AuditLog.objects.filter(
            target_model="tickets.Ticket",
            action=AuditAction.DELETE,
            target_id=self.ticket.id,
        )
        self.assertEqual(logs.count(), 1)
        log = logs.first()
        self.assertEqual(log.actor, self.super_admin)

        # Rich payload: an operator scrolling the audit feed sees the
        # ticket_no and title without a cross-lookup.
        self.assertEqual(log.changes["ticket_no"]["before"], ticket_no)
        self.assertEqual(log.changes["title"]["before"], ticket_title)
        self.assertEqual(
            log.changes["deleted_by_email"]["after"], self.super_admin.email
        )

    def test_soft_delete_records_request_ip_from_xff(self):
        # Sprint 11 nginx forwards XFF; the audit middleware reads the
        # FIRST hop. This test confirms the soft-delete view picks up
        # the same request_ip the rest of the audit infrastructure does.
        self.authenticate(self.super_admin)
        response = self.client.delete(
            f"/api/tickets/{self.ticket.id}/",
            HTTP_X_FORWARDED_FOR="203.0.113.7, 10.0.0.5",
        )
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)

        log = AuditLog.objects.filter(
            target_model="tickets.Ticket",
            action=AuditAction.DELETE,
            target_id=self.ticket.id,
        ).get()
        self.assertEqual(log.request_ip, "203.0.113.7")

    def test_forbidden_delete_does_not_write_audit_row(self):
        # A 403 response means the mutation never ran — no audit row
        # should appear. Same posture as the membership-audit tests.
        self.authenticate(self.manager)  # not the creator
        response = self.client.delete(f"/api/tickets/{self.ticket.id}/")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

        self.assertEqual(
            AuditLog.objects.filter(
                target_model="tickets.Ticket", target_id=self.ticket.id
            ).count(),
            0,
        )
