"""
Sprint 152 — the two-company fixture every timesheets test builds on.

Deliberately its own fixture rather than `test_utils.TenantFixtureMixin`:
that mixin builds tickets, customers and customer-user access rows, none
of which this module has any relationship to. Importing it would make
the timesheets tests fail whenever the TICKET fixture changes, which is
exactly the coupling the module is designed not to have.

Shape: two provider companies, each with a COMPANY_ADMIN, a
BUILDING_MANAGER, a STAFF member, a building and an hour type — plus a
SUPER_ADMIN and one CUSTOMER_USER for the 403 matrix.
"""
from __future__ import annotations

from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from buildings.models import (
    Building,
    BuildingManagerAssignment,
    BuildingStaffVisibility,
)
from companies.models import Company, CompanyUserMembership
from customers.models import Customer, CustomerUserMembership

from timesheets.models import HourType, TimeEntry


User = get_user_model()
PASSWORD = "StrongerTestPassword152!"

HOUR_TYPES_URL = "/api/timesheets/hour-types/"
STANDARD_SET_URL = "/api/timesheets/hour-types/standard-set/"
EMPLOYEES_URL = "/api/timesheets/employees/"
ENTRIES_URL = "/api/timesheets/entries/"
WEEKS_URL = "/api/timesheets/weeks/"
WEEK_STATUS_URL = "/api/timesheets/weeks/status/"
WEEK_CLOSE_URL = "/api/timesheets/weeks/close/"
WEEK_REOPEN_URL = "/api/timesheets/weeks/reopen/"
SUMMARY_URL = "/api/timesheets/summary/"
SUMMARY_CSV_URL = "/api/timesheets/summary/export.csv"


def hour_type_detail_url(hour_type_id):
    return f"/api/timesheets/hour-types/{hour_type_id}/"


def entry_detail_url(entry_id):
    return f"/api/timesheets/entries/{entry_id}/"


def mk_user(email, role, **extra):
    return User.objects.create_user(
        email=email,
        password=PASSWORD,
        role=role,
        full_name=email.split("@")[0],
        **extra,
    )


class TimesheetsFixture(TestCase):
    """Two isolated provider companies with a full provider workforce
    each. Every cross-tenant assertion in this package is written
    against company B being genuinely populated — an isolation test that
    passes because the other side is empty proves nothing.
    """

    @classmethod
    def setUpTestData(cls):
        cls.company_a = Company.objects.create(name="Prov A", slug="prov-a-152")
        cls.company_b = Company.objects.create(name="Prov B", slug="prov-b-152")

        cls.sa = mk_user("sa-152@example.com", "SUPER_ADMIN", is_staff=True)
        cls.ca_a = mk_user("ca-a-152@example.com", "COMPANY_ADMIN")
        cls.ca_b = mk_user("ca-b-152@example.com", "COMPANY_ADMIN")
        cls.bm_a = mk_user("bm-a-152@example.com", "BUILDING_MANAGER")
        cls.bm_b = mk_user("bm-b-152@example.com", "BUILDING_MANAGER")
        cls.staff_a = mk_user("staff-a-152@example.com", "STAFF")
        cls.staff_a2 = mk_user("staff-a2-152@example.com", "STAFF")
        cls.staff_b = mk_user("staff-b-152@example.com", "STAFF")
        cls.customer_user = mk_user("cu-152@example.com", "CUSTOMER_USER")

        CompanyUserMembership.objects.create(user=cls.ca_a, company=cls.company_a)
        CompanyUserMembership.objects.create(user=cls.ca_b, company=cls.company_b)

        cls.building_a = Building.objects.create(
            company=cls.company_a, name="Building A", address="A street 1"
        )
        cls.building_b = Building.objects.create(
            company=cls.company_b, name="Building B", address="B street 1"
        )
        BuildingManagerAssignment.objects.create(
            user=cls.bm_a, building=cls.building_a
        )
        BuildingManagerAssignment.objects.create(
            user=cls.bm_b, building=cls.building_b
        )
        BuildingStaffVisibility.objects.create(
            user=cls.staff_a, building=cls.building_a
        )
        BuildingStaffVisibility.objects.create(
            user=cls.staff_a2, building=cls.building_a
        )
        BuildingStaffVisibility.objects.create(
            user=cls.staff_b, building=cls.building_b
        )

        # A customer-side user needs a real customer to be a realistic
        # 403 subject rather than a role string with no data behind it.
        cls.customer_a = Customer.objects.create(
            company=cls.company_a, name="Customer A"
        )
        CustomerUserMembership.objects.create(
            user=cls.customer_user, customer=cls.customer_a
        )

        cls.normal_a = HourType.objects.create(
            company=cls.company_a,
            name="Normale uren",
            multiplier=Decimal("1.00"),
            sort_order=10,
        )
        cls.overtime_a = HourType.objects.create(
            company=cls.company_a,
            name="Overwerk",
            multiplier=Decimal("1.50"),
            sort_order=20,
        )
        cls.normal_b = HourType.objects.create(
            company=cls.company_b,
            name="Normale uren",
            multiplier=Decimal("1.00"),
            sort_order=10,
        )

    def api(self, user):
        client = APIClient()
        client.force_authenticate(user=user)
        return client

    def make_entry(self, employee, date, hour_type, hours="8.00", **extra):
        """Create an entry directly through the ORM, snapshotting the
        multiplier the way the view layer does. Used to set up state for
        tests whose subject is something OTHER than the create endpoint.
        """
        return TimeEntry.objects.create(
            company=extra.pop("company", None) or hour_type.company,
            employee=employee,
            date=date,
            hour_type=hour_type,
            hours=Decimal(hours),
            multiplier_snapshot=hour_type.multiplier,
            created_by=extra.pop("created_by", None) or employee,
            **extra,
        )
