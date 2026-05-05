from rest_framework import status
from rest_framework.test import APITestCase

from buildings.models import Building, BuildingManagerAssignment
from customers.models import Customer
from test_utils import TenantFixtureMixin
from tickets.models import Ticket, TicketPriority, TicketStatus


class TicketStatsByBuildingTests(TenantFixtureMixin, APITestCase):
    URL = "/api/tickets/stats/by-building/"

    def test_super_admin_sees_all_buildings(self):
        self.authenticate(self.super_admin)
        response = self.client.get(self.URL)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        building_ids = {row["building_id"] for row in response.data}
        self.assertEqual(building_ids, {self.building.id, self.other_building.id})

    def test_company_admin_only_sees_own_company_buildings(self):
        self.authenticate(self.company_admin)
        response = self.client.get(self.URL)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        building_ids = {row["building_id"] for row in response.data}
        self.assertEqual(building_ids, {self.building.id})

    def test_building_manager_only_sees_assigned_buildings(self):
        # Add a second building in the same company; the manager is NOT assigned to it.
        other_building_same_company = Building.objects.create(
            company=self.company,
            name="Building A2",
            address="Other side of campus",
        )
        Customer.objects.create(
            company=self.company,
            building=other_building_same_company,
            name="Customer A2",
        )
        Ticket.objects.create(
            company=self.company,
            building=other_building_same_company,
            customer=Customer.objects.filter(building=other_building_same_company).first(),
            created_by=self.customer_user,
            title="Out of manager scope",
            description="manager is not assigned to this building",
        )

        self.authenticate(self.manager)
        response = self.client.get(self.URL)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        building_ids = {row["building_id"] for row in response.data}
        self.assertEqual(building_ids, {self.building.id})

    def test_customer_user_only_sees_their_customer_buildings(self):
        self.authenticate(self.customer_user)
        response = self.client.get(self.URL)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        building_ids = {row["building_id"] for row in response.data}
        self.assertEqual(building_ids, {self.building.id})

    def test_urgent_excludes_closed_tickets_per_building(self):
        Ticket.objects.create(
            company=self.company,
            building=self.building,
            customer=self.customer,
            created_by=self.customer_user,
            title="Urgent open",
            description="hot",
            priority=TicketPriority.URGENT,
            status=TicketStatus.OPEN,
        )
        Ticket.objects.create(
            company=self.company,
            building=self.building,
            customer=self.customer,
            created_by=self.customer_user,
            title="Urgent closed",
            description="historical",
            priority=TicketPriority.URGENT,
            status=TicketStatus.CLOSED,
        )

        self.authenticate(self.company_admin)
        response = self.client.get(self.URL)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        rows = {row["building_id"]: row for row in response.data}
        self.assertEqual(rows[self.building.id]["urgent"], 1)

    def test_empty_response_when_user_has_no_buildings_in_scope(self):
        # Build a brand-new building manager with zero assignments.
        from django.contrib.auth import get_user_model

        from accounts.models import UserRole

        unassigned_manager = get_user_model().objects.create_user(
            email="lone-manager@example.com",
            password=self.password,
            role=UserRole.BUILDING_MANAGER,
        )
        # No BuildingManagerAssignment created intentionally.
        self.assertFalse(
            BuildingManagerAssignment.objects.filter(user=unassigned_manager).exists()
        )

        self.authenticate(unassigned_manager)
        response = self.client.get(self.URL)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(list(response.data), [])
