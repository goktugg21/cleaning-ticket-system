"""W-N1 §1 + §2 — the deadline reminder and the part-assignment notice.

Both are machine-sent, so both are pinned on what they DO NOT do as much
as on what they do: the reminder must not become a daily nag, and the
part notice must not tell you what you just did to yourself.
"""
from __future__ import annotations

import datetime

from django.utils import timezone
from rest_framework.test import APITestCase

from accounts.models import StaffProfile, UserRole
from buildings.models import BuildingStaffVisibility
from notifications.models import (
    Notification,
    NotificationEventType,
    NotificationLog,
)
from test_utils import TenantFixtureMixin
from tickets import deadline_reminders
from tickets.models import SubTask, TicketStaffAssignment, TicketStatus


class _Fixture(TenantFixtureMixin, APITestCase):
    def setUp(self):
        super().setUp()
        self.worker = self.make_user("wn1-worker@example.com", UserRole.STAFF)
        StaffProfile.objects.create(user=self.worker)
        BuildingStaffVisibility.objects.create(
            user=self.worker, building=self.building
        )
        self.ticket.status = TicketStatus.IN_PROGRESS
        self.ticket.save(update_fields=["status"])

    def _slot(self, *, user=None, sub_task=None, assigned_by=None, days=None):
        when = None
        if days is not None:
            when = timezone.now() + datetime.timedelta(days=days)
        return TicketStaffAssignment.objects.create(
            ticket=self.ticket,
            user=user or self.worker,
            sub_task=sub_task,
            assigned_by=assigned_by or self.company_admin,
            scheduled_start_at=when,
            scheduled_end_at=when,
        )

    def _deadline_rows(self, user):
        event = NotificationEventType.TICKET_DEADLINE_APPROACHING
        return (
            Notification.objects.filter(
                recipient=user, ticket=self.ticket, event_type=event
            ).count(),
            NotificationLog.objects.filter(
                recipient_user=user, ticket=self.ticket, event_type=event
            ).count(),
        )


class TheReminderFiresInsideTheWindowTests(_Fixture):
    def test_fires_when_the_deadline_is_inside_the_window(self):
        self._slot(days=1)
        told = deadline_reminders.sweep()["told"]
        self.assertGreaterEqual(told, 1)
        bell, mail = self._deadline_rows(self.worker)
        self.assertEqual(bell, 1)
        self.assertEqual(mail, 1)

    def test_silent_when_the_deadline_is_beyond_the_window(self):
        # 10 days out: planned, not approaching.
        self._slot(days=10)
        self.assertEqual(deadline_reminders.sweep()["told"], 0)
        self.assertEqual(self._deadline_rows(self.worker), (0, 0))

    def test_silent_when_the_deadline_is_already_past(self):
        # Overdue is a different thing and the Work Plan already says it.
        self._slot(days=-3)
        self.assertEqual(deadline_reminders.sweep()["told"], 0)
        self.assertEqual(self._deadline_rows(self.worker), (0, 0))


class TheReminderDoesNotRepeatTests(_Fixture):
    def test_a_second_sweep_tells_nobody_again(self):
        self._slot(days=1)
        first = deadline_reminders.sweep()["told"]
        self.assertGreaterEqual(first, 1)
        second = deadline_reminders.sweep()["told"]
        self.assertEqual(second, 0, "the reminder became a daily nag")
        bell, mail = self._deadline_rows(self.worker)
        self.assertEqual(bell, 1)
        self.assertEqual(mail, 1)

    def test_a_bell_row_alone_holds_the_door_shut(self):
        """The throttle asks BOTH tables, so a half-written send still
        suppresses the next tick — the same self-healing the SLA cooldown
        has."""
        self._slot(days=1)
        event = NotificationEventType.TICKET_DEADLINE_APPROACHING
        Notification.objects.create(
            recipient=self.worker,
            actor=None,
            event_type=event,
            ticket=self.ticket,
            is_directed=False,
            summary="already told",
        )
        deadline_reminders.sweep()
        _, mail = self._deadline_rows(self.worker)
        self.assertEqual(mail, 0, "the bell row did not suppress the mail")


class TheReminderIgnoresFinishedWorkTests(_Fixture):
    def test_silent_for_a_terminal_ticket(self):
        self._slot(days=1)
        self.ticket.status = TicketStatus.CLOSED
        self.ticket.save(update_fields=["status"])
        self.assertEqual(deadline_reminders.sweep()["told"], 0)
        self.assertEqual(self._deadline_rows(self.worker), (0, 0))


class BeingPutOnAPartTests(_Fixture):
    def _part_rows(self, user):
        return Notification.objects.filter(
            recipient=user,
            ticket=self.ticket,
            event_type=NotificationEventType.TICKET_PART_ASSIGNED,
        )

    def test_assigning_a_part_notifies_the_person(self):
        part = SubTask.objects.create(ticket=self.ticket, title="Windows")
        self._slot()  # base slot, no part: tells nobody
        self.assertEqual(self._part_rows(self.worker).count(), 0)

        self._slot(sub_task=part)
        rows = self._part_rows(self.worker)
        self.assertEqual(rows.count(), 1)
        row = rows.first()
        self.assertTrue(row.is_directed, "a part assignment is directed")
        self.assertEqual(row.actor_id, self.company_admin.id)

    def test_self_assignment_is_silent(self):
        part = SubTask.objects.create(ticket=self.ticket, title="Kitchen")
        self._slot(sub_task=part, assigned_by=self.worker)
        self.assertEqual(
            self._part_rows(self.worker).count(),
            0,
            "a notification told the worker what they had just done",
        )

    def test_moving_a_slot_onto_a_different_part_notifies(self):
        a = SubTask.objects.create(ticket=self.ticket, title="A")
        b = SubTask.objects.create(ticket=self.ticket, title="B")
        slot = self._slot(sub_task=a)
        self.assertEqual(self._part_rows(self.worker).count(), 1)
        slot.sub_task = b
        slot.save(update_fields=["sub_task"])
        self.assertEqual(
            self._part_rows(self.worker).count(),
            2,
            "a move onto a different part is a new assignment",
        )

    def test_saving_without_changing_the_part_is_silent(self):
        a = SubTask.objects.create(ticket=self.ticket, title="A")
        slot = self._slot(sub_task=a)
        self.assertEqual(self._part_rows(self.worker).count(), 1)
        slot.assignment_note = "touched"
        slot.save(update_fields=["assignment_note"])
        self.assertEqual(self._part_rows(self.worker).count(), 1)

    def test_moving_a_slot_off_a_part_is_silent(self):
        a = SubTask.objects.create(ticket=self.ticket, title="A")
        slot = self._slot(sub_task=a)
        before = self._part_rows(self.worker).count()
        slot.sub_task = None
        slot.save(update_fields=["sub_task"])
        self.assertEqual(self._part_rows(self.worker).count(), before)
