"""Sprint 180 §1/§2/§3 — the two tracks, the ticket link, and billed_to.

An Extra Work has two lives: a commercial one (quote, price, approval)
and an operational one (scheduled, started, done). The list showed both
on one line. The dividing question is exactly one thing — has an
operational ticket been born from this extra work? — and this module
pins the answer the API gives to it.

Three things are locked here:

  * §1  `has_operational_ticket` uses the CANONICAL FK
        (`Ticket.extra_work_request`) and nothing else, matching
        `extra_work.billing.build_ticket_map` and `reports.dimensions`.
        A soft-deleted ticket does not count.
  * §2  `spawned_tickets` carries the number and the id to link to, on
        BOTH the list and the detail shape, and neither the ticket link
        nor `started_before_plan` costs a query per row.
  * §3  `billed_to` round-trips through create and is rendered by both
        serializers, for the provider and the customer.

Every field here gets a test that RENDERS the endpoint carrying it: a
missing `fields` entry took the whole Extra Work page down in Sprint 173
and a filter test never catches that, because a filter test issues a
query but never serialises a row.
"""
from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from rest_framework import status

from extra_work.models import (
    ExtraWorkBilledTo,
    ExtraWorkRequest,
    ExtraWorkStatus,
    ExtraWorkStatusHistory,
)
from extra_work.tests.test_m4_billing_run import _InvoiceRunFixture, _dt
from tickets.models import Ticket, TicketStatus


LIST_URL = "/api/extra-work/"


def _detail_url(ew_id) -> str:
    return f"{LIST_URL}{ew_id}/"


class _TrackFixture(_InvoiceRunFixture):
    """Adds a ticket-less Extra Work builder to the M4 fixture."""

    def _make_ew(self, *, status_value=ExtraWorkStatus.REQUESTED, **extra):
        return ExtraWorkRequest.objects.create(
            company=self.company,
            building=self.building,
            customer=self.customer,
            created_by=extra.pop("created_by", self.admin),
            title=extra.pop("title", "Track EW"),
            description="customer-visible description",
            status=status_value,
            subtotal_amount=Decimal("100.00"),
            vat_amount=Decimal("21.00"),
            total_amount=Decimal("121.00"),
            **extra,
        )

    def _row_for(self, response, ew_id):
        for row in response.data["results"]:
            if row["id"] == ew_id:
                return row
        self.fail(f"EW {ew_id} not in the list response")


class TrackSplitTests(_TrackFixture):
    def test_no_ticket_is_quote_and_price_track(self):
        ew = self._make_ew()
        resp = self._api(self.admin).get(LIST_URL)
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        row = self._row_for(resp, ew.id)
        self.assertFalse(row["has_operational_ticket"])
        self.assertEqual(row["spawned_tickets"], [])

    def test_spawned_ticket_moves_the_row_to_work_started(self):
        ew = self._make_ew_with_ticket(
            ticket_status=TicketStatus.OPEN, closed_at=None
        )
        row = self._row_for(self._api(self.admin).get(LIST_URL), ew.id)
        self.assertTrue(row["has_operational_ticket"])
        self.assertEqual(len(row["spawned_tickets"]), 1)

    def test_customer_approved_with_no_ticket_stays_in_quote_and_price(self):
        """§1(b) — the anomaly, and it stays on the commercial track.

        The spawn is synchronous with approval, so zero tickets means the
        spawn FAILED. Operationally nothing has started, which is what
        the track means, so the row does not move; the UI marks it as an
        anomaly and offers the existing recovery button
        (POST /api/extra-work/<id>/spawn/). Silence is how work gets
        lost, but so is filing a failure under "work started".
        """
        ew = self._make_ew(status_value=ExtraWorkStatus.CUSTOMER_APPROVED)
        row = self._row_for(self._api(self.admin).get(LIST_URL), ew.id)
        self.assertEqual(row["status"], ExtraWorkStatus.CUSTOMER_APPROVED)
        self.assertFalse(
            row["has_operational_ticket"],
            "approval without a spawned ticket is not started work",
        )

    def test_legacy_chain_only_link_does_not_count(self):
        """§1(a) — the canonical FK alone decides.

        `tickets.filters.TicketFilter.filter_extra_work_request` unions
        three chains (canonical FK, cart-item, proposal-line). A ticket
        linked ONLY through the legacy cart-item chain is found by that
        filter but is NOT what `extra_work.billing.build_ticket_map`
        considers the spawned ticket, so it may not move a row onto the
        operational track: money must win over the looser definition,
        or the list would say work had started on a row the invoice run
        treats as unstarted.
        """
        from extra_work.models import ExtraWorkRequestItem

        ew = self._make_ew()
        item = ExtraWorkRequestItem.objects.create(
            extra_work_request=ew,
            custom_description="ad-hoc line",
            quantity=Decimal("1.00"),
            unit_type="OTHER",
            requested_date=date(2026, 5, 1),
        )
        Ticket.objects.create(
            company=self.company,
            building=self.building,
            customer=self.customer,
            created_by=self.admin,
            title="Legacy-chain ticket",
            description="d",
            status=TicketStatus.OPEN,
            extra_work_request_item=item,
        )
        row = self._row_for(self._api(self.admin).get(LIST_URL), ew.id)
        self.assertFalse(row["has_operational_ticket"])
        self.assertEqual(row["spawned_tickets"], [])

    def test_soft_deleted_ticket_does_not_count(self):
        ew = self._make_ew_with_ticket(
            ticket_status=TicketStatus.OPEN, closed_at=None
        )
        Ticket.objects.filter(extra_work_request=ew).update(
            deleted_at=timezone.now()
        )
        row = self._row_for(self._api(self.admin).get(LIST_URL), ew.id)
        self.assertFalse(row["has_operational_ticket"])
        self.assertEqual(row["spawned_tickets"], [])


class SpawnedTicketLinkTests(_TrackFixture):
    def test_list_row_carries_number_and_id(self):
        ew = self._make_ew_with_ticket(
            ticket_status=TicketStatus.OPEN, closed_at=None
        )
        ticket = Ticket.objects.get(extra_work_request=ew)
        row = self._row_for(self._api(self.admin).get(LIST_URL), ew.id)
        # W12 §2 added the ticket's own schedule to this payload (the
        # screen shows a conflict it used to compute and throw away);
        # the pinned shape moved with it.
        self.assertEqual(
            row["spawned_tickets"],
            [
                {
                    "id": ticket.id,
                    "ticket_no": ticket.ticket_no,
                    "status": TicketStatus.OPEN,
                    "scheduled_start_at": None,
                    "schedule_status": "UNSCHEDULED",
                }
            ],
        )

    def test_detail_carries_the_same_pair(self):
        ew = self._make_ew_with_ticket(
            ticket_status=TicketStatus.CLOSED, closed_at=_dt(2026, 5, 20)
        )
        ticket = Ticket.objects.get(extra_work_request=ew)
        resp = self._api(self.admin).get(_detail_url(ew.id))
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertTrue(resp.data["has_operational_ticket"])
        self.assertEqual(
            [t["id"] for t in resp.data["spawned_tickets"]], [ticket.id]
        )

    def test_customer_sees_the_ticket_link_too(self):
        ew = self._make_ew_with_ticket(
            ticket_status=TicketStatus.OPEN,
            closed_at=None,
            created_by=self.customer_user,
        )
        row = self._row_for(
            self._api(self.customer_user).get(LIST_URL), ew.id
        )
        self.assertTrue(row["has_operational_ticket"])
        self.assertEqual(len(row["spawned_tickets"]), 1)

    def test_cross_tenant_row_is_still_absent(self):
        """The new fields must not become a leak: company B's admin sees
        neither company A's row nor its ticket."""
        ew = self._make_ew_with_ticket(
            ticket_status=TicketStatus.OPEN, closed_at=None
        )
        resp = self._api(self.admin_b).get(LIST_URL)
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertNotIn(ew.id, {r["id"] for r in resp.data["results"]})


class ListQueryGrowthTests(_TrackFixture):
    """The claim is GROWTH, not an absolute number — an unrelated
    middleware change must not break these. Same shape as
    `test_sprint138_catalog_lifecycle.test_has_price_rows_does_not_scale
    _with_row_count`.
    """

    def _seed_row(self, *, with_history: bool):
        ew = self._make_ew_with_ticket(
            ticket_status=TicketStatus.OPEN, closed_at=None
        )
        ExtraWorkRequest.objects.filter(pk=ew.pk).update(
            preferred_date=timezone.localdate() + timedelta(days=30)
        )
        if with_history:
            for new_status in (
                ExtraWorkStatus.CUSTOMER_APPROVED,
                ExtraWorkStatus.IN_PROGRESS,
            ):
                ExtraWorkStatusHistory.objects.create(
                    extra_work=ew,
                    old_status=ExtraWorkStatus.REQUESTED,
                    new_status=new_status,
                    changed_by=self.admin,
                )
        return ew

    def _count_list_queries(self):
        api = self._api(self.admin)
        with CaptureQueriesContext(connection) as ctx:
            resp = api.get(LIST_URL)
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        return len(ctx.captured_queries), resp

    def test_ticket_link_and_started_before_plan_do_not_scale_with_rows(self):
        """§2 — the N+1 that predates this sprint.

        `started_before_plan` is declared on the list serializer and its
        model property read `status_history` once PER ROW; the new
        `spawned_tickets` field could easily have added a second. One
        row and three rows must now cost the same number of queries.
        """
        self._seed_row(with_history=True)
        baseline, first = self._count_list_queries()
        self.assertEqual(len(first.data["results"]), 1)

        for _ in range(2):
            self._seed_row(with_history=True)

        grown, second = self._count_list_queries()
        self.assertEqual(len(second.data["results"]), 3)
        self.assertEqual(
            grown,
            baseline,
            "listing three Extra Work rows must cost the same number of "
            "queries as listing one",
        )

    def test_started_before_plan_still_correct_under_prefetch(self):
        """The N+1 fix moved the narrowing from SQL into Python. The
        answer must not have moved with it: work started BEFORE the
        planned window opened is still flagged, and work with no start
        is still not."""
        early = self._seed_row(with_history=True)
        never_started = self._seed_row(with_history=False)

        resp = self._api(self.admin).get(LIST_URL)
        self.assertTrue(self._row_for(resp, early.id)["started_before_plan"])
        self.assertFalse(
            self._row_for(resp, never_started.id)["started_before_plan"]
        )


class BilledToTests(_TrackFixture):
    def test_defaults_to_null_meaning_follow_the_customer(self):
        """Sprint 182 §6 changed this rule, by owner decision.

        Sprint 180 defaulted the column to BUILDING, which was harmless
        while nothing read it. Once invoice generation started reading
        it, that default would have silently re-targeted every customer
        configured for one-invoice-per-customer — so NULL ("follow the
        customer's setting") is the default now, and migration 0032 set
        every pre-182 row to it. Asserting BUILDING here is what this
        test used to do; it is now the wrong contract."""
        ew = self._make_ew()
        self.assertIsNone(ew.billed_to)
        row = self._row_for(self._api(self.admin).get(LIST_URL), ew.id)
        self.assertIsNone(row["billed_to"])

    def test_rendered_on_detail_for_provider_and_customer(self):
        ew = self._make_ew(created_by=self.customer_user)
        ExtraWorkRequest.objects.filter(pk=ew.pk).update(
            billed_to=ExtraWorkBilledTo.CUSTOMER
        )
        for actor in (self.admin, self.customer_user):
            resp = self._api(actor).get(_detail_url(ew.id))
            self.assertEqual(resp.status_code, status.HTTP_200_OK)
            self.assertEqual(resp.data["billed_to"], "CUSTOMER")

    def test_create_accepts_an_explicit_value(self):
        resp = self._api(self.admin).post(
            LIST_URL,
            {
                "building": self.building.id,
                "customer": self.customer.id,
                "title": "Billed to the customer",
                "description": "d",
                "billed_to": "CUSTOMER",
                "line_items": [
                    {
                        "custom_description": "ad-hoc work",
                        "quantity": "1.00",
                    }
                ],
            },
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED, resp.data)
        self.assertEqual(resp.data["billed_to"], "CUSTOMER")
        self.assertEqual(
            ExtraWorkRequest.objects.get(pk=resp.data["id"]).billed_to,
            ExtraWorkBilledTo.CUSTOMER,
        )

    def test_create_without_the_field_stores_null(self):
        resp = self._api(self.admin).post(
            LIST_URL,
            {
                "building": self.building.id,
                "customer": self.customer.id,
                "title": "Legacy client, no billed_to",
                "description": "d",
                "line_items": [
                    {
                        "custom_description": "ad-hoc work",
                        "quantity": "1.00",
                    }
                ],
            },
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED, resp.data)
        # Sprint 182 §6 — omitting the field now stores NULL ("follow the
        # customer"), not BUILDING. See the docstring on
        # `test_defaults_to_null_meaning_follow_the_customer`.
        self.assertIsNone(resp.data["billed_to"])

    def test_create_rejects_a_third_value(self):
        resp = self._api(self.admin).post(
            LIST_URL,
            {
                "building": self.building.id,
                "customer": self.customer.id,
                "title": "Bad billing target",
                "description": "d",
                "billed_to": "PER_BUILDING_DEPARTMENT_WORK_TYPE",
                "line_items": [
                    {
                        "custom_description": "ad-hoc work",
                        "quantity": "1.00",
                    }
                ],
            },
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("billed_to", resp.data)

    def test_converted_extra_work_stores_null(self):
        """`extra_work.conversion` builds its row with `objects.create()`
        and never touches the create serializer, so the model default is
        what makes "every Extra Work has a billing target" true on EVERY
        write path rather than only on the form's."""
        from extra_work.conversion import convert_ticket_to_extra_work

        source = Ticket.objects.create(
            company=self.company,
            building=self.building,
            customer=self.customer,
            created_by=self.admin,
            title="Inbound melding",
            description="d",
            status=TicketStatus.OPEN,
        )
        ew, _spawned = convert_ticket_to_extra_work(
            source,
            actor=self.admin,
            request_intent="REQUEST_QUOTE",
            line_items_data=[
                {
                    "service": None,
                    "custom_description": "ad-hoc",
                    "quantity": Decimal("1.00"),
                    "requested_date": date(2026, 5, 1),
                    "customer_note": "",
                }
            ],
        )
        # Sprint 182 §6 — the conversion path defaults to NULL too.
        # Leaving it at BUILDING would have made converted requests the
        # only rows in the system carrying a target nobody chose, and
        # that value would then override the customer's own setting.
        self.assertIsNone(ew.billed_to)
