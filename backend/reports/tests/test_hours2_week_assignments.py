"""hours2 Part 3 — the admin week grid's row proposal.

    GET /api/reports/week-assignments/

What is pinned here, each line one somebody could undo without any
other test noticing:

1. **A slot dated in the week proposes the row**, with the ticket's
   building prefilled — the reason the grid stops multiplying people by
   buildings.
2. **An undated slot falls back to the ticket's own day.** A flat
   assignment on a ticket scheduled Tuesday is Tuesday's work.
3. **A slot in another week is a job, not a proposal.** It stays in
   `jobs` so the manual "Add row" can still offer it as an exception,
   and is absent from `assignments`.
4. **The plan's days propose via the spawned ticket**, whether or not a
   slot has been cut yet — the plan IS the proposal.
5. **A finished ticket is offered nowhere.** Same rule the source picker
   keeps.
6. **Buildings are the person's grants, not the company's list.** A
   STAFF member's `building_ids` are the buildings they hold visibility
   on; a building they cannot enter is absent.
7. **Tenant and gate.** Another company's employee id is absent from
   the answer (never "forbidden"), another company's tickets never
   surface, `?company=` outside scope is 404, STAFF / BM / customer are
   403, and a missing week is 400.
"""
from __future__ import annotations

import datetime as dt

from django.utils import timezone

from buildings.models import Building, BuildingStaffVisibility
from customers.models import Customer, CustomerBuildingMembership
from extra_work.models import ExtraWorkPlannedHours, ExtraWorkRequest
from tickets.models import (
    Ticket,
    TicketStaffAssignment,
    TicketStatus,
    TicketType,
)
from timesheets.tests.fixtures import TimesheetsFixture


URL = "/api/reports/week-assignments/"

# ISO 2026-W32 runs Mon 2026-08-03 .. Sun 2026-08-09.
ISO_YEAR, ISO_WEEK = 2026, 32
TUESDAY = dt.date(2026, 8, 4)
WEDNESDAY = dt.date(2026, 8, 5)


def at(day: dt.date, hour: int = 9) -> dt.datetime:
    return timezone.make_aware(
        dt.datetime(day.year, day.month, day.day, hour, 0),
        timezone.get_current_timezone(),
    )


class WeekAssignmentsBase(TimesheetsFixture):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.customer_a = Customer.objects.create(
            company=cls.company_a, name="Cust A"
        )
        cls.customer_b = Customer.objects.create(
            company=cls.company_b, name="Cust B"
        )
        CustomerBuildingMembership.objects.create(
            customer=cls.customer_a, building=cls.building_a
        )
        CustomerBuildingMembership.objects.create(
            customer=cls.customer_b, building=cls.building_b
        )
        # A second building in company A that NOBODY holds visibility on.
        cls.building_a2 = Building.objects.create(
            company=cls.company_a, name="Building A2", address="A street 2"
        )

    def make_ticket(self, company, building, customer, title, **kwargs):
        defaults = dict(
            company=company,
            building=building,
            customer=customer,
            type=TicketType.REPORT,
            title=title,
            description="x",
            created_by=self.ca_a if company == self.company_a else self.ca_b,
        )
        defaults.update(kwargs)
        return Ticket.objects.create(**defaults)

    def get(self, user, **params):
        query = {"iso_year": ISO_YEAR, "iso_week": ISO_WEEK}
        query.update(params)
        return self.api(user).get(URL, query)

    def person(self, response, employee):
        rows = [
            row for row in response.data["employees"] if row["employee"] == employee.id
        ]
        self.assertEqual(len(rows), 1, response.data)
        return rows[0]

    @staticmethod
    def ids(jobs):
        return {job["source_id"] for job in jobs}


class ProposalTests(WeekAssignmentsBase):
    def setUp(self):
        super().setUp()
        # 1. A slot dated inside the week.
        self.dated = self.make_ticket(
            self.company_a, self.building_a, self.customer_a, "Dated slot"
        )
        TicketStaffAssignment.objects.create(
            ticket=self.dated, user=self.staff_a, scheduled_start_at=at(TUESDAY)
        )
        # 2. An undated slot on a ticket scheduled inside the week.
        self.ticket_day = self.make_ticket(
            self.company_a,
            self.building_a,
            self.customer_a,
            "Ticket day",
            scheduled_start_at=at(WEDNESDAY),
        )
        TicketStaffAssignment.objects.create(
            ticket=self.ticket_day, user=self.staff_a
        )
        # 3. A slot NEXT week: a job, not this week's proposal.
        self.next_week = self.make_ticket(
            self.company_a, self.building_a, self.customer_a, "Next week"
        )
        TicketStaffAssignment.objects.create(
            ticket=self.next_week,
            user=self.staff_a,
            scheduled_start_at=at(TUESDAY + dt.timedelta(days=7)),
        )
        # 5. A closed ticket with a slot in the week: offered nowhere.
        self.closed = self.make_ticket(
            self.company_a,
            self.building_a,
            self.customer_a,
            "Closed",
            status=TicketStatus.CLOSED,
        )
        TicketStaffAssignment.objects.create(
            ticket=self.closed, user=self.staff_a, scheduled_start_at=at(TUESDAY)
        )

    def test_a_dated_slot_in_the_week_proposes_the_row_with_its_building(self):
        response = self.get(self.ca_a, employee=self.staff_a.id)
        self.assertEqual(response.status_code, 200, response.data)
        row = self.person(response, self.staff_a)
        proposed = {job["source_id"]: job for job in row["assignments"]}
        self.assertIn(self.dated.id, proposed)
        self.assertEqual(proposed[self.dated.id]["source_type"], "TICKET")
        self.assertEqual(proposed[self.dated.id]["building"], self.building_a.id)
        self.assertIn("Dated slot", proposed[self.dated.id]["title"])

    def test_an_undated_slot_falls_back_to_the_tickets_day(self):
        response = self.get(self.ca_a, employee=self.staff_a.id)
        row = self.person(response, self.staff_a)
        self.assertIn(self.ticket_day.id, self.ids(row["assignments"]))

    def test_a_slot_in_another_week_is_a_job_not_a_proposal(self):
        response = self.get(self.ca_a, employee=self.staff_a.id)
        row = self.person(response, self.staff_a)
        self.assertNotIn(self.next_week.id, self.ids(row["assignments"]))
        self.assertIn(self.next_week.id, self.ids(row["jobs"]))
        self.assertFalse(row["jobs_truncated"])

    def test_a_finished_ticket_is_offered_nowhere(self):
        response = self.get(self.ca_a, employee=self.staff_a.id)
        row = self.person(response, self.staff_a)
        self.assertNotIn(self.closed.id, self.ids(row["assignments"]))
        self.assertNotIn(self.closed.id, self.ids(row["jobs"]))

    def test_a_person_with_no_slots_gets_empty_lists_not_an_error(self):
        response = self.get(self.ca_a, employee=self.staff_a2.id)
        row = self.person(response, self.staff_a2)
        self.assertEqual(row["assignments"], [])
        self.assertEqual(row["jobs"], [])

    def test_the_week_is_echoed_back_with_its_bounds(self):
        response = self.get(self.ca_a, employee=self.staff_a.id)
        self.assertEqual(response.data["week_start"], "2026-08-03")
        self.assertEqual(response.data["week_end"], "2026-08-09")
        self.assertEqual(response.data["company"], self.company_a.id)


class PlannedDayTests(WeekAssignmentsBase):
    def setUp(self):
        super().setUp()
        self.ew = ExtraWorkRequest.objects.create(
            company=self.company_a,
            customer=self.customer_a,
            building=self.building_a,
            title="Repaint the stairwell",
            description="x",
            created_by=self.ca_a,
        )
        self.spawned = self.make_ticket(
            self.company_a,
            self.building_a,
            self.customer_a,
            "Repaint the stairwell",
            extra_work_request=self.ew,
        )
        # staff_a2 is PLANNED for Wednesday and holds no slot at all.
        ExtraWorkPlannedHours.objects.create(
            extra_work_request=self.ew, user=self.staff_a2, date=WEDNESDAY, hours=4
        )
        # staff_a is planned for a day OUTSIDE the week.
        ExtraWorkPlannedHours.objects.create(
            extra_work_request=self.ew,
            user=self.staff_a,
            date=WEDNESDAY + dt.timedelta(days=7),
            hours=4,
        )

    def test_a_planned_day_proposes_the_spawned_ticket_without_a_slot(self):
        response = self.get(self.ca_a, employee=self.staff_a2.id)
        row = self.person(response, self.staff_a2)
        self.assertEqual(self.ids(row["assignments"]), {self.spawned.id})
        self.assertEqual(
            row["assignments"][0]["building"], self.building_a.id
        )

    def test_a_planned_day_outside_the_week_proposes_nothing(self):
        response = self.get(self.ca_a, employee=self.staff_a.id)
        row = self.person(response, self.staff_a)
        self.assertEqual(row["assignments"], [])


class BuildingGrantTests(WeekAssignmentsBase):
    def test_buildings_are_the_persons_grants_not_the_companys_list(self):
        response = self.get(self.ca_a, employee=self.staff_a.id)
        row = self.person(response, self.staff_a)
        self.assertEqual(row["building_ids"], [self.building_a.id])
        self.assertNotIn(self.building_a2.id, row["building_ids"])

    def test_a_new_grant_appears_and_a_retired_building_does_not(self):
        BuildingStaffVisibility.objects.create(
            user=self.staff_a, building=self.building_a2
        )
        response = self.get(self.ca_a, employee=self.staff_a.id)
        self.assertEqual(
            self.person(response, self.staff_a)["building_ids"],
            sorted([self.building_a.id, self.building_a2.id]),
        )
        Building.objects.filter(pk=self.building_a2.pk).update(is_active=False)
        response = self.get(self.ca_a, employee=self.staff_a.id)
        self.assertEqual(
            self.person(response, self.staff_a)["building_ids"],
            [self.building_a.id],
        )

    def test_a_building_manager_gets_the_buildings_they_manage(self):
        response = self.get(self.ca_a, employee=self.bm_a.id)
        row = self.person(response, self.bm_a)
        self.assertEqual(row["building_ids"], [self.building_a.id])

    def test_a_company_admin_gets_every_active_building(self):
        response = self.get(self.ca_a, employee=self.ca_a.id)
        row = self.person(response, self.ca_a)
        self.assertEqual(
            row["building_ids"], sorted([self.building_a.id, self.building_a2.id])
        )


class TenantAndGateTests(WeekAssignmentsBase):
    def setUp(self):
        super().setUp()
        self.foreign = self.make_ticket(
            self.company_b, self.building_b, self.customer_b, "Company B private"
        )
        TicketStaffAssignment.objects.create(
            ticket=self.foreign, user=self.staff_b, scheduled_start_at=at(TUESDAY)
        )

    def test_another_companys_employee_is_absent_not_forbidden(self):
        response = self.get(
            self.ca_a, employee=[self.staff_a.id, self.staff_b.id]
        )
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(
            [row["employee"] for row in response.data["employees"]],
            [self.staff_a.id],
        )

    def test_another_companys_tickets_never_surface(self):
        # Even a SUPER_ADMIN asking about company A never sees B's work.
        response = self.get(
            self.sa, company=self.company_a.id, employee=self.staff_b.id
        )
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["employees"], [])
        response = self.get(
            self.sa, company=self.company_b.id, employee=self.staff_b.id
        )
        row = self.person(response, self.staff_b)
        self.assertEqual(self.ids(row["assignments"]), {self.foreign.id})

    def test_a_company_outside_scope_is_404(self):
        response = self.get(
            self.ca_a, company=self.company_b.id, employee=self.staff_b.id
        )
        self.assertEqual(response.status_code, 404, response.data)

    def test_staff_bm_and_customer_are_refused(self):
        for user in (self.staff_a, self.bm_a, self.customer_user):
            response = self.get(user, employee=self.staff_a.id)
            self.assertEqual(response.status_code, 403, (user.email, response.data))

    def test_a_missing_or_impossible_week_is_400(self):
        response = self.api(self.ca_a).get(URL, {"employee": self.staff_a.id})
        self.assertEqual(response.status_code, 400, response.data)
        self.assertEqual(response.data["iso_week"][0].code, "week_required")
        # 2025 has 52 ISO weeks (2026 has 53), so W53 of 2025 does not exist.
        response = self.api(self.ca_a).get(
            URL, {"iso_year": 2025, "iso_week": 53, "employee": self.staff_a.id}
        )
        self.assertEqual(response.status_code, 400, response.data)

    def test_no_employee_asked_is_an_empty_answer(self):
        response = self.get(self.ca_a)
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["employees"], [])
