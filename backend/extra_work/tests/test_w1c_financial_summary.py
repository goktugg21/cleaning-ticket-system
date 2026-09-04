"""W1-C — the Extra Work money strip's aggregate.

`GET /api/extra-work/financial-summary/` returns FOUR figures
(`docs/planning/ew-gap-closing-plan.md` §2.4). What is worth testing
about it is not the arithmetic — the arithmetic is
`reports.dimensions._amounts_for_state`, which has its own tests — but
the four things that could make it lie:

  * the buckets (which row lands in which figure, and that figure 4 is a
    SUBSET of figure 3);
  * tenancy (a company admin sees their company and nothing else) and
    the role gate;
  * that the SQL narrowing loses no row, checked against a brute-force
    walk of everything in scope;
  * that the query count is constant, so an N+1 cannot creep in behind
    a passing assertion.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from django.test import TestCase
from rest_framework import status

from accounts.models import UserRole
from buildings.models import BuildingManagerAssignment
from extra_work.models import ExtraWorkRequest, ExtraWorkStatus
from extra_work.views_financials import FIGURE_KEYS, compute_financial_summary
from tickets.models import Ticket, TicketStatus

from extra_work.tests.test_m4_billing_run import _InvoiceRunFixture, _dt, _mk


URL = "/api/extra-work/financial-summary/"


class _StripFixture(_InvoiceRunFixture):
    """Adds the two row shapes `_InvoiceRunFixture` has no helper for:
    an Extra Work with no spawned ticket at all, and one whose ticket is
    still running."""

    def _ew_without_ticket(self, *, ew_status, subtotal="100.00", vat="21.00"):
        return ExtraWorkRequest.objects.create(
            company=self.company,
            building=self.building,
            customer=self.customer,
            created_by=self.admin,
            title="No ticket yet",
            description="customer-visible description",
            status=ew_status,
            subtotal_amount=Decimal(subtotal),
            vat_amount=Decimal(vat),
            total_amount=Decimal(subtotal) + Decimal(vat),
        )

    def _summary(self, user, **params):
        response = self._api(user).get(URL, params)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        return response.data["figures"]

    def _totals(self, figures):
        return {key: figures[key]["total"] for key in FIGURE_KEYS}


class BucketTests(_StripFixture):
    def test_four_figures_and_only_four(self):
        figures = self._summary(self.admin)
        self.assertEqual(tuple(figures.keys()), FIGURE_KEYS)
        self.assertEqual(len(figures), 4)

    def test_approved_with_no_ticket_is_quoted_not_started(self):
        self._ew_without_ticket(ew_status=ExtraWorkStatus.CUSTOMER_APPROVED)
        totals = self._totals(self._summary(self.admin))
        self.assertEqual(totals["quoted_not_started"], "121.00")
        self.assertEqual(totals["in_progress"], "0.00")

    def test_spawned_but_still_open_ticket_is_quoted_not_started(self):
        # The spawn is synchronous with approval, so this — not the
        # ticketless row above — is the ordinary shape of "committed,
        # nobody has started".
        self._make_ew_with_ticket(
            ticket_status=TicketStatus.OPEN, closed_at=None
        )
        totals = self._totals(self._summary(self.admin))
        self.assertEqual(totals["quoted_not_started"], "121.00")
        self.assertEqual(totals["in_progress"], "0.00")

    def test_running_ticket_is_in_progress(self):
        self._make_ew_with_ticket(
            ticket_status=TicketStatus.IN_PROGRESS, closed_at=None
        )
        totals = self._totals(self._summary(self.admin))
        self.assertEqual(totals["in_progress"], "121.00")
        self.assertEqual(totals["quoted_not_started"], "0.00")

    def test_closed_this_period_is_done_and_not_invoiced(self):
        self._make_ew_with_ticket(
            ticket_status=TicketStatus.CLOSED, closed_at=_dt(2026, 5, 20)
        )
        totals = self._totals(self._summary(self.admin, billing_period="2026-05"))
        self.assertEqual(totals["done_this_period"], "121.00")
        self.assertEqual(totals["invoiced_this_period"], "0.00")

    def test_invoiced_is_a_subset_of_done(self):
        self._make_ew_with_ticket(
            ticket_status=TicketStatus.CLOSED,
            closed_at=_dt(2026, 5, 20),
            is_invoiced=True,
        )
        self._make_ew_with_ticket(
            ticket_status=TicketStatus.CLOSED, closed_at=_dt(2026, 5, 21)
        )
        figures = self._summary(self.admin, billing_period="2026-05")
        # "Done this period" is EVERYTHING finished in the month, and
        # "Invoiced this period" is the part of it that has been billed —
        # not a bucket beside it. Two rows done, one of them billed.
        self.assertEqual(figures["done_this_period"]["total"], "242.00")
        self.assertEqual(figures["done_this_period"]["count"], 2)
        self.assertEqual(figures["invoiced_this_period"]["total"], "121.00")
        self.assertEqual(figures["invoiced_this_period"]["count"], 1)

    def test_the_w1b_cutoff_arm_moves_work_into_done_by_itself(self):
        # This module states, in its own docstring and the endpoint's,
        # that W1-B's widening of `is_earned` arrives here without a
        # change — because the endpoint CALLS `is_billable` rather than
        # restating what earned means. That is a claim, so it is tested
        # rather than asserted in prose: a ticket at
        # WAITING_CUSTOMER_APPROVAL with `sent_for_approval_at` stamped
        # is finished work handed to the customer, and it belongs in
        # "Done this period", NOT in "In progress".
        ew = self._make_ew_with_ticket(
            ticket_status=TicketStatus.WAITING_CUSTOMER_APPROVAL,
            closed_at=None,
        )
        Ticket.objects.filter(extra_work_request=ew).update(
            sent_for_approval_at=_dt(2026, 5, 29)
        )
        totals = self._totals(self._summary(self.admin, billing_period="2026-05"))
        self.assertEqual(totals["done_this_period"], "121.00")
        self.assertEqual(totals["in_progress"], "0.00")

    def test_waiting_manager_review_is_not_done(self):
        # The guard W1-B calls the whole point of its change: staff
        # saying "done" with nobody having checked is not billable, so
        # it must read as work in progress, not as money that landed.
        ew = self._make_ew_with_ticket(
            ticket_status=TicketStatus.WAITING_MANAGER_REVIEW, closed_at=None
        )
        Ticket.objects.filter(extra_work_request=ew).update(
            sent_for_approval_at=_dt(2026, 5, 29)
        )
        totals = self._totals(self._summary(self.admin, billing_period="2026-05"))
        self.assertEqual(totals["done_this_period"], "0.00")
        self.assertEqual(totals["in_progress"], "121.00")

    def test_closed_in_another_month_reaches_no_figure(self):
        self._make_ew_with_ticket(
            ticket_status=TicketStatus.CLOSED, closed_at=_dt(2026, 4, 20)
        )
        totals = self._totals(self._summary(self.admin, billing_period="2026-05"))
        self.assertEqual(set(totals.values()), {"0.00"})

    def test_invoice_date_override_moves_the_month(self):
        self._make_ew_with_ticket(
            ticket_status=TicketStatus.CLOSED,
            closed_at=_dt(2026, 5, 31),
            invoice_date=date(2026, 6, 15),
        )
        may = self._totals(self._summary(self.admin, billing_period="2026-05"))
        jun = self._totals(self._summary(self.admin, billing_period="2026-06"))
        self.assertEqual(may["done_this_period"], "0.00")
        self.assertEqual(jun["done_this_period"], "121.00")

    def test_cancelled_work_is_in_no_figure(self):
        # `is_billable` rules CANCELLED and CUSTOMER_REJECTED out however
        # their ticket ended — you do not put work you called off in a
        # figure about money that is going to land.
        ew = self._make_ew_with_ticket(
            ticket_status=TicketStatus.CLOSED, closed_at=_dt(2026, 5, 20)
        )
        ExtraWorkRequest.objects.filter(pk=ew.pk).update(
            status=ExtraWorkStatus.CANCELLED
        )
        running = self._make_ew_with_ticket(
            ticket_status=TicketStatus.IN_PROGRESS, closed_at=None
        )
        ExtraWorkRequest.objects.filter(pk=running.pk).update(
            status=ExtraWorkStatus.CUSTOMER_REJECTED
        )
        totals = self._totals(self._summary(self.admin, billing_period="2026-05"))
        self.assertEqual(set(totals.values()), {"0.00"})

    def test_unpriced_quote_is_not_committed_money(self):
        # PRICING_PROPOSED is `quoted_pipeline`: the customer has not
        # said yes, so it is not "money committed".
        self._ew_without_ticket(ew_status=ExtraWorkStatus.PRICING_PROPOSED)
        totals = self._totals(self._summary(self.admin))
        self.assertEqual(set(totals.values()), {"0.00"})

    def test_final_amount_wins_over_the_quote(self):
        # rowAmounts(): prefer the final actual-hours amount, fall back
        # to the quote only when it is NULL. One rule, and this is it.
        ew = self._make_ew_with_ticket(
            ticket_status=TicketStatus.CLOSED, closed_at=_dt(2026, 5, 20)
        )
        ExtraWorkRequest.objects.filter(pk=ew.pk).update(
            final_subtotal_amount=Decimal("200.00"),
            final_vat_amount=Decimal("42.00"),
            final_total_amount=Decimal("242.00"),
        )
        figures = self._summary(self.admin, billing_period="2026-05")
        self.assertEqual(figures["done_this_period"]["total"], "242.00")
        self.assertEqual(figures["done_this_period"]["subtotal"], "200.00")

    def test_unpriced_rows_are_counted_not_hidden(self):
        # Zero is a legal price. An unpriced row still contributes zero
        # to the sum (`sumRows` in billing.ts is deliberately untouched),
        # but the strip has to be able to say "nobody has priced this"
        # instead of printing EUR 0,00 as if the work were free.
        self._ew_without_ticket(
            ew_status=ExtraWorkStatus.CUSTOMER_APPROVED,
            subtotal="0.00",
            vat="0.00",
        )
        figures = self._summary(self.admin)
        bucket = figures["quoted_not_started"]
        self.assertEqual(bucket["count"], 1)
        self.assertEqual(bucket["unpriced_count"], 1)
        self.assertEqual(bucket["total"], "0.00")

    def test_a_priced_row_is_not_counted_as_unpriced(self):
        # The other half of the same fact: `unpriced_count` has to be
        # able to come back ZERO, or the em dash would be permanent and
        # the strip would never show money at all.
        from extra_work.models import ExtraWorkPricingLineItem

        ew = self._ew_without_ticket(
            ew_status=ExtraWorkStatus.CUSTOMER_APPROVED
        )
        ExtraWorkPricingLineItem.objects.create(
            extra_work=ew,
            description="Priced line",
            quantity=Decimal("1.00"),
            unit_price=Decimal("100.00"),
            vat_rate=Decimal("21.00"),
        )
        bucket = self._summary(self.admin)["quoted_not_started"]
        self.assertEqual(bucket["count"], 1)
        self.assertEqual(bucket["unpriced_count"], 0)

    def test_stocks_sum_to_the_revenue_report_in_progress_bucket(self):
        # Figures 1 and 2 are a SPLIT of one shared classifier state, not
        # a second opinion about it. If that ever stops being true, the
        # strip and the revenue report have started disagreeing.
        from reports.dimensions import compute_extra_work_revenue

        self._ew_without_ticket(ew_status=ExtraWorkStatus.CUSTOMER_APPROVED)
        self._make_ew_with_ticket(
            ticket_status=TicketStatus.OPEN, closed_at=None
        )
        self._make_ew_with_ticket(
            ticket_status=TicketStatus.IN_PROGRESS, closed_at=None
        )
        figures = self._summary(self.admin)
        strip = Decimal(figures["quoted_not_started"]["total"]) + Decimal(
            figures["in_progress"]["total"]
        )
        # Default window: the last 30 days, which is where a row created
        # by this test's own setUp lands.
        report = compute_extra_work_revenue(self.admin, {})
        self.assertEqual(strip, Decimal(report["states"]["in_progress"]["total"]))

    def test_stocks_drop_called_off_work_the_report_still_counts(self):
        # The other half of the sentence above. The revenue report
        # classifies on the TICKET, so a cancelled Extra Work whose
        # ticket runs on still lands in its `in_progress` bucket. The
        # strip is about money that is going to be billed, so it must
        # not — and that is the ONE place the two legitimately differ.
        from reports.dimensions import compute_extra_work_revenue

        running = self._make_ew_with_ticket(
            ticket_status=TicketStatus.IN_PROGRESS, closed_at=None
        )
        ExtraWorkRequest.objects.filter(pk=running.pk).update(
            status=ExtraWorkStatus.CANCELLED
        )
        figures = self._summary(self.admin)
        self.assertEqual(figures["in_progress"]["total"], "0.00")
        report = compute_extra_work_revenue(self.admin, {})
        self.assertEqual(report["states"]["in_progress"]["total"], "121.00")


class ScopeTests(_StripFixture):
    def test_company_admin_sees_only_their_company(self):
        self._make_ew_with_ticket(
            ticket_status=TicketStatus.IN_PROGRESS, closed_at=None
        )
        self._make_ew_with_ticket(
            ticket_status=TicketStatus.IN_PROGRESS,
            closed_at=None,
            company=self.company_b,
            building=self.building_b,
            customer=self.customer_b,
            created_by=self.admin_b,
        )
        self.assertEqual(
            self._totals(self._summary(self.admin))["in_progress"], "121.00"
        )
        self.assertEqual(
            self._totals(self._summary(self.admin_b))["in_progress"], "121.00"
        )
        # And the super admin sees the pair, which is the only way to be
        # sure the two admins were each seeing a DIFFERENT one row.
        self.assertEqual(
            self._totals(self._summary(self.super_admin))["in_progress"],
            "242.00",
        )

    def test_customer_user_is_refused(self):
        response = self._api(self.customer_user).get(URL)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_staff_is_refused(self):
        staff = _mk("staff-w1c@example.com", UserRole.STAFF)
        response = self._api(staff).get(URL)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_anonymous_is_refused(self):
        from rest_framework.test import APIClient

        response = APIClient().get(URL)
        self.assertIn(
            response.status_code,
            (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN),
        )

    def test_building_manager_sees_only_assigned_buildings(self):
        manager = _mk("bm-w1c@example.com", UserRole.BUILDING_MANAGER)
        BuildingManagerAssignment.objects.create(
            user=manager, building=self.building
        )
        self._make_ew_with_ticket(
            ticket_status=TicketStatus.IN_PROGRESS, closed_at=None
        )
        self._make_ew_with_ticket(
            ticket_status=TicketStatus.IN_PROGRESS,
            closed_at=None,
            company=self.company_b,
            building=self.building_b,
            customer=self.customer_b,
            created_by=self.admin_b,
        )
        self.assertEqual(
            self._totals(self._summary(manager))["in_progress"], "121.00"
        )

    def test_customer_narrowing_cannot_widen_scope(self):
        # `?customer=` is a convenience; the scope helper already ran, so
        # naming another tenant's customer returns nothing rather than
        # their money.
        self._make_ew_with_ticket(
            ticket_status=TicketStatus.IN_PROGRESS,
            closed_at=None,
            company=self.company_b,
            building=self.building_b,
            customer=self.customer_b,
            created_by=self.admin_b,
        )
        totals = self._totals(
            self._summary(self.admin, customer=self.customer_b.id)
        )
        self.assertEqual(set(totals.values()), {"0.00"})


class BadInputTests(_StripFixture):
    def test_unparseable_period_is_400(self):
        for bad in ("2026", "2026-13", "not-a-month", "0000-05"):
            response = self._api(self.admin).get(URL, {"billing_period": bad})
            self.assertEqual(
                response.status_code,
                status.HTTP_400_BAD_REQUEST,
                msg=f"billing_period={bad!r} should fail closed",
            )

    def test_non_integer_customer_is_400(self):
        response = self._api(self.admin).get(URL, {"customer": "abc"})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)


class NarrowingLosesNothingTests(_StripFixture):
    """The endpoint narrows in SQL before classifying in Python. This
    proves the narrowing is a superset: the same numbers come out of a
    brute-force walk over EVERY row in scope, with no filter at all."""

    def _brute_force(self, actor, year, month):
        from reports.dimensions import _amounts_for_state, _classify_extra_work
        from extra_work.billing import build_ticket_map
        from extra_work.scoping import scope_extra_work_for
        from extra_work.views_financials import figures_for

        rows = list(scope_extra_work_for(actor))
        ticket_map = build_ticket_map([r.id for r in rows])
        acc = {key: Decimal("0.00") for key in FIGURE_KEYS}
        for ew in rows:
            ticket = ticket_map.get(ew.id)
            state = _classify_extra_work(ew, ticket)
            _s, _v, total = _amounts_for_state(ew, state)
            for key in figures_for(ew, ticket, (year, month), state):
                acc[key] += total if total is not None else Decimal("0.00")
        return {k: str(v.quantize(Decimal("0.01"))) for k, v in acc.items()}

    def test_agrees_with_a_walk_of_everything_in_scope(self):
        self._ew_without_ticket(ew_status=ExtraWorkStatus.CUSTOMER_APPROVED)
        self._ew_without_ticket(ew_status=ExtraWorkStatus.PRICING_PROPOSED)
        self._make_ew_with_ticket(
            ticket_status=TicketStatus.OPEN, closed_at=None
        )
        self._make_ew_with_ticket(
            ticket_status=TicketStatus.IN_PROGRESS, closed_at=None
        )
        self._make_ew_with_ticket(
            ticket_status=TicketStatus.WAITING_CUSTOMER_APPROVAL, closed_at=None
        )
        # W1-B's cutoff arm: earned without ever being CLOSED, and
        # anchored on `sent_for_approval_at` rather than `closed_at`.
        # The narrowing keeps it because WAITING_CUSTOMER_APPROVAL is not
        # a terminal ticket status — the clause that exists for exactly
        # this row.
        cutoff_ew = self._make_ew_with_ticket(
            ticket_status=TicketStatus.WAITING_CUSTOMER_APPROVAL, closed_at=None
        )
        Ticket.objects.filter(extra_work_request=cutoff_ew).update(
            sent_for_approval_at=_dt(2026, 5, 28)
        )
        self._make_ew_with_ticket(
            ticket_status=TicketStatus.CLOSED, closed_at=_dt(2026, 5, 10)
        )
        self._make_ew_with_ticket(
            ticket_status=TicketStatus.CLOSED,
            closed_at=_dt(2026, 5, 11),
            is_invoiced=True,
        )
        # Terminal and OUTSIDE the period — the rows the narrowing drops.
        self._make_ew_with_ticket(
            ticket_status=TicketStatus.CLOSED, closed_at=_dt(2026, 3, 3)
        )
        self._make_ew_with_ticket(
            ticket_status=TicketStatus.REJECTED, closed_at=_dt(2026, 3, 4)
        )
        # A provider-set invoice_date pulls a March completion into May.
        self._make_ew_with_ticket(
            ticket_status=TicketStatus.CLOSED,
            closed_at=_dt(2026, 3, 5),
            invoice_date=date(2026, 5, 9),
        )

        endpoint = self._totals(self._summary(self.admin, billing_period="2026-05"))
        self.assertEqual(endpoint, self._brute_force(self.admin, 2026, 5))
        # Not a vacuous pass: the walk found real money in three figures.
        self.assertNotEqual(set(endpoint.values()), {"0.00"})


class QueryCountTests(_StripFixture):
    """One query for the rows, one for the spawned-ticket map. Constant
    in the number of rows — that constancy is the whole assertion, so
    the count is measured at two very different sizes."""

    def _make_n(self, n):
        for i in range(n):
            self._make_ew_with_ticket(
                ticket_status=TicketStatus.IN_PROGRESS, closed_at=None
            )
            self._ew_without_ticket(
                ew_status=ExtraWorkStatus.CUSTOMER_APPROVED
            )
            self._make_ew_with_ticket(
                ticket_status=TicketStatus.CLOSED,
                closed_at=_dt(2026, 5, 1 + (i % 28)),
                is_invoiced=bool(i % 2),
            )

    def test_two_queries_at_three_rows(self):
        self._make_n(1)
        with self.assertNumQueries(2):
            compute_financial_summary(self.admin, {"billing_period": "2026-05"})

    def test_still_two_queries_at_sixty_rows(self):
        self._make_n(20)
        with self.assertNumQueries(2):
            result = compute_financial_summary(
                self.admin, {"billing_period": "2026-05"}
            )
        # A count that stayed at two because nothing was returned would
        # prove nothing.
        self.assertEqual(result["figures"]["in_progress"]["count"], 20)
        self.assertEqual(result["figures"]["quoted_not_started"]["count"], 20)
        self.assertEqual(result["figures"]["done_this_period"]["count"], 20)

    def test_ticket_rows_are_not_refetched_per_row(self):
        # Guards the OTHER shape of N+1: `build_ticket_map` loads the
        # columns `is_earned` reads with `.only(...)`. If a future sprint
        # teaches `is_earned` to read a column that map does not load —
        # W1-B's billing cutoff reads `sent_for_approval_at` — every
        # caller silently gets a query per row, and this fails.
        self._make_n(10)
        self.assertEqual(Ticket.objects.count(), 20)
        with self.assertNumQueries(2):
            compute_financial_summary(self.admin, {"billing_period": "2026-05"})
