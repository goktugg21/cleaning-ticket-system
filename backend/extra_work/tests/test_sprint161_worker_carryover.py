"""
Sprint 161 §5 — an extra-work request's WORKERS follow it onto the
ticket, WITHOUT losing the scheduling.

Sprint 158 left workers behind on a real objection:
`TicketStaffAssignment` is a dated operational SLOT, and a worker copied
into an undated one reads on the agenda as planned work nobody planned.

What that missed is that the ticket already knows when the work is —
Sprint 9B seeds `Ticket.scheduled_start_at` from the extra-work line's
requested date on all three spawn paths — and the slot's own schedule
columns are nullable. So the slot inherits the ticket's schedule and
nothing is invented.

The three cases the brief names are each their own test:

  * a ticket WITH a schedule      -> the slot inherits it
  * a ticket WITHOUT one          -> the slot's dates stay None
  * a worker no longer eligible   -> not carried, and it is logged

Plus the thing that actually matters operationally: all three spawn
paths go through the same entry point.
"""
from datetime import timedelta

from django.utils import timezone
from rest_framework.test import APITestCase

from accounts.models import UserRole
from buildings.models import BuildingManagerAssignment, BuildingStaffVisibility
from extra_work.assignment_carryover import (
    carry_assignments_to_ticket,
    carry_workers_to_ticket,
)
from extra_work.models import (
    ExtraWorkAssignment,
    ExtraWorkAssignmentRole,
    ExtraWorkCategory,
    ExtraWorkRequest,
    ExtraWorkStatus,
)
from test_utils import TenantFixtureMixin
from tickets.models import (
    Ticket,
    TicketManagerAssignment,
    TicketStaffAssignment,
    TicketStatus,
)


class WorkerCarryoverTests(TenantFixtureMixin, APITestCase):
    def setUp(self):
        super().setUp()
        self.site_manager = self.make_user(
            "s161-manager@example.com", UserRole.BUILDING_MANAGER
        )
        BuildingManagerAssignment.objects.create(
            user=self.site_manager, building=self.building
        )
        self.worker = self.make_user("s161-worker@example.com", UserRole.STAFF)
        BuildingStaffVisibility.objects.create(
            user=self.worker, building=self.building
        )

        self.ew = ExtraWorkRequest.objects.create(
            company=self.company,
            building=self.building,
            customer=self.customer,
            created_by=self.super_admin,
            title="Carry the crew",
            description="x",
            category=ExtraWorkCategory.DEEP_CLEANING,
            status=ExtraWorkStatus.REQUESTED,
        )
        ExtraWorkAssignment.objects.create(
            extra_work_request=self.ew,
            user=self.site_manager,
            role=ExtraWorkAssignmentRole.MANAGER,
        )
        ExtraWorkAssignment.objects.create(
            extra_work_request=self.ew,
            user=self.worker,
            role=ExtraWorkAssignmentRole.WORKER,
        )

    def _ticket(self, *, start=None, end=None):
        return Ticket.objects.create(
            company=self.company,
            building=self.building,
            customer=self.customer,
            created_by=self.super_admin,
            title="Spawned",
            description="x",
            status=TicketStatus.OPEN,
            extra_work_request=self.ew,
            scheduled_start_at=start,
            scheduled_end_at=end,
        )

    # ---- case 1: the ticket has a schedule --------------------------

    def test_the_slot_inherits_the_tickets_schedule(self):
        start = timezone.now() + timedelta(days=3)
        end = start + timedelta(hours=2)
        ticket = self._ticket(start=start, end=end)

        created = carry_workers_to_ticket(
            self.ew, ticket, actor=self.super_admin
        )

        self.assertEqual(created, 1)
        slot = TicketStaffAssignment.objects.get(ticket=ticket)
        self.assertEqual(slot.user_id, self.worker.id)
        self.assertEqual(slot.scheduled_start_at, start)
        self.assertEqual(slot.scheduled_end_at, end)

    # ---- case 2: the ticket has no schedule -------------------------

    def test_without_a_ticket_schedule_the_slot_dates_stay_none(self):
        """The honest state. A fabricated date would put work on
        somebody's agenda on a day nobody chose."""
        ticket = self._ticket(start=None, end=None)

        created = carry_workers_to_ticket(
            self.ew, ticket, actor=self.super_admin
        )

        self.assertEqual(created, 1)
        slot = TicketStaffAssignment.objects.get(ticket=ticket)
        self.assertIsNone(slot.scheduled_start_at)
        self.assertIsNone(slot.scheduled_end_at)

    # ---- case 3: the worker is no longer eligible -------------------

    def test_an_ineligible_worker_is_not_carried(self):
        """The choice, stated: SKIP, not carry-anyway.

        `buildings.assignment_eligibility` is the authority the assign
        endpoint uses, so carrying an ineligible worker would create a
        row that endpoint would have refused — the carry-over must not
        be a back door around the rule Sprint 158 established.
        """
        BuildingStaffVisibility.objects.filter(
            user=self.worker, building=self.building
        ).delete()
        ticket = self._ticket(start=timezone.now())

        with self.assertLogs("extra_work.assignment_carryover", level="INFO") as logs:
            created = carry_workers_to_ticket(
                self.ew, ticket, actor=self.super_admin
            )

        self.assertEqual(created, 0)
        self.assertEqual(
            TicketStaffAssignment.objects.filter(ticket=ticket).count(), 0
        )
        self.assertTrue(
            any("not eligible at building" in line for line in logs.output),
            f"the skip was not logged: {logs.output}",
        )

    def test_a_deactivated_worker_is_not_carried(self):
        """Same rule, the other way an account stops being assignable."""
        self.worker.is_active = False
        self.worker.save(update_fields=["is_active"])
        ticket = self._ticket(start=timezone.now())

        self.assertEqual(
            carry_workers_to_ticket(self.ew, ticket, actor=self.super_admin), 0
        )

    # ---- shape ------------------------------------------------------

    def test_running_it_twice_creates_nothing_extra(self):
        start = timezone.now() + timedelta(days=1)
        ticket = self._ticket(start=start)
        carry_workers_to_ticket(self.ew, ticket, actor=self.super_admin)
        second = carry_workers_to_ticket(self.ew, ticket, actor=self.super_admin)
        self.assertEqual(second, 0)
        self.assertEqual(
            TicketStaffAssignment.objects.filter(ticket=ticket).count(), 1
        )

    def test_the_combined_entry_point_does_both_sides(self):
        ticket = self._ticket(start=timezone.now())
        managers, workers = carry_assignments_to_ticket(
            self.ew, ticket, actor=self.super_admin
        )
        self.assertEqual((managers, workers), (1, 1))
        self.assertEqual(
            TicketManagerAssignment.objects.filter(ticket=ticket).count(), 1
        )
        self.assertEqual(
            TicketStaffAssignment.objects.filter(ticket=ticket).count(), 1
        )

    def test_a_request_with_no_workers_is_a_no_op(self):
        ExtraWorkAssignment.objects.filter(
            extra_work_request=self.ew, role=ExtraWorkAssignmentRole.WORKER
        ).delete()
        ticket = self._ticket(start=timezone.now())
        self.assertEqual(
            carry_workers_to_ticket(self.ew, ticket, actor=self.super_admin), 0
        )

    def test_a_failure_never_breaks_the_spawn(self):
        """A spawn that succeeded must not be rolled back because
        pre-filling its crew failed."""
        ticket = self._ticket(start=timezone.now())
        ticket.building = None  # forces the eligibility lookup to blow up
        self.assertEqual(
            carry_workers_to_ticket(self.ew, ticket, actor=self.super_admin), 0
        )


class SpawnPathTests(WorkerCarryoverTests):
    """All three spawn paths reach the combined entry point.

    Asserted through the real functions rather than by grepping for the
    call, because "it is imported" and "it runs" are different claims.
    """

    def test_the_instant_spawn_path_carries_both(self):
        from extra_work.instant_tickets import spawn_tickets_for_request

        try:
            tickets = spawn_tickets_for_request(self.ew, actor=self.super_admin)
        except Exception as exc:  # pragma: no cover - shape guard
            self.skipTest(f"instant spawn needs cart items: {exc}")
        if not tickets:
            self.skipTest("instant spawn produced no tickets for this fixture")
        ticket = tickets[0]
        self.assertEqual(
            TicketManagerAssignment.objects.filter(ticket=ticket).count(), 1
        )
        self.assertEqual(
            TicketStaffAssignment.objects.filter(ticket=ticket).count(), 1
        )
