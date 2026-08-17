"""
Sprint 160 — the two-company fixture every contracts test builds on.

Deliberately its own fixture rather than `test_utils.TenantFixtureMixin`
or the timesheets one, for the reason the timesheets fixture gives about
itself: importing another module's fixture makes this module's tests
fail whenever that module's data changes, which is exactly the coupling
the app is designed not to have.

Shape: two provider companies, each genuinely POPULATED — a
COMPANY_ADMIN, a BUILDING_MANAGER, two buildings, a customer, a
contract type and a contract. A cross-tenant assertion that passes
because the other side is empty proves nothing, so company B is built
out as fully as company A.
"""
from __future__ import annotations

from datetime import date
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

from contracts.models import (
    BillingPeriod,
    BillingType,
    Contract,
    ContractBuilding,
    ContractLifecycle,
    ContractLine,
    ContractRevision,
    ContractType,
)


User = get_user_model()
PASSWORD = "StrongerTestPassword160!"

CONTRACTS_URL = "/api/contracts/"
STATS_URL = "/api/contracts/stats/"
OPTIONS_URL = "/api/contracts/options/"
TYPES_URL = "/api/contracts/types/"


def contract_detail_url(contract_id):
    return f"/api/contracts/{contract_id}/"


def contract_revisions_url(contract_id):
    return f"/api/contracts/{contract_id}/revisions/"


def contract_forecast_url(contract_id):
    return f"/api/contracts/{contract_id}/forecast/"


def revision_detail_url(revision_id):
    return f"/api/contracts/revisions/{revision_id}/"


def revision_lines_url(revision_id):
    return f"/api/contracts/revisions/{revision_id}/lines/"


def line_detail_url(line_id):
    return f"/api/contracts/lines/{line_id}/"


def type_detail_url(type_id):
    return f"/api/contracts/types/{type_id}/"


def mk_user(email, role, **extra):
    return User.objects.create_user(
        email=email,
        password=PASSWORD,
        role=role,
        full_name=email.split("@")[0],
        **extra,
    )


class ContractsFixture(TestCase):
    """Two isolated provider companies, both populated."""

    @classmethod
    def setUpTestData(cls):
        cls.company_a = Company.objects.create(name="Prov A", slug="prov-a-160")
        cls.company_b = Company.objects.create(name="Prov B", slug="prov-b-160")

        cls.sa = mk_user("sa-160@example.com", "SUPER_ADMIN", is_staff=True)
        cls.ca_a = mk_user("ca-a-160@example.com", "COMPANY_ADMIN")
        cls.ca_b = mk_user("ca-b-160@example.com", "COMPANY_ADMIN")
        cls.bm_a = mk_user("bm-a-160@example.com", "BUILDING_MANAGER")
        cls.bm_a2 = mk_user("bm-a2-160@example.com", "BUILDING_MANAGER")
        cls.bm_b = mk_user("bm-b-160@example.com", "BUILDING_MANAGER")
        cls.staff_a = mk_user("staff-a-160@example.com", "STAFF")
        cls.customer_user = mk_user("cu-160@example.com", "CUSTOMER_USER")

        CompanyUserMembership.objects.create(user=cls.ca_a, company=cls.company_a)
        CompanyUserMembership.objects.create(user=cls.ca_b, company=cls.company_b)

        cls.building_a = Building.objects.create(
            company=cls.company_a, name="Building A", address="A street 1"
        )
        # A SECOND building in company A that bm_a does NOT manage — the
        # BUILDING_MANAGER narrowing is only meaningful if there is
        # something inside their own company they still cannot see.
        cls.building_a2 = Building.objects.create(
            company=cls.company_a, name="Building A2", address="A street 2"
        )
        cls.building_b = Building.objects.create(
            company=cls.company_b, name="Building B", address="B street 1"
        )
        BuildingManagerAssignment.objects.create(
            user=cls.bm_a, building=cls.building_a
        )
        BuildingManagerAssignment.objects.create(
            user=cls.bm_a2, building=cls.building_a2
        )
        BuildingManagerAssignment.objects.create(
            user=cls.bm_b, building=cls.building_b
        )
        BuildingStaffVisibility.objects.create(
            user=cls.staff_a, building=cls.building_a
        )

        cls.customer_a = Customer.objects.create(
            company=cls.company_a, name="Customer A"
        )
        cls.customer_b = Customer.objects.create(
            company=cls.company_b, name="Customer B"
        )
        CustomerUserMembership.objects.create(
            user=cls.customer_user, customer=cls.customer_a
        )

        cls.type_a = ContractType.objects.create(
            company=cls.company_a, name="Schoonmaak", sort_order=10
        )
        cls.type_b = ContractType.objects.create(
            company=cls.company_b, name="Machines", sort_order=10
        )

        cls.contract_a = make_contract(
            company=cls.company_a,
            customer=cls.customer_a,
            contract_type=cls.type_a,
            contract_no="CNT-2026-0001",
            buildings=[cls.building_a],
            lines=[("Dagelijkse schoonmaak", "1000.00", "40.00")],
        )
        cls.contract_a2 = make_contract(
            company=cls.company_a,
            customer=cls.customer_a,
            contract_type=cls.type_a,
            contract_no="CNT-2026-0002",
            buildings=[cls.building_a2],
            lines=[("Glasbewassing", "500.00", "10.00")],
        )
        cls.contract_b = make_contract(
            company=cls.company_b,
            customer=cls.customer_b,
            contract_type=cls.type_b,
            contract_no="CNT-2026-0001",
            buildings=[cls.building_b],
            lines=[("Machineonderhoud", "2000.00", "20.00")],
        )

    def api(self, user):
        client = APIClient()
        client.force_authenticate(user=user)
        return client


def make_contract(
    *,
    company,
    customer,
    contract_no,
    contract_type=None,
    buildings=(),
    lines=(),
    start_date=date(2026, 1, 1),
    end_date=None,
    lifecycle=ContractLifecycle.ACTIVE,
    billing_period=BillingPeriod.MONTHLY,
    billing_day=1,
    billing_type=BillingType.ADVANCE,
    start_proration=True,
    revision_effective_from=None,
    payment_terms_days=30,
):
    """Create a contract with its first revision and lines, through the
    ORM.

    Used to set up state for tests whose subject is something OTHER than
    the create endpoint. It mirrors what `serializers.create_contract`
    does — contract, building links, one revision — deliberately by hand
    rather than by calling it, so a bug in the create path shows up as a
    failing create test rather than silently shaping every fixture.
    """
    contract = Contract.objects.create(
        company=company,
        customer=customer,
        contract_type=contract_type,
        contract_no=contract_no,
        start_date=start_date,
        end_date=end_date,
        lifecycle=lifecycle,
        billing_period=billing_period,
        billing_day=billing_day,
        billing_type=billing_type,
        start_proration=start_proration,
        payment_terms_days=payment_terms_days,
    )
    for building in buildings:
        ContractBuilding.objects.create(contract=contract, building=building)
    revision = ContractRevision.objects.create(
        contract=contract,
        label="Oorspronkelijk contract",
        effective_from=revision_effective_from or start_date,
    )
    for index, spec in enumerate(lines):
        name, amount, hours = spec
        ContractLine.objects.create(
            revision=revision,
            name=name,
            amount=Decimal(amount),
            hours=Decimal(hours),
            sort_order=(index + 1) * 10,
        )
    return contract
