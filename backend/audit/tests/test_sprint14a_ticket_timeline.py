"""Sprint 14A — unified read-only ticket audit timeline.

GET /api/audit/tickets/<ticket_id>/timeline/

The endpoint aggregates, for one ticket and READ-ONLY:
  * TicketStatusHistory rows (the H-11 workflow trail)        -> source "status_history"
  * AuditLog rows anchored to the ticket / its assignments    -> source "audit_log"
  * linked ExtraWorkRequest reference + its status history    -> "extra_work_link" / "extra_work_status_history"
  * planned-occurrence origin reference                       -> "planned_occurrence_link"

Pinned guarantees:
  - workflow status transitions surface (drive at least one transition);
  - a ticket-anchored AuditLog event (a staff assignment) surfaces;
  - entries are merged + ascending-sorted, each carrying a 'source' tag;
  - out-of-scope provider (other-company CA / unassigned BM) -> 404;
  - CUSTOMER_USER -> 403; STAFF -> 403 (no provider-internal audit);
  - hitting the endpoint writes NO AuditLog rows (read-only / no double-write).
"""
from __future__ import annotations

from rest_framework import status
from rest_framework.test import APITestCase

from accounts.models import UserRole
from audit.models import AuditLog
from buildings.models import BuildingStaffVisibility
from tickets.models import TicketStaffAssignment, TicketStatus
from tickets.state_machine import apply_transition
from test_utils import TenantFixtureMixin


class _TimelineBase(TenantFixtureMixin, APITestCase):
    def setUp(self):
        super().setUp()
        # STAFF persona with building visibility + a per-ticket assignment
        # on self.ticket, so the staff-assignment audit row exists and the
        # 403 path is exercised with a realistic, in-scope STAFF user.
        self.staff = self.make_user("staff-a@example.com", UserRole.STAFF)
        BuildingStaffVisibility.objects.create(
            user=self.staff,
            building=self.building,
            visibility_level=BuildingStaffVisibility.VisibilityLevel.BUILDING_READ_AND_ASSIGN,
        )

    def _url(self, ticket_id):
        return f"/api/audit/tickets/{ticket_id}/timeline/"


class TicketTimelineContentTests(_TimelineBase):
    def test_status_history_workflow_entries_surface(self):
        # Drive one real workflow transition so a TicketStatusHistory row
        # exists for self.ticket.
        apply_transition(
            self.ticket, self.super_admin, TicketStatus.IN_PROGRESS, note="kick off"
        )

        self.authenticate(self.super_admin)
        response = self.client.get(self._url(self.ticket.id))
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        self.assertEqual(response.data["ticket_id"], self.ticket.id)
        self.assertIn("generated_at", response.data)

        status_entries = [
            e for e in response.data["timeline"] if e["source"] == "status_history"
        ]
        self.assertEqual(len(status_entries), 1)
        entry = status_entries[0]
        self.assertEqual(entry["old_status"], TicketStatus.OPEN)
        self.assertEqual(entry["new_status"], TicketStatus.IN_PROGRESS)
        self.assertEqual(entry["note"], "kick off")
        self.assertEqual(entry["changed_by_email"], self.super_admin.email)
        self.assertIn("is_override", entry)

    def test_override_history_row_carries_override_fields(self):
        # WAITING_CUSTOMER_APPROVAL -> APPROVED driven by a provider
        # operator coerces is_override=True and requires a reason; that
        # fact lives on the status-history row (H-11) and must surface.
        self.move_ticket_to_customer_approval(self.ticket)
        apply_transition(
            self.ticket,
            self.super_admin,
            TicketStatus.APPROVED,
            is_override=True,
            override_reason="customer approved by phone",
        )

        self.authenticate(self.company_admin)
        response = self.client.get(self._url(self.ticket.id))
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        override_entries = [
            e
            for e in response.data["timeline"]
            if e["source"] == "status_history" and e["is_override"]
        ]
        self.assertEqual(len(override_entries), 1)
        self.assertEqual(
            override_entries[0]["override_reason"], "customer approved by phone"
        )

    def test_ticket_anchored_audit_log_entries_surface(self):
        # A staff assignment writes a tickets.TicketStaffAssignment audit
        # row anchored to this ticket's assignment pk. It must surface as
        # an "audit_log" entry.
        self.authenticate(self.super_admin)
        TicketStaffAssignment.objects.create(
            ticket=self.ticket, user=self.staff, assigned_by=self.super_admin
        )

        response = self.client.get(self._url(self.ticket.id))
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        audit_entries = [
            e for e in response.data["timeline"] if e["source"] == "audit_log"
        ]
        self.assertGreaterEqual(len(audit_entries), 1)
        self.assertTrue(
            any(
                e["target_model"] == "tickets.TicketStaffAssignment"
                for e in audit_entries
            )
        )

    def test_entries_merged_sorted_ascending_and_tagged(self):
        # Two transitions + one assignment -> at least three entries that
        # must come back timestamp-ascending, each carrying a source tag.
        apply_transition(
            self.ticket, self.super_admin, TicketStatus.IN_PROGRESS, note="t1"
        )
        # apply_transition mutates the DB row; refresh the in-memory
        # instance so the next transition's stale-status guard sees the
        # current status (OPEN-in-memory vs IN_PROGRESS-in-DB would 400).
        self.ticket.refresh_from_db()
        TicketStaffAssignment.objects.create(
            ticket=self.ticket, user=self.staff, assigned_by=self.super_admin
        )
        apply_transition(
            self.ticket,
            self.super_admin,
            TicketStatus.WAITING_CUSTOMER_APPROVAL,
            note="t2",
        )

        self.authenticate(self.super_admin)
        response = self.client.get(self._url(self.ticket.id))
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        timeline = response.data["timeline"]
        self.assertGreaterEqual(len(timeline), 3)
        for entry in timeline:
            self.assertIn("source", entry)
            self.assertIn("timestamp", entry)
        timestamps = [e["timestamp"] for e in timeline]
        self.assertEqual(timestamps, sorted(timestamps))

    def test_read_only_no_audit_rows_written(self):
        # Hitting the timeline endpoint must not write any AuditLog rows
        # (proves no double-write of the workflow trail).
        apply_transition(
            self.ticket, self.super_admin, TicketStatus.IN_PROGRESS, note="seed"
        )
        before = AuditLog.objects.count()

        self.authenticate(self.super_admin)
        response = self.client.get(self._url(self.ticket.id))
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        self.assertEqual(AuditLog.objects.count(), before)


class TicketTimelineScopeTests(_TimelineBase):
    def test_super_admin_sees_any_ticket(self):
        self.authenticate(self.super_admin)
        response = self.client.get(self._url(self.other_ticket.id))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["ticket_id"], self.other_ticket.id)

    def test_company_admin_sees_own_company_ticket(self):
        self.authenticate(self.company_admin)
        response = self.client.get(self._url(self.ticket.id))
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_company_admin_of_other_company_gets_404(self):
        # other_company_admin manages self.other_company; self.ticket is in
        # self.company -> existence must not leak.
        self.authenticate(self.other_company_admin)
        response = self.client.get(self._url(self.ticket.id))
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_building_manager_sees_assigned_building_ticket(self):
        self.authenticate(self.manager)
        response = self.client.get(self._url(self.ticket.id))
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_building_manager_not_assigned_gets_404(self):
        # other_manager is assigned to self.other_building, not self.building.
        self.authenticate(self.other_manager)
        response = self.client.get(self._url(self.ticket.id))
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_nonexistent_ticket_gets_404(self):
        self.authenticate(self.super_admin)
        response = self.client.get(self._url(999999))
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)


class TicketTimelinePermissionTests(_TimelineBase):
    def test_customer_user_forbidden(self):
        # customer_user created self.ticket and can see it, but the
        # provider-internal audit timeline is closed to customers.
        self.authenticate(self.customer_user)
        response = self.client.get(self._url(self.ticket.id))
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_staff_forbidden(self):
        # self.staff is assigned to self.ticket (in operational scope) but
        # must NOT see provider-internal audit detail.
        TicketStaffAssignment.objects.create(
            ticket=self.ticket, user=self.staff, assigned_by=self.super_admin
        )
        self.authenticate(self.staff)
        response = self.client.get(self._url(self.ticket.id))
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_unauthenticated_rejected(self):
        response = self.client.get(self._url(self.ticket.id))
        self.assertIn(
            response.status_code,
            (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN),
        )
