"""
Sprint 7 — bulk manager-confirm endpoint (POST /api/tickets/bulk-status/).

"The select button": provider management advances many tickets sitting
in WAITING_MANAGER_REVIEW to WAITING_CUSTOMER_APPROVAL in one call.

What this file locks:

  * Provider-management gate — CUSTOMER_USER and STAFF get 403 outright;
    only SUPER_ADMIN / COMPANY_ADMIN / BUILDING_MANAGER may call it.
  * PER-ITEM semantics (NOT all-or-nothing): each ticket transitions in
    its own transaction via the existing `apply_transition`, so a
    wrong-state item or an out-of-scope item fails individually while
    valid items still advance — each writing a TicketStatusHistory row.
  * No duplication of state-machine logic — out-of-building / cross-
    company items are rejected by the same scope rules the single-status
    action uses (they never even resolve through the scoped queryset).
  * Notification parity — exactly one send_ticket_status_changed_email
    per SUCCESSFULLY transitioned ticket, none for failures.
  * Request-envelope validation — empty / oversized / wrong-target /
    duplicate ids.
"""
from __future__ import annotations

from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework import status
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
from tickets.models import Ticket, TicketStatus, TicketStatusHistory


User = get_user_model()
PASSWORD = "StrongerTestPassword123!"
BULK_URL = "/api/tickets/bulk-status/"
EMAIL_PATH = "tickets.views.send_ticket_status_changed_email"


def _mk(email, role, **extra):
    return User.objects.create_user(
        email=email,
        password=PASSWORD,
        role=role,
        full_name=email.split("@")[0],
        **extra,
    )


def _ticket(*, company, building, customer, created_by, status_value):
    return Ticket.objects.create(
        company=company,
        building=building,
        customer=customer,
        created_by=created_by,
        title="Work item",
        description="x",
        status=status_value,
    )


def _seed():
    """
    Provider company A + building B1 + customer + a BM assigned to B1 +
    a CUSTOMER_USER with (customer, B1) access. A second building B2 in
    the SAME company (no BM assignment) and a second company B with its
    own building/customer give the out-of-scope fixtures.
    """
    company = Company.objects.create(name="Provider Co", slug="provider-co")
    b1 = Building.objects.create(company=company, name="B1")
    b2 = Building.objects.create(company=company, name="B2")
    customer = Customer.objects.create(
        company=company, name="Cust A", building=b1
    )
    CustomerBuildingMembership.objects.create(customer=customer, building=b1)
    CustomerBuildingMembership.objects.create(customer=customer, building=b2)

    bm = _mk("bm@example.com", UserRole.BUILDING_MANAGER)
    BuildingManagerAssignment.objects.create(user=bm, building=b1)

    cust_user = _mk("cust@example.com", UserRole.CUSTOMER_USER)
    membership = CustomerUserMembership.objects.create(
        user=cust_user, customer=customer
    )
    CustomerUserBuildingAccess.objects.create(
        membership=membership, building=b1
    )

    # Second company, fully isolated.
    other_company = Company.objects.create(name="Rival Co", slug="rival-co")
    ob = Building.objects.create(company=other_company, name="OB")
    other_customer = Customer.objects.create(
        company=other_company, name="Cust B", building=ob
    )
    CustomerBuildingMembership.objects.create(
        customer=other_customer, building=ob
    )

    return {
        "company": company,
        "b1": b1,
        "b2": b2,
        "customer": customer,
        "bm": bm,
        "cust_user": cust_user,
        "other_company": other_company,
        "ob": ob,
        "other_customer": other_customer,
    }


class BulkManagerConfirmHappyPathTests(TestCase):
    """All-success batch driven by an in-scope BUILDING_MANAGER."""

    @classmethod
    def setUpTestData(cls):
        cls.s = _seed()

    def setUp(self):
        s = self.s
        self.tickets = [
            _ticket(
                company=s["company"],
                building=s["b1"],
                customer=s["customer"],
                created_by=s["cust_user"],
                status_value=TicketStatus.WAITING_MANAGER_REVIEW,
            )
            for _ in range(3)
        ]
        self.client = APIClient()
        self.client.force_authenticate(user=s["bm"])

    def test_all_advance_with_history_and_notifications(self):
        ids = [t.id for t in self.tickets]
        with patch(EMAIL_PATH) as mocked_email:
            response = self.client.post(
                BULK_URL,
                {
                    "ticket_ids": ids,
                    "to_status": "WAITING_CUSTOMER_APPROVAL",
                    "note": "Looks good, sending to the customer.",
                },
                format="json",
            )
        self.assertEqual(
            response.status_code, status.HTTP_200_OK, response.content
        )
        body = response.json()
        self.assertEqual(body["succeeded"], 3)
        self.assertEqual(body["failed"], 0)
        self.assertEqual(len(body["results"]), 3)
        self.assertTrue(all(r["ok"] for r in body["results"]))
        # Result order mirrors the request id order.
        self.assertEqual([r["id"] for r in body["results"]], ids)

        for ticket in self.tickets:
            ticket.refresh_from_db()
            self.assertEqual(
                ticket.status, TicketStatus.WAITING_CUSTOMER_APPROVAL
            )
            self.assertIsNotNone(ticket.sent_for_approval_at)
            history = TicketStatusHistory.objects.filter(
                ticket=ticket,
                old_status=TicketStatus.WAITING_MANAGER_REVIEW,
                new_status=TicketStatus.WAITING_CUSTOMER_APPROVAL,
            )
            self.assertEqual(history.count(), 1)
            self.assertEqual(history.first().changed_by_id, self.s["bm"].id)
            self.assertEqual(history.first().note, "Looks good, sending to the customer.")

        # Notification parity: one email per successfully advanced ticket.
        self.assertEqual(mocked_email.call_count, 3)
        for call in mocked_email.call_args_list:
            self.assertEqual(
                call.kwargs["old_status"], TicketStatus.WAITING_MANAGER_REVIEW
            )
            self.assertEqual(
                call.kwargs["new_status"], TicketStatus.WAITING_CUSTOMER_APPROVAL
            )
            self.assertEqual(call.kwargs["actor"].id, self.s["bm"].id)

    def test_company_admin_can_drive_bulk_confirm(self):
        ca = _mk("ca@example.com", UserRole.COMPANY_ADMIN)
        CompanyUserMembership.objects.create(user=ca, company=self.s["company"])
        client = APIClient()
        client.force_authenticate(user=ca)
        with patch(EMAIL_PATH):
            response = client.post(
                BULK_URL,
                {
                    "ticket_ids": [self.tickets[0].id],
                    "to_status": "WAITING_CUSTOMER_APPROVAL",
                },
                format="json",
            )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["succeeded"], 1)


class BulkManagerConfirmPerItemTests(TestCase):
    """Mixed batches prove per-item, not all-or-nothing, semantics."""

    @classmethod
    def setUpTestData(cls):
        cls.s = _seed()

    def setUp(self):
        self.client = APIClient()

    def _valid_ticket(self):
        s = self.s
        return _ticket(
            company=s["company"],
            building=s["b1"],
            customer=s["customer"],
            created_by=s["cust_user"],
            status_value=TicketStatus.WAITING_MANAGER_REVIEW,
        )

    def test_wrong_state_items_fail_valid_items_succeed(self):
        s = self.s
        good = self._valid_ticket()
        # OPEN -> WAITING_CUSTOMER_APPROVAL is not an allowed transition.
        wrong_state = _ticket(
            company=s["company"],
            building=s["b1"],
            customer=s["customer"],
            created_by=s["cust_user"],
            status_value=TicketStatus.OPEN,
        )
        self.client.force_authenticate(user=s["bm"])
        with patch(EMAIL_PATH) as mocked_email:
            response = self.client.post(
                BULK_URL,
                {
                    "ticket_ids": [good.id, wrong_state.id],
                    "to_status": "WAITING_CUSTOMER_APPROVAL",
                },
                format="json",
            )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        body = response.json()
        self.assertEqual(body["succeeded"], 1)
        self.assertEqual(body["failed"], 1)
        by_id = {r["id"]: r for r in body["results"]}
        self.assertTrue(by_id[good.id]["ok"])
        self.assertFalse(by_id[wrong_state.id]["ok"])
        # Sprint 7 (Codex P2) — the explicit source-status guard fires
        # before apply_transition, so an OPEN ticket is rejected with
        # `not_in_review` rather than the state machine's
        # `forbidden_transition`.
        self.assertEqual(by_id[wrong_state.id]["error"], "not_in_review")

        good.refresh_from_db()
        wrong_state.refresh_from_db()
        self.assertEqual(good.status, TicketStatus.WAITING_CUSTOMER_APPROVAL)
        # The failed item is untouched — its own transaction rolled back.
        self.assertEqual(wrong_state.status, TicketStatus.OPEN)
        # Notification only for the success.
        self.assertEqual(mocked_email.call_count, 1)

    def test_out_of_scope_item_for_company_admin_fails_in_scope_succeeds(self):
        s = self.s
        in_scope = self._valid_ticket()
        # Cross-company ticket: invisible to a company-A admin.
        cross = _ticket(
            company=s["other_company"],
            building=s["ob"],
            customer=s["other_customer"],
            created_by=s["cust_user"],
            status_value=TicketStatus.WAITING_MANAGER_REVIEW,
        )
        ca = _mk("ca2@example.com", UserRole.COMPANY_ADMIN)
        CompanyUserMembership.objects.create(user=ca, company=s["company"])
        self.client.force_authenticate(user=ca)
        with patch(EMAIL_PATH) as mocked_email:
            response = self.client.post(
                BULK_URL,
                {
                    "ticket_ids": [in_scope.id, cross.id],
                    "to_status": "WAITING_CUSTOMER_APPROVAL",
                },
                format="json",
            )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        body = response.json()
        self.assertEqual(body["succeeded"], 1)
        self.assertEqual(body["failed"], 1)
        by_id = {r["id"]: r for r in body["results"]}
        self.assertTrue(by_id[in_scope.id]["ok"])
        self.assertFalse(by_id[cross.id]["ok"])
        self.assertEqual(by_id[cross.id]["error"], "not_found")

        in_scope.refresh_from_db()
        cross.refresh_from_db()
        self.assertEqual(in_scope.status, TicketStatus.WAITING_CUSTOMER_APPROVAL)
        # The cross-company ticket never moved.
        self.assertEqual(cross.status, TicketStatus.WAITING_MANAGER_REVIEW)
        self.assertEqual(mocked_email.call_count, 1)

    def test_bm_out_of_building_scope_cannot_advance(self):
        s = self.s
        in_scope = self._valid_ticket()  # B1 — assigned
        # B2 (same company) — the BM is NOT assigned here.
        out_of_building = _ticket(
            company=s["company"],
            building=s["b2"],
            customer=s["customer"],
            created_by=s["cust_user"],
            status_value=TicketStatus.WAITING_MANAGER_REVIEW,
        )
        self.client.force_authenticate(user=s["bm"])
        with patch(EMAIL_PATH) as mocked_email:
            response = self.client.post(
                BULK_URL,
                {
                    "ticket_ids": [in_scope.id, out_of_building.id],
                    "to_status": "WAITING_CUSTOMER_APPROVAL",
                },
                format="json",
            )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        body = response.json()
        self.assertEqual(body["succeeded"], 1)
        self.assertEqual(body["failed"], 1)
        by_id = {r["id"]: r for r in body["results"]}
        self.assertTrue(by_id[in_scope.id]["ok"])
        self.assertFalse(by_id[out_of_building.id]["ok"])
        self.assertEqual(by_id[out_of_building.id]["error"], "not_found")

        out_of_building.refresh_from_db()
        self.assertEqual(
            out_of_building.status, TicketStatus.WAITING_MANAGER_REVIEW
        )
        self.assertEqual(mocked_email.call_count, 1)

    def test_super_admin_wrong_state_items_blocked(self):
        # Sprint 7 (Codex P2) — a SUPER_ADMIN's can_transition allows ANY
        # source status, so without the explicit source-status guard the
        # endpoint would advance OPEN/CLOSED tickets too. This proves the
        # override hole is closed: only the WAITING_MANAGER_REVIEW item
        # advances; OPEN and CLOSED are per-item `not_in_review` failures.
        review = self._valid_ticket()
        open_ticket = _ticket(
            company=self.s["company"],
            building=self.s["b1"],
            customer=self.s["customer"],
            created_by=self.s["cust_user"],
            status_value=TicketStatus.OPEN,
        )
        closed_ticket = _ticket(
            company=self.s["company"],
            building=self.s["b1"],
            customer=self.s["customer"],
            created_by=self.s["cust_user"],
            status_value=TicketStatus.CLOSED,
        )
        sa = _mk("sa-block@example.com", UserRole.SUPER_ADMIN)
        self.client.force_authenticate(user=sa)
        with patch(EMAIL_PATH) as mocked_email:
            response = self.client.post(
                BULK_URL,
                {
                    "ticket_ids": [review.id, open_ticket.id, closed_ticket.id],
                    "to_status": "WAITING_CUSTOMER_APPROVAL",
                },
                format="json",
            )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        body = response.json()
        self.assertEqual(body["succeeded"], 1)
        self.assertEqual(body["failed"], 2)
        by_id = {r["id"]: r for r in body["results"]}
        self.assertTrue(by_id[review.id]["ok"])
        self.assertFalse(by_id[open_ticket.id]["ok"])
        self.assertFalse(by_id[closed_ticket.id]["ok"])
        self.assertEqual(by_id[open_ticket.id]["error"], "not_in_review")
        self.assertEqual(by_id[closed_ticket.id]["error"], "not_in_review")

        review.refresh_from_db()
        open_ticket.refresh_from_db()
        closed_ticket.refresh_from_db()
        self.assertEqual(review.status, TicketStatus.WAITING_CUSTOMER_APPROVAL)
        # The wrong-state tickets are untouched.
        self.assertEqual(open_ticket.status, TicketStatus.OPEN)
        self.assertEqual(closed_ticket.status, TicketStatus.CLOSED)
        self.assertEqual(mocked_email.call_count, 1)

    def test_in_progress_ticket_not_advanced(self):
        # Sprint 7 (Codex P2) — every provider role can drive the direct
        # IN_PROGRESS -> WAITING_CUSTOMER_APPROVAL completion leg via the
        # single-status endpoint. The bulk endpoint must NOT expose it:
        # the source-status guard rejects an IN_PROGRESS ticket as
        # `not_in_review`, leaving it untouched.
        review = self._valid_ticket()
        in_progress = _ticket(
            company=self.s["company"],
            building=self.s["b1"],
            customer=self.s["customer"],
            created_by=self.s["cust_user"],
            status_value=TicketStatus.IN_PROGRESS,
        )
        sa = _mk("sa-inprog@example.com", UserRole.SUPER_ADMIN)
        self.client.force_authenticate(user=sa)
        with patch(EMAIL_PATH) as mocked_email:
            response = self.client.post(
                BULK_URL,
                {
                    "ticket_ids": [review.id, in_progress.id],
                    "to_status": "WAITING_CUSTOMER_APPROVAL",
                },
                format="json",
            )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        body = response.json()
        self.assertEqual(body["succeeded"], 1)
        self.assertEqual(body["failed"], 1)
        by_id = {r["id"]: r for r in body["results"]}
        self.assertTrue(by_id[review.id]["ok"])
        self.assertFalse(by_id[in_progress.id]["ok"])
        self.assertEqual(by_id[in_progress.id]["error"], "not_in_review")

        in_progress.refresh_from_db()
        self.assertEqual(in_progress.status, TicketStatus.IN_PROGRESS)
        self.assertEqual(mocked_email.call_count, 1)


class BulkManagerConfirmGateTests(TestCase):
    """The endpoint-level provider-management gate."""

    @classmethod
    def setUpTestData(cls):
        cls.s = _seed()

    def setUp(self):
        s = self.s
        self.ticket = _ticket(
            company=s["company"],
            building=s["b1"],
            customer=s["customer"],
            created_by=s["cust_user"],
            status_value=TicketStatus.WAITING_MANAGER_REVIEW,
        )
        self.client = APIClient()

    def _post(self):
        return self.client.post(
            BULK_URL,
            {
                "ticket_ids": [self.ticket.id],
                "to_status": "WAITING_CUSTOMER_APPROVAL",
            },
            format="json",
        )

    def test_customer_user_is_forbidden(self):
        self.client.force_authenticate(user=self.s["cust_user"])
        with patch(EMAIL_PATH) as mocked_email:
            response = self._post()
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.ticket.refresh_from_db()
        self.assertEqual(self.ticket.status, TicketStatus.WAITING_MANAGER_REVIEW)
        mocked_email.assert_not_called()

    def test_staff_is_forbidden(self):
        staff = _mk("staff@example.com", UserRole.STAFF)
        self.client.force_authenticate(user=staff)
        with patch(EMAIL_PATH) as mocked_email:
            response = self._post()
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.ticket.refresh_from_db()
        self.assertEqual(self.ticket.status, TicketStatus.WAITING_MANAGER_REVIEW)
        mocked_email.assert_not_called()


class BulkManagerConfirmEnvelopeTests(TestCase):
    """Request-shape validation handled by the input serializer."""

    @classmethod
    def setUpTestData(cls):
        cls.s = _seed()

    def setUp(self):
        self.client = APIClient()
        self.client.force_authenticate(user=self.s["bm"])

    def _ids(self, n):
        s = self.s
        return [
            _ticket(
                company=s["company"],
                building=s["b1"],
                customer=s["customer"],
                created_by=s["cust_user"],
                status_value=TicketStatus.WAITING_MANAGER_REVIEW,
            ).id
            for _ in range(n)
        ]

    def test_empty_ticket_ids_is_rejected(self):
        response = self.client.post(
            BULK_URL,
            {"ticket_ids": [], "to_status": "WAITING_CUSTOMER_APPROVAL"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_oversized_batch_is_rejected(self):
        # 201 ids exceeds the cap of 200 — rejected at the envelope layer.
        response = self.client.post(
            BULK_URL,
            {
                "ticket_ids": list(range(1, 202)),
                "to_status": "WAITING_CUSTOMER_APPROVAL",
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_disallowed_target_status_is_rejected(self):
        ids = self._ids(1)
        response = self.client.post(
            BULK_URL,
            {"ticket_ids": ids, "to_status": "APPROVED"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_duplicate_ids_are_deduped(self):
        ids = self._ids(1)
        with patch(EMAIL_PATH) as mocked_email:
            response = self.client.post(
                BULK_URL,
                {
                    "ticket_ids": [ids[0], ids[0], ids[0]],
                    "to_status": "WAITING_CUSTOMER_APPROVAL",
                },
                format="json",
            )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        body = response.json()
        # Deduped to a single processed item — exactly one transition.
        self.assertEqual(len(body["results"]), 1)
        self.assertEqual(body["succeeded"], 1)
        self.assertEqual(mocked_email.call_count, 1)
