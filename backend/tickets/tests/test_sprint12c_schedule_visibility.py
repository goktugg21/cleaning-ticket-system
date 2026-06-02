"""
Sprint 12C — customer-safe schedule visibility on ticket detail.

When a manager reschedules an operational ticket, a CUSTOMER_USER keeps
the customer-safe operational schedule (current start, window, and the
fact that it was rescheduled via `schedule_status`) but MUST NOT see the
provider-internal reschedule audit fields `reschedule_reason` and
`rescheduled_from`. Provider-side roles keep the full fields.

Reuses the Sprint 9B scheduling fixture (`SchedulingBaseTest`) which
builds a ticket on `self.building`, a CUSTOMER_USER with building access,
and the provider roles (SA / CA / BM).
"""
from datetime import timedelta

from django.utils import timezone
from rest_framework import status

from tickets.models import Ticket, TicketScheduleStatus, TicketStatus
from tickets.tests.test_sprint9b_scheduling import (
    SchedulingBaseTest,
    _schedule_url,
)

_RESCHEDULE_REASON = "short-staffed this week (internal)"


def _detail_url(ticket):
    return f"/api/tickets/{ticket.id}/"


class RescheduleCustomerVisibilityTests(SchedulingBaseTest):
    def setUp(self):
        super().setUp()
        # A ticket OWNED by the customer user so the default customer
        # visibility (own tickets) lets them read it back.
        self.cust_ticket = Ticket.objects.create(
            company=self.company,
            building=self.building,
            customer=self.customer,
            created_by=self.customer_user,
            title="cust-owned",
            description="d",
            status=TicketStatus.OPEN,
        )

    def _reschedule(self):
        self._auth(self.bm)
        start = timezone.now() + timedelta(days=2)
        first = self.client.post(
            _schedule_url(self.cust_ticket),
            {"scheduled_start_at": start.isoformat()},
            format="json",
        )
        self.assertEqual(first.status_code, status.HTTP_200_OK, first.data)
        new_start = timezone.now() + timedelta(days=6)
        second = self.client.post(
            _schedule_url(self.cust_ticket),
            {
                "scheduled_start_at": new_start.isoformat(),
                "reschedule_reason": _RESCHEDULE_REASON,
            },
            format="json",
        )
        self.assertEqual(second.status_code, status.HTTP_200_OK, second.data)
        self.cust_ticket.refresh_from_db()

    def test_customer_cannot_see_internal_reschedule_fields(self):
        self._reschedule()
        self._auth(self.customer_user)
        resp = self.client.get(_detail_url(self.cust_ticket))
        self.assertEqual(resp.status_code, status.HTTP_200_OK, resp.data)
        # Customer-safe operational schedule is still visible.
        self.assertIsNotNone(resp.data["scheduled_start_at"])
        self.assertEqual(
            resp.data["schedule_status"], TicketScheduleStatus.RESCHEDULED
        )
        # Provider-internal reschedule fields are redacted.
        self.assertEqual(resp.data["reschedule_reason"], "")
        self.assertIsNone(resp.data["rescheduled_from"])

    def test_provider_roles_see_full_reschedule_fields(self):
        self._reschedule()
        for actor in (self.sa, self.ca, self.bm):
            self._auth(actor)
            resp = self.client.get(_detail_url(self.cust_ticket))
            self.assertEqual(resp.status_code, status.HTTP_200_OK, resp.data)
            self.assertEqual(
                resp.data["reschedule_reason"], _RESCHEDULE_REASON, actor.email
            )
            self.assertIsNotNone(resp.data["rescheduled_from"], actor.email)
