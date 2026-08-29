"""
FE-4 (Addendum D §D.12 items 2-5) — honest date words, one headline
lateness, settled work in the past tense, and the card and the detail
reading the SAME numbers.

Every assertion here compares `GET /api/tickets/work-plan/` (the card)
with `GET /api/tickets/<id>/` (the detail) for the same ticket, so a
reader who opens a card can never meet a different number inside.
"""
from __future__ import annotations

import datetime

from django.utils import timezone
from rest_framework.test import APITestCase

from accounts.models import UserRole
from buildings.models import BuildingStaffVisibility
from extra_work.models import ExtraWorkRequest, ExtraWorkStatus
from test_utils import TenantFixtureMixin
from tickets.models import (
    StaffAssignmentSlotStatus,
    Ticket,
    TicketStaffAssignment,
    TicketStatus,
    TicketType,
)

PLAN = "/api/tickets/work-plan/"


class _Fixture(TenantFixtureMixin, APITestCase):
    def setUp(self):
        super().setUp()
        self.today = timezone.localdate()
        self.worker = self.make_user("fe4-worker@example.com", UserRole.STAFF)
        BuildingStaffVisibility.objects.create(
            user=self.worker, building=self.building
        )

    def _at(self, offset_days, hour=9):
        return timezone.make_aware(
            datetime.datetime.combine(
                self.today + datetime.timedelta(days=offset_days),
                datetime.time(hour, 0),
            )
        )

    def make_ticket(self, title, status=TicketStatus.OPEN, *, scheduled=None, **extra):
        ticket = Ticket.objects.create(
            company=self.company,
            customer=self.customer,
            building=self.building,
            title=title,
            description="x",
            type=TicketType.REQUEST,
            status=status,
            created_by=self.super_admin,
            scheduled_start_at=self._at(scheduled) if scheduled is not None else None,
            **extra,
        )
        # P-1 — a scheduled fixture is a PERSON's plan, and says so.
        if scheduled is not None:
            self.record_plan(ticket)
        return ticket

    def make_slot(self, ticket, *, days, slot_status=StaffAssignmentSlotStatus.ASSIGNED, completed_at=None):
        return TicketStaffAssignment.objects.create(
            ticket=ticket,
            user=self.worker,
            assigned_by=self.super_admin,
            scheduled_start_at=self._at(days) if days is not None else None,
            slot_status=slot_status,
            completed_at=completed_at,
        )

    def company_plan(self, week=None):
        self.client.force_authenticate(self.company_admin)
        params = {"scope": "company"}
        if week:
            params["week"] = week
        response = self.client.get(PLAN, params)
        self.assertEqual(response.status_code, 200, response.data)
        return response.data

    def own_plan(self, week=None):
        self.client.force_authenticate(self.worker)
        response = self.client.get(PLAN, {"week": week} if week else {})
        self.assertEqual(response.status_code, 200, response.data)
        return response.data

    def detail(self, ticket):
        self.client.force_authenticate(self.company_admin)
        response = self.client.get(f"/api/tickets/{ticket.id}/")
        self.assertEqual(response.status_code, 200, response.data)
        return response.data

    @staticmethod
    def find(payload, key):
        for bucket in (
            "entries",
            "undated_entries",
            "overdue_entries",
            "upcoming_entries",
            "late_entries",
        ):
            for entry in payload.get(bucket, []):
                if entry["key"] == key:
                    return entry
        return None

    def week_of(self, offset_days):
        iso = (self.today + datetime.timedelta(days=offset_days)).isocalendar()
        return f"{iso[0]}-W{iso[1]:02d}"


class CardEqualsDetailTests(_Fixture):
    def test_an_unplanned_open_ticket_is_created_not_planned_on_both(self):
        ticket = self.make_ticket("Ancient and unplanned")
        # The company board lists staffed tickets only (`_ticket_source`).
        self.make_slot(ticket, days=None)
        Ticket.objects.filter(pk=ticket.pk).update(
            created_at=self._at(-87)
        )
        card = self.find(self.company_plan(), f"ticket-{ticket.id}")
        detail = self.detail(ticket)

        self.assertIsNotNone(card)
        self.assertIsNone(card["plan_source"])
        self.assertIsNone(card["planned_start"])
        self.assertIsNone(card["due_kind"])
        self.assertIsNone(card["days_until_due"])
        # `Response.data` still holds the datetime; the wire renders it.
        self.assertEqual(str(card["created_at"])[:10], str(detail["created_at"])[:10])
        # The ONE number both surfaces print for it: how long it has
        # waited for a plan.
        self.assertEqual(card["unplanned_age_days"], 87)
        self.assertEqual(detail["unplanned_age_days"], 87)
        self.assertIsNone(detail["due_kind"])
        self.assertIsNone(detail["days_until_due"])

    def test_a_planned_day_counts_the_same_on_card_and_detail(self):
        ticket = self.make_ticket("Planned", scheduled=3)
        self.make_slot(ticket, days=3)
        card = self.find(self.company_plan(week=self.week_of(3)), f"ticket-{ticket.id}")
        detail = self.detail(ticket)
        self.assertEqual(card["plan_source"], "TICKET")
        self.assertEqual(card["due_kind"], "PLANNED_DAY")
        self.assertEqual(detail["due_kind"], "PLANNED_DAY")
        self.assertEqual(card["days_until_due"], 3)
        self.assertEqual(detail["days_until_due"], 3)
        self.assertIsNone(card["unplanned_age_days"])
        self.assertIsNone(detail["unplanned_age_days"])

    def test_a_real_deadline_is_the_headline_on_both(self):
        extra_work = ExtraWorkRequest.objects.create(
            company=self.company,
            building=self.building,
            customer=self.customer,
            created_by=self.manager,
            title="Deep clean",
            description="",
            status=ExtraWorkStatus.IN_PROGRESS,
            deadline=self.today - datetime.timedelta(days=2),
        )
        ticket = self.make_ticket(
            "Execution",
            TicketStatus.IN_PROGRESS,
            scheduled=-1,
            extra_work_request=extra_work,
        )
        self.make_slot(ticket, days=-1)
        card = self.find(self.company_plan(), f"ticket-{ticket.id}")
        detail = self.detail(ticket)
        self.assertEqual(card["due_kind"], "DEADLINE")
        self.assertEqual(detail["due_kind"], "DEADLINE")
        self.assertEqual(card["days_until_due"], -2)
        self.assertEqual(detail["days_until_due"], -2)

    def test_a_customers_wish_is_a_wish_not_a_plan(self):
        extra_work = ExtraWorkRequest.objects.create(
            company=self.company,
            building=self.building,
            customer=self.customer,
            created_by=self.customer_user,
            title="Wished",
            description="",
            status=ExtraWorkStatus.CUSTOMER_APPROVED,
            preferred_date=self.today + datetime.timedelta(days=2),
        )
        ticket = self.make_ticket("Wished work", extra_work_request=extra_work)
        self.make_slot(ticket, days=None)
        card = self.find(self.company_plan(week=self.week_of(2)), f"ticket-{ticket.id}")
        self.assertIsNotNone(card)
        self.assertEqual(card["plan_source"], "CUSTOMER_WISH")

    def test_closed_work_stops_counting_and_reads_in_the_past_tense(self):
        closed_at = self._at(-1, hour=15)
        ticket = self.make_ticket(
            "Closed late",
            TicketStatus.CLOSED,
            scheduled=-3,
            closed_at=closed_at,
        )
        self.make_slot(
            ticket,
            days=-3,
            slot_status=StaffAssignmentSlotStatus.COMPLETED,
            completed_at=closed_at,
        )
        card = self.find(self.company_plan(week=self.week_of(-3)), f"ticket-{ticket.id}")
        detail = self.detail(ticket)
        self.assertIsNotNone(card)
        self.assertTrue(card["viewer_settled"])
        # No pressure: no countdown on either surface.
        self.assertIsNone(card["days_until_due"])
        self.assertIsNone(detail["days_until_due"])
        # History: when it was finished, and that it came 2 days after
        # its planned day.
        self.assertEqual(str(card["settled_at"])[:10], str(detail["settled_at"])[:10])
        self.assertEqual(card["settled_days_after_due"], 2)
        self.assertEqual(detail["settled_days_after_due"], 2)

    def test_work_waiting_on_the_customer_is_settled_without_a_finish(self):
        ticket = self.make_ticket(
            "With the customer", TicketStatus.WAITING_CUSTOMER_APPROVAL, scheduled=-1
        )
        self.make_slot(ticket, days=-1, slot_status=StaffAssignmentSlotStatus.COMPLETED)
        card = self.find(self.company_plan(), f"ticket-{ticket.id}")
        self.assertIsNotNone(card)
        self.assertTrue(card["viewer_settled"])
        self.assertIsNone(card["days_until_due"])
        self.assertIsNone(card["settled_at"])


class ReadingOrderTests(_Fixture):
    def test_todays_open_work_then_carried_then_settled(self):
        done = self.make_ticket("Done today", scheduled=0)
        done_slot = self.make_slot(
            done,
            days=0,
            slot_status=StaffAssignmentSlotStatus.COMPLETED,
            completed_at=self._at(0, hour=8),
        )
        carried = self.make_ticket("Carried", scheduled=-2)
        carried_slot = self.make_slot(carried, days=-2)
        fresh = self.make_ticket("Today", scheduled=0)
        fresh_slot = self.make_slot(fresh, days=0, )
        payload = self.own_plan()
        today_keys = [
            e["key"] for e in payload["entries"] if e["day"] == self.today.isoformat()
        ]
        self.assertEqual(
            today_keys,
            [f"slot-{fresh_slot.id}", f"slot-{carried_slot.id}", f"slot-{done_slot.id}"],
        )
        by_key = {e["key"]: e for e in payload["entries"]}
        self.assertEqual(by_key[f"slot-{carried_slot.id}"]["placement"], "ROLLED")
        self.assertEqual(by_key[f"slot-{carried_slot.id}"]["plan_source"], "TICKET")
        self.assertIsNotNone(by_key[f"slot-{done_slot.id}"]["settled_at"])
