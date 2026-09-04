"""
WP-1 G4 — the billing-month guard: selector + endpoint.

Acceptance tests 4 and 5 of Addendum D §D.11.3 live here, plus the
gate, the tenancy floor and the month filter. The guard is a READ:
nothing in this file asserts a mutation because the surface cannot
perform one.
"""
from __future__ import annotations

import datetime

from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from accounts.models import UserRole
from extra_work import billing
from extra_work.models import ExtraWorkRequest, ExtraWorkStatus
from invoicing.at_risk import (
    REVIEW_STALL_DAYS,
    STAGE_BLOCKED,
    STAGE_PAST_DEADLINE,
    STAGE_SLOT_DONE,
    STAGE_WAITING_REVIEW,
)
from tickets.models import (
    StaffAssignmentSlotStatus,
    Ticket,
    TicketStaffAssignment,
    TicketStatus,
    TicketType,
)
from test_utils import TenantFixtureMixin


URL = "/api/invoices/at-risk/"


class AtRiskFixture(TenantFixtureMixin):
    def setUp(self):
        super().setUp()
        self.today = timezone.localdate()
        self.now = timezone.now()
        self.worker = self.make_user("worker-atrisk@example.com", UserRole.STAFF)

    def make_ew(self, title, *, deadline=None, preferred=None, ew_status=None):
        return ExtraWorkRequest.objects.create(
            company=self.company,
            building=self.building,
            customer=self.customer,
            created_by=self.super_admin,
            title=title,
            description="x",
            preferred_date=preferred,
            deadline=deadline,
            status=ew_status or ExtraWorkStatus.IN_PROGRESS,
        )

    def spawn(self, ew, ticket_status, **stamps):
        ticket = Ticket.objects.create(
            company=self.company,
            customer=self.customer,
            building=self.building,
            title=f"Spawned for {ew.title}",
            description="x",
            type=TicketType.REQUEST,
            status=ticket_status,
            created_by=self.super_admin,
            extra_work_request=ew,
            **stamps,
        )
        return ticket

    def make_slot(self, ticket, *, slot_status, completed_at=None):
        return TicketStaffAssignment.objects.create(
            ticket=ticket,
            user=self.worker,
            assigned_by=self.super_admin,
            slot_status=slot_status,
            completed_at=completed_at,
        )

    def get_at_risk(self, user):
        self.client.force_authenticate(user)
        response = self.client.get(URL)
        self.assertEqual(
            response.status_code, status.HTTP_200_OK, response.data
        )
        return response.data

    def rows_for(self, payload, customer_id):
        for group in payload["groups"]:
            if group["customer"] == customer_id:
                return group["rows"]
        return []


class AtRiskApiTests(AtRiskFixture, APITestCase):
    def test_4_stalled_manager_review_is_at_risk_until_confirmed(self):
        """Acceptance test 4 — deadline inside the open month, ticket
        sitting in manager review for 7+ days: listed with the review
        stage and its age; confirming the review removes it."""
        ew = self.make_ew("Gutter round", deadline=self.today)
        ticket = self.spawn(
            ew,
            TicketStatus.WAITING_MANAGER_REVIEW,
            manager_review_at=self.now - datetime.timedelta(days=8),
        )

        payload = self.get_at_risk(self.company_admin)
        rows = self.rows_for(payload, self.customer.id)
        self.assertEqual(len(rows), 1, payload)
        row = rows[0]
        self.assertEqual(row["extra_work_id"], ew.id)
        self.assertEqual(row["ticket_id"], ticket.id)
        self.assertEqual(row["stage"], STAGE_WAITING_REVIEW)
        self.assertEqual(row["age_days"], 8)
        self.assertEqual(payload["total"], 1)

        # The manager confirms: the work is handed to the customer,
        # which is the moment it becomes EARNED — the chain is whole
        # again and the guard lets go.
        ticket.status = TicketStatus.WAITING_CUSTOMER_APPROVAL
        ticket.sent_for_approval_at = self.now
        ticket.save(update_fields=["status", "sent_for_approval_at"])
        payload = self.get_at_risk(self.company_admin)
        self.assertEqual(payload["total"], 0)
        self.assertEqual(payload["groups"], [])

    def test_review_under_the_threshold_is_not_at_risk(self):
        """Review in progress is the chain WORKING. Only a stall makes
        the list."""
        ew = self.make_ew("Fresh review", deadline=self.today)
        self.spawn(
            ew,
            TicketStatus.WAITING_MANAGER_REVIEW,
            manager_review_at=self.now
            - datetime.timedelta(days=REVIEW_STALL_DAYS - 1),
        )
        payload = self.get_at_risk(self.company_admin)
        self.assertEqual(payload["total"], 0)

    def test_5_billing_month_follows_completion_with_no_auto_move(self):
        """Acceptance test 5 — planned in month M, confirmed in month
        M+1: the guard listed it while unconfirmed, lets go once earned,
        and the billing month is the Addendum B completion month — the
        guard moved nothing."""
        ew = self.make_ew("Late confirm", preferred=self.today)
        ticket = self.spawn(
            ew,
            TicketStatus.WAITING_MANAGER_REVIEW,
            manager_review_at=self.now - datetime.timedelta(days=10),
        )
        self.assertEqual(self.get_at_risk(self.company_admin)["total"], 1)

        confirmed_at = self.now + datetime.timedelta(days=35)
        ticket.status = TicketStatus.CLOSED
        ticket.closed_at = confirmed_at
        ticket.save(update_fields=["status", "closed_at"])

        self.assertEqual(self.get_at_risk(self.company_admin)["total"], 0)
        confirmed_local = timezone.localtime(confirmed_at).date()
        self.assertEqual(
            billing.billing_month(ew, ticket),
            (confirmed_local.year, confirmed_local.month),
        )
        # NO billing-month write happened: the override field is
        # untouched, so the month above is derived, not moved.
        ew.refresh_from_db()
        self.assertIsNone(ew.invoice_date)

    def test_slots_done_but_ticket_never_moved_is_at_risk(self):
        ew = self.make_ew("Forgotten completion", deadline=self.today)
        ticket = self.spawn(ew, TicketStatus.IN_PROGRESS)
        self.make_slot(
            ticket,
            slot_status=StaffAssignmentSlotStatus.COMPLETED,
            completed_at=self.now - datetime.timedelta(days=3),
        )
        payload = self.get_at_risk(self.company_admin)
        rows = self.rows_for(payload, self.customer.id)
        self.assertEqual(len(rows), 1, payload)
        self.assertEqual(rows[0]["stage"], STAGE_SLOT_DONE)
        self.assertEqual(rows[0]["age_days"], 3)

    def test_blocked_work_is_at_risk(self):
        ew = self.make_ew("Rejected execution", deadline=self.today)
        self.spawn(
            ew,
            TicketStatus.REJECTED,
            rejected_at=self.now - datetime.timedelta(days=5),
        )
        payload = self.get_at_risk(self.company_admin)
        rows = self.rows_for(payload, self.customer.id)
        self.assertEqual(len(rows), 1, payload)
        self.assertEqual(rows[0]["stage"], STAGE_BLOCKED)
        self.assertEqual(rows[0]["age_days"], 5)

    def test_execution_past_its_deadline_is_at_risk(self):
        ew = self.make_ew(
            "Slow execution",
            deadline=self.today - datetime.timedelta(days=2),
        )
        ticket = self.spawn(ew, TicketStatus.IN_PROGRESS)
        self.make_slot(
            ticket, slot_status=StaffAssignmentSlotStatus.ASSIGNED
        )
        payload = self.get_at_risk(self.company_admin)
        rows = self.rows_for(payload, self.customer.id)
        self.assertEqual(len(rows), 1, payload)
        self.assertEqual(rows[0]["stage"], STAGE_PAST_DEADLINE)
        self.assertEqual(rows[0]["age_days"], 2)

    def test_work_tied_to_a_future_month_is_not_yet_at_risk(self):
        """The guard watches the OPEN billing month and everything
        before it — never ahead."""
        ew = self.make_ew(
            "Next month's job",
            deadline=self.today + datetime.timedelta(days=40),
        )
        self.spawn(
            ew,
            TicketStatus.WAITING_MANAGER_REVIEW,
            manager_review_at=self.now - datetime.timedelta(days=10),
        )
        payload = self.get_at_risk(self.company_admin)
        self.assertEqual(payload["total"], 0)

    def test_cancelled_and_rejected_requests_are_not_at_risk(self):
        for ew_status in (
            ExtraWorkStatus.CANCELLED,
            ExtraWorkStatus.CUSTOMER_REJECTED,
        ):
            with self.subTest(status=ew_status):
                ew = self.make_ew(
                    f"Called off {ew_status}",
                    deadline=self.today - datetime.timedelta(days=1),
                    ew_status=ew_status,
                )
                self.spawn(ew, TicketStatus.REJECTED)
        payload = self.get_at_risk(self.company_admin)
        self.assertEqual(payload["total"], 0)

    def test_the_gate_refuses_non_operators(self):
        for user in (self.customer_user, self.worker):
            with self.subTest(user=user.email):
                self.client.force_authenticate(user)
                response = self.client.get(URL)
                self.assertEqual(
                    response.status_code, status.HTTP_403_FORBIDDEN
                )

    def test_no_tenant_crosses(self):
        """H-1 — a company admin sees only their own customers' risk."""
        ew = self.make_ew("Mine at risk", deadline=self.today)
        self.spawn(
            ew,
            TicketStatus.WAITING_MANAGER_REVIEW,
            manager_review_at=self.now - datetime.timedelta(days=9),
        )
        payload = self.get_at_risk(self.other_company_admin)
        self.assertEqual(payload["total"], 0)
        self.assertEqual(payload["groups"], [])

    def test_the_envelope_names_the_open_period_and_its_bound(self):
        payload = self.get_at_risk(self.company_admin)
        self.assertEqual(
            set(payload),
            {
                "period_year",
                "period_month",
                "total",
                "limit",
                "truncated",
                "groups",
            },
        )
        self.assertEqual(payload["period_year"], self.today.year)
        self.assertEqual(payload["period_month"], self.today.month)
        self.assertFalse(payload["truncated"])
