"""
Sprint 173 §4 — the deadline, the planned window, and the inconsistency
made visible.

The father's complaint was eleven date columns that keep breaking date
queries. We are structurally ahead: `ExtraWorkStatusHistory` records
every transition with who and when, so "when was it approved" is a
QUERY over the history rather than a column. What we genuinely lacked
is a deadline and a planned END, and that is all this adds.

What these pin:

  * `is_overdue` is past-deadline AND unfinished — finished work is
    never late, and a record with no deadline is never late either
    (inventing a due date to call something late is worse than not
    marking it);
  * `started_before_plan` is derived from the STATUS HISTORY, not from
    a started_at column;
  * the QUERY filters agree with the PYTHON properties. Two definitions
    of "late" is exactly the drift this sprint exists to remove.
"""
from __future__ import annotations

from datetime import timedelta

from django.utils import timezone

from django.test import TestCase

from extra_work.models import ExtraWorkRequest, ExtraWorkStatus

from .test_extra_work_mvp import ExtraWorkFixtureMixin


class DeadlineTests(ExtraWorkFixtureMixin, TestCase):
    @classmethod
    def setUpTestData(cls):
        # The mixin builds its fixture through `_setup_fixture`, which
        # each test class calls itself — it is not a `setUpTestData`
        # override, so inheriting the mixin alone gives you nothing.
        cls._setup_fixture()

    def mk(self, **kwargs):
        defaults = dict(
            company=self.provider_a,
            customer=self.customer_a,
            building=self.building_a1,
            title="Late job",
            description="x",
            created_by=self.admin_a,
        )
        defaults.update(kwargs)
        return ExtraWorkRequest.objects.create(**defaults)

    def test_past_deadline_and_unfinished_is_overdue(self):
        row = self.mk(deadline=timezone.localdate() - timedelta(days=1))
        self.assertTrue(row.is_overdue)

    def test_finished_work_is_never_late(self):
        row = self.mk(
            deadline=timezone.localdate() - timedelta(days=5),
            status=ExtraWorkStatus.COMPLETED,
        )
        self.assertFalse(row.is_overdue)

    def test_no_deadline_is_never_late(self):
        """Nobody said when it was due. Inventing a due date to call
        something late is worse than not marking it."""
        self.assertFalse(self.mk(deadline=None).is_overdue)

    def test_a_future_deadline_is_not_late(self):
        row = self.mk(deadline=timezone.localdate() + timedelta(days=3))
        self.assertFalse(row.is_overdue)

    def test_the_query_filter_agrees_with_the_property(self):
        """Two definitions of "late" is the drift this removes."""
        late = self.mk(deadline=timezone.localdate() - timedelta(days=2))
        self.mk(deadline=timezone.localdate() + timedelta(days=2))
        self.mk(deadline=None)
        self.mk(
            deadline=timezone.localdate() - timedelta(days=9),
            status=ExtraWorkStatus.CANCELLED,
        )

        from extra_work.filters import ExtraWorkRequestFilter

        filtered = ExtraWorkRequestFilter(
            {"overdue": "true"}, queryset=ExtraWorkRequest.objects.all()
        ).qs
        by_property = {
            row.id for row in ExtraWorkRequest.objects.all() if row.is_overdue
        }
        self.assertEqual({row.id for row in filtered}, by_property)
        self.assertEqual(by_property, {late.id})

    def test_the_planned_window_is_a_pair(self):
        today = timezone.localdate()
        row = self.mk(
            preferred_date=today, planned_end_date=today + timedelta(days=3)
        )
        row.refresh_from_db()
        self.assertEqual(row.preferred_date, today)
        self.assertEqual(row.planned_end_date, today + timedelta(days=3))

    def test_started_before_plan_reads_the_history_not_a_column(self):
        """The father's own example: entered today, started today,
        planned for September."""
        from extra_work.models import ExtraWorkStatusHistory

        row = self.mk(preferred_date=timezone.localdate() + timedelta(days=30))
        self.assertFalse(row.started_before_plan)

        ExtraWorkStatusHistory.objects.create(
            extra_work=row,
            old_status=ExtraWorkStatus.REQUESTED,
            new_status=ExtraWorkStatus.IN_PROGRESS,
            changed_by=self.admin_a,
        )
        self.assertTrue(row.started_before_plan)

    def test_starting_within_the_plan_is_not_flagged(self):
        from extra_work.models import ExtraWorkStatusHistory

        row = self.mk(preferred_date=timezone.localdate() - timedelta(days=5))
        ExtraWorkStatusHistory.objects.create(
            extra_work=row,
            old_status=ExtraWorkStatus.REQUESTED,
            new_status=ExtraWorkStatus.IN_PROGRESS,
            changed_by=self.admin_a,
        )
        self.assertFalse(row.started_before_plan)
