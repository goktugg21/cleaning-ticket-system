"""P-13 C — archive can never hide money.

The owner's worry, probed door by door (C1) and closed where a door
existed (C2):

  * ARCHIVE does not move money: `archived_at` lives on the ticket and
    no billing code reads it — an archived job's extra work stays in
    the unbilled pool. Pinned so a future "clean up the pool" change
    cannot quietly start reading it.
  * DELETE has no door: the extra-work API exposes no destroy, and the
    ticket API refuses to soft-delete an EW-born ticket.
  * CANCEL is the one way out, and it is no longer silent: whatever
    the from-status, cancelling a request with an earned-but-unbilled
    amount without a reason is refused with the amount in the message
    (`cancel_unbilled_requires_reason`); with a reason it is coerced
    onto the override surface, so the history row logs who/why.
  * A request with NO money keeps its old, frictionless cancels.
"""
from __future__ import annotations

from django.utils import timezone

from rest_framework.test import APIClient

from extra_work.models import (
    ExtraWorkRequest,
    ExtraWorkStatus,
    ExtraWorkStatusHistory,
)
from extra_work.state_machine import TransitionError, apply_transition
from invoicing.selectors import unbilled_extra_work_through
from tickets.models import Ticket, TicketStatus

from ._helpers import InvoicingFixture


class ArchiveNeverHidesMoneyTests(InvoicingFixture):
    def _pool_ids(self):
        today = timezone.localdate()
        return {
            ew.id
            for ew in unbilled_extra_work_through(
                self.admin,
                self.company.id,
                self.customer.id,
                today.year,
                today.month,
            )
        }

    def test_archiving_the_ticket_keeps_the_money_in_the_pool(self):
        ew = self.make_ew()
        self.assertIn(ew.id, self._pool_ids())

        ticket = Ticket.objects.get(extra_work_request=ew)
        ticket.archived_at = timezone.now()
        ticket.archived_by = self.admin
        ticket.save(update_fields=["archived_at", "archived_by"])

        self.assertIn(ew.id, self._pool_ids())

    def test_deleting_an_ew_born_ticket_is_refused(self):
        ew = self.make_ew()
        ticket = Ticket.objects.get(extra_work_request=ew)
        client = APIClient()
        client.force_authenticate(user=self.admin)
        resp = client.delete(f"/api/tickets/{ticket.id}/")
        self.assertEqual(resp.status_code, 400, resp.data)
        self.assertEqual(
            resp.data.get("code"), "extra_work_ticket_not_deletable"
        )
        ticket.refresh_from_db()
        self.assertIsNone(ticket.deleted_at)

    def test_cancel_without_reason_is_refused_with_the_amount(self):
        # The quiet door: an EW still at UNDER_REVIEW whose ticket ran
        # to CLOSED — no override coercion applied here before P-13.
        ew = self.make_ew()
        ew.status = ExtraWorkStatus.UNDER_REVIEW
        ew.save(update_fields=["status"])

        with self.assertRaises(TransitionError) as caught:
            apply_transition(ew, self.admin, ExtraWorkStatus.CANCELLED)
        self.assertEqual(
            caught.exception.code, "cancel_unbilled_requires_reason"
        )
        self.assertIn("121.00", str(caught.exception))
        ew.refresh_from_db()
        self.assertEqual(ew.status, ExtraWorkStatus.UNDER_REVIEW)
        self.assertIn(ew.id, self._pool_ids())

    def test_cancel_with_reason_leaves_the_pool_and_is_logged(self):
        ew = self.make_ew()
        ew.status = ExtraWorkStatus.UNDER_REVIEW
        ew.save(update_fields=["status"])

        apply_transition(
            ew,
            self.admin,
            ExtraWorkStatus.CANCELLED,
            override_reason="Customer withdrew after completion",
        )
        ew.refresh_from_db()
        self.assertEqual(ew.status, ExtraWorkStatus.CANCELLED)
        self.assertNotIn(ew.id, self._pool_ids())

        row = (
            ExtraWorkStatusHistory.objects.filter(
                extra_work=ew, new_status=ExtraWorkStatus.CANCELLED
            )
            .order_by("-id")
            .first()
        )
        self.assertIsNotNone(row)
        self.assertTrue(row.is_override)
        self.assertEqual(ew.override_reason, "Customer withdrew after completion")
        self.assertEqual(ew.override_by_id, self.admin.id)

    def test_ticket_detail_carries_the_money_fact_for_providers(self):
        """P-13 C/D — the archive confirm and the Done banner read
        `extra_work_billing` off the ticket: the unbilled amount and
        the customer's billing day; null once a live invoice claims
        the work."""
        self.customer.invoice_day_of_month = 1
        self.customer.save(update_fields=["invoice_day_of_month"])
        ew = self.make_ew()
        ticket = Ticket.objects.get(extra_work_request=ew)
        client = APIClient()
        client.force_authenticate(user=self.admin)

        resp = client.get(f"/api/tickets/{ticket.id}/")
        self.assertEqual(resp.status_code, 200, resp.data)
        self.assertEqual(
            resp.data["extra_work_billing"],
            {
                "unbilled_total": "121.00",
                "customer_name": self.customer.name,
                "customer_invoice_day": 1,
            },
        )

        self.claim_with_invoice(ew)
        resp = client.get(f"/api/tickets/{ticket.id}/")
        self.assertIsNone(resp.data["extra_work_billing"])

    def test_a_moneyless_request_keeps_its_frictionless_cancel(self):
        ew = ExtraWorkRequest.objects.create(
            company=self.company,
            building=self.building,
            customer=self.customer,
            created_by=self.customer_user,
            title="Nothing earned yet",
            description="d",
            status=ExtraWorkStatus.REQUESTED,
        )
        apply_transition(ew, self.customer_user, ExtraWorkStatus.CANCELLED)
        ew.refresh_from_db()
        self.assertEqual(ew.status, ExtraWorkStatus.CANCELLED)

    def test_an_invoiced_request_is_not_this_guards_business(self):
        # Already claimed by a live invoice: the claim predicate (not
        # this guard) owns that story. Cancel still needs whatever the
        # pair itself demands, but not the money message.
        ew = self.make_ew()
        ew.status = ExtraWorkStatus.UNDER_REVIEW
        ew.save(update_fields=["status"])
        self.claim_with_invoice(ew)
        apply_transition(ew, self.admin, ExtraWorkStatus.CANCELLED)
        ew.refresh_from_db()
        self.assertEqual(ew.status, ExtraWorkStatus.CANCELLED)
