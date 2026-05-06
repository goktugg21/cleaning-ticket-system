from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from test_utils import TenantFixtureMixin
from tickets.models import Ticket


URL = "/api/reports/sla-distribution/"


def _force(ticket, **fields):
    Ticket.objects.filter(pk=ticket.pk).update(**fields)
    ticket.refresh_from_db()
    return ticket


class SLADistributionTests(TenantFixtureMixin, APITestCase):
    def setUp(self):
        super().setUp()
        # Spread the company-A tickets across the SLA states to exercise
        # bucket assignment and the paused-overrides priority.
        self.t_at_risk = Ticket.objects.create(
            company=self.company,
            building=self.building,
            customer=self.customer,
            created_by=self.customer_user,
            title="At risk", description="At risk",
        )
        _force(self.t_at_risk, sla_status="AT_RISK")

        self.t_breached = Ticket.objects.create(
            company=self.company,
            building=self.building,
            customer=self.customer,
            created_by=self.customer_user,
            title="Breached", description="Breached",
        )
        _force(self.t_breached, sla_status="BREACHED")

        self.t_paused_breached = Ticket.objects.create(
            company=self.company,
            building=self.building,
            customer=self.customer,
            created_by=self.customer_user,
            title="Paused-while-breached",
            description="Paused-while-breached",
        )
        _force(
            self.t_paused_breached,
            sla_status="BREACHED",
            sla_paused_at=timezone.now(),
        )

        self.t_completed = Ticket.objects.create(
            company=self.company,
            building=self.building,
            customer=self.customer,
            created_by=self.customer_user,
            title="Completed", description="Completed",
        )
        _force(self.t_completed, sla_status="COMPLETED")

        self.t_historical = Ticket.objects.create(
            company=self.company,
            building=self.building,
            customer=self.customer,
            created_by=self.customer_user,
            title="Historical", description="Historical",
        )
        _force(self.t_historical, sla_status="HISTORICAL")

        # self.ticket stays ON_TRACK (default after signal). Company A:
        # ON_TRACK=1, AT_RISK=1, BREACHED=1, PAUSED=1, COMPLETED=1, HISTORICAL=1
        # for a total of 6.

    def test_unauthenticated_returns_401(self):
        response = self.client.get(URL)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_customer_user_returns_403(self):
        self.client.force_authenticate(user=self.customer_user)
        response = self.client.get(URL)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_returns_six_buckets_in_fixed_order(self):
        self.client.force_authenticate(user=self.super_admin)
        response = self.client.get(URL)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        states = [b["state"] for b in response.data["buckets"]]
        self.assertEqual(
            states,
            ["ON_TRACK", "AT_RISK", "BREACHED", "PAUSED", "COMPLETED", "HISTORICAL"],
        )

    def test_company_admin_sees_only_own_company(self):
        self.client.force_authenticate(user=self.company_admin)
        response = self.client.get(URL)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        counts = {b["state"]: b["count"] for b in response.data["buckets"]}
        # Company A: ON_TRACK=1 (self.ticket), AT_RISK=1, BREACHED=1,
        # PAUSED=1, COMPLETED=1, HISTORICAL=1.
        self.assertEqual(counts["ON_TRACK"], 1)
        self.assertEqual(counts["AT_RISK"], 1)
        self.assertEqual(counts["BREACHED"], 1)
        self.assertEqual(counts["PAUSED"], 1)
        self.assertEqual(counts["COMPLETED"], 1)
        self.assertEqual(counts["HISTORICAL"], 1)
        self.assertEqual(response.data["total"], 6)

    def test_paused_overrides_breached(self):
        # The paused-while-breached ticket counts in PAUSED, not BREACHED.
        self.client.force_authenticate(user=self.company_admin)
        response = self.client.get(URL)
        counts = {b["state"]: b["count"] for b in response.data["buckets"]}
        self.assertEqual(counts["PAUSED"], 1)
        # Only the unpaused breached ticket appears in BREACHED.
        self.assertEqual(counts["BREACHED"], 1)

    def test_building_manager_sees_assigned_building_only(self):
        self.client.force_authenticate(user=self.manager)
        response = self.client.get(URL)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        # Manager A is on building A; sees the same 6 company-A tickets.
        self.assertEqual(response.data["total"], 6)

    def test_cross_tenant_returns_403(self):
        self.client.force_authenticate(user=self.company_admin)
        response = self.client.get(URL, {"company": self.other_company.id})
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_empty_scope_still_returns_six_buckets(self):
        from companies.models import Company

        empty = Company.objects.create(name="Empty Co", slug="empty-co")
        self.client.force_authenticate(user=self.super_admin)
        response = self.client.get(URL, {"company": empty.id})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["total"], 0)
        self.assertEqual(
            [b["state"] for b in response.data["buckets"]],
            ["ON_TRACK", "AT_RISK", "BREACHED", "PAUSED", "COMPLETED", "HISTORICAL"],
        )
        self.assertTrue(all(b["count"] == 0 for b in response.data["buckets"]))
