"""
P-9 D2 -- the Tickets queue shows every operational ticket, whatever its
origin, and says on the row WHERE it came from.

Pins:

  * `kind` on the LIST row (`TicketListSerializer`), the same three
    values the detail's fact block shows, from the same rule
    (`detail_facts.ticket_kind`): a customer's REPORT is MELDING, a
    ticket spawned from an extra work is MEERWERK (both spawn paths), a
    provider-created ticket is TICKET -- even when the provider typed it
    REPORT, which is why `?type=REPORT` cannot be the "Melding" filter;
  * an occurrence ticket is kind TICKET with a populated
    `occurrence_origin` (the row's "Recurring" reading);
  * `kind` adds no query per row (the author is already select_related);
  * `?origin=melding|meerwerk|recurring|ticket` partitions the list
    exactly the way the column labels the rows, the four sum to the
    total, and a junk value is no opinion (200, unfiltered);
  * `/api/tickets/stats/` follows the same parameter, so the tab counts
    describe the rows under them under every setting of the control.
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
ORIGINS = ("melding", "meerwerk", "recurring", "ticket")


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
            description="P-9 fixture",
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
        # One row of every origin the column can print, plus the trap:
        # a provider-created ticket TYPED "REPORT".
        self.melding = self._ticket(
            created_by=self.cust_user,
            title="Customer melding",
            ticket_type=TicketType.REPORT,
        )
        _ew, _item, self.meerwerk_instant = self._make_instant_ticket()
        # crmtest: every EW-spawned ticket is typed REPORT too (the spawn
        # copies the request's type). Mirrored, so the `type=REPORT`
        # assertion below fails the way the real data would.
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
        self.expected_origin = {
            "melding": {self.melding.id},
            "meerwerk": {self.meerwerk_instant.id, self.meerwerk_proposal.id},
            "recurring": {self.recurring.id},
            "ticket": {self.plain.id, self.provider_report.id},
        }
        self.all_ids = set().union(*self.expected_origin.values())

    def _list(self, **params):
        response = self._api(self.super_admin).get(
            TICKETS_URL, {"page_size": 100, **params}
        )
        self.assertEqual(response.status_code, 200, response.data)
        return {row["id"]: row for row in _rows(response)}


class ListRowKindTests(_Fixture):
    def test_every_row_carries_the_detail_kind(self):
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
            detail = self._api(self.super_admin).get(f"{TICKETS_URL}{ticket_id}/")
            self.assertEqual(detail.status_code, 200, detail.data)
            self.assertEqual(detail.data["kind"], rows[ticket_id]["kind"])

    def test_recurring_row_is_a_ticket_with_an_occurrence_origin(self):
        rows = self._list()
        row = rows[self.recurring.id]
        self.assertEqual(row["kind"], "TICKET")
        self.assertIsNotNone(row["occurrence_origin"])
        self.assertEqual(
            row["occurrence_origin"]["recurring_job_title"], "Weekly clean"
        )
        for other in (self.plain, self.melding, self.meerwerk_instant):
            self.assertIsNone(rows[other.id]["occurrence_origin"])

    def test_kind_adds_no_query_per_row(self):
        client = self._api(self.super_admin)
        with CaptureQueriesContext(connection) as before:
            client.get(TICKETS_URL, {"page_size": 100})
        for i in range(3):
            self._ticket(
                created_by=self.cust_user,
                title=f"More melding {i}",
                ticket_type=TicketType.REPORT,
            )
            self._ticket(created_by=self.admin, title=f"More ticket {i}")
            self._make_instant_ticket()
        with CaptureQueriesContext(connection) as after:
            response = client.get(TICKETS_URL, {"page_size": 100})
        self.assertEqual(len(_rows(response)), len(self.all_ids) + 9)
        self.assertEqual(
            len(after.captured_queries),
            len(before.captured_queries),
            "kind must read the row, never fetch per row",
        )


class OriginFilterTests(_Fixture):
    def test_origin_partitions_the_list_exactly(self):
        seen = []
        for origin in ORIGINS:
            ids = set(self._list(origin=origin))
            self.assertEqual(ids, self.expected_origin[origin], origin)
            seen.append(ids)
        union = set().union(*seen)
        self.assertEqual(union, self.all_ids)
        self.assertEqual(sum(len(s) for s in seen), len(self.all_ids))

    def test_origin_filter_agrees_with_the_column(self):
        label_of = {
            "melding": lambda r: r["kind"] == "MELDING",
            "meerwerk": lambda r: r["kind"] == "MEERWERK",
            "recurring": lambda r: r["kind"] == "TICKET"
            and r["occurrence_origin"] is not None,
            "ticket": lambda r: r["kind"] == "TICKET"
            and r["occurrence_origin"] is None,
        }
        for origin in ORIGINS:
            for row in self._list(origin=origin).values():
                self.assertTrue(label_of[origin](row), (origin, row["id"]))

    def test_junk_origin_is_no_opinion(self):
        self.assertEqual(set(self._list(origin="banana")), self.all_ids)
        self.assertEqual(set(self._list(origin="")), self.all_ids)

    def test_type_report_is_not_the_melding_filter(self):
        # The reason `?origin=` exists: on the real data every EW-spawned
        # ticket is typed REPORT, and a provider may type one REPORT too.
        ids = set(self._list(type="REPORT"))
        self.assertIn(self.meerwerk_instant.id, ids)
        self.assertIn(self.provider_report.id, ids)
        self.assertNotEqual(ids, self.expected_origin["melding"])

    def test_origin_composes_with_the_tab_statuses(self):
        self.plain.status = TicketStatus.IN_PROGRESS
        self.plain.save(update_fields=["status"])
        ids = set(self._list(origin="ticket", status__in="OPEN,ACKNOWLEDGED"))
        self.assertEqual(ids, {self.provider_report.id})


class StatsFollowOriginTests(_Fixture):
    def _stats(self, **params):
        response = self._api(self.super_admin).get(STATS_URL, params)
        self.assertEqual(response.status_code, 200, response.data)
        return response.data

    def test_stats_count_the_rows_the_list_returns(self):
        total = self._stats()["total"]
        self.assertEqual(total, len(self.all_ids))
        summed = 0
        for origin in ORIGINS:
            data = self._stats(origin=origin)
            self.assertEqual(data["total"], len(self.expected_origin[origin]), origin)
            self.assertEqual(data["by_status"].get("OPEN", 0), data["total"])
            summed += data["total"]
        self.assertEqual(summed, total)

    def test_stats_junk_origin_is_no_opinion(self):
        self.assertEqual(self._stats(origin="banana")["total"], len(self.all_ids))

    def test_stats_origin_composes_with_the_period(self):
        self.melding.created_at = self.melding.created_at - datetime.timedelta(days=90)
        self.melding.save(update_fields=["created_at"])
        today = datetime.date.today().isoformat()
        narrowed = self._stats(
            origin="melding", date_from=today, date_to=today
        )
        self.assertEqual(narrowed["total"], 0)
        self.assertEqual(self._stats(origin="melding")["total"], 1)
