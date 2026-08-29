"""
FE-3 (Addendum D §D.4 / §D.11) — `kind` and the due facts on the ticket
detail.

The pure functions first (the rule as a table), then the rendered detail
response, so a screen reading `kind` / `due_date` / `due_kind` /
`days_until_due` gets the same answer the Werkplanning's placement
rule gives.
"""
from __future__ import annotations

import datetime

from django.utils import timezone
from rest_framework import status as http
from rest_framework.test import APITestCase

from extra_work.models import ExtraWorkRequest, ExtraWorkStatus
from test_utils import TenantFixtureMixin
from tickets.detail_facts import (
    DUE_KIND_DEADLINE,
    DUE_KIND_PLANNED_DAY,
    KIND_MEERWERK,
    KIND_MELDING,
    KIND_TICKET,
    TICKET_KINDS,
    ticket_due,
    ticket_kind,
)
from tickets.models import Ticket, TicketStatus


class TicketKindTests(TenantFixtureMixin, APITestCase):
    def test_a_customer_report_is_a_melding(self):
        # The fixture ticket is created by `customer_user`.
        self.assertEqual(ticket_kind(self.ticket), KIND_MELDING)

    def test_provider_created_work_is_a_ticket(self):
        row = Ticket.objects.create(
            company=self.company,
            building=self.building,
            customer=self.customer,
            created_by=self.manager,
            title="Provider work",
            description="",
        )
        self.assertEqual(ticket_kind(row), KIND_TICKET)

    def test_work_with_a_parent_is_meerwerk_whoever_created_it(self):
        extra_work = ExtraWorkRequest.objects.create(
            company=self.company,
            building=self.building,
            customer=self.customer,
            created_by=self.customer_user,
            title="Deep clean",
            description="",
            status=ExtraWorkStatus.CUSTOMER_APPROVED,
        )
        row = Ticket.objects.create(
            company=self.company,
            building=self.building,
            customer=self.customer,
            created_by=self.customer_user,
            title="Deep clean",
            description="",
            extra_work_request=extra_work,
        )
        self.assertEqual(ticket_kind(row), KIND_MEERWERK)

    def test_every_answer_is_in_the_enum(self):
        self.assertIn(ticket_kind(self.ticket), TICKET_KINDS)


class TicketDueTests(TenantFixtureMixin, APITestCase):
    today = datetime.date(2026, 8, 29)

    def _aware(self, day: datetime.date):
        return timezone.make_aware(
            datetime.datetime.combine(day, datetime.time(9, 0))
        )

    def test_nothing_planned_means_no_due(self):
        facts = ticket_due(self.ticket, self.today)
        self.assertEqual(
            {k: facts[k] for k in ("due_date", "due_kind", "days_until_due")},
            {"due_date": None, "due_kind": None, "days_until_due": None},
        )
        # FE-4 — an unplanned live ticket reports how long it has waited.
        self.assertIsNotNone(facts["unplanned_age_days"])

    def test_a_planned_day_counts_down_as_a_plan_not_a_deadline(self):
        self.ticket.scheduled_start_at = self._aware(datetime.date(2026, 9, 1))
        self.ticket.scheduled_end_at = self._aware(datetime.date(2026, 9, 2))
        self.ticket.save()
        facts = ticket_due(self.ticket, self.today)
        self.assertEqual(facts["due_date"], "2026-09-02")
        self.assertEqual(facts["due_kind"], DUE_KIND_PLANNED_DAY)
        self.assertEqual(facts["days_until_due"], 4)

    def test_the_extra_work_deadline_wins_and_counts_over(self):
        extra_work = ExtraWorkRequest.objects.create(
            company=self.company,
            building=self.building,
            customer=self.customer,
            created_by=self.manager,
            title="Deep clean",
            description="",
            status=ExtraWorkStatus.IN_PROGRESS,
            deadline=datetime.date(2026, 8, 27),
        )
        self.ticket.extra_work_request = extra_work
        self.ticket.scheduled_start_at = self._aware(datetime.date(2026, 9, 10))
        self.ticket.status = TicketStatus.IN_PROGRESS
        self.ticket.save()
        facts = ticket_due(self.ticket, self.today)
        self.assertEqual(facts["due_date"], "2026-08-27")
        self.assertEqual(facts["due_kind"], DUE_KIND_DEADLINE)
        self.assertEqual(facts["days_until_due"], -2)

    def test_a_finished_job_keeps_its_date_but_stops_counting(self):
        self.ticket.scheduled_start_at = self._aware(datetime.date(2026, 8, 20))
        self.ticket.status = TicketStatus.CLOSED
        self.ticket.save()
        facts = ticket_due(self.ticket, self.today)
        self.assertEqual(facts["due_date"], "2026-08-20")
        self.assertIsNone(facts["days_until_due"])


class TicketDetailFactsSerializerTests(TenantFixtureMixin, APITestCase):
    def test_the_detail_carries_the_four_facts(self):
        self.ticket.scheduled_start_at = timezone.now() + datetime.timedelta(
            days=3
        )
        self.ticket.save(update_fields=["scheduled_start_at"])
        self.client.force_authenticate(self.company_admin)
        response = self.client.get(f"/api/tickets/{self.ticket.id}/")
        self.assertEqual(response.status_code, http.HTTP_200_OK, response.data)
        self.assertEqual(response.data["kind"], KIND_MELDING)
        self.assertEqual(response.data["due_kind"], DUE_KIND_PLANNED_DAY)
        self.assertEqual(response.data["days_until_due"], 3)
        self.assertEqual(
            response.data["due_date"],
            timezone.localdate(self.ticket.scheduled_start_at).isoformat(),
        )

    def test_the_customer_reads_the_same_facts(self):
        self.client.force_authenticate(self.customer_user)
        response = self.client.get(f"/api/tickets/{self.ticket.id}/")
        self.assertEqual(response.status_code, http.HTTP_200_OK, response.data)
        self.assertEqual(response.data["kind"], KIND_MELDING)
        self.assertIsNone(response.data["due_date"])
        self.assertIsNone(response.data["days_until_due"])

    def test_the_other_tenant_still_gets_a_wall(self):
        self.client.force_authenticate(self.other_customer_user)
        response = self.client.get(f"/api/tickets/{self.ticket.id}/")
        self.assertEqual(response.status_code, http.HTTP_404_NOT_FOUND)
