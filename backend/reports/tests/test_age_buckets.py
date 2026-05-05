from datetime import timedelta

from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from test_utils import TenantFixtureMixin
from tickets.models import Ticket, TicketStatus

from ._fixtures import make_ticket_at, set_status


URL = "/api/reports/age-buckets/"


class AgeBucketsTests(TenantFixtureMixin, APITestCase):
    def _make_open_at(self, when, *, company=None, building=None, customer=None,
                      creator=None, status_value=TicketStatus.OPEN):
        ticket = make_ticket_at(
            when,
            company=company or self.company,
            building=building or self.building,
            customer=customer or self.customer,
            created_by=creator or self.customer_user,
            title="t",
            description="t",
        )
        if status_value != TicketStatus.OPEN:
            set_status(ticket, status_value)
        return ticket

    def setUp(self):
        super().setUp()
        # The TenantFixtureMixin already created self.ticket and self.other_ticket
        # at "now" (auto_now_add). They are OPEN by default. Force them out of
        # scope of these tests by deleting; we'll create fresh ones with known
        # ages.
        Ticket.objects.all().delete()

    def test_unauthenticated_returns_401(self):
        response = self.client.get(URL)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_customer_user_returns_403(self):
        self.client.force_authenticate(user=self.customer_user)
        response = self.client.get(URL)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_buckets_partition_open_tickets_by_age(self):
        now = timezone.now()
        # Bucket 0_1: 0 days and 1 day old.
        self._make_open_at(now - timedelta(hours=2))
        self._make_open_at(now - timedelta(days=1))
        # Bucket 2_7: 5 days old.
        self._make_open_at(now - timedelta(days=5))
        # Bucket 8_30: 20 days old.
        self._make_open_at(now - timedelta(days=20))
        # Bucket 31_plus: 100 days old.
        self._make_open_at(now - timedelta(days=100))

        self.client.force_authenticate(user=self.super_admin)
        response = self.client.get(URL)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        by_key = {b["key"]: b["count"] for b in response.data["buckets"]}
        self.assertEqual(by_key["0_1"], 2)
        self.assertEqual(by_key["2_7"], 1)
        self.assertEqual(by_key["8_30"], 1)
        self.assertEqual(by_key["31_plus"], 1)
        self.assertEqual(response.data["total_open"], 5)

    def test_terminal_statuses_excluded(self):
        now = timezone.now()
        # APPROVED and REJECTED are terminal: must NOT count.
        self._make_open_at(
            now - timedelta(days=3), status_value=TicketStatus.APPROVED
        )
        self._make_open_at(
            now - timedelta(days=3), status_value=TicketStatus.REJECTED
        )
        # CLOSED counts as open per the strict spec interpretation.
        self._make_open_at(
            now - timedelta(days=3), status_value=TicketStatus.CLOSED
        )
        # WAITING_CUSTOMER_APPROVAL counts as open.
        self._make_open_at(
            now - timedelta(days=3),
            status_value=TicketStatus.WAITING_CUSTOMER_APPROVAL,
        )

        self.client.force_authenticate(user=self.super_admin)
        response = self.client.get(URL)
        # Only CLOSED + WAITING_CUSTOMER_APPROVAL count: 2 in bucket 2_7.
        by_key = {b["key"]: b["count"] for b in response.data["buckets"]}
        self.assertEqual(by_key["2_7"], 2)
        self.assertEqual(response.data["total_open"], 2)

    def test_super_admin_sees_all_companies(self):
        now = timezone.now()
        self._make_open_at(now - timedelta(days=5))
        self._make_open_at(
            now - timedelta(days=5),
            company=self.other_company,
            building=self.other_building,
            customer=self.other_customer,
            creator=self.other_customer_user,
        )
        self.client.force_authenticate(user=self.super_admin)
        response = self.client.get(URL)
        self.assertEqual(response.data["total_open"], 2)

    def test_company_admin_sees_only_own_company(self):
        now = timezone.now()
        self._make_open_at(now - timedelta(days=5))
        self._make_open_at(
            now - timedelta(days=5),
            company=self.other_company,
            building=self.other_building,
            customer=self.other_customer,
            creator=self.other_customer_user,
        )
        self.client.force_authenticate(user=self.company_admin)
        response = self.client.get(URL)
        self.assertEqual(response.data["total_open"], 1)

    def test_company_admin_cross_tenant_returns_403(self):
        self.client.force_authenticate(user=self.company_admin)
        response = self.client.get(URL, {"company": self.other_company.id})
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_building_manager_sees_assigned_building(self):
        now = timezone.now()
        self._make_open_at(now - timedelta(days=5))
        self.client.force_authenticate(user=self.manager)
        response = self.client.get(URL)
        self.assertEqual(response.data["total_open"], 1)

    def test_building_manager_cross_building_returns_403(self):
        self.client.force_authenticate(user=self.manager)
        response = self.client.get(URL, {"building": self.other_building.id})
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_bucket_boundaries_exposed_in_payload(self):
        self.client.force_authenticate(user=self.super_admin)
        response = self.client.get(URL)
        keys = [b["key"] for b in response.data["buckets"]]
        self.assertEqual(keys, ["0_1", "2_7", "8_30", "31_plus"])
        last = response.data["buckets"][-1]
        self.assertEqual(last["min_days"], 31)
        self.assertIsNone(last["max_days"])

    def test_empty_scope_returns_zero_total(self):
        self.client.force_authenticate(user=self.super_admin)
        response = self.client.get(URL)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["total_open"], 0)
        self.assertEqual(len(response.data["buckets"]), 4)
