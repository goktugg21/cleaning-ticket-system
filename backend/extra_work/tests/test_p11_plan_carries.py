"""P-11 A8 — the plan made on the request carries onto the ticket.

The owner planned the request (dates, Ahmet 3 h + 4 h, Gökhan 2 h),
priced it, started it — and the spawned ticket said "Not planned yet"
with undated slots. Since P-1 every spawn path seeded `_UNPLANNED` and
`assignment_carryover` dated the slots from the ticket's (empty)
schedule; nothing read the plan a person had already made on the
request.

Pins:

  * `plan_seed` — a spawned ticket is born on the PROVIDER's plan when
    one exists (local midnight, the end only when it is after the
    start, `SCHEDULED`), else unplanned exactly as P-1 ruled — and all
    three spawn paths read the one function;
  * the spawn end to end: the ticket is dated, each person's slot is
    dated from their OWN planned days (09:00/17:00 —
    `_sync_slot_windows`'s clocks, so a slot dated at spawn and one
    moved by a later plan edit are indistinguishable), a person planned
    without days inherits the ticket's window, managers as before;
  * the board: the spawned ticket is ON its day, not in "Not planned
    yet".
"""
from __future__ import annotations

import datetime

from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from accounts.models import UserRole
from buildings.models import BuildingManagerAssignment, BuildingStaffVisibility
from extra_work.instant_tickets import plan_seed
from extra_work.models import (
    ExtraWorkAssignment,
    ExtraWorkAssignmentRole,
    ExtraWorkPlannedHours,
    ExtraWorkRequest,
    ExtraWorkStatus,
)
from extra_work.proposal_tickets import spawn_tickets_for_extra_work_request
from test_utils import TenantFixtureMixin
from tickets.models import (
    TicketManagerAssignment,
    TicketScheduleStatus,
    TicketStaffAssignment,
)

WORK_PLAN_URL = "/api/tickets/work-plan/"


def _local(day: datetime.date, hour: int) -> datetime.datetime:
    return timezone.make_aware(
        datetime.datetime.combine(day, datetime.time(hour, 0))
    )


class PlanCarriesFixture(TenantFixtureMixin):
    def setUp(self):
        super().setUp()
        self.today = timezone.localdate()
        self.manager = self.make_user(
            "p11-manager@example.com", UserRole.BUILDING_MANAGER
        )
        BuildingManagerAssignment.objects.create(
            user=self.manager, building=self.building
        )
        self.worker_a = self.make_user("p11-ahmet@example.com", UserRole.STAFF)
        self.worker_b = self.make_user("p11-gokhan@example.com", UserRole.STAFF)
        for worker in (self.worker_a, self.worker_b):
            BuildingStaffVisibility.objects.create(
                user=worker, building=self.building
            )

    def make_request(self, *, planned=None, planned_end=None):
        request = ExtraWorkRequest.objects.create(
            company=self.company,
            building=self.building,
            customer=self.customer,
            created_by=self.super_admin,
            title="Opleverschoonmaak kantoor 2",
            description="x",
            status=ExtraWorkStatus.CUSTOMER_APPROVED,
            provider_planned_date=planned,
            provider_planned_end_date=planned_end,
        )
        ExtraWorkAssignment.objects.create(
            extra_work_request=request,
            user=self.manager,
            role=ExtraWorkAssignmentRole.MANAGER,
        )
        for worker in (self.worker_a, self.worker_b):
            ExtraWorkAssignment.objects.create(
                extra_work_request=request,
                user=worker,
                role=ExtraWorkAssignmentRole.WORKER,
            )
        return request

    def plan_hours(self, request, user, day, hours):
        ExtraWorkPlannedHours.objects.create(
            extra_work_request=request,
            user=user,
            date=day,
            hours=hours,
            set_by=self.super_admin,
        )


class PlanSeedTests(PlanCarriesFixture, APITestCase):
    def test_a_planned_request_seeds_the_window_at_local_midnight(self):
        request = self.make_request(
            planned=self.today, planned_end=self.today + datetime.timedelta(days=2)
        )
        start, end, schedule_status = plan_seed(request)
        self.assertEqual(start, _local(self.today, 0))
        self.assertEqual(end, _local(self.today + datetime.timedelta(days=2), 0))
        self.assertEqual(schedule_status, TicketScheduleStatus.SCHEDULED)

    def test_a_one_day_plan_carries_no_end(self):
        request = self.make_request(planned=self.today, planned_end=self.today)
        start, end, schedule_status = plan_seed(request)
        self.assertEqual(start, _local(self.today, 0))
        self.assertIsNone(end)
        self.assertEqual(schedule_status, TicketScheduleStatus.SCHEDULED)

    def test_an_unplanned_request_stays_unplanned_p1_stands(self):
        request = self.make_request()
        self.assertEqual(
            plan_seed(request), (None, None, TicketScheduleStatus.UNSCHEDULED)
        )

    def test_all_three_spawn_paths_read_the_one_seed(self):
        # "It is imported" and "it runs" are different claims — the end
        # to end below runs the legacy path; this pins that the other
        # two modules resolve to the same function object.
        from extra_work import instant_tickets, proposal_tickets

        self.assertIs(proposal_tickets.plan_seed, instant_tickets.plan_seed)


class PlanCarriesOntoTheTicketTests(PlanCarriesFixture, APITestCase):
    def _spawn(self, request):
        tickets = spawn_tickets_for_extra_work_request(
            request, actor=self.super_admin
        )
        self.assertEqual(len(tickets), 1)
        return tickets[0]

    def test_the_owner_scenario_day_people_and_hours_arrive(self):
        tomorrow = self.today + datetime.timedelta(days=1)
        request = self.make_request(planned=self.today, planned_end=tomorrow)
        self.plan_hours(request, self.worker_a, self.today, "3.00")
        self.plan_hours(request, self.worker_a, tomorrow, "4.00")
        self.plan_hours(request, self.worker_b, self.today, "2.00")

        ticket = self._spawn(request)

        self.assertEqual(ticket.scheduled_start_at, _local(self.today, 0))
        self.assertEqual(ticket.scheduled_end_at, _local(tomorrow, 0))
        self.assertEqual(
            str(ticket.schedule_status), str(TicketScheduleStatus.SCHEDULED)
        )
        # Each person's slot carries THEIR planned days.
        slot_a = TicketStaffAssignment.objects.get(
            ticket=ticket, user=self.worker_a
        )
        self.assertEqual(slot_a.scheduled_start_at, _local(self.today, 9))
        self.assertEqual(slot_a.scheduled_end_at, _local(tomorrow, 17))
        slot_b = TicketStaffAssignment.objects.get(
            ticket=ticket, user=self.worker_b
        )
        self.assertEqual(slot_b.scheduled_start_at, _local(self.today, 9))
        self.assertIsNone(slot_b.scheduled_end_at)
        # Managers as before.
        self.assertEqual(
            TicketManagerAssignment.objects.filter(
                ticket=ticket, user=self.manager
            ).count(),
            1,
        )

    def test_a_person_planned_without_days_inherits_the_tickets_window(self):
        request = self.make_request(planned=self.today)
        # No planned-hours rows at all: both slots read the ticket.
        ticket = self._spawn(request)
        for worker in (self.worker_a, self.worker_b):
            slot = TicketStaffAssignment.objects.get(ticket=ticket, user=worker)
            self.assertEqual(slot.scheduled_start_at, ticket.scheduled_start_at)
            self.assertEqual(slot.scheduled_end_at, ticket.scheduled_end_at)

    def test_an_unplanned_request_still_spawns_an_unplanned_ticket(self):
        request = self.make_request()
        ticket = self._spawn(request)
        self.assertIsNone(ticket.scheduled_start_at)
        self.assertIsNone(ticket.scheduled_end_at)
        self.assertEqual(
            str(ticket.schedule_status), str(TicketScheduleStatus.UNSCHEDULED)
        )
        slot = TicketStaffAssignment.objects.get(
            ticket=ticket, user=self.worker_a
        )
        self.assertIsNone(slot.scheduled_start_at)

    def test_my_schedule_shows_the_ticket_on_its_day_not_in_not_planned_yet(self):
        request = self.make_request(planned=self.today)
        self.plan_hours(request, self.worker_a, self.today, "3.00")
        ticket = self._spawn(request)

        self.client.force_authenticate(self.super_admin)
        response = self.client.get(WORK_PLAN_URL, {"scope": "company"})
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        payload = response.data
        key = f"ticket-{ticket.id}"
        board = {e["key"]: e for e in payload["entries"]}
        self.assertIn(key, board, sorted(board))
        self.assertEqual(board[key]["day"], self.today.isoformat())
        self.assertNotIn(
            key, {e["key"] for e in payload["undated_entries"]}
        )
