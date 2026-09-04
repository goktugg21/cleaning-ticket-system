"""P-5 S7 — THE CONNECTIONS LAYER: what feeds what, as linked facts.

The owner's example is the spec: a contract holds building work (facade
cleaning, 2x/year) -> occurrences run it -> the building is billed ->
the cost split divides it across the building's customers -> tickets
carry it -> people do it. Every detail page names the records it
connects to, with one line of context, and these tests pin the
additive read-only fields that carry it:

  * contract detail  -> its buildings WITH their cost split, its visits
                        (occurrence tickets), its invoice trail
  * building detail  -> the contracts covering it
  * occurrence ticket -> its recurring job and, through the contract
                        line, the contract; which visit of the year
  * invoice          -> the contract period it was generated for; each
                        extra-work line's meerwerk and building
"""
from __future__ import annotations

import datetime
from decimal import Decimal

from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from buildings.models import BuildingCostShare
from contracts.models import ContractInvoice, ContractLine
from contracts.tests.fixtures import make_contract
from invoicing.models import Invoice
from planned_work.models import PlannedOccurrence, PlannedOccurrenceStatus
from planned_work.tests._base import PlannedWorkFixtureMixin
from tickets.models import Ticket, TicketStatus


class ConnectionsTests(PlannedWorkFixtureMixin, APITestCase):
    def setUp(self):
        super().setUp()
        self.contract = make_contract(
            company=self.company,
            customer=self.customer,
            contract_no="C-2026-0001",
            buildings=[self.building],
        )
        self.revision = self.contract.revisions.order_by("id").first()
        self.line = ContractLine.objects.create(
            revision=self.revision,
            name="Facade cleaning",
            amount=Decimal("600.00"),
            hours=Decimal("4.00"),
            sort_order=10,
        )
        BuildingCostShare.objects.create(
            building=self.building, customer=self.customer, share_pct=Decimal("60.00")
        )
        BuildingCostShare.objects.create(
            building=self.building,
            customer=self.other_customer,
            share_pct=Decimal("40.00"),
        )
        self.job = self.make_recurring_job()
        self.job.contract_line = self.line
        self.job.save(update_fields=["contract_line"])
        today = timezone.localdate()
        self.occurrence = PlannedOccurrence.objects.create(
            recurring_job=self.job,
            company=self.company,
            building=self.building,
            customer=self.customer,
            planned_date=today - datetime.timedelta(days=3),
            status=PlannedOccurrenceStatus.TICKET_CREATED,
            source_window=self.default_window(self.job),
        )
        PlannedOccurrence.objects.create(
            recurring_job=self.job,
            company=self.company,
            building=self.building,
            customer=self.customer,
            planned_date=today + datetime.timedelta(days=30),
            status=PlannedOccurrenceStatus.PLANNED,
            source_window=self.default_window(self.job),
        )
        self.ticket = Ticket.objects.create(
            company=self.company,
            building=self.building,
            customer=self.customer,
            created_by=self.super_admin,
            title="Facade cleaning — visit",
            description="",
            status=TicketStatus.OPEN,
            planned_occurrence=self.occurrence,
        )
        self.invoice = Invoice.objects.create(
            company=self.company,
            customer=self.customer,
            status=Invoice.Status.DRAFT,
            created_by=self.super_admin,
        )
        ContractInvoice.objects.create(
            contract=self.contract,
            invoice=self.invoice,
            revision=self.revision,
            period_start=datetime.date(2026, 8, 1),
            period_end=datetime.date(2026, 8, 31),
            invoice_date=datetime.date(2026, 8, 1),
        )

    def test_a_contract_reaches_its_building_split_visits_and_invoices(self):
        self.authenticate(self.super_admin)
        response = self.client.get(f"/api/contracts/{self.contract.id}/")
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        building = response.data["buildings"][0]
        self.assertEqual(building["id"], self.building.id)
        self.assertEqual(
            [(s["customer_name"], s["share_pct"]) for s in building["cost_shares"]],
            [(self.customer.name, "60.00"), (self.other_customer.name, "40.00")],
        )
        visits = response.data["visits"]
        self.assertEqual(visits["total"], 2)
        self.assertEqual(visits["recent"][0]["ticket_id"], self.ticket.id)
        self.assertEqual(visits["recent"][0]["ticket_no"], self.ticket.ticket_no)
        self.assertEqual(len(visits["next"]), 1)
        trail = response.data["invoice_trail"]
        self.assertEqual(trail[0]["invoice_id"], self.invoice.id)
        self.assertEqual(trail[0]["period_start"], "2026-08-01")

    def test_the_list_does_not_pay_for_the_connections(self):
        self.authenticate(self.super_admin)
        response = self.client.get("/api/contracts/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        rows = response.data["results"] if "results" in response.data else response.data
        row = next(r for r in rows if r["id"] == self.contract.id)
        self.assertIsNone(row["visits"])
        self.assertNotIn("cost_shares", row["buildings"][0])

    def test_a_building_reaches_its_contracts(self):
        self.authenticate(self.super_admin)
        response = self.client.get(f"/api/buildings/{self.building.id}/")
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        contracts = response.data["contracts"]
        self.assertEqual(contracts[0]["id"], self.contract.id)
        self.assertEqual(contracts[0]["contract_no"], "C-2026-0001")
        self.assertEqual(contracts[0]["customer_name"], self.customer.name)
        self.assertEqual(contracts[0]["period_amount"], "600.00")
        listed = self.client.get("/api/buildings/")
        rows = listed.data["results"] if "results" in listed.data else listed.data
        self.assertIsNone(next(r for r in rows if r["id"] == self.building.id)["contracts"])

    def test_an_occurrence_ticket_says_its_origin(self):
        self.authenticate(self.super_admin)
        response = self.client.get(f"/api/tickets/{self.ticket.id}/")
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        origin = response.data["occurrence_origin"]
        self.assertEqual(origin["contract_id"], self.contract.id)
        self.assertEqual(origin["contract_no"], "C-2026-0001")
        self.assertEqual(origin["recurring_job_title"], self.job.title)
        self.assertEqual(origin["contract_line_name"], "Facade cleaning")
        self.assertEqual(origin["visit_index"], 1)
        self.assertEqual(origin["visits_this_year"], 2)

    def test_a_plain_ticket_has_no_occurrence_origin(self):
        self.ticket.planned_occurrence = None
        self.ticket.save(update_fields=["planned_occurrence"])
        self.authenticate(self.super_admin)
        response = self.client.get(f"/api/tickets/{self.ticket.id}/")
        self.assertIsNone(response.data["occurrence_origin"])

    def test_an_invoice_names_its_contract(self):
        self.authenticate(self.super_admin)
        response = self.client.get(f"/api/invoices/{self.invoice.id}/")
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertEqual(response.data["contract"]["id"], self.contract.id)
        self.assertEqual(response.data["contract"]["period_end"], "2026-08-31")
