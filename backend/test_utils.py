from django.contrib.auth import get_user_model

from accounts.models import UserRole
from buildings.models import Building, BuildingManagerAssignment
from companies.models import Company, CompanyUserMembership
from customers.models import Customer, CustomerUserMembership
from tickets.models import Ticket, TicketStatus


class TenantFixtureMixin:
    password = "StrongerTestPassword123!"

    def make_user(self, email, role, **extra):
        defaults = {
            "role": role,
            "full_name": email.split("@")[0],
        }
        defaults.update(extra)
        return get_user_model().objects.create_user(
            email=email,
            password=self.password,
            **defaults,
        )

    def setUp(self):
        self.super_admin = self.make_user(
            "super@example.com",
            UserRole.SUPER_ADMIN,
            is_staff=True,
            is_superuser=True,
        )
        self.company_admin = self.make_user("admin-a@example.com", UserRole.COMPANY_ADMIN)
        self.other_company_admin = self.make_user("admin-b@example.com", UserRole.COMPANY_ADMIN)
        self.manager = self.make_user("manager-a@example.com", UserRole.BUILDING_MANAGER)
        self.other_manager = self.make_user("manager-b@example.com", UserRole.BUILDING_MANAGER)
        self.customer_user = self.make_user("customer-a@example.com", UserRole.CUSTOMER_USER)
        self.other_customer_user = self.make_user("customer-b@example.com", UserRole.CUSTOMER_USER)

        self.company = Company.objects.create(name="Company A", slug="company-a")
        self.other_company = Company.objects.create(name="Company B", slug="company-b")

        self.building = Building.objects.create(
            company=self.company,
            name="Building A",
            address="Main Street 1",
        )
        self.other_building = Building.objects.create(
            company=self.other_company,
            name="Building B",
            address="Other Street 1",
        )

        self.customer = Customer.objects.create(
            company=self.company,
            building=self.building,
            name="Customer A",
            contact_email="customer-a@example.com",
        )
        self.other_customer = Customer.objects.create(
            company=self.other_company,
            building=self.other_building,
            name="Customer B",
            contact_email="customer-b@example.com",
        )

        CompanyUserMembership.objects.create(user=self.company_admin, company=self.company)
        CompanyUserMembership.objects.create(user=self.other_company_admin, company=self.other_company)
        BuildingManagerAssignment.objects.create(user=self.manager, building=self.building)
        BuildingManagerAssignment.objects.create(user=self.other_manager, building=self.other_building)
        CustomerUserMembership.objects.create(user=self.customer_user, customer=self.customer)
        CustomerUserMembership.objects.create(user=self.other_customer_user, customer=self.other_customer)

        self.ticket = Ticket.objects.create(
            company=self.company,
            building=self.building,
            customer=self.customer,
            created_by=self.customer_user,
            title="Ticket A",
            description="Scoped ticket A",
        )
        self.other_ticket = Ticket.objects.create(
            company=self.other_company,
            building=self.other_building,
            customer=self.other_customer,
            created_by=self.other_customer_user,
            title="Ticket B",
            description="Scoped ticket B",
        )

    def authenticate(self, user):
        self.client.force_authenticate(user=user)

    def response_ids(self, response):
        data = response.data.get("results", response.data)
        return {item["id"] for item in data}

    def create_ticket_payload(self, **overrides):
        payload = {
            "title": "Created by API",
            "description": "Created by API description",
            "type": "REPORT",
            "priority": "NORMAL",
            "building": self.building.id,
            "customer": self.customer.id,
        }
        payload.update(overrides)
        return payload

    def move_ticket_to_customer_approval(self, ticket=None):
        ticket = ticket or self.ticket
        ticket.status = TicketStatus.WAITING_CUSTOMER_APPROVAL
        ticket.save(update_fields=["status", "updated_at"])
        return ticket
