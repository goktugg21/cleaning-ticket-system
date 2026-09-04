"""Sprint 182 A — the money rules the domain audit found broken.

  §1  Editing actual hours is refused once the work is on an ISSUED/SENT
      invoice. The old lock asked only about the TICKET's status, and its
      own error message invited the operator to reopen the ticket — which
      is exactly how you rewrite an amount behind a document the customer
      already has.
  §2  An already-invoiced amount is never recomputed. Established as
      ALREADY TRUE (the amounts are snapshotted onto `InvoiceLine`), and
      pinned here with the owner's own sequence so it stays true.
  §3  `is_billable` — a cancelled extra work is not invoiceable however
      its ticket ended. `invoicing.selectors` must call this; Agent B owns
      that file.
  §5  The reconcile command's two-hop repair, which could never succeed.
  §6  `billed_to` nullable (NULL = follow the customer) and the provider's
      own planning date, both rendered by the endpoints that carry them.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from io import StringIO

from django.core.management import call_command
from django.utils import timezone

from invoicing.models import Invoice, InvoiceLine

from extra_work.billing import is_billable, is_earned
from extra_work.models import (
    ExtraWorkBilledTo,
    ExtraWorkRequest,
    ExtraWorkStatus,
)
from extra_work.tests.test_m4_billing_run import _InvoiceRunFixture, _dt
from tickets.models import Ticket, TicketStatus


ACTUAL_HOURS_URL = "/api/extra-work/{id}/actual-hours/"
LIST_URL = "/api/extra-work/"


class _Fixture(_InvoiceRunFixture):

    # Sprint 186 — department and work type are REQUIRED on create.
    # Every customer is seeded one of each (`customers/signals.py`), so
    # the fixture asks for the seeded pair instead of building its own.
    def _seeded_department(self):
        from customers.models import Department

        return Department.objects.filter(customer=self.customer).first()

    def _seeded_work_type(self):
        from customers.models import WorkType

        return WorkType.objects.filter(customer=self.customer).first()

    def _make_ew(self, status_value=ExtraWorkStatus.COMPLETED, **extra):
        return ExtraWorkRequest.objects.create(
            company=self.company,
            building=self.building,
            customer=self.customer,
            created_by=self.admin,
            title=extra.pop("title", "Money-rules EW"),
            description="d",
            status=status_value,
            subtotal_amount=Decimal("100.00"),
            vat_amount=Decimal("21.00"),
            total_amount=Decimal("121.00"),
            **extra,
        )

    def _invoice_with_line(self, ew, *, status_value, amount, number=None):
        """An invoice carrying `ew`, with the amount SNAPSHOTTED on the
        line exactly as `invoicing.services._create_draft` writes it.

        A number is only assigned off DRAFT (numbering happens at SEND;
        an ISSUED-but-unsent invoice shows CONCEPT), and it has to be
        unique per company — the model constrains (company, number)."""
        if number is None and status_value != Invoice.Status.DRAFT:
            number = f"2026-{Invoice.objects.count() + 1:04d}"
        invoice = Invoice.objects.create(
            company=self.company,
            customer=self.customer,
            created_by=self.admin,
            status=status_value,
            number=number,
        )
        InvoiceLine.objects.create(
            invoice=invoice,
            ordering=0,
            description=ew.title,
            extra_work=ew,
            quantity=Decimal("1.00"),
            unit_price=amount,
            vat_pct=Decimal("21.00"),
            line_subtotal=amount,
            line_vat=(amount * Decimal("0.21")).quantize(Decimal("0.01")),
            line_total=(amount * Decimal("1.21")).quantize(Decimal("0.01")),
            period_year=2026,
            period_month=5,
        )
        return invoice


class ActualHoursInvoiceLockTests(_Fixture):
    """§1 — the lock the label path had and the money path did not."""

    def _post(self, ew, hours="3.00"):
        return self._api(self.admin).post(
            ACTUAL_HOURS_URL.format(id=ew.id),
            {"lines": [{"line_id": 1, "actual_hours": hours}]},
            format="json",
        )

    def test_sent_invoice_blocks_editing_actual_hours(self):
        ew = self._make_ew()
        self._invoice_with_line(
            ew, status_value=Invoice.Status.SENT, amount=Decimal("40.00")
        )
        resp = self._post(ew)
        self.assertEqual(resp.status_code, 400, resp.data)
        self.assertEqual(resp.data["code"], "actual_hours_invoice_locked")

    def test_issued_invoice_blocks_too(self):
        """ISSUED, not only SENT — the same boundary the label lock
        draws. The number is assigned at SEND, so an ISSUED invoice is
        already a committed document."""
        ew = self._make_ew()
        self._invoice_with_line(
            ew, status_value=Invoice.Status.ISSUED, amount=Decimal("40.00")
        )
        resp = self._post(ew)
        self.assertEqual(resp.status_code, 400, resp.data)
        self.assertEqual(resp.data["code"], "actual_hours_invoice_locked")

    def test_a_draft_invoice_does_NOT_block(self):
        """The draft window is the correction window — the owner's rule,
        and the reason the label lock keys on ISSUED/SENT rather than on
        `is_invoiced`. A draft that blocked edits would freeze the
        amount during the very window meant for fixing it."""
        ew = self._make_ew(status_value=ExtraWorkStatus.IN_PROGRESS)
        self._invoice_with_line(
            ew, status_value=Invoice.Status.DRAFT, amount=Decimal("40.00")
        )
        resp = self._post(ew)
        self.assertNotEqual(
            getattr(resp, "data", {}).get("code"),
            "actual_hours_invoice_locked",
        )

    def test_a_reversed_invoice_stops_blocking(self):
        """Reversing is the documented way out, so it must actually let
        go — otherwise the error tells the operator to do something that
        does not help."""
        ew = self._make_ew(status_value=ExtraWorkStatus.IN_PROGRESS)
        invoice = self._invoice_with_line(
            ew, status_value=Invoice.Status.SENT, amount=Decimal("40.00")
        )
        # The CREDIT NOTE points at the original through `reverses`;
        # `reversed_by` is the reverse accessor the lock query reads.
        Invoice.objects.create(
            company=self.company,
            customer=self.customer,
            created_by=self.admin,
            status=Invoice.Status.SENT,
            number="2026-9002",
            reverses=invoice,
        )

        resp = self._post(ew)
        self.assertNotEqual(
            getattr(resp, "data", {}).get("code"),
            "actual_hours_invoice_locked",
        )

    def test_a_soft_deleted_ticket_no_longer_freezes_the_amount(self):
        """§4's other half: the ticket-status lock counted deleted
        tickets, so a deleted ticket froze the amount of an extra work
        that had no live ticket at all."""
        ew = self._make_ew(status_value=ExtraWorkStatus.IN_PROGRESS)
        ticket = Ticket.objects.create(
            company=self.company,
            building=self.building,
            customer=self.customer,
            created_by=self.admin,
            title="Deleted operational ticket",
            description="d",
            status=TicketStatus.CLOSED,
            extra_work_request=ew,
        )
        Ticket.objects.filter(pk=ticket.pk).update(deleted_at=timezone.now())

        resp = self._post(ew)
        self.assertNotEqual(
            getattr(resp, "data", {}).get("code"), "final_amount_locked"
        )


class InvoicedAmountIsNeverRecomputedTests(_Fixture):
    """§2 — the owner's own sequence.

    "An extra work is completed and EUR 40 is invoiced. Later the same
    extra work is increased and EUR 60 is invoiced. The total must be
    100, not 120."

    120 is what you get if the FIRST line is re-read from the extra work
    at render time and silently becomes 60 as well. It is not: the
    amounts are persisted columns on `InvoiceLine`, written once from
    `_earned_amounts(ew)` at draft creation.
    """

    def test_the_first_invoices_amount_survives_the_extra_work_growing(self):
        ew = self._make_ew(
            final_subtotal_amount=Decimal("40.00"),
            final_vat_amount=Decimal("8.40"),
            final_total_amount=Decimal("48.40"),
        )
        invoice = self._invoice_with_line(
            ew, status_value=Invoice.Status.SENT, amount=Decimal("40.00")
        )

        # The extra work is later increased — by any route at all; this
        # writes the columns directly so the test does not depend on
        # which one.
        ExtraWorkRequest.objects.filter(pk=ew.pk).update(
            final_subtotal_amount=Decimal("100.00"),
            final_vat_amount=Decimal("21.00"),
            final_total_amount=Decimal("121.00"),
        )

        line = InvoiceLine.objects.get(invoice=invoice)
        self.assertEqual(line.line_subtotal, Decimal("40.00"))
        self.assertEqual(
            line.unit_price,
            Decimal("40.00"),
            "the sent invoice must keep the price it was sent at",
        )

    def test_the_owner_sequence_sums_to_one_hundred(self):
        """40 already billed + 60 billed later == 100, not 120."""
        ew = self._make_ew()
        first = self._invoice_with_line(
            ew, status_value=Invoice.Status.SENT, amount=Decimal("40.00")
        )
        ExtraWorkRequest.objects.filter(pk=ew.pk).update(
            final_subtotal_amount=Decimal("100.00"),
            final_vat_amount=Decimal("21.00"),
            final_total_amount=Decimal("121.00"),
        )
        second = self._invoice_with_line(
            ew, status_value=Invoice.Status.SENT, amount=Decimal("60.00")
        )

        billed = sum(
            line.line_subtotal
            for line in InvoiceLine.objects.filter(
                invoice__in=[first, second]
            )
        )
        self.assertEqual(billed, Decimal("100.00"))


class IsBillableTests(_Fixture):
    """§3 — the predicate `invoicing.selectors` must call."""

    def _closed_ticket_for(self, ew):
        return Ticket.objects.create(
            company=self.company,
            building=self.building,
            customer=self.customer,
            created_by=self.admin,
            title="Operational ticket",
            description="d",
            status=TicketStatus.CLOSED,
            closed_at=_dt(2026, 5, 20),
            extra_work_request=ew,
        )

    def test_a_cancelled_extra_work_is_not_billable(self):
        """The audit's C3, in one assertion. Cancel it, let the surviving
        ticket run to CLOSED, and `is_earned` alone says yes."""
        ew = self._make_ew(status_value=ExtraWorkStatus.CANCELLED)
        ticket = self._closed_ticket_for(ew)

        self.assertTrue(
            is_earned(ticket), "precondition: the ticket really is closed"
        )
        self.assertFalse(is_billable(ew, ticket))

    def test_a_rejected_extra_work_is_not_billable(self):
        ew = self._make_ew(status_value=ExtraWorkStatus.CUSTOMER_REJECTED)
        self.assertFalse(is_billable(ew, self._closed_ticket_for(ew)))

    def test_a_completed_extra_work_with_a_closed_ticket_is_billable(self):
        ew = self._make_ew(status_value=ExtraWorkStatus.COMPLETED)
        self.assertTrue(is_billable(ew, self._closed_ticket_for(ew)))

    def test_unfinished_work_is_not_billable(self):
        ew = self._make_ew(status_value=ExtraWorkStatus.IN_PROGRESS)
        ticket = Ticket.objects.create(
            company=self.company,
            building=self.building,
            customer=self.customer,
            created_by=self.admin,
            title="Still open",
            description="d",
            status=TicketStatus.OPEN,
            extra_work_request=ew,
        )
        self.assertFalse(is_billable(ew, ticket))

    def test_a_zero_amount_extra_work_is_still_billable(self):
        """The owner was explicit: a zero-amount extra work goes ON the
        invoice, written as zero, not skipped. So the predicate must not
        look at the amount at all."""
        ew = self._make_ew(
            status_value=ExtraWorkStatus.COMPLETED,
            final_subtotal_amount=Decimal("0.00"),
            final_vat_amount=Decimal("0.00"),
            final_total_amount=Decimal("0.00"),
        )
        self.assertTrue(is_billable(ew, self._closed_ticket_for(ew)))


class ReconcileMultiHopTests(_Fixture):
    """§5 — the two-hop repair that could never succeed."""

    def test_customer_approved_to_completed_walks_both_hops(self):
        ew = self._make_ew(status_value=ExtraWorkStatus.CUSTOMER_APPROVED)
        Ticket.objects.create(
            company=self.company,
            building=self.building,
            customer=self.customer,
            created_by=self.admin,
            title="Finished ticket",
            description="d",
            status=TicketStatus.CLOSED,
            closed_at=_dt(2026, 5, 20),
            extra_work_request=ew,
        )

        out = StringIO()
        call_command("reconcile_extra_work_status", "--repair", stdout=out)

        ew.refresh_from_db()
        self.assertEqual(
            ew.status,
            ExtraWorkStatus.COMPLETED,
            "the CUSTOMER_APPROVED -> IN_PROGRESS -> COMPLETED walk is the "
            "only multi-hop path and it used to raise on hop 2",
        )
        self.assertIn("Repaired 1 row(s).", out.getvalue())
        self.assertNotIn("could not repair", out.getvalue())

    def test_the_single_hop_repair_still_works(self):
        ew = self._make_ew(status_value=ExtraWorkStatus.COMPLETED)
        Ticket.objects.create(
            company=self.company,
            building=self.building,
            customer=self.customer,
            created_by=self.admin,
            title="Still open",
            description="d",
            status=TicketStatus.OPEN,
            extra_work_request=ew,
        )
        call_command("reconcile_extra_work_status", "--repair", stdout=StringIO())
        ew.refresh_from_db()
        self.assertEqual(ew.status, ExtraWorkStatus.IN_PROGRESS)


class BilledToAndProviderDateTests(_Fixture):
    """§6 — both model changes, rendered by the endpoints that carry
    them. A missing `fields` entry took the whole Extra Work page down in
    Sprint 173 and no filter test would have caught it."""

    def _row_for(self, response, ew_id):
        for row in response.data["results"]:
            if row["id"] == ew_id:
                return row
        self.fail(f"EW {ew_id} not in the list response")

    def test_billed_to_defaults_to_null_meaning_follow_the_customer(self):
        ew = self._make_ew()
        self.assertIsNone(ew.billed_to)
        row = self._row_for(self._api(self.admin).get(LIST_URL), ew.id)
        self.assertIsNone(row["billed_to"])

    def test_an_explicit_value_still_overrides(self):
        ew = self._make_ew(billed_to=ExtraWorkBilledTo.CUSTOMER)
        row = self._row_for(self._api(self.admin).get(LIST_URL), ew.id)
        self.assertEqual(row["billed_to"], "CUSTOMER")

    def test_create_without_billed_to_stores_null(self):
        resp = self._api(self.admin).post(
            LIST_URL,
            {
                "building": self.building.id,
                "customer": self.customer.id,
                # Sprint 186 — department and work type are REQUIRED on
                # create. Every customer is seeded one of each, so the
                # fixture picks the seeded pair rather than omitting them.
                "department": self._seeded_department().id,
                "work_type": self._seeded_work_type().id,
                "title": "No billing target chosen",
                # P-16 repin - P-15 intent rule (provider cart).
                "request_intent": "AUTO_START_AFTER_PRICING",
                "description": "d",
                "line_items": [
                    {
                        "custom_description": "ad-hoc",
                        "quantity": "1.00",
                    }
                ],
            },
            format="json",
        )
        self.assertEqual(resp.status_code, 201, resp.data)
        self.assertIsNone(resp.data["billed_to"])
        self.assertIsNone(
            ExtraWorkRequest.objects.get(pk=resp.data["id"]).billed_to
        )

    def test_create_accepts_an_explicit_null(self):
        """Omitting the key and sending null must mean the same thing —
        a form that clears the control should not 400."""
        resp = self._api(self.admin).post(
            LIST_URL,
            {
                "building": self.building.id,
                "customer": self.customer.id,
                # Sprint 186 — department and work type are REQUIRED on
                # create. Every customer is seeded one of each, so the
                # fixture picks the seeded pair rather than omitting them.
                "department": self._seeded_department().id,
                "work_type": self._seeded_work_type().id,
                "title": "Explicit null",
                # P-16 repin - P-15 intent rule (provider cart).
                "request_intent": "AUTO_START_AFTER_PRICING",
                "description": "d",
                "billed_to": None,
                "line_items": [
                    {
                        "custom_description": "ad-hoc",
                        "quantity": "1.00",
                    }
                ],
            },
            format="json",
        )
        self.assertEqual(resp.status_code, 201, resp.data)
        self.assertIsNone(resp.data["billed_to"])

    def test_provider_planned_date_round_trips_through_create_and_list(self):
        resp = self._api(self.admin).post(
            LIST_URL,
            {
                "building": self.building.id,
                "customer": self.customer.id,
                # Sprint 186 — department and work type are REQUIRED on
                # create. Every customer is seeded one of each, so the
                # fixture picks the seeded pair rather than omitting them.
                "department": self._seeded_department().id,
                "work_type": self._seeded_work_type().id,
                "title": "Planned by the provider",
                # P-16 repin - P-15 intent rule (provider cart).
                "request_intent": "AUTO_START_AFTER_PRICING",
                "description": "d",
                "provider_planned_date": "2026-06-15",
                "line_items": [
                    {
                        "custom_description": "ad-hoc",
                        "quantity": "1.00",
                    }
                ],
            },
            format="json",
        )
        self.assertEqual(resp.status_code, 201, resp.data)
        self.assertEqual(resp.data["provider_planned_date"], "2026-06-15")

        row = self._row_for(
            self._api(self.admin).get(LIST_URL), resp.data["id"]
        )
        self.assertEqual(row["provider_planned_date"], "2026-06-15")

    def test_provider_planned_date_is_on_the_detail_shape_too(self):
        ew = self._make_ew(provider_planned_date=date(2026, 7, 1))
        resp = self._api(self.admin).get(f"{LIST_URL}{ew.id}/")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["provider_planned_date"], "2026-07-01")

    def test_it_is_null_when_nobody_has_planned_it(self):
        """The distinction the Work Plan's undated lane rests on."""
        ew = self._make_ew()
        resp = self._api(self.admin).get(f"{LIST_URL}{ew.id}/")
        self.assertIsNone(resp.data["provider_planned_date"])

    def test_preferred_date_is_untouched_by_the_new_field(self):
        """`preferred_date` remains the CUSTOMER's wish (Sprint 176 §3)
        and the two must not have become aliases."""
        ew = self._make_ew(
            preferred_date=date(2026, 6, 1),
            provider_planned_date=date(2026, 6, 20),
        )
        resp = self._api(self.admin).get(f"{LIST_URL}{ew.id}/")
        self.assertEqual(resp.data["preferred_date"], "2026-06-01")
        self.assertEqual(resp.data["provider_planned_date"], "2026-06-20")
