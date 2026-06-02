"""
Sprint 13C — staff "My Jobs" / assigned-to-me agenda filter.

Pins the additive `my_jobs` BooleanFilter on the ticket list:

  * `my_jobs=true` returns exactly the tickets where the requesting STAFF
    holds a `TicketStaffAssignment` row, excluding tickets they are NOT
    assigned to even when otherwise scope-visible.
  * `my_jobs` composes with the Sprint 9B scheduled_*/agenda filters.
  * a BUILDING_READ staff (building-wide scope) is narrowed by
    `my_jobs=true` to only their TicketStaffAssignment tickets.
  * an ASSIGNED_ONLY staff never sees an unassigned same-building ticket
    via `scope_tickets_for` — re-asserting the scope floor with/without
    the filter.
  * `my_jobs` keys off `TicketStaffAssignment` (the M:N), NOT the legacy
    `Ticket.assigned_to` FK.

The filter is OPT-IN and additive: the default list (no `my_jobs` param)
is unchanged. It runs on top of `scope_tickets_for` (already applied in
`get_queryset`), so it can only ever narrow within the caller's scope.
"""

from __future__ import annotations

from datetime import datetime, time, timedelta

from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from accounts.models import User, UserRole
from buildings.models import Building, BuildingStaffVisibility
from companies.models import Company
from customers.models import Customer
from tickets.models import (
    Ticket,
    TicketScheduleStatus,
    TicketStaffAssignment,
    TicketStatus,
)


class _MyJobsBase(APITestCase):
    def setUp(self):
        self.company = Company.objects.create(name="Osius", slug="osius")
        self.building = Building.objects.create(
            company=self.company, name="B1"
        )
        self.customer = Customer.objects.create(
            company=self.company, name="Cust"
        )

        # The actor under test: a STAFF with BUILDING_READ visibility on B1
        # (the default level), so scope_tickets_for shows building-wide.
        self.staff = User.objects.create_user(
            email="staff@osius.nl", password="x", role=UserRole.STAFF
        )
        BuildingStaffVisibility.objects.create(
            user=self.staff, building=self.building
        )

        # A second STAFF used as the "someone else" assignee for the
        # legacy-FK distinction test.
        self.other_staff = User.objects.create_user(
            email="other-staff@osius.nl", password="x", role=UserRole.STAFF
        )
        BuildingStaffVisibility.objects.create(
            user=self.other_staff, building=self.building
        )

        # An admin used only as `created_by` / `assigned_by`.
        self.admin = User.objects.create_user(
            email="sa@osius.nl", password="x", role=UserRole.SUPER_ADMIN
        )

    def _ticket(self, title, **extra):
        return Ticket.objects.create(
            company=self.company,
            building=self.building,
            customer=self.customer,
            created_by=self.admin,
            title=title,
            description="d",
            **extra,
        )

    def _ids(self, resp):
        return [row["id"] for row in resp.data["results"]]


class MyJobsScopeTests(_MyJobsBase):
    def test_my_jobs_returns_only_assigned_to_me(self):
        mine = self._ticket("mine")
        TicketStaffAssignment.objects.create(
            ticket=mine, user=self.staff, assigned_by=self.admin
        )
        # A building-wide visible ticket the staff is NOT assigned to.
        not_mine = self._ticket("not-mine")

        self.client.force_authenticate(user=self.staff)
        resp = self.client.get("/api/tickets/", {"my_jobs": "true"})
        self.assertEqual(resp.status_code, status.HTTP_200_OK, resp.data)
        ids = self._ids(resp)
        self.assertIn(mine.id, ids)
        self.assertNotIn(not_mine.id, ids)

    def test_default_list_unchanged_without_filter(self):
        # Without my_jobs the BUILDING_READ staff still sees both tickets
        # (building-wide scope) — proving the filter is opt-in.
        mine = self._ticket("mine")
        TicketStaffAssignment.objects.create(
            ticket=mine, user=self.staff, assigned_by=self.admin
        )
        not_mine = self._ticket("not-mine")

        self.client.force_authenticate(user=self.staff)
        resp = self.client.get("/api/tickets/")
        ids = self._ids(resp)
        self.assertIn(mine.id, ids)
        self.assertIn(not_mine.id, ids)

    def test_my_jobs_false_does_not_narrow(self):
        mine = self._ticket("mine")
        TicketStaffAssignment.objects.create(
            ticket=mine, user=self.staff, assigned_by=self.admin
        )
        not_mine = self._ticket("not-mine")

        self.client.force_authenticate(user=self.staff)
        resp = self.client.get("/api/tickets/", {"my_jobs": "false"})
        ids = self._ids(resp)
        self.assertIn(mine.id, ids)
        self.assertIn(not_mine.id, ids)


class MyJobsBuildingReadNarrowingTests(_MyJobsBase):
    def test_building_read_staff_narrowed_to_assigned_only(self):
        # The staff holds BUILDING_READ visibility, so an UNASSIGNED
        # building ticket is visible by default but must be excluded under
        # my_jobs=true.
        assigned = self._ticket("assigned")
        TicketStaffAssignment.objects.create(
            ticket=assigned, user=self.staff, assigned_by=self.admin
        )
        building_wide = self._ticket("building-wide-unassigned")

        self.client.force_authenticate(user=self.staff)

        # Without the filter: both visible (building-wide scope).
        plain = self.client.get("/api/tickets/")
        plain_ids = self._ids(plain)
        self.assertIn(assigned.id, plain_ids)
        self.assertIn(building_wide.id, plain_ids)

        # With my_jobs=true: only the assigned ticket.
        narrowed = self.client.get("/api/tickets/", {"my_jobs": "true"})
        narrowed_ids = self._ids(narrowed)
        self.assertIn(assigned.id, narrowed_ids)
        self.assertNotIn(building_wide.id, narrowed_ids)


class MyJobsAssignedOnlyFloorTests(_MyJobsBase):
    def setUp(self):
        super().setUp()
        # Downgrade this staff's visibility to ASSIGNED_ONLY: scope_tickets_for
        # must NOT widen building-wide for them.
        self.staff.building_visibility.update(
            visibility_level=(
                BuildingStaffVisibility.VisibilityLevel.ASSIGNED_ONLY
            )
        )

    def test_assigned_only_staff_never_sees_unassigned_same_building(self):
        assigned = self._ticket("assigned")
        TicketStaffAssignment.objects.create(
            ticket=assigned, user=self.staff, assigned_by=self.admin
        )
        unassigned = self._ticket("unassigned-same-building")

        self.client.force_authenticate(user=self.staff)

        # Scope floor: without the filter, the unassigned same-building
        # ticket is already invisible (ASSIGNED_ONLY does not widen).
        plain = self.client.get("/api/tickets/")
        plain_ids = self._ids(plain)
        self.assertIn(assigned.id, plain_ids)
        self.assertNotIn(unassigned.id, plain_ids)

        # With my_jobs=true the result is identical (consistent with the
        # already-narrow scope).
        narrowed = self.client.get("/api/tickets/", {"my_jobs": "true"})
        narrowed_ids = self._ids(narrowed)
        self.assertIn(assigned.id, narrowed_ids)
        self.assertNotIn(unassigned.id, narrowed_ids)


class MyJobsComposesWithDateFiltersTests(_MyJobsBase):
    def setUp(self):
        super().setUp()
        today_start = timezone.make_aware(
            datetime.combine(timezone.localdate(), time(9, 0))
        )
        next_week = timezone.now() + timedelta(days=7)

        self.assigned_today = self._ticket(
            "assigned-today",
            scheduled_start_at=today_start,
            schedule_status=TicketScheduleStatus.SCHEDULED,
        )
        self.assigned_next_week = self._ticket(
            "assigned-next-week",
            scheduled_start_at=next_week,
            schedule_status=TicketScheduleStatus.SCHEDULED,
        )
        for t in (self.assigned_today, self.assigned_next_week):
            TicketStaffAssignment.objects.create(
                ticket=t, user=self.staff, assigned_by=self.admin
            )
        self.client.force_authenticate(user=self.staff)

    def test_my_jobs_with_agenda_today(self):
        resp = self.client.get(
            "/api/tickets/", {"my_jobs": "true", "agenda": "today"}
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK, resp.data)
        ids = self._ids(resp)
        self.assertIn(self.assigned_today.id, ids)
        self.assertNotIn(self.assigned_next_week.id, ids)

    def test_my_jobs_with_scheduled_on_today(self):
        resp = self.client.get(
            "/api/tickets/",
            {
                "my_jobs": "true",
                "scheduled_on": timezone.localdate().isoformat(),
            },
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK, resp.data)
        ids = self._ids(resp)
        self.assertIn(self.assigned_today.id, ids)
        self.assertNotIn(self.assigned_next_week.id, ids)


class MyJobsUsesM2NNotLegacyFKTests(_MyJobsBase):
    def test_my_jobs_keys_off_m2n_not_legacy_assigned_to(self):
        # Legacy `assigned_to` points at someone ELSE, but the staff holds a
        # TicketStaffAssignment row -> my_jobs=true MUST return it.
        ticket = self._ticket("legacy-other-m2n-mine")
        ticket.assigned_to = self.other_staff
        ticket.save(update_fields=["assigned_to"])
        TicketStaffAssignment.objects.create(
            ticket=ticket, user=self.staff, assigned_by=self.admin
        )

        self.client.force_authenticate(user=self.staff)
        resp = self.client.get("/api/tickets/", {"my_jobs": "true"})
        self.assertEqual(resp.status_code, status.HTTP_200_OK, resp.data)
        self.assertIn(ticket.id, self._ids(resp))

    def test_legacy_assigned_to_alone_does_not_satisfy_my_jobs(self):
        # The inverse: legacy assigned_to == staff but NO TicketStaffAssignment
        # row -> my_jobs=true must NOT return it (the filter is M:N-only).
        ticket = self._ticket("legacy-mine-no-m2n")
        ticket.assigned_to = self.staff
        ticket.save(update_fields=["assigned_to"])

        self.client.force_authenticate(user=self.staff)
        resp = self.client.get("/api/tickets/", {"my_jobs": "true"})
        self.assertEqual(resp.status_code, status.HTTP_200_OK, resp.data)
        self.assertNotIn(ticket.id, self._ids(resp))
