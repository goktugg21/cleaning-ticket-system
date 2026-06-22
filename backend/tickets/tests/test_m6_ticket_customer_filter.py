"""
M6.1 — ticket list `?customer=` / `?type=` / `?exclude_type=` filters.

The provider customer-detail page surfaces a customer's tickets and
meldingen as disjoint sub-tabs:
  * meldingen tab → `?customer=<id>&type=REPORT`
  * tickets tab   → `?customer=<id>&exclude_type=REPORT`

All three params apply ON TOP of `scope_tickets_for`, so they can only
narrow the role-permitted set. These tests drive the list endpoint as a
SUPER_ADMIN (sees all in scope) and assert against DB-derived expected
sets so they stay robust against the shared fixture tickets.
"""
from __future__ import annotations

from rest_framework import status
from rest_framework.test import APITestCase

from customers.models import Customer
from tickets.models import Ticket, TicketType
from test_utils import TenantFixtureMixin


TICKETS_URL = "/api/tickets/"


class TicketCustomerTypeFilterTests(TenantFixtureMixin, APITestCase):
    def setUp(self):
        super().setUp()
        # A second customer in the SAME provider company (in scope).
        self.customer2 = Customer.objects.create(
            company=self.company,
            building=self.building,
            name="Customer A2",
            contact_email="a2@example.com",
        )

        def mk(customer, ttype, title):
            return Ticket.objects.create(
                company=self.company,
                building=self.building,
                customer=customer,
                created_by=self.customer_user,
                title=title,
                description="M6 filter test",
                type=ttype,
            )

        # customer A: one melding + two non-meldingen.
        self.t_report = mk(self.customer, TicketType.REPORT, "A report")
        self.t_complaint = mk(self.customer, TicketType.COMPLAINT, "A complaint")
        self.t_request = mk(self.customer, TicketType.REQUEST, "A request")
        # A ticket for a different (in-scope, same-provider) customer.
        self.t_other_customer = mk(
            self.customer2, TicketType.REPORT, "Other customer report"
        )

        self.authenticate(self.super_admin)

    def test_customer_filter_narrows_to_one_customer(self):
        response = self.client.get(f"{TICKETS_URL}?customer={self.customer.id}")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        ids = self.response_ids(response)
        expected = set(
            Ticket.objects.filter(customer=self.customer).values_list(
                "id", flat=True
            )
        )
        self.assertEqual(ids, expected)
        # Other customers excluded.
        self.assertNotIn(self.t_other_customer.id, ids)
        self.assertNotIn(self.other_ticket.id, ids)

    def test_type_report_returns_only_meldingen(self):
        response = self.client.get(f"{TICKETS_URL}?type=REPORT")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        ids = self.response_ids(response)
        expected = set(
            Ticket.objects.filter(type=TicketType.REPORT).values_list(
                "id", flat=True
            )
        )
        self.assertEqual(ids, expected)
        self.assertIn(self.t_report.id, ids)
        self.assertNotIn(self.t_complaint.id, ids)
        self.assertNotIn(self.t_request.id, ids)

    def test_exclude_type_report_returns_only_non_meldingen(self):
        response = self.client.get(f"{TICKETS_URL}?exclude_type=REPORT")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        ids = self.response_ids(response)
        expected = set(
            Ticket.objects.exclude(type=TicketType.REPORT).values_list(
                "id", flat=True
            )
        )
        self.assertEqual(ids, expected)
        self.assertIn(self.t_complaint.id, ids)
        self.assertIn(self.t_request.id, ids)
        self.assertNotIn(self.t_report.id, ids)

    def test_customer_meldingen_and_tickets_are_disjoint_and_complete(self):
        all_a = set(
            Ticket.objects.filter(customer=self.customer).values_list(
                "id", flat=True
            )
        )
        meldingen = self.response_ids(
            self.client.get(
                f"{TICKETS_URL}?customer={self.customer.id}&type=REPORT"
            )
        )
        tickets = self.response_ids(
            self.client.get(
                f"{TICKETS_URL}?customer={self.customer.id}&exclude_type=REPORT"
            )
        )
        # Disjoint — no ticket appears in both sub-tabs.
        self.assertEqual(meldingen & tickets, set())
        # Together they cover the customer's full set.
        self.assertEqual(meldingen | tickets, all_a)
        # Sanity: the right rows land in the right tab.
        self.assertIn(self.t_report.id, meldingen)
        self.assertIn(self.t_complaint.id, tickets)
        self.assertIn(self.t_request.id, tickets)

    def test_bad_customer_param_is_rejected_cleanly_not_500(self):
        # `customer` is a declared TicketFilter field (FK exact), so an
        # unparseable value is rejected by django-filter with a clean
        # 400 — never a 500 — matching the project's fail-closed
        # convention for bad filter input (cf. reports out-of-range 400).
        response = self.client.get(f"{TICKETS_URL}?customer=abc")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertNotEqual(response.status_code, 500)

    def test_exclude_type_csv_drops_all_listed_types(self):
        # Exercises the new _apply_customer_type_filters CSV path:
        # `exclude_type` is NOT a TicketFilter field, so the hand-rolled
        # method owns it and splits the comma-separated list.
        response = self.client.get(
            f"{TICKETS_URL}?exclude_type=REPORT,COMPLAINT"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        ids = self.response_ids(response)
        self.assertIn(self.t_request.id, ids)
        self.assertNotIn(self.t_report.id, ids)
        self.assertNotIn(self.t_complaint.id, ids)
        returned_types = set(
            Ticket.objects.filter(id__in=ids).values_list("type", flat=True)
        )
        self.assertEqual(
            returned_types & {TicketType.REPORT, TicketType.COMPLAINT}, set()
        )

    def test_type_in_csv_includes_all_listed_types(self):
        # CSV multi-type include via the canonical django-filter `in`
        # lookup (?type__in=) — proves multi-type filtering works.
        response = self.client.get(f"{TICKETS_URL}?type__in=REPORT,COMPLAINT")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        ids = self.response_ids(response)
        self.assertIn(self.t_report.id, ids)
        self.assertIn(self.t_complaint.id, ids)
        self.assertNotIn(self.t_request.id, ids)
        returned_types = set(
            Ticket.objects.filter(id__in=ids).values_list("type", flat=True)
        )
        self.assertTrue(
            returned_types <= {TicketType.REPORT, TicketType.COMPLAINT}
        )
