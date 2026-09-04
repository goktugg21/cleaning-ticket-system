"""
P-10 B3 -- extra work never appears on the Tickets page.

The owner, twice: "Tickets page: no extra work. Ever. It only creates
confusion." A spawned ticket is found from Extra work -> Approved and on
My schedule; the Tickets queue is meldings, provider tickets and the
recurring visits. P-9 D2 had put every origin on the queue behind an
`?origin=` axis; that axis is gone again, and the page pins
`?is_extra_work=false` on the list AND on `/api/tickets/stats/`.

Pins:

  * `?is_extra_work=false` drops the spawned tickets of BOTH spawn
    paths (instant cart, proposal line) and keeps a customer's melding,
    a provider ticket -- even one typed REPORT -- and an occurrence
    (recurring) ticket;
  * `/api/tickets/stats/` follows the same parameter, so the tab counts
    describe the rows under them, with and without a period (the empty
    tab's "Earlier: N open" is the all-time call);
  * `?origin=` is no longer a filter: sending it changes nothing;
  * a deep link to a spawned ticket keeps working -- `GET
    /api/tickets/<id>/` still answers 200 for both spawn paths;
  * the list row still carries `kind` (the detail's fact block reads
    the same rule), and reading it costs no query per row.
"""
from __future__ import annotations

import datetime

from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext

from planned_work.models import (
    Frequency,
    PlannedOccurrence,
    PlannedOccurrenceStatus,
    RecurringJob,
    RecurringJobWindow,
)
from tickets.models import Ticket, TicketStatus, TicketType
from tickets.tests.test_extra_work_origin import ExtraWorkOriginFixtureMixin


TICKETS_URL = "/api/tickets/"
STATS_URL = "/api/tickets/stats/"
#: What the Tickets page sends, on the list and on the stats call.
TICKETS_PAGE = {"is_extra_work": "false"}


def _rows(response):
    return response.data.get("results", response.data)


class _Fixture(ExtraWorkOriginFixtureMixin, TestCase):
    @classmethod
    def setUpTestData(cls):
        cls._setup_fixture()

    def _ticket(self, *, created_by, title, ticket_type=TicketType.REQUEST, **extra):
        return Ticket.objects.create(
            company=self.company,
            building=self.building,
            customer=self.customer,
            created_by=created_by,
            title=title,
            description="P-10 fixture",
            status=TicketStatus.OPEN,
            type=ticket_type,
            **extra,
        )

    def _occurrence_ticket(self, title="Recurring visit"):
        job = RecurringJob.objects.create(
            company=self.company,
            building=self.building,
            customer=self.customer,
            title="Weekly clean",
            frequency=Frequency.WEEKLY,
            start_date=datetime.date(2026, 6, 1),
            created_by=self.admin,
        )
        window = RecurringJobWindow.objects.create(recurring_job=job, ordering=0)
        occurrence = PlannedOccurrence.objects.create(
            recurring_job=job,
            source_window=window,
            company=self.company,
            building=self.building,
            customer=self.customer,
            planned_date=datetime.date(2026, 6, 1),
            status=PlannedOccurrenceStatus.PLANNED,
        )
        return self._ticket(
            created_by=self.admin, title=title, planned_occurrence=occurrence
        )

    def setUp(self):
        super().setUp()
        # One row of every kind the queue can hold, plus the two it must
        # never hold (one per spawn path) and the trap: a provider-created
        # ticket TYPED "REPORT" -- which is why `type` was never the axis.
        self.melding = self._ticket(
            created_by=self.cust_user,
            title="Customer melding",
            ticket_type=TicketType.REPORT,
        )
        _ew, _item, self.meerwerk_instant = self._make_instant_ticket()
        # crmtest: every EW-spawned ticket is typed REPORT too (the spawn
        # copies the request's type).
        self.meerwerk_instant.type = TicketType.REPORT
        self.meerwerk_instant.save(update_fields=["type"])
        _ew2, _line, self.meerwerk_proposal = self._make_proposal_ticket()
        self.plain = self._ticket(created_by=self.admin, title="Provider ticket")
        self.provider_report = self._ticket(
            created_by=self.admin,
            title="Provider-typed report",
            ticket_type=TicketType.REPORT,
        )
        self.recurring = self._occurrence_ticket()
        self.spawned_ids = {self.meerwerk_instant.id, self.meerwerk_proposal.id}
        self.queue_ids = {
            self.melding.id,
            self.plain.id,
            self.provider_report.id,
            self.recurring.id,
        }
        self.all_ids = self.spawned_ids | self.queue_ids

    def _list(self, **params):
        response = self._api(self.super_admin).get(
            TICKETS_URL, {"page_size": 100, **params}
        )
        self.assertEqual(response.status_code, 200, response.data)
        return {row["id"]: row for row in _rows(response)}

    def _stats(self, **params):
        response = self._api(self.super_admin).get(STATS_URL, params)
        self.assertEqual(response.status_code, 200, response.data)
        return response.data


class ListExcludesExtraWorkTests(_Fixture):
    def test_the_tickets_page_never_lists_a_spawned_ticket(self):
        ids = set(self._list(**TICKETS_PAGE))
        self.assertEqual(ids, self.queue_ids)
        self.assertTrue(ids.isdisjoint(self.spawned_ids))

    def test_meldings_provider_tickets_and_recurring_visits_stay(self):
        rows = self._list(**TICKETS_PAGE)
        self.assertEqual(rows[self.melding.id]["kind"], "MELDING")
        self.assertEqual(rows[self.plain.id]["kind"], "TICKET")
        # Typed REPORT by a provider: still a provider ticket, still here.
        self.assertEqual(rows[self.provider_report.id]["kind"], "TICKET")
        self.assertEqual(rows[self.recurring.id]["kind"], "TICKET")
        self.assertIsNotNone(rows[self.recurring.id]["occurrence_origin"])
        self.assertEqual(
            rows[self.recurring.id]["occurrence_origin"]["recurring_job_title"],
            "Weekly clean",
        )

    def test_an_absent_parameter_is_no_opinion(self):
        # Other callers (the extra-work pages, `?extra_work_request=`)
        # still read the whole set; the narrowing is the page's, not
        # the endpoint's.
        self.assertEqual(set(self._list()), self.all_ids)

    def test_the_two_halves_are_complements(self):
        chargeable = set(self._list(is_extra_work="true"))
        ordinary = set(self._list(is_extra_work="false"))
        self.assertEqual(chargeable, self.spawned_ids)
        self.assertEqual(ordinary, self.queue_ids)
        self.assertEqual(chargeable | ordinary, self.all_ids)
        self.assertTrue(chargeable.isdisjoint(ordinary))

    def test_origin_is_no_longer_a_filter(self):
        # P-9 D2's axis is gone: an `?origin=` in an old bookmark changes
        # nothing, with or without the page's own parameter.
        self.assertEqual(set(self._list(origin="meerwerk")), self.all_ids)
        self.assertEqual(set(self._list(origin="melding")), self.all_ids)
        self.assertEqual(
            set(self._list(origin="meerwerk", **TICKETS_PAGE)), self.queue_ids
        )

    def test_every_row_still_carries_the_detail_kind(self):
        rows = self._list()
        expected = {
            self.melding.id: "MELDING",
            self.meerwerk_instant.id: "MEERWERK",
            self.meerwerk_proposal.id: "MEERWERK",
            self.plain.id: "TICKET",
            self.provider_report.id: "TICKET",
            self.recurring.id: "TICKET",
        }
        for ticket_id, kind in expected.items():
            self.assertIn(ticket_id, rows)
            self.assertEqual(rows[ticket_id]["kind"], kind, ticket_id)

    def test_kind_adds_no_query_per_row(self):
        client = self._api(self.super_admin)
        with CaptureQueriesContext(connection) as before:
            client.get(TICKETS_URL, {"page_size": 100, **TICKETS_PAGE})
        for i in range(3):
            self._ticket(
                created_by=self.cust_user,
                title=f"More melding {i}",
                ticket_type=TicketType.REPORT,
            )
            self._ticket(created_by=self.admin, title=f"More ticket {i}")
            self._make_instant_ticket()
        with CaptureQueriesContext(connection) as after:
            response = client.get(TICKETS_URL, {"page_size": 100, **TICKETS_PAGE})
        # Six queue rows more; the three new spawned rows stay out.
        self.assertEqual(len(_rows(response)), len(self.queue_ids) + 6)
        self.assertEqual(
            len(after.captured_queries),
            len(before.captured_queries),
            "kind must read the row, never fetch per row",
        )


class SpawnedTicketDeepLinkTests(_Fixture):
    def test_a_spawned_ticket_still_opens_by_id(self):
        # Absent from the queue is not absent from the system: the
        # extra-work pages and My schedule link straight to the ticket.
        for ticket in (self.meerwerk_instant, self.meerwerk_proposal):
            detail = self._api(self.super_admin).get(f"{TICKETS_URL}{ticket.id}/")
            self.assertEqual(detail.status_code, 200, detail.data)
            self.assertEqual(detail.data["id"], ticket.id)
            self.assertEqual(detail.data["kind"], "MEERWERK")
            self.assertIsNotNone(detail.data["extra_work_origin"])


class StatsExcludeExtraWorkTests(_Fixture):
    def test_stats_count_the_rows_the_tickets_page_lists(self):
        data = self._stats(**TICKETS_PAGE)
        self.assertEqual(data["total"], len(self.queue_ids))
        self.assertEqual(data["by_status"].get("OPEN", 0), len(self.queue_ids))
        self.assertEqual(data["my_open"], len(self.queue_ids))

    def test_stats_without_the_parameter_count_everything(self):
        self.assertEqual(self._stats()["total"], len(self.all_ids))

    def test_stats_halves_sum_to_the_whole(self):
        chargeable = self._stats(is_extra_work="true")["total"]
        ordinary = self._stats(is_extra_work="false")["total"]
        self.assertEqual(chargeable, len(self.spawned_ids))
        self.assertEqual(ordinary, len(self.queue_ids))
        self.assertEqual(chargeable + ordinary, self._stats()["total"])

    def test_stats_ignore_origin(self):
        self.assertEqual(self._stats(origin="meerwerk")["total"], len(self.all_ids))
        self.assertEqual(
            self._stats(origin="meerwerk", **TICKETS_PAGE)["total"],
            len(self.queue_ids),
        )

    def test_stats_exclusion_holds_with_and_without_a_period(self):
        # The empty tab's sentence ("No new tickets created in September
        # yet. Earlier: N open") is two calls: one with the month, one
        # without. Both must leave the spawned tickets out.
        for ticket in (self.melding, self.meerwerk_instant):
            ticket.created_at = ticket.created_at - datetime.timedelta(days=90)
            ticket.save(update_fields=["created_at"])
        today = datetime.date.today().isoformat()
        narrowed = self._stats(date_from=today, date_to=today, **TICKETS_PAGE)
        # Today: plain, provider_report, recurring (the melding moved back;
        # the spawned proposal ticket is today but excluded).
        self.assertEqual(narrowed["total"], 3)
        all_time = self._stats(**TICKETS_PAGE)
        self.assertEqual(all_time["total"], len(self.queue_ids))
        # And without the page's parameter the moved spawned ticket is
        # back in the all-time count, so the exclusion is the parameter's.
        self.assertEqual(self._stats()["total"], len(self.all_ids))
