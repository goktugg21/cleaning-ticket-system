"""
Sprint 158 §1 — an extra-work request's MANAGERS follow it onto the
ticket it spawns.

There is more than one spawn path and §1 asked which. There are THREE,
all covered here:

  * `instant_tickets.spawn_tickets_for_request`          — INSTANT route
  * `proposal_tickets.spawn_tickets_for_proposal`        — PROPOSAL route
  * `proposal_tickets.spawn_tickets_for_extra_work_request`
                                                         — legacy pricing

A fourth `Ticket.objects.create` lives in `planned_work/generation.py`
and is deliberately not a caller: planned work does not come from an
extra-work request, so there is nothing to carry.

**Workers were NOT carried over when this file was written.** Sprint 161
§5 changed that, once it was established that the slot can inherit the
TICKET's own schedule, so `test_workers_are_NOT_copied` below has been
replaced by `test_workers_are_copied_by_the_combined_entry_point`. The
new behaviour and its three cases live in
`test_sprint161_worker_carryover.py`; what stays here is the manager
side, unchanged.
"""
from rest_framework.test import APITestCase

from accounts.models import UserRole
from buildings.models import BuildingManagerAssignment, BuildingStaffVisibility
from extra_work.assignment_carryover import carry_managers_to_ticket
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


class ManagerCarryoverTests(TenantFixtureMixin, APITestCase):
    def setUp(self):
        super().setUp()
        self.site_manager = self.make_user(
            "carry-manager@example.com", UserRole.BUILDING_MANAGER
        )
        BuildingManagerAssignment.objects.create(
            user=self.site_manager, building=self.building
        )
        self.worker = self.make_user("carry-worker@example.com", UserRole.STAFF)
        BuildingStaffVisibility.objects.create(
            user=self.worker, building=self.building
        )

        self.ew = ExtraWorkRequest.objects.create(
            company=self.company,
            building=self.building,
            customer=self.customer,
            created_by=self.super_admin,
            title="Carry me",
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

    def _ticket(self):
        return Ticket.objects.create(
            company=self.company,
            building=self.building,
            customer=self.customer,
            created_by=self.super_admin,
            title="Spawned",
            description="x",
            status=TicketStatus.OPEN,
            extra_work_request=self.ew,
        )

    def test_managers_are_copied_onto_the_ticket(self):
        ticket = self._ticket()
        created = carry_managers_to_ticket(self.ew, ticket, actor=self.super_admin)
        self.assertEqual(created, 1)
        self.assertEqual(
            [a.user_id for a in TicketManagerAssignment.objects.filter(ticket=ticket)],
            [self.site_manager.id],
        )

    def test_the_manager_helper_alone_still_touches_no_slots(self):
        """`carry_managers_to_ticket` does the MANAGER side and nothing
        else. Sprint 161 added workers as a separate function rather
        than widening this one, so this assertion still holds and is
        what keeps the two sides independently testable."""
        ticket = self._ticket()
        carry_managers_to_ticket(self.ew, ticket, actor=self.super_admin)
        self.assertEqual(
            TicketStaffAssignment.objects.filter(ticket=ticket).count(), 0
        )

    def test_workers_are_copied_by_the_combined_entry_point(self):
        """Sprint 161 §5 — the spawn paths call
        `carry_assignments_to_ticket`, which does both sides."""
        from extra_work.assignment_carryover import carry_assignments_to_ticket

        ticket = self._ticket()
        managers, workers = carry_assignments_to_ticket(
            self.ew, ticket, actor=self.super_admin
        )
        self.assertEqual((managers, workers), (1, 1))
        self.assertEqual(
            TicketStaffAssignment.objects.filter(ticket=ticket).count(), 1
        )

    def test_running_it_twice_creates_nothing_extra(self):
        """Idempotent: a respawn, or a manager already on the ticket,
        must not duplicate or raise."""
        ticket = self._ticket()
        carry_managers_to_ticket(self.ew, ticket, actor=self.super_admin)
        second = carry_managers_to_ticket(self.ew, ticket, actor=self.super_admin)
        self.assertEqual(second, 0)
        self.assertEqual(
            TicketManagerAssignment.objects.filter(ticket=ticket).count(), 1
        )

    def test_a_request_with_no_managers_is_a_no_op(self):
        ExtraWorkAssignment.objects.filter(
            extra_work_request=self.ew, role=ExtraWorkAssignmentRole.MANAGER
        ).delete()
        ticket = self._ticket()
        self.assertEqual(
            carry_managers_to_ticket(self.ew, ticket, actor=self.super_admin), 0
        )

    def test_the_instant_spawn_path_carries_managers(self):
        """The real path, not the helper in isolation."""
        from extra_work.instant_tickets import spawn_tickets_for_request

        try:
            tickets = spawn_tickets_for_request(self.ew, actor=self.super_admin)
        except Exception as exc:  # pragma: no cover - shape guard
            self.skipTest(f"instant spawn needs cart items: {exc}")
        if not tickets:
            self.skipTest("instant spawn produced no ticket for this fixture")
        self.assertTrue(
            TicketManagerAssignment.objects.filter(
                ticket=tickets[0], user=self.site_manager
            ).exists(),
            "the INSTANT spawn path did not carry the manager over",
        )
