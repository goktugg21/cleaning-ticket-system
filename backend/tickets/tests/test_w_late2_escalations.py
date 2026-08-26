"""W-LATE §2 — the ladder speaks.

Pinned on the promise, not on clocks: every assertion below sets a
planned day and a deadline and asks the sweep what it says about them.
And pinned on ONCE: the second sweep is always asked, and always has to
be silent, except when the promise itself was re-made.
"""
from __future__ import annotations

import datetime
from decimal import Decimal

from django.test import SimpleTestCase
from django.utils import timezone
from rest_framework.test import APITestCase

from accounts.models import StaffProfile, UserRole
from buildings.models import BuildingStaffVisibility
from extra_work.models import ExtraWorkRequest, ExtraWorkStatus
from notifications.models import (
    Notification,
    NotificationLog,
    NotificationSeverity,
)
from test_utils import TenantFixtureMixin
from tickets import escalations
from tickets.models import (
    StaffAssignmentSlotStatus,
    TicketEscalation,
    TicketEscalationStep,
    TicketManagerAssignment,
    TicketStaffAssignment,
    TicketStatus,
)

L2_MANAGERS = "TICKET_LATE_L2_MANAGERS"
L2_ESCALATED = "TICKET_LATE_L2_ESCALATED"
L3_QUARANTINE = "TICKET_LATE_L3_QUARANTINE"


class PersistDaysTests(SimpleTestCase):
    """Half the promise's own span, never under a day."""

    def test_half_the_planned_span(self):
        deadline = datetime.date(2026, 8, 20)
        self.assertEqual(
            escalations.l2_persist_days(
                planned_start=datetime.date(2026, 8, 10),
                deadline=deadline,
                created_on=datetime.date(2026, 8, 1),
            ),
            5,
        )

    def test_rounds_up(self):
        deadline = datetime.date(2026, 8, 20)
        self.assertEqual(
            escalations.l2_persist_days(
                planned_start=datetime.date(2026, 8, 15),
                deadline=deadline,
                created_on=datetime.date(2026, 8, 1),
            ),
            3,
        )

    def test_falls_back_to_the_day_the_ticket_was_raised(self):
        deadline = datetime.date(2026, 8, 20)
        self.assertEqual(
            escalations.l2_persist_days(
                planned_start=None,
                deadline=deadline,
                created_on=datetime.date(2026, 8, 16),
            ),
            2,
        )

    def test_never_under_a_day(self):
        deadline = datetime.date(2026, 8, 20)
        self.assertEqual(
            escalations.l2_persist_days(
                planned_start=datetime.date(2026, 8, 25),
                deadline=deadline,
                created_on=datetime.date(2026, 8, 25),
            ),
            1,
        )


class _Fixture(TenantFixtureMixin, APITestCase):
    def setUp(self):
        super().setUp()
        self.today = timezone.localdate()
        self.ticket.status = TicketStatus.IN_PROGRESS
        self.ticket.title = "Zonwering"
        self.ticket.save(update_fields=["status", "title"])
        # The explicit per-ticket responsible manager — tier one of the
        # roster the L2 step speaks to.
        TicketManagerAssignment.objects.create(
            ticket=self.ticket, user=self.manager, assigned_by=self.company_admin
        )

    def _at(self, days, hour=9):
        naive = datetime.datetime.combine(
            self.today + datetime.timedelta(days=days), datetime.time(hour, 0)
        )
        return timezone.make_aware(naive)

    def _promise(self, *, planned_days, deadline_days):
        """The promise: planned for one day, owed by another."""
        ew = ExtraWorkRequest.objects.create(
            company=self.company,
            building=self.building,
            customer=self.customer,
            created_by=self.company_admin,
            title="Zonwering",
            description="x",
            deadline=self.today + datetime.timedelta(days=deadline_days),
            status=ExtraWorkStatus.IN_PROGRESS,
        )
        self.ticket.extra_work_request = ew
        self.ticket.scheduled_start_at = (
            self._at(planned_days) if planned_days is not None else None
        )
        self.ticket.save(update_fields=["extra_work_request", "scheduled_start_at"])
        return ew

    def _rows(self, user, event):
        return (
            Notification.objects.filter(
                recipient=user, ticket=self.ticket, event_type=event
            ),
            NotificationLog.objects.filter(
                recipient_user=user, ticket=self.ticket, event_type=event
            ),
        )


class DeadlinePassedTests(_Fixture):
    def test_tells_the_assigned_managers_once_on_both_channels(self):
        self._promise(planned_days=-21, deadline_days=-1)
        told = escalations.sweep()["told"]
        self.assertGreaterEqual(told, 1)

        bell, mail = self._rows(self.manager, L2_MANAGERS)
        self.assertEqual(bell.count(), 1)
        self.assertEqual(mail.count(), 1)
        row = bell.get()
        self.assertEqual(row.severity, NotificationSeverity.L2)
        self.assertIn("Zonwering", row.summary)
        self.assertIn(self.ticket.ticket_no, row.summary)
        self.assertIn("is 1 dag overschreden", row.summary)

        step = TicketEscalation.objects.get(
            ticket=self.ticket, step=TicketEscalationStep.L2_MANAGERS
        )
        self.assertEqual(step.anchor_date, self.ticket.extra_work_request.deadline)
        self.assertEqual(step.recipient_ids, [self.manager.id])
        self.assertEqual(step.recipient_count, 1)

        # The second sweep is silent.
        self.assertEqual(escalations.sweep()["told"], 0)
        bell, mail = self._rows(self.manager, L2_MANAGERS)
        self.assertEqual(bell.count(), 1)
        self.assertEqual(mail.count(), 1)

    def test_one_day_late_on_a_long_promise_does_not_reach_the_ring_above(self):
        # Promised over twenty days; one day late is not yet "persisting".
        self._promise(planned_days=-21, deadline_days=-1)
        escalations.sweep()
        self.assertFalse(
            TicketEscalation.objects.filter(
                ticket=self.ticket, step=TicketEscalationStep.L2_ESCALATED
            ).exists()
        )
        bell, _ = self._rows(self.company_admin, L2_ESCALATED)
        self.assertEqual(bell.count(), 0)

    def test_persisting_past_half_the_promise_tells_bm_and_ca_once(self):
        # Planned ten days before a deadline that is now six days past:
        # half of four is two, and six is past two.
        self._promise(planned_days=-10, deadline_days=-6)
        escalations.sweep()
        for user in (self.company_admin, self.manager):
            bell, mail = self._rows(user, L2_ESCALATED)
            self.assertEqual(bell.count(), 1, user.email)
            self.assertEqual(mail.count(), 1, user.email)
            self.assertEqual(bell.get().severity, NotificationSeverity.L2)
            self.assertIn("nog niet af", bell.get().summary)
        # Never the other tenant's admin (H-1).
        bell, _ = self._rows(self.other_company_admin, L2_ESCALATED)
        self.assertEqual(bell.count(), 0)
        self.assertEqual(escalations.sweep()["told"], 0)

    def test_an_english_reader_gets_english(self):
        self.manager.language = "en"
        self.manager.save(update_fields=["language"])
        self._promise(planned_days=-21, deadline_days=-1)
        escalations.sweep()
        bell, mail = self._rows(self.manager, L2_MANAGERS)
        self.assertIn("is 1 day past", bell.get().summary)
        self.assertIn("Deadline passed", mail.get().subject)

    def test_a_new_deadline_speaks_again_and_the_same_one_never(self):
        ew = self._promise(planned_days=-21, deadline_days=-1)
        escalations.sweep()
        self.assertEqual(escalations.sweep()["told"], 0)
        # The promise is re-made: a new (still past) deadline.
        ew.deadline = self.today - datetime.timedelta(days=2)
        ew.save(update_fields=["deadline"])
        self.assertGreaterEqual(escalations.sweep()["told"], 1)
        self.assertEqual(
            TicketEscalation.objects.filter(
                ticket=self.ticket, step=TicketEscalationStep.L2_MANAGERS
            ).count(),
            2,
        )
        bell, _ = self._rows(self.manager, L2_MANAGERS)
        self.assertEqual(bell.count(), 2)
        self.assertEqual(escalations.sweep()["told"], 0)

    def test_work_in_review_is_left_alone(self):
        self._promise(planned_days=-21, deadline_days=-1)
        self.ticket.status = TicketStatus.WAITING_MANAGER_REVIEW
        self.ticket.save(update_fields=["status"])
        self.assertEqual(escalations.sweep()["told"], 0)
        self.assertFalse(TicketEscalation.objects.filter(ticket=self.ticket).exists())

    def test_a_plan_passed_with_the_deadline_ahead_says_nothing(self):
        # L1 is the strip's rung and the strip's alone.
        self._promise(planned_days=-3, deadline_days=+5)
        self.assertEqual(escalations.sweep()["told"], 0)
        self.assertFalse(TicketEscalation.objects.filter(ticket=self.ticket).exists())


class QuarantineTests(_Fixture):
    def test_thirty_days_without_an_hour_tells_the_provider_admins(self):
        self._promise(planned_days=-40, deadline_days=-31)
        escalations.sweep()
        bell, mail = self._rows(self.company_admin, L3_QUARANTINE)
        self.assertEqual(bell.count(), 1)
        self.assertEqual(mail.count(), 1)
        row = bell.get()
        self.assertEqual(row.severity, NotificationSeverity.L3)
        self.assertIn("zonder één gewerkt uur", row.summary)
        self.assertIn("31 dagen voorbij de deadline", row.summary)
        step = TicketEscalation.objects.get(
            ticket=self.ticket, step=TicketEscalationStep.L3_QUARANTINE
        )
        self.assertIsNone(step.anchor_date)
        self.assertEqual(step.recipient_ids, [self.company_admin.id])
        # Not the other tenant's admin, and not the super admin.
        self.assertEqual(self._rows(self.other_company_admin, L3_QUARANTINE)[0].count(), 0)
        self.assertEqual(self._rows(self.super_admin, L3_QUARANTINE)[0].count(), 0)
        self.assertEqual(escalations.sweep()["told"], 0)

    def test_the_anchor_is_the_planned_day_when_there_is_no_deadline(self):
        # No extra work, no deadline: thirty-one days past the plan.
        self.ticket.scheduled_start_at = self._at(-31)
        self.ticket.save(update_fields=["scheduled_start_at"])
        escalations.sweep()
        bell, _ = self._rows(self.company_admin, L3_QUARANTINE)
        self.assertEqual(bell.count(), 1)
        self.assertIn("voorbij de geplande dag", bell.get().summary)

    def test_a_booked_hour_keeps_quarantine_silent(self):
        from timesheets.models import HourSource, HourType, TimeEntry

        self._promise(planned_days=-40, deadline_days=-31)
        hour_type = HourType.objects.create(
            company=self.company, name="Normal", multiplier=Decimal("1.00")
        )
        TimeEntry.objects.create(
            company=self.company,
            employee=self.company_admin,
            hour_type=hour_type,
            date=self.today,
            hours=Decimal("1.00"),
            multiplier_snapshot=Decimal("1.00"),
            source_type=HourSource.TICKET,
            source_id=self.ticket.id,
            created_by=self.company_admin,
        )
        escalations.sweep()
        self.assertFalse(
            TicketEscalation.objects.filter(
                ticket=self.ticket, step=TicketEscalationStep.L3_QUARANTINE
            ).exists()
        )
        # ...but the deadline steps still speak: the promise is broken.
        self.assertTrue(
            TicketEscalation.objects.filter(
                ticket=self.ticket, step=TicketEscalationStep.L2_MANAGERS
            ).exists()
        )


class TheWorkPlanNamesTheStepTests(_Fixture):
    URL = "/api/tickets/work-plan/"

    def test_the_late_entry_says_who_was_told(self):
        worker = self.make_user("late2-worker@example.com", UserRole.STAFF)
        StaffProfile.objects.create(user=worker)
        BuildingStaffVisibility.objects.create(user=worker, building=self.building)
        TicketStaffAssignment.objects.create(
            ticket=self.ticket,
            user=worker,
            assigned_by=self.company_admin,
            scheduled_start_at=self._at(-21),
            slot_status=StaffAssignmentSlotStatus.ASSIGNED,
        )
        self._promise(planned_days=-21, deadline_days=-1)
        escalations.sweep()

        self.authenticate(self.company_admin)
        payload = self.client.get(self.URL, {"scope": "company"}).data
        [row] = [r for r in payload["late_entries"] if r["ticket_id"] == self.ticket.id]
        self.assertEqual(row["lateness"]["level"], 2)
        steps = row["lateness"]["escalation_steps"]
        self.assertEqual([s["step"] for s in steps], ["L2_MANAGERS"])
        self.assertEqual(steps[0]["names"], [self.manager.full_name])
        self.assertTrue(steps[0]["notified_at"])


    def test_the_extra_work_row_carries_its_spawned_tickets_step(self):
        """W-FIX1 A1 lets the extra-work row front a job whose spawned
        ticket has no live slot; the ladder spoke about the ticket, and
        the row must say so too."""
        from extra_work.models import ExtraWorkAssignment, ExtraWorkAssignmentRole

        worker = self.make_user("late2-ew-worker@example.com", UserRole.STAFF)
        StaffProfile.objects.create(user=worker)
        BuildingStaffVisibility.objects.create(user=worker, building=self.building)
        ew = self._promise(planned_days=-21, deadline_days=-1)
        ew.preferred_date = self.today - datetime.timedelta(days=21)
        ew.save(update_fields=["preferred_date"])
        ExtraWorkAssignment.objects.create(
            extra_work_request=ew, user=worker,
            role=ExtraWorkAssignmentRole.WORKER, assigned_by=self.company_admin,
        )
        escalations.sweep()

        self.authenticate(self.company_admin)
        payload = self.client.get(self.URL, {"scope": "company"}).data
        [row] = [r for r in payload["late_entries"] if r["extra_work_id"] == ew.id]
        self.assertEqual(row["kind"], "EXTRA_WORK")
        steps = row["lateness"]["escalation_steps"]
        self.assertEqual([s["step"] for s in steps], ["L2_MANAGERS"])
        self.assertEqual(steps[0]["names"], [self.manager.full_name])


class TheTaskTests(_Fixture):
    def test_the_task_never_raises_and_reports(self):
        from tickets.tasks import sweep_late_escalations

        self._promise(planned_days=-21, deadline_days=-1)
        result = sweep_late_escalations()
        self.assertIn("told", result)
        self.assertIn("checked", result)
        self.assertGreaterEqual(result["told"], 1)
