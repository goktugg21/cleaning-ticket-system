"""P-13 A (O1) — the at-risk fold says the state the job is in.

The owner met a row reading "Stuck at: stuck". Every row now carries a
`reason` (the job's real state), a `since` date, and — for the review
wait — the manager names, so the screen renders a sentence and the
word "stuck" leaves the vocabulary. Two states the fold was blind to
join it: an ON_HOLD job (the Part G seed's required fixture) and a job
whose promised day passed with nobody having planned it.
"""
from __future__ import annotations

import datetime

from django.utils import timezone
from rest_framework.test import APITestCase

from accounts.models import UserRole
from extra_work.models import (
    ExtraWorkAssignment,
    ExtraWorkAssignmentRole,
)
from invoicing.at_risk import (
    REASON_NOT_PLANNED,
    REASON_ON_HOLD,
    REASON_REVIEW_WAIT,
    STAGE_NOT_PLANNED,
    STAGE_ON_HOLD,
)
from tickets.models import TicketStatus, TicketStatusHistory

from .test_at_risk import AtRiskFixture


class AtRiskReasonTests(AtRiskFixture, APITestCase):
    def test_on_hold_job_is_listed_with_its_hold_date(self):
        ew = self.make_ew("Held job", deadline=self.today)
        ticket = self.spawn(ew, TicketStatus.ON_HOLD)
        history = TicketStatusHistory.objects.create(
            ticket=ticket,
            old_status=TicketStatus.IN_PROGRESS,
            new_status=TicketStatus.ON_HOLD,
            changed_by=self.super_admin,
        )
        # auto_now_add wins on create; backdate the hold to five days
        # ago the way the walk scripts do.
        held_on = timezone.now() - datetime.timedelta(days=5)
        TicketStatusHistory.objects.filter(pk=history.pk).update(
            created_at=held_on
        )

        rows = self.rows_for(
            self.get_at_risk(self.super_admin), self.customer.id
        )
        self.assertEqual(len(rows), 1, rows)
        row = rows[0]
        self.assertEqual(row["stage"], STAGE_ON_HOLD)
        self.assertEqual(row["reason"], REASON_ON_HOLD)
        self.assertEqual(
            row["since"], timezone.localtime(held_on).date().isoformat()
        )
        self.assertEqual(row["age_days"], 5)

    def test_unplanned_job_past_its_day_is_listed(self):
        ew = self.make_ew(
            "Never planned",
            deadline=self.today - datetime.timedelta(days=3),
        )
        self.spawn(ew, TicketStatus.OPEN)  # no slots, no schedule

        rows = self.rows_for(
            self.get_at_risk(self.super_admin), self.customer.id
        )
        self.assertEqual(len(rows), 1, rows)
        row = rows[0]
        self.assertEqual(row["stage"], STAGE_NOT_PLANNED)
        self.assertEqual(row["reason"], REASON_NOT_PLANNED)
        self.assertEqual(row["age_days"], 3)

    def test_review_wait_row_names_the_managers(self):
        ew = self.make_ew("Waiting on the check", deadline=self.today)
        manager = self.make_user(
            "gokhan-atrisk@example.com", UserRole.BUILDING_MANAGER
        )
        manager.full_name = "Gökhan"
        manager.save(update_fields=["full_name"])
        ExtraWorkAssignment.objects.create(
            extra_work_request=ew,
            user=manager,
            role=ExtraWorkAssignmentRole.MANAGER,
            assigned_by=self.super_admin,
        )
        self.spawn(
            ew,
            TicketStatus.WAITING_MANAGER_REVIEW,
            manager_review_at=timezone.now() - datetime.timedelta(days=8),
        )

        rows = self.rows_for(
            self.get_at_risk(self.super_admin), self.customer.id
        )
        self.assertEqual(len(rows), 1, rows)
        row = rows[0]
        self.assertEqual(row["reason"], REASON_REVIEW_WAIT)
        self.assertEqual(row["manager_names"], ["Gökhan"])
