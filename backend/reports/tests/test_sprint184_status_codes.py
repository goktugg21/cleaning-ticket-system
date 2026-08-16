"""
Sprint 184 §2 — the status chart stopped shipping a fourth vocabulary.

`/api/reports/status-distribution/` used to emit `TicketStatus.choices`'
English label beside each code ("Approved", "Waiting Customer
Approval"), and the chart printed it as it arrived — so a Dutch-first
screen showed English status words that had never passed through the
translation layer. The label is GONE from the payload rather than merely
unused by the chart: a display-shaped string on the wire is how the next
caller renders it again.

This is the test that renders the endpoint carrying the change, which is
what the gate asks for whenever a field moves.
"""
from __future__ import annotations

from rest_framework.test import APIClient, APITestCase

from tickets.models import Ticket, TicketStatus
from test_utils import TenantFixtureMixin

URL = "/api/reports/status-distribution/"


class StatusDistributionPayloadTests(TenantFixtureMixin, APITestCase):
    def api(self, user):
        client = APIClient()
        client.force_authenticate(user=user)
        return client

    def test_every_bucket_carries_a_status_code(self):
        response = self.api(self.super_admin).get(URL)
        self.assertEqual(response.status_code, 200, response.data)
        codes = [bucket["status"] for bucket in response.data["buckets"]]
        self.assertEqual(sorted(codes), sorted(TicketStatus.values))

    def test_no_bucket_carries_a_display_label(self):
        """The whole point. A `label` key returning would put the English
        vocabulary back on a Dutch screen."""
        response = self.api(self.super_admin).get(URL)
        for bucket in response.data["buckets"]:
            with self.subTest(status=bucket["status"]):
                self.assertEqual(
                    sorted(bucket.keys()),
                    ["count", "status"],
                    "status-distribution buckets are a code and a count. "
                    "A display string here is a vocabulary the client "
                    "cannot translate.",
                )

    def test_the_counts_still_count(self):
        """The shape changed; the arithmetic must not have."""
        Ticket.objects.create(
            company=self.company,
            building=self.building,
            customer=self.customer,
            title="Sprint 184 status chart",
            description="x",
            type="REPORT",
            status=TicketStatus.OPEN,
            created_by=self.super_admin,
        )
        response = self.api(self.super_admin).get(URL)
        buckets = {b["status"]: b["count"] for b in response.data["buckets"]}
        self.assertGreaterEqual(buckets[str(TicketStatus.OPEN)], 1)
        self.assertEqual(
            response.data["total"], sum(b["count"] for b in response.data["buckets"])
        )

    def test_the_ninth_status_is_a_bucket_like_any_other(self):
        """`CONVERTED_TO_EXTRA_WORK` is a real status with real rows; the
        chart has to be able to name it, which it now can because it
        receives the code rather than a label the server chose."""
        codes = [
            b["status"]
            for b in self.api(self.super_admin).get(URL).data["buckets"]
        ]
        self.assertIn(str(TicketStatus.CONVERTED_TO_EXTRA_WORK), codes)
