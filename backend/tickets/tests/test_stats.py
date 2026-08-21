from rest_framework import status
from rest_framework.test import APITestCase

from test_utils import TenantFixtureMixin
from tickets.models import Ticket, TicketCategory, TicketPriority, TicketStatus


class TicketStatsTests(TenantFixtureMixin, APITestCase):
    def test_super_admin_sees_aggregate_across_companies(self):
        self.authenticate(self.super_admin)
        response = self.client.get("/api/tickets/stats/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["total"], 2)
        self.assertEqual(response.data["by_status"][TicketStatus.OPEN], 2)

    def test_company_admin_only_counts_own_company(self):
        self.authenticate(self.company_admin)
        response = self.client.get("/api/tickets/stats/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["total"], 1)
        self.assertNotIn(self.other_ticket.id, [self.ticket.id])  # sanity
        self.assertEqual(response.data["by_status"][TicketStatus.OPEN], 1)

    def test_customer_only_counts_linked_tickets(self):
        self.authenticate(self.customer_user)
        response = self.client.get("/api/tickets/stats/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["total"], 1)

    def test_my_open_excludes_closed_approved_rejected(self):
        Ticket.objects.create(
            company=self.company,
            building=self.building,
            customer=self.customer,
            created_by=self.customer_user,
            title="Closed",
            description="closed ticket",
            status=TicketStatus.CLOSED,
        )
        Ticket.objects.create(
            company=self.company,
            building=self.building,
            customer=self.customer,
            created_by=self.customer_user,
            title="Approved",
            description="approved ticket",
            status=TicketStatus.APPROVED,
        )

        self.authenticate(self.company_admin)
        response = self.client.get("/api/tickets/stats/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        # 3 in company total: original OPEN + CLOSED + APPROVED.
        self.assertEqual(response.data["total"], 3)
        # my_open counts only the OPEN one.
        self.assertEqual(response.data["my_open"], 1)

    def test_urgent_counts_only_non_closed(self):
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
        response = self.client.get("/api/tickets/stats/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["urgent"], 1)
        self.assertEqual(response.data["by_priority"][TicketPriority.URGENT], 2)

    def test_waiting_customer_approval_count(self):
        self.move_ticket_to_customer_approval()
        self.authenticate(self.company_admin)
        response = self.client.get("/api/tickets/stats/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["waiting_customer_approval"], 1)


class TicketStatsCategoryTests(TenantFixtureMixin, APITestCase):
    """Sprint 187 §5 — the chips count the rows they sit above.

    (W13 renamed the catalog behind this filter from `WorkCategory` to
    `TicketCategory`; the defect and the fix are unchanged.)

    Sprint 185 gave the Tickets page a category dropdown and taught
    it to the LIST only: `/tickets/stats/` never learned the filter at
    all. Choosing a category narrowed the rows and left the counts above
    them describing the whole company — the same defect as the work-type
    dash (Sprint 183 §2) and the customer's "25" (the `customer` block
    beside this one), one filter later.

    Both lookups the page can send are covered, and the pairing test is
    the one that actually matters: the stats endpoint and the list
    endpoint must answer for the same population, because a chip that
    disagrees with the table under it is worse than no chip.
    """

    def setUp(self):
        super().setUp()
        # W13 — two of the company's SEEDED categories, which every
        # company now has. Creating fresh ones would work too; using the
        # seeded pair keeps the fixture honest about what a real tenant
        # has in front of it.
        self.category = TicketCategory.objects.get(
            company=self.company, slug="klacht"
        )
        self.other_category = TicketCategory.objects.get(
            company=self.company, slug="verzoek"
        )
        self.ticket.category = self.category
        self.ticket.save(update_fields=["category"])
        self.untagged = Ticket.objects.create(
            company=self.company,
            building=self.building,
            customer=self.customer,
            created_by=self.customer_user,
            title="Untagged",
            description="no category yet",
            status=TicketStatus.OPEN,
        )

    def _stats(self, **params):
        response = self.client.get("/api/tickets/stats/", params)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        return response.data

    def _list_count(self, **params):
        response = self.client.get("/api/tickets/", params)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        return response.data["count"]

    def test_unfiltered_stats_count_every_in_scope_ticket(self):
        self.authenticate(self.company_admin)
        self.assertEqual(self._stats()["total"], 2)

    def test_category_narrows_the_counts(self):
        self.authenticate(self.company_admin)
        self.assertEqual(self._stats(category=self.category.id)["total"], 1)
        self.assertEqual(
            self._stats(category=self.other_category.id)["total"], 0
        )

    def test_category_isnull_counts_the_untagged_queue(self):
        self.authenticate(self.company_admin)
        data = self._stats(category__isnull="true")
        self.assertEqual(data["total"], 1)
        self.assertEqual(data["by_status"][TicketStatus.OPEN], 1)

    def test_stats_and_list_agree_for_every_value_the_page_sends(self):
        """The actual contract. If these two ever disagree the chips are
        describing a different population than the rows."""
        self.authenticate(self.company_admin)
        for params in (
            {},
            {"category": self.category.id},
            {"category": self.other_category.id},
            {"category__isnull": "true"},
        ):
            with self.subTest(params=params):
                self.assertEqual(
                    self._stats(**params)["total"],
                    self._list_count(**params),
                )

    def test_a_junk_category_is_no_opinion_rather_than_a_500(self):
        """The same tolerant parse `customer` uses directly above it: an
        unparseable value leaves the queryset alone."""
        self.authenticate(self.company_admin)
        self.assertEqual(self._stats(category="not-a-number")["total"], 2)

    def test_the_category_filter_cannot_widen_scope(self):
        """H-1: narrowing runs INSIDE `scope_tickets_for`, so a company
        admin naming another company's ticket category still sees only
        their own — never the other tenant's rows."""
        other_category = TicketCategory.objects.get(
            company=self.other_company, slug="klacht"
        )
        self.other_ticket.category = other_category
        self.other_ticket.save(update_fields=["category"])

        self.authenticate(self.company_admin)
        self.assertEqual(self._stats(category=other_category.id)["total"], 0)
