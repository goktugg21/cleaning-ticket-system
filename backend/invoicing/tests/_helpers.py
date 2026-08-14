"""Shared fixtures for the invoicing tests.

Not a test module (name does not match `test*.py`, so the runner does not
auto-collect it). Imported explicitly by the test files.

Sprint 180 §3 — MEDIA_ROOT ISOLATION. Sending an invoice now WRITES A FILE:
`send_invoice` freezes the PDF onto `Invoice.pdf_file`. A `TestCase` rolls
its database rows back, but nothing rolls a file back, so without isolation
every send in the suite would deposit a real PDF into the developer's
`backend/media/` and leave it there. `MediaRootIsolation` gives each test
CLASS its own temporary MEDIA_ROOT and deletes it afterwards, which also
means one test can never read a file another test wrote.
"""
from __future__ import annotations

import shutil
import tempfile
from datetime import datetime
from datetime import timezone as dt_timezone
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.utils import timezone

from accounts.models import UserRole
from buildings.models import Building
from companies.models import Company, CompanyUserMembership
from customers.models import (
    Customer,
    CustomerBuildingMembership,
    Department,
    WorkType,
)
from extra_work.models import ExtraWorkRequest, ExtraWorkStatus
from invoicing.models import Invoice, InvoiceLine
from tickets.models import Ticket, TicketStatus

User = get_user_model()
PASSWORD = "StrongerTestPassword123!"


def dt(year: int, month: int, day: int) -> datetime:
    # Noon UTC so .date() never rolls into an adjacent day under any TZ.
    return datetime(year, month, day, 12, 0, tzinfo=dt_timezone.utc)


# Sprint 120 — make_ew's `closed_at` needs to tell "caller omitted it" apart
# from "caller explicitly passed None" (the latter is a real, deliberately
# used case: an earned-but-unresolvable-billing-month fixture). None can't
# do that itself, since it IS the value some callers explicitly want.
_UNSET = object()


class MediaRootIsolation:
    """Point MEDIA_ROOT at a throwaway directory for the whole test class.

    Mix in FIRST, before the `TestCase` base, so its `setUpClass` runs the
    override BEFORE `setUpTestData` builds any fixture that might write a
    file.

    `setUpClass`/`tearDownClass` rather than `setUp`/`tearDown`: Django
    builds `setUpTestData` fixtures once per class, and an override that
    only existed per-test would not cover them.

    **Do not combine with a class-level `@override_settings(MEDIA_ROOT=...)`.**
    Django enables a class's own `_overridden_settings` inside
    `SimpleTestCase.setUpClass`, which this mixin calls through `super()` —
    so the decorator is enabled LAST and wins. Measured, not assumed. If a
    test genuinely needs its own MEDIA_ROOT it should not mix this in at all,
    rather than mix it in and be quietly overruled.
    """

    @classmethod
    def setUpClass(cls):
        cls._media_dir = tempfile.mkdtemp(prefix="invoicing-media-")
        cls._media_override = override_settings(MEDIA_ROOT=cls._media_dir)
        cls._media_override.enable()
        try:
            super().setUpClass()
        except Exception:
            # A failure in the rest of setUpClass must not leave the
            # override enabled for whatever class runs next — that would
            # point a LATER test's files at a directory this one is about
            # to delete.
            cls._media_override.disable()
            shutil.rmtree(cls._media_dir, ignore_errors=True)
            raise

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        cls._media_override.disable()
        shutil.rmtree(cls._media_dir, ignore_errors=True)


class InvoicingFixture(MediaRootIsolation, TestCase):
    """Two tenants (A + B). Company A has two buildings under one customer
    so per-building vs per-customer generation can be exercised.

    Carries `MediaRootIsolation` because sending an invoice writes its
    frozen PDF (Sprint 180 §1) — see the module docstring.
    """

    @classmethod
    def setUpTestData(cls):
        # --- Company A: two buildings, one customer ---
        cls.company = Company.objects.create(name="Prov A", slug="prov-a-inv2a")
        cls.building = Building.objects.create(company=cls.company, name="A-B1")
        cls.building2 = Building.objects.create(company=cls.company, name="A-B2")
        cls.customer = Customer.objects.create(
            company=cls.company, name="Cust A", building=cls.building
        )
        CustomerBuildingMembership.objects.create(
            customer=cls.customer, building=cls.building
        )
        CustomerBuildingMembership.objects.create(
            customer=cls.customer, building=cls.building2
        )
        # Sprint 132 — Department/WorkType labels for the
        # PER_BUILDING_DEPARTMENT_WORK_TYPE granularity tests.
        cls.dept_a = Department.objects.create(customer=cls.customer, name="Dept A")
        cls.dept_b = Department.objects.create(customer=cls.customer, name="Dept B")
        cls.wt_a = WorkType.objects.create(customer=cls.customer, name="WT A")
        cls.wt_b = WorkType.objects.create(customer=cls.customer, name="WT B")
        cls.admin = User.objects.create_user(
            email="admin-inv2a@example.com",
            password=PASSWORD,
            role=UserRole.COMPANY_ADMIN,
            full_name="Admin A",
        )
        CompanyUserMembership.objects.create(user=cls.admin, company=cls.company)
        cls.customer_user = User.objects.create_user(
            email="cust-inv2a@example.com",
            password=PASSWORD,
            role=UserRole.CUSTOMER_USER,
            full_name="Cust User",
        )

        # --- Company B (separate tenant) ---
        cls.company_b = Company.objects.create(name="Prov B", slug="prov-b-inv2a")
        cls.building_b = Building.objects.create(
            company=cls.company_b, name="B-B1"
        )
        cls.customer_b = Customer.objects.create(
            company=cls.company_b, name="Cust B", building=cls.building_b
        )
        CustomerBuildingMembership.objects.create(
            customer=cls.customer_b, building=cls.building_b
        )
        cls.admin_b = User.objects.create_user(
            email="admin-b-inv2a@example.com",
            password=PASSWORD,
            role=UserRole.COMPANY_ADMIN,
            full_name="Admin B",
        )
        CompanyUserMembership.objects.create(
            user=cls.admin_b, company=cls.company_b
        )

    def make_ew(
        self,
        *,
        ticket_status=TicketStatus.CLOSED,
        closed_at=_UNSET,
        company=None,
        building=None,
        customer=None,
        created_by=None,
        is_invoiced=False,
        subtotal=Decimal("100.00"),
        vat=Decimal("21.00"),
        total=Decimal("121.00"),
        final_subtotal=None,
        final_vat=None,
        final_total=None,
        invoice_date=None,
        department=None,
        work_type=None,
    ):
        """Create an EW + its spawned operational Ticket.

        When `closed_at` is omitted, it defaults to a real earned timestamp
        (2026-05-31) IF `ticket_status` is CLOSED — matching is_earned()'s
        only check (ticket.status), so a bare make_ew() is earned in May
        2026 as documented — and to None otherwise, since a non-CLOSED
        ticket has no closed_at in practice.

        Sprint 120 — the OLD default was a bare `closed_at=None` regardless
        of `ticket_status`, so a bare `make_ew()` silently built a CLOSED
        ticket with NO closed_at: earned (is_earned only checks status) but
        with an unresolvable billing_month(), which crashes any ordering
        comparison against it (`unbilled_extra_work_through`'s `<=`). Pass
        `closed_at=None` EXPLICITLY (with `ticket_status=TicketStatus.
        CLOSED`, the default) to still build that exact edge case on
        purpose — see test_due_unresolvable_billing_month_excluded_not_500.
        """
        if closed_at is _UNSET:
            closed_at = dt(2026, 5, 31) if ticket_status == TicketStatus.CLOSED else None
        company = company or self.company
        building = building or self.building
        customer = customer or self.customer
        created_by = created_by or self.admin
        ew = ExtraWorkRequest.objects.create(
            company=company,
            building=building,
            customer=customer,
            created_by=created_by,
            title="Work performed",
            description="desc",
            status=ExtraWorkStatus.CUSTOMER_APPROVED,
            subtotal_amount=subtotal,
            vat_amount=vat,
            total_amount=total,
            final_subtotal_amount=final_subtotal,
            final_vat_amount=final_vat,
            final_total_amount=final_total,
            invoice_date=invoice_date,
            is_invoiced=is_invoiced,
            department=department,
            work_type=work_type,
        )
        Ticket.objects.create(
            company=company,
            building=building,
            customer=customer,
            created_by=created_by,
            title="Spawned operational ticket",
            description="op",
            status=ticket_status,
            closed_at=closed_at,
            extra_work_request=ew,
        )
        return ew

    def claim_with_invoice(self, ew, *, deleted=False):
        """Create an Invoice + InvoiceLine claiming `ew`. When `deleted`, the
        invoice is soft-deleted (the release path leaves the line but the
        invoice soft-deleted)."""
        inv = Invoice.objects.create(
            company=ew.company,
            customer=ew.customer,
            building=None,
            status=Invoice.Status.DRAFT,
            created_by=self.admin,
            deleted_at=(timezone.now() if deleted else None),
        )
        InvoiceLine.objects.create(
            invoice=inv, ordering=0, description=ew.title, extra_work=ew
        )
        return inv
