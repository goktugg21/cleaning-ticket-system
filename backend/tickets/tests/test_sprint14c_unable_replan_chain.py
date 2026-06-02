"""
Sprint 14C — end-to-end regression for the unable-to-complete recovery loop.

The individual legs of this workflow are each covered in isolation by the
Sprint 9B (scheduling) and Sprint 10B (assignment / unable-to-complete)
suites, but the operationally critical *combined* loop is never pinned as
one sequence. This test proves it once:

    ticket IN_PROGRESS, staff_a assigned
      -> provider schedules it (a first date)
      -> staff_a marks it unable-to-complete  (-> WAITING_MANAGER_REVIEW)
      -> provider RESCHEDULES the SAME ticket to a later date
      -> provider assigns a DIFFERENT staff (adds staff_a_two, drops staff_a)
      -> status / schedule / staff membership / status-history stay correct.

The production code already supports this because WAITING_MANAGER_REVIEW is
deliberately NON-terminal for `/schedule/`, `/staff-assignments/` and
`/manager-assignments/`. This test is the missing safety net: a future
terminal-set or gate change cannot silently break the
"staff blocked -> manager replans + reassigns" workflow without turning
this test red.
"""
import datetime

from django.utils import timezone

from tickets.models import (
    TicketScheduleStatus,
    TicketStaffAssignment,
    TicketStatus,
)

from .test_sprint10b_assignment import _Sprint10BFixture


class UnableToCompleteReplanReassignChainTests(_Sprint10BFixture):
    def setUp(self):
        super().setUp()
        # ticket_a starts IN_PROGRESS with staff_a assigned — the worker who
        # will hit the wall.
        self.ticket_a.status = TicketStatus.IN_PROGRESS
        self.ticket_a.save(update_fields=["status"])
        TicketStaffAssignment.objects.create(
            ticket=self.ticket_a, user=self.staff_a, assigned_by=self.admin_a
        )

    def _schedule_url(self):
        return f"/api/tickets/{self.ticket_a.id}/schedule/"

    def _staff_list_url(self):
        return f"/api/tickets/{self.ticket_a.id}/staff-assignments/"

    def _staff_detail_url(self, user):
        return f"/api/tickets/{self.ticket_a.id}/staff-assignments/{user.id}/"

    def test_unable_to_complete_replan_reassign_chain(self):
        admin = self._api(self.admin_a)
        first_start = (timezone.now() + datetime.timedelta(days=7)).replace(
            microsecond=0
        )
        later_start = first_start + datetime.timedelta(days=1)

        # (1) Provider schedules the ticket for the first date.
        resp = admin.post(
            self._schedule_url(),
            {"scheduled_start_at": first_start.isoformat()},
            format="json",
        )
        self.assertEqual(resp.status_code, 200, resp.data)
        self.ticket_a.refresh_from_db()
        self.assertEqual(
            self.ticket_a.schedule_status, TicketScheduleStatus.SCHEDULED
        )
        self.assertIsNotNone(self.ticket_a.scheduled_start_at)
        self.assertIsNone(self.ticket_a.rescheduled_from)
        first_stored = self.ticket_a.scheduled_start_at

        # (2) The assigned staff hits a wall and marks it unable-to-complete.
        resp = self._api(self.staff_a).post(
            f"/api/tickets/{self.ticket_a.id}/unable-to-complete/",
            {"reason": "Locked out, no key available"},
            format="json",
        )
        self.assertEqual(resp.status_code, 200, resp.data)
        self.ticket_a.refresh_from_db()
        self.assertEqual(
            self.ticket_a.status, TicketStatus.WAITING_MANAGER_REVIEW
        )

        # (3) Provider RESCHEDULES the SAME ticket to a later date while it
        #     sits in WAITING_MANAGER_REVIEW — proving /schedule/ is NOT
        #     blocked by the non-terminal manager-review state. A true
        #     reschedule requires a reason.
        resp = admin.post(
            self._schedule_url(),
            {
                "scheduled_start_at": later_start.isoformat(),
                "reschedule_reason": "staff could not complete; replanned",
            },
            format="json",
        )
        self.assertEqual(resp.status_code, 200, resp.data)
        self.ticket_a.refresh_from_db()
        self.assertEqual(
            self.ticket_a.schedule_status, TicketScheduleStatus.RESCHEDULED
        )
        self.assertGreater(self.ticket_a.scheduled_start_at, first_stored)
        self.assertEqual(self.ticket_a.rescheduled_from, first_stored)
        # Scheduling never moves the lifecycle — still in manager review.
        self.assertEqual(
            self.ticket_a.status, TicketStatus.WAITING_MANAGER_REVIEW
        )

        # (4) Provider assigns a DIFFERENT staff and drops the original one,
        #     all while the ticket is in WAITING_MANAGER_REVIEW.
        resp = admin.post(
            self._staff_list_url(),
            {"user_id": self.staff_a_two.id},
            format="json",
        )
        self.assertEqual(resp.status_code, 201, resp.data)
        resp = admin.delete(self._staff_detail_url(self.staff_a))
        self.assertEqual(resp.status_code, 204, getattr(resp, "data", None))

        membership = set(
            TicketStaffAssignment.objects.filter(
                ticket=self.ticket_a
            ).values_list("user_id", flat=True)
        )
        self.assertEqual(membership, {self.staff_a_two.id})

        # (5) Status history stays correct: exactly ONE lifecycle-moving row
        #     (IN_PROGRESS -> WAITING_MANAGER_REVIEW, authored by the staff
        #     who could not complete, carrying the unable marker). Neither
        #     the (re)schedule annotations nor the staff reassignment churn
        #     introduced any spurious lifecycle transition.
        history = list(self.ticket_a.status_history.order_by("created_at"))
        real_changes = [h for h in history if h.old_status != h.new_status]
        self.assertEqual(len(real_changes), 1, [h.note for h in history])
        unable_row = real_changes[0]
        self.assertEqual(unable_row.old_status, TicketStatus.IN_PROGRESS)
        self.assertEqual(
            unable_row.new_status, TicketStatus.WAITING_MANAGER_REVIEW
        )
        self.assertEqual(unable_row.changed_by, self.staff_a)
        self.assertIn("[UNABLE TO COMPLETE]", unable_row.note)
        # The ticket is left in the manager-review queue, replanned for the
        # later date and reassigned to a fresh worker.
        self.assertEqual(
            self.ticket_a.status, TicketStatus.WAITING_MANAGER_REVIEW
        )
