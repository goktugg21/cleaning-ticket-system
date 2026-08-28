"""
FE-2 (Addendum D §D.4) — the folded requester timeline.

Pins three things: chronological ORDER over both sources, the WORDING
contract (machine event keys only — no status enums, no free text, so
the B1/B7 note-privacy floor holds by construction), and the privacy /
tenancy walls (internal steps produce no entry for anyone; a foreign
tenant's timeline is a 404).
"""
from __future__ import annotations

import datetime

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone
from rest_framework import status as http
from rest_framework.test import APIClient

from accounts.models import UserRole
from buildings.models import Building
from companies.models import Company, CompanyUserMembership
from customers.models import (
    Customer,
    CustomerBuildingMembership,
    CustomerUserBuildingAccess,
    CustomerUserMembership,
)
from extra_work.models import (
    ExtraWorkRequest,
    ExtraWorkStatus,
    ExtraWorkStatusHistory,
)
from tickets.models import (
    Ticket,
    TicketStatus,
    TicketStatusHistory,
    TicketType,
)

User = get_user_model()
PASSWORD = "StrongerTestPassword123!"

ENTRY_KEYS = {"at", "event", "actor", "source"}


class TimelineTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        suffix = "fe2tl"
        cls.company = Company.objects.create(
            name=f"Provider {suffix}", slug=f"prov-{suffix}"
        )
        cls.building = Building.objects.create(
            company=cls.company, name=f"Building {suffix}"
        )
        cls.customer = Customer.objects.create(
            company=cls.company, name=f"Customer {suffix}", building=cls.building
        )
        CustomerBuildingMembership.objects.create(
            customer=cls.customer, building=cls.building
        )
        cls.admin = User.objects.create_user(
            email=f"admin-{suffix}@example.com",
            password=PASSWORD,
            role=UserRole.COMPANY_ADMIN,
            full_name="Anna Admin",
        )
        CompanyUserMembership.objects.create(user=cls.admin, company=cls.company)
        cls.cust_user = User.objects.create_user(
            email=f"cust-{suffix}@example.com",
            password=PASSWORD,
            role=UserRole.CUSTOMER_USER,
            full_name="Kees Klant",
        )
        membership = CustomerUserMembership.objects.create(
            customer=cls.customer, user=cls.cust_user
        )
        CustomerUserBuildingAccess.objects.create(
            membership=membership, building=cls.building
        )

        cls.ew = ExtraWorkRequest.objects.create(
            company=cls.company,
            building=cls.building,
            customer=cls.customer,
            created_by=cls.cust_user,
            title=f"EW {suffix}",
            description="seed",
            status=ExtraWorkStatus.IN_PROGRESS,
        )

        base = timezone.now() - datetime.timedelta(days=10)
        # `requested_at` is auto_now_add; place the request itself at
        # the start of the story the backdated rows tell.
        ExtraWorkRequest.objects.filter(pk=cls.ew.pk).update(requested_at=base)
        cls.ew.refresh_from_db()

        def ew_row(offset_h, old, new, actor, note=""):
            row = ExtraWorkStatusHistory.objects.create(
                extra_work=cls.ew,
                old_status=old,
                new_status=new,
                changed_by=actor,
                note=note,
            )
            # auto_now_add wins on create; place the row in time.
            ExtraWorkStatusHistory.objects.filter(pk=row.pk).update(
                created_at=base + datetime.timedelta(hours=offset_h)
            )
            return row

        ew_row(1, ExtraWorkStatus.REQUESTED, ExtraWorkStatus.UNDER_REVIEW, cls.admin)
        ew_row(
            2,
            ExtraWorkStatus.UNDER_REVIEW,
            ExtraWorkStatus.PRICING_PROPOSED,
            cls.admin,
            note="Internal: margin is tight.",
        )
        ew_row(
            3,
            ExtraWorkStatus.PRICING_PROPOSED,
            ExtraWorkStatus.CUSTOMER_APPROVED,
            cls.cust_user,
        )

        cls.ticket = Ticket.objects.create(
            company=cls.company,
            customer=cls.customer,
            building=cls.building,
            title="Spawned",
            description="x",
            type=TicketType.REQUEST,
            status=TicketStatus.WAITING_CUSTOMER_APPROVAL,
            created_by=cls.admin,
            extra_work_request=cls.ew,
        )

        def ticket_row(offset_h, old, new, actor):
            row = TicketStatusHistory.objects.create(
                ticket=cls.ticket,
                old_status=old,
                new_status=new,
                changed_by=actor,
            )
            TicketStatusHistory.objects.filter(pk=row.pk).update(
                created_at=base + datetime.timedelta(hours=offset_h)
            )
            return row

        ticket_row(4, "", TicketStatus.OPEN, cls.admin)
        ticket_row(5, TicketStatus.OPEN, TicketStatus.IN_PROGRESS, cls.admin)
        # The internal double-check — must produce NO timeline entry.
        ticket_row(
            6,
            TicketStatus.IN_PROGRESS,
            TicketStatus.WAITING_MANAGER_REVIEW,
            cls.admin,
        )
        ticket_row(
            7,
            TicketStatus.WAITING_MANAGER_REVIEW,
            TicketStatus.WAITING_CUSTOMER_APPROVAL,
            cls.admin,
        )

    def _timeline(self, user):
        client = APIClient()
        client.force_authenticate(user)
        return client.get(f"/api/extra-work/{self.ew.id}/timeline/")

    def test_one_story_in_order_with_phase_words_only(self):
        response = self._timeline(self.cust_user)
        self.assertEqual(response.status_code, http.HTTP_200_OK, response.data)
        events = [entry["event"] for entry in response.data["entries"]]
        self.assertEqual(
            events,
            [
                "requested",
                "price_in_preparation",
                "quote_sent",
                "approved",
                "work_created",
                "completion_submitted",
            ],
        )
        stamps = [entry["at"] for entry in response.data["entries"]]
        self.assertEqual(stamps, sorted(stamps))
        self.assertEqual(response.data["count"], len(events))

    def test_no_internal_step_and_no_free_text_reaches_any_viewer(self):
        """The manager-review step is absent, the ticket's IN_PROGRESS
        mirror is absent, and no entry carries note text — the entry
        shape IS the privacy contract."""
        for viewer in (self.cust_user, self.admin):
            response = self._timeline(viewer)
            for entry in response.data["entries"]:
                with self.subTest(viewer=viewer.email, entry=entry["event"]):
                    self.assertEqual(set(entry), ENTRY_KEYS)
                    self.assertNotIn("Internal", str(entry.values()))
            events = [entry["event"] for entry in response.data["entries"]]
            self.assertNotIn("WAITING_MANAGER_REVIEW", events)

    def test_the_actor_is_a_display_name(self):
        response = self._timeline(self.cust_user)
        by_event = {e["event"]: e for e in response.data["entries"]}
        self.assertEqual(by_event["requested"]["actor"], "Kees Klant")
        self.assertEqual(by_event["quote_sent"]["actor"], "Anna Admin")
        self.assertEqual(by_event["work_created"]["source"], "TICKET")
        self.assertEqual(by_event["quote_sent"]["source"], "MEERWERK")

    def test_a_foreign_tenant_gets_a_404(self):
        other_company = Company.objects.create(name="Other", slug="other-fe2tl")
        outsider = User.objects.create_user(
            email="outsider-fe2tl@example.com",
            password=PASSWORD,
            role=UserRole.COMPANY_ADMIN,
        )
        CompanyUserMembership.objects.create(
            user=outsider, company=other_company
        )
        response = self._timeline(outsider)
        self.assertEqual(response.status_code, http.HTTP_404_NOT_FOUND)
