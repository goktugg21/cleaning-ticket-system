"""Sprint W1-B item 14 — the billing cutoff arm of `is_earned`.

The owner's case is the first test: billing date 30 August, work
completed 29 August, customer approves 4 September. Before this sprint
the August run found nothing; September billed August's work.

The single most important test in the module is
`test_waiting_manager_review_is_never_earned`. WAITING_MANAGER_REVIEW is
staff saying "done" with nobody having checked it, and billing it would
bill unverified work.
"""
from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from customers.models import Customer
from extra_work.billing import billing_month, earned_at, is_billable, is_earned
from extra_work.models import ExtraWorkRequest, ExtraWorkStatus
from invoicing.selectors import unbilled_extra_work
from test_utils import TenantFixtureMixin
from tickets.models import Ticket, TicketStatus


def _aug(day, hour=12):
    """Noon Europe/Amsterdam on a day in August 2026, as an aware UTC dt."""
    return timezone.make_aware(
        timezone.datetime(2026, 8, day, hour, 0), timezone.get_current_timezone()
    )


class BillingCutoffEarnedTests(TenantFixtureMixin, TestCase):
    def _ew_with_ticket(self, *, status, sent_for_approval_at=None, closed_at=None):
        ew = ExtraWorkRequest.objects.create(
            company=self.company,
            building=self.building,
            customer=self.customer,
            created_by=self.company_admin,
            title="Trapportaal reinigen",
            description="customer-visible description",
            status=ExtraWorkStatus.CUSTOMER_APPROVED,
            subtotal_amount=Decimal("100.00"),
            vat_amount=Decimal("21.00"),
            total_amount=Decimal("121.00"),
        )
        ticket = Ticket.objects.create(
            company=self.company,
            building=self.building,
            customer=self.customer,
            created_by=self.company_admin,
            title="Spawned operational ticket",
            description="op ticket",
            status=status,
            extra_work_request=ew,
        )
        # Written straight to the column: the point under test is what
        # `is_earned` reads, not how the state machine stamps it (that is
        # `tickets.tests.test_state_machine`'s job).
        Ticket.objects.filter(pk=ticket.pk).update(
            sent_for_approval_at=sent_for_approval_at, closed_at=closed_at
        )
        return ew, Ticket.objects.get(pk=ticket.pk)

    # -- the owner's case -------------------------------------------------

    def test_owner_case_completed_29_august_bills_in_august(self):
        """Billing date 30-08, completed 29-08, approval still pending."""
        self.customer.invoice_day_of_month = 30
        self.customer.save(update_fields=["invoice_day_of_month"])
        ew, ticket = self._ew_with_ticket(
            status=TicketStatus.WAITING_CUSTOMER_APPROVAL,
            sent_for_approval_at=_aug(29),
        )
        self.assertTrue(is_earned(ticket))
        self.assertTrue(is_billable(ew, ticket))
        self.assertEqual(billing_month(ew, ticket), (2026, 8))

        # The pool the 30-08 run reads.
        pool = unbilled_extra_work(
            self.company_admin, self.company.id, self.customer.id, 2026, 8
        )
        self.assertIn(ew.id, [e.id for e in pool])

    def test_before_this_sprint_it_would_have_missed_september_instead(self):
        """The same row must NOT also answer to September."""
        ew, ticket = self._ew_with_ticket(
            status=TicketStatus.WAITING_CUSTOMER_APPROVAL,
            sent_for_approval_at=_aug(29),
        )
        pool = unbilled_extra_work(
            self.company_admin, self.company.id, self.customer.id, 2026, 9
        )
        self.assertNotIn(ew.id, [e.id for e in pool])

    # -- the guard --------------------------------------------------------

    def test_waiting_manager_review_is_never_earned(self):
        """Staff said done; nobody checked. Never billable, whatever the
        timestamps say."""
        ew, ticket = self._ew_with_ticket(
            status=TicketStatus.WAITING_MANAGER_REVIEW,
            # Even with the customer-approval stamp present — a leftover
            # from an earlier loop through the states — this must not
            # qualify. The status is the gate, not the column.
            sent_for_approval_at=_aug(29),
        )
        self.assertFalse(is_earned(ticket))
        self.assertFalse(is_billable(ew, ticket))
        pool = unbilled_extra_work(
            self.company_admin, self.company.id, self.customer.id, 2026, 8
        )
        self.assertNotIn(ew.id, [e.id for e in pool])

    def test_in_progress_is_not_earned(self):
        ew, ticket = self._ew_with_ticket(status=TicketStatus.IN_PROGRESS)
        self.assertFalse(is_earned(ticket))

    def test_waiting_customer_approval_without_the_stamp_is_not_earned(self):
        """A NULL `sent_for_approval_at` is a row that never went through
        the transition — there is no date to bill it against."""
        ew, ticket = self._ew_with_ticket(
            status=TicketStatus.WAITING_CUSTOMER_APPROVAL,
            sent_for_approval_at=None,
        )
        self.assertFalse(is_earned(ticket))
        self.assertIsNone(billing_month(ew, ticket))

    # -- the original arm is untouched ------------------------------------

    def test_closed_is_still_earned_on_status_alone(self):
        ew, ticket = self._ew_with_ticket(
            status=TicketStatus.CLOSED, closed_at=None
        )
        self.assertTrue(is_earned(ticket))
        # ...and still unresolvable for a month, exactly as before.
        self.assertIsNone(billing_month(ew, ticket))

    def test_closed_bills_on_closed_at(self):
        ew, ticket = self._ew_with_ticket(
            status=TicketStatus.CLOSED, closed_at=_aug(29)
        )
        self.assertEqual(billing_month(ew, ticket), (2026, 8))
        self.assertEqual(earned_at(ticket), ticket.closed_at)

    def test_invoice_date_still_wins_over_the_cutoff_arm(self):
        ew, ticket = self._ew_with_ticket(
            status=TicketStatus.WAITING_CUSTOMER_APPROVAL,
            sent_for_approval_at=_aug(29),
        )
        ew.invoice_date = date(2026, 7, 15)
        ew.save(update_fields=["invoice_date"])
        self.assertEqual(billing_month(ew, ticket), (2026, 7))

    def test_reopen_loop_prefers_the_new_hand_off_not_the_stale_close(self):
        """A ticket closed in July, reopened, and re-sent to the customer
        in August bills in AUGUST — the stale `closed_at` must not win."""
        ew, ticket = self._ew_with_ticket(
            status=TicketStatus.WAITING_CUSTOMER_APPROVAL,
            sent_for_approval_at=_aug(29),
            closed_at=timezone.make_aware(
                timezone.datetime(2026, 7, 3, 12, 0),
                timezone.get_current_timezone(),
            ),
        )
        self.assertEqual(billing_month(ew, ticket), (2026, 8))

    # -- a cancelled row stays out ----------------------------------------

    def test_cancelled_extra_work_is_not_billable_under_the_new_arm(self):
        ew, ticket = self._ew_with_ticket(
            status=TicketStatus.WAITING_CUSTOMER_APPROVAL,
            sent_for_approval_at=_aug(29),
        )
        ew.status = ExtraWorkStatus.CANCELLED
        ew.save(update_fields=["status"])
        self.assertTrue(is_earned(ticket))
        self.assertFalse(is_billable(ew, ticket))

    # -- tenant scoping ---------------------------------------------------

    def test_cutoff_arm_does_not_leak_across_tenants(self):
        """Company B's admin must not see Company A's newly-earned row."""
        ew, _ = self._ew_with_ticket(
            status=TicketStatus.WAITING_CUSTOMER_APPROVAL,
            sent_for_approval_at=_aug(29),
        )
        pool = unbilled_extra_work(
            self.other_company_admin, self.company.id, self.customer.id, 2026, 8
        )
        self.assertEqual([e.id for e in pool], [])


class ReportsEarnedParityTests(TenantFixtureMixin, TestCase):
    """`reports.dimensions` must classify EXACTLY what billing bills."""

    def test_classifier_calls_is_earned(self):
        from reports.dimensions import _classify_extra_work

        ew = ExtraWorkRequest.objects.create(
            company=self.company,
            building=self.building,
            customer=self.customer,
            created_by=self.company_admin,
            title="Parity",
            description="customer-visible description",
            status=ExtraWorkStatus.CUSTOMER_APPROVED,
            subtotal_amount=Decimal("10.00"),
            vat_amount=Decimal("2.10"),
            total_amount=Decimal("12.10"),
        )
        ticket = Ticket.objects.create(
            company=self.company,
            building=self.building,
            customer=self.customer,
            created_by=self.company_admin,
            title="Spawned",
            description="op",
            status=TicketStatus.WAITING_CUSTOMER_APPROVAL,
            extra_work_request=ew,
        )
        Ticket.objects.filter(pk=ticket.pk).update(sent_for_approval_at=_aug(29))
        ticket.refresh_from_db()
        self.assertTrue(is_earned(ticket))
        self.assertEqual(_classify_extra_work(ew, ticket), "earned")

    def test_manager_review_classifies_in_progress_not_earned(self):
        from reports.dimensions import _classify_extra_work

        ew = ExtraWorkRequest.objects.create(
            company=self.company,
            building=self.building,
            customer=self.customer,
            created_by=self.company_admin,
            title="Parity 2",
            description="customer-visible description",
            status=ExtraWorkStatus.CUSTOMER_APPROVED,
            subtotal_amount=Decimal("10.00"),
            vat_amount=Decimal("2.10"),
            total_amount=Decimal("12.10"),
        )
        ticket = Ticket.objects.create(
            company=self.company,
            building=self.building,
            customer=self.customer,
            created_by=self.company_admin,
            title="Spawned",
            description="op",
            status=TicketStatus.WAITING_MANAGER_REVIEW,
            extra_work_request=ew,
        )
        self.assertEqual(_classify_extra_work(ew, ticket), "in_progress")
