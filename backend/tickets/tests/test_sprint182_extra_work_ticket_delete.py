"""Sprint 182 §4 — an extra-work-born ticket cannot be soft-deleted.

The audit's C4: `destroy()` had no extra-work guard, and deleting the
ticket did two silent things at once. `billing.is_earned` reads the
ticket, so the extra work dropped out of the unbilled pool with nothing
on any screen saying the money had stopped being owed; and the
spawn-idempotency guards query `Ticket.objects.filter(extra_work_request=…)`
WITHOUT `deleted_at__isnull=True`, so the deleted row went on occupying
the slot and no replacement could ever be spawned.

The decision was to REFUSE the delete rather than free the slot — see the
comment in `tickets/views.py` for why. These tests pin both halves: the
refusal, and that an ordinary ticket is unaffected.
"""
from __future__ import annotations

from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from accounts.models import UserRole
from buildings.models import Building
from companies.models import Company, CompanyUserMembership
from customers.models import Customer, CustomerBuildingMembership
from extra_work.models import ExtraWorkRequest, ExtraWorkStatus
from tickets.models import Ticket, TicketStatus


User = get_user_model()
PASSWORD = "StrongerTestPassword182!"


class ExtraWorkTicketDeleteGuardTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.company = Company.objects.create(name="Prov", slug="prov-182")
        cls.building = Building.objects.create(
            company=cls.company, name="B", address="B 1"
        )
        cls.customer = Customer.objects.create(
            company=cls.company, name="Cust 182", building=cls.building
        )
        CustomerBuildingMembership.objects.create(
            customer=cls.customer, building=cls.building
        )
        cls.super_admin = User.objects.create_user(
            email="sa-182@example.com",
            password=PASSWORD,
            role=UserRole.SUPER_ADMIN,
            full_name="SA",
            is_staff=True,
            is_superuser=True,
        )
        cls.admin = User.objects.create_user(
            email="ca-182@example.com",
            password=PASSWORD,
            role=UserRole.COMPANY_ADMIN,
            full_name="CA",
        )
        CompanyUserMembership.objects.create(
            user=cls.admin, company=cls.company
        )

    def api(self, user):
        client = APIClient()
        client.force_authenticate(user=user)
        return client

    def _ticket(self, **extra):
        return Ticket.objects.create(
            company=self.company,
            building=self.building,
            customer=self.customer,
            created_by=self.admin,
            title=extra.pop("title", "A ticket"),
            description="d",
            status=TicketStatus.OPEN,
            **extra,
        )

    def _extra_work(self):
        return ExtraWorkRequest.objects.create(
            company=self.company,
            building=self.building,
            customer=self.customer,
            created_by=self.admin,
            title="Chargeable work",
            description="d",
            status=ExtraWorkStatus.CUSTOMER_APPROVED,
            subtotal_amount=Decimal("100.00"),
            vat_amount=Decimal("21.00"),
            total_amount=Decimal("121.00"),
        )

    def test_an_extra_work_ticket_cannot_be_deleted(self):
        ew = self._extra_work()
        ticket = self._ticket(extra_work_request=ew, title="Born from an EW")

        resp = self.api(self.super_admin).delete(f"/api/tickets/{ticket.id}/")
        self.assertEqual(resp.status_code, 400, resp.data)
        self.assertEqual(resp.data["code"], "extra_work_ticket_not_deletable")
        self.assertEqual(resp.data["extra_work_request_id"], ew.id)

        ticket.refresh_from_db()
        self.assertIsNone(
            ticket.deleted_at, "the money must still be attached to a ticket"
        )

    def test_even_a_super_admin_cannot(self):
        """Not a permissions answer — the ticket is a financial record,
        and no role changes that."""
        ew = self._extra_work()
        ticket = self._ticket(extra_work_request=ew)
        for actor in (self.super_admin, self.admin):
            resp = self.api(actor).delete(f"/api/tickets/{ticket.id}/")
            self.assertEqual(resp.status_code, 400, resp.data)
            self.assertEqual(
                resp.data["code"], "extra_work_ticket_not_deletable"
            )

    def test_an_ordinary_ticket_is_still_deletable(self):
        """The guard is narrow: Sprint 12's soft-delete of an
        accidentally-opened melding is untouched."""
        ticket = self._ticket(title="An ordinary melding")
        resp = self.api(self.super_admin).delete(f"/api/tickets/{ticket.id}/")
        self.assertEqual(resp.status_code, 204)
        ticket.refresh_from_db()
        self.assertIsNotNone(ticket.deleted_at)

    def test_the_error_names_the_action_that_does_work(self):
        """An operator told only "no" invents a workaround; the message
        points at cancelling the extra work, which is audited and
        reason-required."""
        ew = self._extra_work()
        ticket = self._ticket(extra_work_request=ew)
        resp = self.api(self.super_admin).delete(f"/api/tickets/{ticket.id}/")
        self.assertIn("Cancel the extra work", resp.data["detail"])
