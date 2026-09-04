"""W-FIX1 D6 (audit F27) — seen-and-scheduled work that never starts
still warns.

W10 added ACKNOWLEDGED ("seen, scheduled, not started") after the
not-started sweep was written, and the sweep's status set never learned
it. Tickets 336, 356 and 371 on crmtest sat ACKNOWLEDGED with starts
days in the past and no warning. ON_HOLD is deliberately left out:
parked work is parked on purpose.
"""
from __future__ import annotations

import datetime

from notifications.models import NotificationType
from sla import warnings as sla_warnings
from tickets.models import Ticket, TicketStatus

from .test_w4q_inapp_warnings import NOW, InAppWarningTestBase, _bell_recipients


class AcknowledgedTicketsWarnTests(InAppWarningTestBase):
    def _stage(self, ticket_status, days=2):
        Ticket.objects.filter(pk=self.ticket.pk).update(
            status=ticket_status,
            scheduled_start_at=NOW - datetime.timedelta(days=days),
        )

    def test_an_acknowledged_ticket_past_its_start_warns(self):
        self._stage(TicketStatus.ACKNOWLEDGED)
        sla_warnings.sweep(now=NOW)
        self.assertIn(
            self.manager.email,
            _bell_recipients(NotificationType.SLA_WORK_NOT_STARTED),
        )

    def test_the_set_names_acknowledged(self):
        self.assertIn(
            TicketStatus.ACKNOWLEDGED, sla_warnings.NOT_STARTED_TICKET_STATUSES
        )
        self.assertNotIn(TicketStatus.ON_HOLD, sla_warnings.NOT_STARTED_TICKET_STATUSES)
        self.assertNotIn(
            TicketStatus.IN_PROGRESS, sla_warnings.NOT_STARTED_TICKET_STATUSES
        )

    def test_a_started_ticket_does_not_warn(self):
        self._stage(TicketStatus.IN_PROGRESS)
        sla_warnings.sweep(now=NOW)
        self.assertNotIn(
            self.manager.email,
            _bell_recipients(NotificationType.SLA_WORK_NOT_STARTED),
        )
