"""
Sprint 184 — the dates must travel with the work.

§1  The extra work's dates reach its ticket through the LINK, not
    through a copy. `extra_work_origin` carries them; nothing is
    duplicated onto the Ticket, so editing a date on the extra work
    moves what the ticket shows in the same instant. The one exception
    is `provider_planned_date`, which is an ACTION: planning the work
    moves the spawned ticket's own schedule.
§3  A melding can carry the customer's wanted date — a WISH, never a
    deadline — and it survives conversion into `preferred_date`.

The read/write split in one line: three dates are borrowed on read;
`provider_planned_date` writes, because when the provider commits to a
day the work moves.
"""
from __future__ import annotations

import datetime
from decimal import Decimal

from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient

from extra_work.dates import apply_extra_work_dates
from extra_work.models import ExtraWorkRequest, ExtraWorkStatus
from extra_work.planned_date import apply_planned_date_to_tickets
from tickets.models import Ticket, TicketScheduleStatus, TicketStatus
from tickets.serializers import resolve_extra_work_origin_core

from .test_sprint29_batch29_8_operational_states import (  # noqa: F401
    _OperationalFixtureMixin,
)

from django.test import TestCase


PREFERRED = datetime.date(2026, 6, 1)
PLANNED_END = datetime.date(2026, 6, 3)
DEADLINE = datetime.date(2026, 6, 30)
PLANNED = datetime.date(2026, 6, 10)


class OriginCarriesTheDatesTests(_OperationalFixtureMixin, TestCase):
    """§1 read — borrowed through the link, never copied."""

    @classmethod
    def setUpTestData(cls):
        cls._setup_fixture(suffix="184-read")

    def setUp(self):
        super().setUp()
        self.ew.preferred_date = PREFERRED
        self.ew.planned_end_date = PLANNED_END
        self.ew.deadline = DEADLINE
        self.ew.provider_planned_date = PLANNED
        self.ew.save(
            update_fields=[
                "preferred_date",
                "planned_end_date",
                "deadline",
                "provider_planned_date",
            ]
        )

    def test_the_origin_payload_carries_all_four_dates(self):
        origin = resolve_extra_work_origin_core(self.ticket_a)
        self.assertIsNotNone(origin)
        # ISO strings, not `date` objects — the resolver formats them
        # so `response.data` and the wire agree (see `_iso_date`).
        self.assertEqual(origin["preferred_date"], PREFERRED.isoformat())
        self.assertEqual(origin["planned_end_date"], PLANNED_END.isoformat())
        self.assertEqual(origin["deadline"], DEADLINE.isoformat())
        self.assertEqual(
            origin["provider_planned_date"], PLANNED.isoformat()
        )

    def test_the_dates_are_not_copied_onto_the_ticket(self):
        # THE POINT OF §1. If a date were copied, the Ticket would carry
        # its own column and this assertion would fail — and the copy
        # would be silently wrong the first time somebody edited the
        # extra work.
        ticket_fields = {f.name for f in Ticket._meta.get_fields()}
        for name in ("preferred_date", "planned_end_date", "deadline"):
            self.assertNotIn(
                name,
                ticket_fields,
                f"Ticket grew its own {name} — that is the copy §1 forbids",
            )

    def test_editing_the_extra_work_moves_what_the_ticket_shows(self):
        # The consequence of borrowing rather than copying, stated as a
        # behaviour: no sync step, no staleness window.
        moved = datetime.date(2026, 7, 15)
        self.ew.deadline = moved
        self.ew.save(update_fields=["deadline"])

        ticket = Ticket.objects.get(pk=self.ticket_a.pk)
        self.assertEqual(
            resolve_extra_work_origin_core(ticket)["deadline"],
            moved.isoformat(),
        )

    def test_a_ticket_with_no_extra_work_has_no_origin_at_all(self):
        plain = Ticket.objects.create(
            company=self.company,
            building=self.building,
            customer=self.customer,
            created_by=self.admin,
            title="Plain ticket",
            description="d",
            status=TicketStatus.OPEN,
        )
        self.assertIsNone(resolve_extra_work_origin_core(plain))

    def test_the_ticket_endpoints_render_the_dates(self):
        # Every field exposed gets a test that RENDERS the endpoint
        # carrying it — a resolver test alone would not catch a missing
        # `fields` entry.
        client = APIClient()
        client.force_authenticate(user=self.admin)

        detail = client.get(f"/api/tickets/{self.ticket_a.id}/")
        self.assertEqual(detail.status_code, status.HTTP_200_OK, detail.data)
        origin = detail.data["extra_work_origin"]
        for key in (
            "preferred_date",
            "planned_end_date",
            "deadline",
            "provider_planned_date",
        ):
            self.assertIn(key, origin)
        self.assertEqual(origin["deadline"], DEADLINE.isoformat())

        listing = client.get("/api/tickets/", {"page_size": 100})
        self.assertEqual(listing.status_code, status.HTTP_200_OK)
        row = next(
            r
            for r in listing.data["results"]
            if r["id"] == self.ticket_a.id
        )
        self.assertEqual(
            row["extra_work_origin"]["deadline"], DEADLINE.isoformat()
        )


class PlannedDateMovesTheWorkTests(_OperationalFixtureMixin, TestCase):
    """§1 write — planning the work moves the work."""

    @classmethod
    def setUpTestData(cls):
        cls._setup_fixture(suffix="184-write")

    def _expected(self, day):
        return timezone.make_aware(
            datetime.datetime.combine(day, datetime.time.min)
        )

    def test_planning_moves_an_unscheduled_ticket(self):
        self.ticket_a.schedule_status = TicketScheduleStatus.UNSCHEDULED
        self.ticket_a.scheduled_start_at = None
        self.ticket_a.save(
            update_fields=["schedule_status", "scheduled_start_at"]
        )
        self.ew.provider_planned_date = PLANNED
        self.ew.save(update_fields=["provider_planned_date"])

        result = apply_planned_date_to_tickets(self.ew)

        self.ticket_a.refresh_from_db()
        self.assertIn(self.ticket_a.id, result["moved"])
        self.assertEqual(
            self.ticket_a.scheduled_start_at, self._expected(PLANNED)
        )
        self.assertEqual(
            str(self.ticket_a.schedule_status),
            str(TicketScheduleStatus.SCHEDULED),
        )

    def test_a_hand_rescheduled_ticket_keeps_its_own_date(self):
        # THE DECISION. Somebody looked at this ticket, moved it, and
        # wrote down why. Overwriting that from a field on the parent
        # would throw away a human decision AND its stated reason, and
        # the person who made it would get no signal at all.
        own = self._expected(datetime.date(2026, 6, 20))
        self.ticket_a.scheduled_start_at = own
        self.ticket_a.schedule_status = TicketScheduleStatus.RESCHEDULED
        self.ticket_a.reschedule_reason = "Customer asked for the 20th"
        self.ticket_a.save(
            update_fields=[
                "scheduled_start_at",
                "schedule_status",
                "reschedule_reason",
            ]
        )
        self.ew.provider_planned_date = PLANNED
        self.ew.save(update_fields=["provider_planned_date"])

        result = apply_planned_date_to_tickets(self.ew)

        self.ticket_a.refresh_from_db()
        self.assertEqual(self.ticket_a.scheduled_start_at, own)
        # ...and it is REPORTED, not silently skipped.
        self.assertIn(self.ticket_a.id, result["kept_own_date"])
        self.assertNotIn(self.ticket_a.id, result["moved"])

    def test_clearing_the_planned_date_does_not_unschedule_tickets(self):
        # Un-planning an extra work is not a statement that its tickets
        # should become undated.
        original = self._expected(datetime.date(2026, 6, 5))
        self.ticket_a.scheduled_start_at = original
        self.ticket_a.schedule_status = TicketScheduleStatus.SCHEDULED
        self.ticket_a.save(
            update_fields=["scheduled_start_at", "schedule_status"]
        )
        self.ew.provider_planned_date = None
        self.ew.save(update_fields=["provider_planned_date"])

        result = apply_planned_date_to_tickets(self.ew)

        self.ticket_a.refresh_from_db()
        self.assertEqual(self.ticket_a.scheduled_start_at, original)
        self.assertEqual(result, {"moved": [], "kept_own_date": []})

    def test_a_ticket_already_on_the_day_is_not_reported_as_moved(self):
        self.ticket_a.scheduled_start_at = self._expected(PLANNED)
        self.ticket_a.schedule_status = TicketScheduleStatus.SCHEDULED
        self.ticket_a.save(
            update_fields=["scheduled_start_at", "schedule_status"]
        )
        self.ew.provider_planned_date = PLANNED
        self.ew.save(update_fields=["provider_planned_date"])

        result = apply_planned_date_to_tickets(self.ew)
        # The fixture spawns TWO tickets from this extra work, and the
        # sibling legitimately moves; the assertion is about the one
        # that was already on the day.
        self.assertNotIn(self.ticket_a.id, result["moved"])

    def test_the_dates_writer_drives_it_and_reports_back(self):
        # The single write path (`apply_extra_work_dates`) is what both
        # the per-request PATCH and the bulk action call, so hooking it
        # there is what makes this reachable from either.
        self.ticket_a.schedule_status = TicketScheduleStatus.UNSCHEDULED
        self.ticket_a.save(update_fields=["schedule_status"])

        error = apply_extra_work_dates(
            self.ew, {"provider_planned_date": PLANNED}
        )
        self.assertIsNone(error)
        self.assertIn(
            self.ticket_a.id,
            self.ew.planned_date_ticket_result["moved"],
        )

    def test_writing_only_a_deadline_does_not_touch_schedules(self):
        # `deadline` is borrowed on read. It must not move anything.
        before = self._expected(datetime.date(2026, 6, 5))
        self.ticket_a.scheduled_start_at = before
        self.ticket_a.schedule_status = TicketScheduleStatus.SCHEDULED
        self.ticket_a.save(
            update_fields=["scheduled_start_at", "schedule_status"]
        )

        apply_extra_work_dates(self.ew, {"deadline": DEADLINE})

        self.ticket_a.refresh_from_db()
        self.assertEqual(self.ticket_a.scheduled_start_at, before)
        self.assertIsNone(
            getattr(self.ew, "planned_date_ticket_result", None)
        )


class MeldingWantedDateTests(_OperationalFixtureMixin, TestCase):
    """§3 — the customer's wish, and it survives conversion."""

    @classmethod
    def setUpTestData(cls):
        cls._setup_fixture(suffix="184-wish")

    def test_a_deadline_is_not_offered_on_a_ticket(self):
        # The distinction the system settled and must keep: a deadline is
        # a PROVIDER COMMITMENT. A customer who could type one would be
        # setting the provider's commitment, and the overdue rules read
        # deadlines.
        ticket_fields = {f.name for f in Ticket._meta.get_fields()}
        self.assertIn("customer_wanted_date", ticket_fields)
        self.assertNotIn("deadline", ticket_fields)

    def test_a_customer_can_state_a_wanted_date_when_opening_a_melding(self):
        client = APIClient()
        client.force_authenticate(user=self.cust_user)
        response = client.post(
            "/api/tickets/",
            {
                "title": "Lift is dirty",
                "description": "Please clean the lift",
                "type": "REPORT",
                "priority": "NORMAL",
                "building": self.building.id,
                "customer": self.customer.id,
                "customer_wanted_date": "2026-06-01",
            },
            format="json",
        )
        self.assertEqual(
            response.status_code, status.HTTP_201_CREATED, response.data
        )
        self.assertEqual(response.data["customer_wanted_date"], "2026-06-01")
        ticket = Ticket.objects.get(pk=response.data["id"])
        self.assertEqual(ticket.customer_wanted_date, PREFERRED)

    def test_a_melding_without_one_is_still_valid(self):
        client = APIClient()
        client.force_authenticate(user=self.cust_user)
        response = client.post(
            "/api/tickets/",
            {
                "title": "No date given",
                "description": "d",
                "type": "REPORT",
                "priority": "NORMAL",
                "building": self.building.id,
                "customer": self.customer.id,
            },
            format="json",
        )
        self.assertEqual(
            response.status_code, status.HTTP_201_CREATED, response.data
        )
        self.assertIsNone(
            Ticket.objects.get(pk=response.data["id"]).customer_wanted_date
        )

    def test_the_detail_endpoint_renders_it(self):
        ticket = Ticket.objects.create(
            company=self.company,
            building=self.building,
            customer=self.customer,
            created_by=self.cust_user,
            title="Wanted date",
            description="d",
            status=TicketStatus.OPEN,
            customer_wanted_date=PREFERRED,
        )
        client = APIClient()
        client.force_authenticate(user=self.admin)
        response = client.get(f"/api/tickets/{ticket.id}/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            response.data["customer_wanted_date"], PREFERRED.isoformat()
        )

    def test_the_wanted_date_survives_conversion(self):
        # A date the customer typed that vanishes at conversion is worse
        # than never having asked for it.
        from extra_work.conversion import convert_ticket_to_extra_work

        ticket = Ticket.objects.create(
            company=self.company,
            building=self.building,
            customer=self.customer,
            created_by=self.cust_user,
            title="Convert me",
            description="d",
            status=TicketStatus.OPEN,
            customer_wanted_date=PREFERRED,
        )
        ew, _spawned = convert_ticket_to_extra_work(
            ticket,
            actor=self.admin,
            request_intent=self._conversion_intent(),
            line_items_data=[self._conversion_line()],
        )
        self.assertEqual(ew.preferred_date, PREFERRED)

    def test_conversion_without_a_wanted_date_leaves_preferred_null(self):
        # NULL stays NULL rather than being invented from the conversion
        # day.
        from extra_work.conversion import convert_ticket_to_extra_work

        ticket = Ticket.objects.create(
            company=self.company,
            building=self.building,
            customer=self.customer,
            created_by=self.cust_user,
            title="No wish",
            description="d",
            status=TicketStatus.OPEN,
        )
        ew, _spawned = convert_ticket_to_extra_work(
            ticket,
            actor=self.admin,
            request_intent=self._conversion_intent(),
            line_items_data=[self._conversion_line()],
        )
        self.assertIsNone(ew.preferred_date)

    # -- helpers -------------------------------------------------------

    def _conversion_intent(self):
        from extra_work.models import ExtraWorkRequestIntent

        return ExtraWorkRequestIntent.REQUEST_QUOTE

    def _conversion_line(self):
        return {
            "service": self.service,
            "quantity": Decimal("1.00"),
            "unit_type": self.service.unit_type,
            "requested_date": PREFERRED,
            "customer_note": "",
        }
