"""Sprint 11B Batch 4 — SLA regression for planned tickets.

Covers brief scenario 22: a planned/recurring ticket spawned up to 14
days ahead of its planned date must stay SLA-exempt (HISTORICAL) and be
excluded from breach counting, even after the periodic reconcile task
runs. This proves a look-ahead planned ticket never false-breaches.
"""
from __future__ import annotations

import datetime

from rest_framework.test import APITestCase

from planned_work.generation import generate_occurrences
from planned_work.models import Frequency, PlannedOccurrence
from sla.tasks import reconcile_sla_states
from tickets.models import Ticket

from ._base import PlannedWorkFixtureMixin


TODAY = datetime.date(2026, 6, 1)


class PlannedTicketSlaExemptTests(PlannedWorkFixtureMixin, APITestCase):
    def test_planned_ticket_stays_historical_after_reconcile(self):
        job = self.make_recurring_job(
            frequency=Frequency.WEEKLY, start_date=TODAY, end_date=TODAY
        )
        generate_occurrences(days_ahead=14, today=TODAY)
        occ = PlannedOccurrence.objects.get(recurring_job=job)
        ticket = Ticket.objects.get(planned_occurrence=occ)

        # Pre-condition: spawn already forced HISTORICAL exemption.
        self.assertEqual(ticket.sla_status, "HISTORICAL")
        self.assertIsNone(ticket.sla_due_at)

        result = reconcile_sla_states()

        ticket.refresh_from_db()
        self.assertEqual(ticket.sla_status, "HISTORICAL")
        self.assertNotIn(ticket.sla_status, {"BREACHED", "AT_RISK"})

        # The reconcile task excludes HISTORICAL tickets from the
        # checked/breach-counted set entirely.
        self.assertNotIn(
            ticket.pk,
            set(
                Ticket.objects.exclude(sla_status="HISTORICAL").values_list(
                    "pk", flat=True
                )
            ),
        )
        self.assertIsInstance(result, dict)
