"""W-H — the Scheduling card's four answers, on the wire.

The card was asked when a job starts, when it ends, how long it runs and
who planned it, and could answer only the first. Three of the four were
already in the database and had no way out of it. These tests lock the
routes they now take:

  * `scheduled_end_at` round-trips through the schedule endpoint, so
    "when does it end" and therefore "how long" have a stored answer.
  * `schedule_planned_by_name` / `schedule_planned_at` name the operator
    who set the current schedule, read off the annotation row that has
    recorded them since Sprint 9B — nothing new is stored, and a
    CUSTOMER_USER gets neither.
  * `extra_work_origin` carries the provider's committed window as a
    PAIR, so a ticket spawned from a job planned Monday-to-Wednesday can
    show both ends rather than only the Monday.
"""
from __future__ import annotations

from datetime import date, timedelta

from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from tickets.models import Ticket, TicketStatus
from tickets.schedule_history import SCHEDULE_NOTE_PREFIX, latest_schedule_change
from tickets.tests.test_extra_work_origin import ExtraWorkOriginFixtureMixin
from tickets.tests.test_sprint9b_scheduling import (
    SchedulingBaseTest,
    _schedule_url,
)


def _detail_url(ticket):
    return f"/api/tickets/{ticket.id}/"


class ScheduleWindowTests(SchedulingBaseTest):
    """When it starts, when it ends."""

    def test_end_date_round_trips_through_the_endpoint(self):
        self._auth(self.bm)
        start = timezone.now() + timedelta(days=2)
        end = start + timedelta(days=2)
        resp = self.client.post(
            _schedule_url(self.ticket),
            {
                "scheduled_start_at": start.isoformat(),
                "scheduled_end_at": end.isoformat(),
            },
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK, resp.data)
        self.ticket.refresh_from_db()
        self.assertIsNotNone(self.ticket.scheduled_end_at)

        read = self.client.get(_detail_url(self.ticket))
        self.assertEqual(read.status_code, status.HTTP_200_OK, read.data)
        self.assertIsNotNone(read.data["scheduled_end_at"])


class SchedulePlannerTests(SchedulingBaseTest):
    """Who planned it."""

    def _plan_as(self, actor, **extra):
        self._auth(actor)
        start = timezone.now() + timedelta(days=3)
        payload = {"scheduled_start_at": start.isoformat()}
        payload.update(extra)
        resp = self.client.post(
            _schedule_url(self.ticket), payload, format="json"
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK, resp.data)
        self.ticket.refresh_from_db()
        return resp

    def test_unplanned_ticket_names_nobody(self):
        self._auth(self.sa)
        resp = self.client.get(_detail_url(self.ticket))
        self.assertEqual(resp.status_code, status.HTTP_200_OK, resp.data)
        self.assertIsNone(resp.data["schedule_planned_by_name"])
        self.assertIsNone(resp.data["schedule_planned_at"])

    def test_the_operator_who_set_it_is_named(self):
        self._plan_as(self.bm)
        self._auth(self.sa)
        resp = self.client.get(_detail_url(self.ticket))
        expected = (self.bm.full_name or "").strip() or self.bm.email
        self.assertEqual(resp.data["schedule_planned_by_name"], expected)
        self.assertIsNotNone(resp.data["schedule_planned_at"])

    def test_a_reschedule_names_whoever_moved_it_last(self):
        self._plan_as(self.bm)
        self._plan_as(self.ca, reschedule_reason="crew swapped")
        self._auth(self.sa)
        resp = self.client.get(_detail_url(self.ticket))
        expected = (self.ca.full_name or "").strip() or self.ca.email
        self.assertEqual(resp.data["schedule_planned_by_name"], expected)

    def test_the_planner_is_provider_side_only(self):
        """Which employee typed the date is internal staffing detail,
        gated exactly like `reschedule_reason` beside it."""
        cust_ticket = Ticket.objects.create(
            company=self.company,
            building=self.building,
            customer=self.customer,
            created_by=self.customer_user,
            title="cust-owned",
            description="d",
            status=TicketStatus.OPEN,
        )
        self._auth(self.bm)
        start = timezone.now() + timedelta(days=4)
        planned = self.client.post(
            _schedule_url(cust_ticket),
            {"scheduled_start_at": start.isoformat()},
            format="json",
        )
        self.assertEqual(planned.status_code, status.HTTP_200_OK, planned.data)

        self._auth(self.customer_user)
        resp = self.client.get(_detail_url(cust_ticket))
        self.assertEqual(resp.status_code, status.HTTP_200_OK, resp.data)
        # The customer still sees WHEN the work is due...
        self.assertIsNotNone(resp.data["scheduled_start_at"])
        # ...and not who inside the provider arranged it.
        self.assertIsNone(resp.data["schedule_planned_by_name"])
        self.assertIsNone(resp.data["schedule_planned_at"])

    def test_the_reader_recognises_the_row_by_the_shared_prefix(self):
        """The writer and the reader hold ONE constant between them.

        If the note wording ever changes without the prefix moving with
        it, this fails here rather than silently emptying the card.
        """
        self._plan_as(self.bm)
        row = latest_schedule_change(self.ticket)
        self.assertIsNotNone(row)
        self.assertTrue(row.note.startswith(SCHEDULE_NOTE_PREFIX))
        self.assertEqual(row.changed_by_id, self.bm.id)

    def test_a_workflow_move_is_not_mistaken_for_a_plan(self):
        """Only schedule rows count. An ordinary status change writes a
        history row too, and must not end up answering "who planned it"."""
        self._plan_as(self.bm)
        self._auth(self.sa)
        moved = self.client.post(
            f"/api/tickets/{self.ticket.id}/status/",
            {"to_status": TicketStatus.IN_PROGRESS, "note": "starting"},
            format="json",
        )
        self.assertEqual(moved.status_code, status.HTTP_200_OK, moved.data)
        resp = self.client.get(_detail_url(self.ticket))
        expected = (self.bm.full_name or "").strip() or self.bm.email
        self.assertEqual(resp.data["schedule_planned_by_name"], expected)


class CommittedWindowOnOriginTests(ExtraWorkOriginFixtureMixin, APITestCase):
    """What the extra work committed to — both ends of it."""

    @classmethod
    def setUpTestData(cls):
        cls._setup_fixture()

    def test_origin_carries_both_ends_of_the_committed_window(self):
        ew, _item, ticket = self._make_instant_ticket()
        ew.provider_planned_date = date(2026, 9, 7)
        ew.provider_planned_end_date = date(2026, 9, 9)
        ew.preferred_date = date(2026, 9, 4)
        ew.planned_end_date = date(2026, 9, 6)
        ew.deadline = date(2026, 9, 11)
        ew.save(
            update_fields=[
                "provider_planned_date",
                "provider_planned_end_date",
                "preferred_date",
                "planned_end_date",
                "deadline",
            ]
        )

        client = self._api(self.super_admin)
        resp = client.get(_detail_url(ticket))
        self.assertEqual(resp.status_code, status.HTTP_200_OK, resp.data)
        origin = resp.data["extra_work_origin"]
        self.assertEqual(origin["provider_planned_date"], "2026-09-07")
        self.assertEqual(origin["provider_planned_end_date"], "2026-09-09")
        self.assertEqual(origin["preferred_date"], "2026-09-04")
        self.assertEqual(origin["planned_end_date"], "2026-09-06")
        self.assertEqual(origin["deadline"], "2026-09-11")

    def test_an_unplanned_parent_commits_to_nothing(self):
        _ew, _item, ticket = self._make_instant_ticket()
        client = self._api(self.super_admin)
        resp = client.get(_detail_url(ticket))
        origin = resp.data["extra_work_origin"]
        self.assertIsNone(origin["provider_planned_date"])
        self.assertIsNone(origin["provider_planned_end_date"])
