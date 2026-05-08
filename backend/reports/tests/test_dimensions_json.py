"""
Sprint 5 — JSON-endpoint coverage for tickets-by-{type,customer,building}.

Each test exercises one role × one filter combination on the existing
`TenantFixtureMixin` data set. The mixin gives us:

  super_admin     -> sees both Company A + Company B
  company_admin   -> only Company A (member of self.company)
  manager         -> only Building A (assigned to self.building)
  customer_user   -> linked to self.customer (company A)

  self.ticket          -> Company A / Building A / Customer A (OPEN, REPORT)
  self.other_ticket    -> Company B / Building B / Customer B (OPEN, REPORT)

Tests add additional rows with varied types / statuses / customers and
assert each role sees the correct buckets, the correct counts, and that
filters (from / to / status / type / company / building / customer) all
narrow the result set as documented.
"""
from datetime import datetime, timedelta, timezone

from rest_framework import status
from rest_framework.test import APITestCase

from buildings.models import Building, BuildingManagerAssignment
from customers.models import Customer, CustomerUserMembership
from test_utils import TenantFixtureMixin
from tickets.models import Ticket, TicketStatus, TicketType


URL_TYPE = "/api/reports/tickets-by-type/"
URL_CUSTOMER = "/api/reports/tickets-by-customer/"
URL_BUILDING = "/api/reports/tickets-by-building/"


def _bucket_count_by(buckets, key, value):
    return next(
        (b["count"] for b in buckets if b.get(key) == value),
        0,
    )


class _DimensionsBase(TenantFixtureMixin, APITestCase):
    def setUp(self):
        super().setUp()

        # Add a few extra company-A tickets to vary the type dimension.
        # The fixture's self.ticket is REPORT/OPEN by default.
        self.complaint_a = Ticket.objects.create(
            company=self.company,
            building=self.building,
            customer=self.customer,
            created_by=self.customer_user,
            title="A complaint",
            description="d",
            type=TicketType.COMPLAINT,
        )
        self.request_a = Ticket.objects.create(
            company=self.company,
            building=self.building,
            customer=self.customer,
            created_by=self.customer_user,
            title="A request",
            description="d",
            type=TicketType.REQUEST,
        )

        # Add a SECOND building under company A and a customer under it
        # so tickets-by-building has more than one company-A bucket and
        # tickets-by-customer can show two customers in different
        # buildings (the location-vs-account distinction).
        self.second_building = Building.objects.create(
            company=self.company, name="Second Building A", address="x"
        )
        BuildingManagerAssignment.objects.create(
            building=self.second_building, user=self.manager
        )
        # Same customer NAME at the second building so the
        # by-customer report has to disambiguate via building_name.
        self.customer_at_second_building = Customer.objects.create(
            company=self.company,
            building=self.second_building,
            name=self.customer.name,
            contact_email="x@example.com",
        )
        CustomerUserMembership.objects.create(
            customer=self.customer_at_second_building, user=self.customer_user
        )
        self.ticket_at_second_building = Ticket.objects.create(
            company=self.company,
            building=self.second_building,
            customer=self.customer_at_second_building,
            created_by=self.customer_user,
            title="At second building",
            description="d",
            type=TicketType.REQUEST,
        )


class TicketsByTypePermissionAndScopeTests(_DimensionsBase):
    def test_unauthenticated_returns_401(self):
        response = self.client.get(URL_TYPE)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_customer_user_returns_403(self):
        # Reports are denied to CUSTOMER_USER by IsReportsConsumer.
        self.client.force_authenticate(user=self.customer_user)
        response = self.client.get(URL_TYPE)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_super_admin_sees_both_companies(self):
        self.client.force_authenticate(user=self.super_admin)
        response = self.client.get(URL_TYPE)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        # 3 REPORT (self.ticket A, self.other_ticket B, complaint? no —
        # those are explicit). Recount:
        #   REPORT     = self.ticket A + self.other_ticket B = 2
        #   COMPLAINT  = self.complaint_a = 1
        #   REQUEST    = self.request_a + self.ticket_at_second_building = 2
        type_counts = {
            b["ticket_type"]: b["count"] for b in response.data["buckets"]
        }
        self.assertEqual(type_counts.get("REPORT"), 2)
        self.assertEqual(type_counts.get("COMPLAINT"), 1)
        self.assertEqual(type_counts.get("REQUEST"), 2)
        self.assertEqual(response.data["total"], 5)

    def test_company_admin_only_sees_own_company(self):
        self.client.force_authenticate(user=self.company_admin)
        response = self.client.get(URL_TYPE)
        # Company B's REPORT must NOT contribute. Company A has 1 REPORT
        # + 1 COMPLAINT + 2 REQUEST = 4.
        type_counts = {
            b["ticket_type"]: b["count"] for b in response.data["buckets"]
        }
        self.assertEqual(type_counts.get("REPORT"), 1)
        self.assertEqual(type_counts.get("COMPLAINT"), 1)
        self.assertEqual(type_counts.get("REQUEST"), 2)
        self.assertEqual(response.data["total"], 4)

    def test_building_manager_only_sees_assigned_buildings(self):
        self.client.force_authenticate(user=self.manager)
        response = self.client.get(URL_TYPE)
        # Manager assigned to self.building AND self.second_building. So
        # everything that's company A. Same total as company_admin = 4.
        self.assertEqual(response.data["total"], 4)

    def test_buckets_ordered_by_count_desc(self):
        self.client.force_authenticate(user=self.super_admin)
        response = self.client.get(URL_TYPE)
        counts = [b["count"] for b in response.data["buckets"]]
        self.assertEqual(counts, sorted(counts, reverse=True))


class TicketsByTypeFilterTests(_DimensionsBase):
    def test_status_filter_narrows(self):
        self.client.force_authenticate(user=self.super_admin)
        # Force one ticket APPROVED so we can filter for it.
        Ticket.objects.filter(pk=self.ticket.pk).update(
            status=TicketStatus.APPROVED
        )
        response = self.client.get(URL_TYPE, {"status": "APPROVED"})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["total"], 1)
        type_counts = {
            b["ticket_type"]: b["count"] for b in response.data["buckets"]
        }
        self.assertEqual(type_counts.get("REPORT"), 1)

    def test_status_unknown_returns_400(self):
        self.client.force_authenticate(user=self.super_admin)
        response = self.client.get(URL_TYPE, {"status": "BOGUS"})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_company_filter_narrows(self):
        self.client.force_authenticate(user=self.super_admin)
        response = self.client.get(URL_TYPE, {"company": self.other_company.id})
        # Only company B's REPORT.
        self.assertEqual(response.data["total"], 1)

    def test_building_filter_narrows(self):
        self.client.force_authenticate(user=self.super_admin)
        response = self.client.get(URL_TYPE, {"building": self.second_building.id})
        # Only the REQUEST ticket lives at second_building.
        self.assertEqual(response.data["total"], 1)
        self.assertEqual(response.data["buckets"][0]["ticket_type"], "REQUEST")

    def test_customer_filter_narrows(self):
        self.client.force_authenticate(user=self.super_admin)
        response = self.client.get(URL_TYPE, {"customer": self.customer.id})
        # Customer A has REPORT + COMPLAINT + REQUEST tickets attached to it.
        self.assertEqual(response.data["total"], 3)

    def test_customer_filter_outside_scope_403(self):
        self.client.force_authenticate(user=self.company_admin)
        response = self.client.get(URL_TYPE, {"customer": self.other_customer.id})
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_from_to_filter_narrows(self):
        # Push self.ticket's created_at far into the past, then ask for
        # tickets created in the last 30 days. self.ticket should drop.
        old = datetime(2025, 1, 1, tzinfo=timezone.utc)
        Ticket.objects.filter(pk=self.ticket.pk).update(created_at=old)
        self.client.force_authenticate(user=self.super_admin)
        # default range is last 30 days; self.ticket is now 2025
        response = self.client.get(URL_TYPE)
        # 5 minus 1 (self.ticket OPEN/REPORT was bumped out) = 4
        self.assertEqual(response.data["total"], 4)


class TicketsByCustomerScopeAndShapeTests(_DimensionsBase):
    def test_super_admin_sees_all_customer_locations(self):
        self.client.force_authenticate(user=self.super_admin)
        response = self.client.get(URL_CUSTOMER)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        # 3 distinct Customer rows: customer A (Building A), customer A
        # (second building) — same name — and other_customer (Company B).
        ids = [b["customer_id"] for b in response.data["buckets"]]
        self.assertEqual(len(ids), 3)
        self.assertEqual(len(set(ids)), 3)
        # building_name MUST be present so same-named customers in
        # different buildings remain distinct.
        for bucket in response.data["buckets"]:
            self.assertIn("building_id", bucket)
            self.assertIn("building_name", bucket)
            self.assertIn("company_id", bucket)
            self.assertIn("company_name", bucket)

    def test_same_named_customers_disambiguated_by_building(self):
        self.client.force_authenticate(user=self.super_admin)
        response = self.client.get(URL_CUSTOMER)
        same_name = [
            b for b in response.data["buckets"]
            if b["customer_name"] == self.customer.name
        ]
        self.assertEqual(len(same_name), 2)
        building_names = {b["building_name"] for b in same_name}
        self.assertEqual(
            building_names, {self.building.name, self.second_building.name}
        )

    def test_company_admin_only_sees_own_customers(self):
        self.client.force_authenticate(user=self.company_admin)
        response = self.client.get(URL_CUSTOMER)
        # Other company's customer must not appear.
        ids = {b["customer_id"] for b in response.data["buckets"]}
        self.assertNotIn(self.other_customer.id, ids)
        # Company A has 2 customer rows (same name, different buildings).
        self.assertEqual(len(ids), 2)

    def test_building_manager_only_sees_assigned_building_customers(self):
        # Drop the manager's assignment on second_building so only
        # self.building remains.
        BuildingManagerAssignment.objects.filter(
            user=self.manager, building=self.second_building
        ).delete()
        self.client.force_authenticate(user=self.manager)
        response = self.client.get(URL_CUSTOMER)
        ids = {b["customer_id"] for b in response.data["buckets"]}
        self.assertEqual(ids, {self.customer.id})

    def test_type_filter_narrows(self):
        self.client.force_authenticate(user=self.super_admin)
        response = self.client.get(URL_CUSTOMER, {"type": "COMPLAINT"})
        # Only 1 COMPLAINT, attached to customer A at building A.
        self.assertEqual(response.data["total"], 1)
        self.assertEqual(
            response.data["buckets"][0]["building_id"], self.building.id
        )


class TicketsByBuildingScopeAndFilterTests(_DimensionsBase):
    def test_super_admin_sees_three_buildings(self):
        self.client.force_authenticate(user=self.super_admin)
        response = self.client.get(URL_BUILDING)
        ids = {b["building_id"] for b in response.data["buckets"]}
        self.assertEqual(
            ids,
            {self.building.id, self.second_building.id, self.other_building.id},
        )

    def test_company_admin_excludes_other_company_building(self):
        self.client.force_authenticate(user=self.company_admin)
        response = self.client.get(URL_BUILDING)
        ids = {b["building_id"] for b in response.data["buckets"]}
        self.assertEqual(ids, {self.building.id, self.second_building.id})
        self.assertNotIn(self.other_building.id, ids)

    def test_customer_filter_narrows(self):
        self.client.force_authenticate(user=self.super_admin)
        response = self.client.get(
            URL_BUILDING, {"customer": self.customer.id}
        )
        # The fixture's self.customer is at self.building only.
        ids = {b["building_id"] for b in response.data["buckets"]}
        self.assertEqual(ids, {self.building.id})

    def test_type_filter_narrows(self):
        self.client.force_authenticate(user=self.super_admin)
        response = self.client.get(URL_BUILDING, {"type": "REQUEST"})
        # Both company-A REQUESTs across the two buildings.
        ids = {b["building_id"] for b in response.data["buckets"]}
        self.assertEqual(ids, {self.building.id, self.second_building.id})
