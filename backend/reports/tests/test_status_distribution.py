from rest_framework import status
from rest_framework.test import APITestCase

from test_utils import TenantFixtureMixin
from tickets.models import Ticket, TicketStatus

from ._fixtures import set_status


URL = "/api/reports/status-distribution/"


class StatusDistributionTests(TenantFixtureMixin, APITestCase):
    def setUp(self):
        super().setUp()
        # Make a few extra tickets in the SAME company A to vary statuses.
        # self.ticket starts in OPEN; create one IN_PROGRESS and one APPROVED.
        in_progress = Ticket.objects.create(
            company=self.company,
            building=self.building,
            customer=self.customer,
            created_by=self.customer_user,
            title="IP",
            description="IP",
        )
        set_status(in_progress, TicketStatus.IN_PROGRESS)
        approved = Ticket.objects.create(
            company=self.company,
            building=self.building,
            customer=self.customer,
            created_by=self.customer_user,
            title="A",
            description="A",
        )
        set_status(approved, TicketStatus.APPROVED)

    def test_unauthenticated_returns_401(self):
        response = self.client.get(URL)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_customer_user_returns_403(self):
        self.client.force_authenticate(user=self.customer_user)
        response = self.client.get(URL)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_super_admin_sees_all_buckets_with_total(self):
        self.client.force_authenticate(user=self.super_admin)
        response = self.client.get(URL)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.data
        # Buckets cover every TicketStatus value, even with count 0.
        bucket_keys = {b["status"] for b in data["buckets"]}
        self.assertEqual(bucket_keys, set(TicketStatus.values))
        # Total equals 4: ticket A in OPEN (self.ticket) + IN_PROGRESS + APPROVED
        # plus the cross-tenant ticket B (self.other_ticket, OPEN). Super admin
        # sees both companies.
        self.assertEqual(data["total"], 4)
        self.assertIn("as_of", data)
        # Scope is null when no ?company= or ?building= is sent.
        self.assertIsNone(data["scope"]["company_id"])
        self.assertIsNone(data["scope"]["building_id"])

    def test_company_admin_sees_only_own_company(self):
        self.client.force_authenticate(user=self.company_admin)
        response = self.client.get(URL)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        # Company A has 3 tickets (OPEN, IN_PROGRESS, APPROVED).
        # Company B's ticket must not contribute.
        self.assertEqual(response.data["total"], 3)

    def test_company_admin_explicit_own_company_param_ok(self):
        self.client.force_authenticate(user=self.company_admin)
        response = self.client.get(URL, {"company": self.company.id})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["scope"]["company_id"], self.company.id)
        self.assertEqual(response.data["scope"]["company_name"], self.company.name)

    def test_company_admin_cross_tenant_returns_403(self):
        self.client.force_authenticate(user=self.company_admin)
        response = self.client.get(URL, {"company": self.other_company.id})
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_building_manager_sees_own_building(self):
        self.client.force_authenticate(user=self.manager)
        response = self.client.get(URL)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        # Manager is assigned to building A; sees the same 3 company-A tickets.
        self.assertEqual(response.data["total"], 3)

    def test_building_manager_cross_building_returns_403(self):
        self.client.force_authenticate(user=self.manager)
        response = self.client.get(URL, {"building": self.other_building.id})
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_building_company_mismatch_returns_400(self):
        # Building B belongs to company B; passing company=A and building=B is
        # inconsistent. The actor here is super admin so neither id is denied
        # outright; the mismatch surfaces as 400.
        self.client.force_authenticate(user=self.super_admin)
        response = self.client.get(
            URL, {"company": self.company.id, "building": self.other_building.id}
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_malformed_company_id_returns_400(self):
        self.client.force_authenticate(user=self.super_admin)
        response = self.client.get(URL, {"company": "not-an-int"})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_empty_scope_returns_zero_total(self):
        # New super admin with no membership doesn't matter for super admin —
        # they see all. But filtering to a company with no tickets should give
        # total=0 with a fully-shaped buckets array.
        from companies.models import Company

        empty_company = Company.objects.create(name="Empty Co", slug="empty-co")
        self.client.force_authenticate(user=self.super_admin)
        response = self.client.get(URL, {"company": empty_company.id})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["total"], 0)
        self.assertEqual(
            {b["status"] for b in response.data["buckets"]},
            set(TicketStatus.values),
        )
        self.assertTrue(all(b["count"] == 0 for b in response.data["buckets"]))
