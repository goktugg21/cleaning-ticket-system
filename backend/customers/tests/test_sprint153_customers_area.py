"""
Sprint 153 — the Customers area backend surface.

Covers, in order:
  * §2.1 sortable columns (`?ordering=`) on the customer list.
  * §2.2 the three annotated per-row counts, and the invariant that the
    query count does NOT grow with the number of rows.
  * §2.3 POST /api/customers/bulk-deactivate/ — all-or-nothing, one
    atomic block, and the H-1 requirement that a FOREIGN id and a
    FICTIONAL id produce the byte-identical rejection.
  * §2.4 GET /api/customers/<id>/summary/ — the dashboard numbers, the
    404-not-403 tenant floor, and the null-not-zero degradation.
"""
from decimal import Decimal

from rest_framework import status
from rest_framework.test import APITestCase

from customers.models import Contact, Customer, CustomerUserMembership
from test_utils import TenantFixtureMixin


LIST_URL = "/api/customers/"
BULK_DEACTIVATE_URL = "/api/customers/bulk-deactivate/"


def summary_url(customer_id):
    return f"/api/customers/{customer_id}/summary/"


class CustomerOrderingTests(TenantFixtureMixin, APITestCase):
    """§2.1 — the list re-sorts by the columns the table header exposes."""

    def setUp(self):
        super().setUp()
        self.zebra = Customer.objects.create(
            company=self.company,
            name="Zebra BV",
            contact_email="zebra@example.com",
        )
        self.alpha = Customer.objects.create(
            company=self.company,
            name="Alpha BV",
            contact_email="alpha@example.com",
        )

    def _names(self, response):
        return [row["name"] for row in response.data["results"]]

    def test_ordering_by_name_both_directions(self):
        self.authenticate(self.company_admin)

        ascending = self.client.get(LIST_URL, {"ordering": "name"})
        self.assertEqual(ascending.status_code, status.HTTP_200_OK)
        names = self._names(ascending)
        self.assertEqual(names, sorted(names))

        descending = self.client.get(LIST_URL, {"ordering": "-name"})
        self.assertEqual(descending.status_code, status.HTTP_200_OK)
        self.assertEqual(self._names(descending), list(reversed(names)))

    def test_ordering_by_contact_email_is_accepted(self):
        self.authenticate(self.company_admin)
        response = self.client.get(LIST_URL, {"ordering": "contact_email"})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        emails = [row["contact_email"] for row in response.data["results"]]
        self.assertEqual(emails, sorted(emails))

    def test_ordering_by_is_active_is_accepted(self):
        self.authenticate(self.super_admin)
        self.zebra.is_active = False
        self.zebra.save(update_fields=["is_active"])
        response = self.client.get(
            LIST_URL, {"ordering": "is_active", "is_active": "all"}
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        flags = [row["is_active"] for row in response.data["results"]]
        self.assertEqual(flags, sorted(flags))

    def test_unknown_ordering_field_is_ignored_not_an_error(self):
        # OrderingFilter drops an unlisted field rather than 400ing. Pin
        # it so nobody "fixes" the allowlist into a leak of a private
        # column via ?ordering=.
        self.authenticate(self.company_admin)
        response = self.client.get(LIST_URL, {"ordering": "phone"})
        self.assertEqual(response.status_code, status.HTTP_200_OK)


class CustomerListCountsTests(TenantFixtureMixin, APITestCase):
    """§2.2 — the counts are real, and they are annotated, not looped."""

    def _make_customers(self, n, prefix):
        made = []
        for i in range(n):
            made.append(
                Customer.objects.create(
                    company=self.company,
                    name=f"{prefix} {i:02d}",
                    contact_email=f"{prefix.lower()}-{i}@example.com",
                )
            )
        return made

    def test_counts_are_correct_on_the_list(self):
        Contact.objects.create(customer=self.customer, full_name="Contact One")
        Contact.objects.create(customer=self.customer, full_name="Contact Two")

        self.authenticate(self.company_admin)
        response = self.client.get(LIST_URL, {"search": self.customer.name})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        row = next(
            r for r in response.data["results"] if r["id"] == self.customer.id
        )
        # One CustomerBuildingMembership + one CustomerUserMembership come
        # from the shared tenant fixture.
        self.assertEqual(row["linked_building_count"], 1)
        self.assertEqual(row["user_count"], 1)
        self.assertEqual(row["contact_count"], 2)

    def test_counts_survive_the_single_object_path(self):
        # `reactivate` re-serialises a bare Customer with no annotation;
        # the `.count()` fallback has to answer there.
        Contact.objects.create(customer=self.customer, full_name="Solo")
        self.customer.is_active = False
        self.customer.save(update_fields=["is_active"])

        self.authenticate(self.super_admin)
        response = self.client.post(
            f"/api/customers/{self.customer.id}/reactivate/"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["linked_building_count"], 1)
        self.assertEqual(response.data["user_count"], 1)
        self.assertEqual(response.data["contact_count"], 1)

    def _measure(self, url, params):
        """Return the query count for `url`, so the caller can assert the
        SAME number holds for a bigger page."""
        from django.db import connection
        from django.test.utils import CaptureQueriesContext

        with CaptureQueriesContext(connection) as ctx:
            self.client.get(url, params)
        return len(ctx.captured_queries)

    def test_two_row_and_ten_row_pages_cost_the_same(self):
        """The N+1 guard (§2.2). Two pages, different sizes, same query
        count. A serializer computing the three counts per row would make
        the ten-row page cost 3 x (10 - 2) = 24 queries more."""
        self.authenticate(self.company_admin)
        for customer in self._make_customers(12, "Bulk"):
            Contact.objects.create(customer=customer, full_name="C")

        # Warm-up, discarded. The FIRST request of a test pays one-off
        # costs (content-type / permission bootstrap) that have nothing
        # to do with row count; measuring it would make the two-row page
        # look more expensive than the ten-row one.
        self._measure(LIST_URL, {"page_size": 2, "ordering": "name"})

        two = self._measure(LIST_URL, {"page_size": 2, "ordering": "name"})
        ten = self._measure(LIST_URL, {"page_size": 10, "ordering": "name"})

        # Sanity: the pages really do differ in size, so a passing
        # assertion below is not "both returned zero rows".
        small_page = self.client.get(
            LIST_URL, {"page_size": 2, "ordering": "name"}
        )
        big_page = self.client.get(
            LIST_URL, {"page_size": 10, "ordering": "name"}
        )
        self.assertEqual(len(small_page.data["results"]), 2)
        self.assertEqual(len(big_page.data["results"]), 10)

        self.assertEqual(
            two,
            ten,
            f"query count grew with page size ({two} -> {ten}); "
            "the per-row counts are no longer annotated",
        )


class CustomerBulkDeactivateTests(TenantFixtureMixin, APITestCase):
    """§2.3 — all-or-nothing bulk deactivate."""

    def setUp(self):
        super().setUp()
        self.extra_one = Customer.objects.create(
            company=self.company, name="Extra One"
        )
        self.extra_two = Customer.objects.create(
            company=self.company, name="Extra Two"
        )

    def test_super_admin_deactivates_several_at_once(self):
        self.authenticate(self.super_admin)
        response = self.client.post(
            BULK_DEACTIVATE_URL,
            {"customers": [self.extra_one.id, self.extra_two.id]},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data, {"deactivated": 2})
        self.extra_one.refresh_from_db()
        self.extra_two.refresh_from_db()
        self.assertFalse(self.extra_one.is_active)
        self.assertFalse(self.extra_two.is_active)

    def test_company_admin_deactivates_within_own_company(self):
        self.authenticate(self.company_admin)
        response = self.client.post(
            BULK_DEACTIVATE_URL,
            {"customers": [self.extra_one.id]},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.extra_one.refresh_from_db()
        self.assertFalse(self.extra_one.is_active)

    def test_deactivate_is_not_a_hard_delete(self):
        self.authenticate(self.super_admin)
        self.client.post(
            BULK_DEACTIVATE_URL, {"customers": [self.extra_one.id]}, format="json"
        )
        self.assertTrue(Customer.objects.filter(pk=self.extra_one.id).exists())

    def test_one_bad_id_rejects_the_whole_batch_with_zero_writes(self):
        self.authenticate(self.company_admin)
        response = self.client.post(
            BULK_DEACTIVATE_URL,
            {"customers": [self.extra_one.id, self.other_customer.id]},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        codes = [
            getattr(err, "code", None)
            for err in response.data.get("customers", [])
        ]
        self.assertIn("bulk_deactivate_customer_invalid", codes)
        self.extra_one.refresh_from_db()
        self.assertTrue(
            self.extra_one.is_active,
            "a partially-applied bulk deactivate leaked past the atomic block",
        )

    def test_foreign_id_and_fictional_id_return_the_identical_body(self):
        """H-1 / the Sprint 142.1 existence-oracle class.

        A COMPANY_ADMIN probing another tenant's customer id must not be
        able to tell it apart from an id that was never issued. Equality
        of the two response BODIES is the assertion — 'both are 400' is
        not enough, because a differing message is the oracle.
        """
        self.authenticate(self.company_admin)

        foreign = self.client.post(
            BULK_DEACTIVATE_URL,
            {"customers": [self.other_customer.id]},
            format="json",
        )
        fictional_id = Customer.objects.order_by("-id").first().id + 10_000
        fictional = self.client.post(
            BULK_DEACTIVATE_URL,
            {"customers": [fictional_id]},
            format="json",
        )

        self.assertEqual(foreign.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(fictional.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            foreign.json(),
            fictional.json(),
            "a foreign customer id is distinguishable from a fictional one",
        )

    def test_inactive_customer_ids_are_out_of_a_company_admin_scope(self):
        # `scope_customers_for` limits a non-SA to active customers, so an
        # already-deactivated id reads exactly like any other unresolvable
        # id — no special-casing, no oracle.
        self.extra_one.is_active = False
        self.extra_one.save(update_fields=["is_active"])
        self.authenticate(self.company_admin)
        response = self.client.post(
            BULK_DEACTIVATE_URL,
            {"customers": [self.extra_one.id]},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_building_manager_is_forbidden(self):
        self.authenticate(self.manager)
        response = self.client.post(
            BULK_DEACTIVATE_URL, {"customers": [self.extra_one.id]}, format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_customer_user_is_forbidden(self):
        self.authenticate(self.customer_user)
        response = self.client.post(
            BULK_DEACTIVATE_URL, {"customers": [self.customer.id]}, format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_anonymous_is_rejected(self):
        response = self.client.post(
            BULK_DEACTIVATE_URL, {"customers": [self.extra_one.id]}, format="json"
        )
        self.assertIn(
            response.status_code,
            (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN),
        )

    def test_empty_selection_is_rejected(self):
        self.authenticate(self.super_admin)
        response = self.client.post(
            BULK_DEACTIVATE_URL, {"customers": []}, format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_repeated_id_counts_once(self):
        self.authenticate(self.super_admin)
        response = self.client.post(
            BULK_DEACTIVATE_URL,
            {"customers": [self.extra_one.id, self.extra_one.id]},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data, {"deactivated": 1})


class CustomerSummaryTests(TenantFixtureMixin, APITestCase):
    """§2.4 — the overview dashboard read."""

    def test_shape_and_customer_local_counts(self):
        Contact.objects.create(customer=self.customer, full_name="Contact One")
        self.authenticate(self.company_admin)

        response = self.client.get(summary_url(self.customer.id))
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        for key in (
            "linked_building_count",
            "user_count",
            "contact_count",
            "pricing_rule_count",
            "open_ticket_count",
            "ticket_count",
            "open_extra_work_count",
            "extra_work_count",
            "unpaid_invoice_count",
            "unpaid_invoice_total",
        ):
            self.assertIn(key, response.data, f"missing summary key {key}")

        self.assertEqual(response.data["linked_building_count"], 1)
        self.assertEqual(response.data["user_count"], 1)
        self.assertEqual(response.data["contact_count"], 1)

    def test_counts_match_the_list_row_for_the_same_customer(self):
        # The chips and the table must not drift apart.
        Contact.objects.create(customer=self.customer, full_name="C1")
        Contact.objects.create(customer=self.customer, full_name="C2")
        self.authenticate(self.company_admin)

        listed = self.client.get(LIST_URL, {"search": self.customer.name})
        row = next(
            r for r in listed.data["results"] if r["id"] == self.customer.id
        )
        summary = self.client.get(summary_url(self.customer.id))

        for key in ("linked_building_count", "user_count", "contact_count"):
            self.assertEqual(row[key], summary.data[key], key)

    def test_ticket_counts_split_open_from_terminal(self):
        from tickets.models import Ticket, TicketStatus

        # The shared fixture already gives `self.customer` one OPEN
        # ticket; these two are on top of it.
        Ticket.objects.create(
            company=self.company,
            building=self.building,
            customer=self.customer,
            created_by=self.company_admin,
            title="Open one",
            description="",
            status=TicketStatus.OPEN,
        )
        Ticket.objects.create(
            company=self.company,
            building=self.building,
            customer=self.customer,
            created_by=self.company_admin,
            title="Closed one",
            description="",
            status=TicketStatus.CLOSED,
        )

        self.authenticate(self.company_admin)
        response = self.client.get(summary_url(self.customer.id))
        # 1 fixture OPEN + 1 new OPEN + 1 new CLOSED.
        self.assertEqual(response.data["ticket_count"], 3)
        self.assertEqual(response.data["open_ticket_count"], 2)
        # The other tenant's ticket is not in either number.
        self.assertEqual(
            Ticket.objects.filter(customer=self.other_customer).count(), 1
        )

    def test_unpaid_total_counts_sent_and_excludes_reversed(self):
        from invoicing.models import Invoice

        Invoice.objects.create(
            company=self.company,
            customer=self.customer,
            status=Invoice.Status.SENT,
            total_amount=Decimal("1250.00"),
            created_by=self.super_admin,
        )
        # A DRAFT has not been handed to anybody — it cannot be unpaid.
        Invoice.objects.create(
            company=self.company,
            customer=self.customer,
            status=Invoice.Status.DRAFT,
            total_amount=Decimal("999.00"),
            created_by=self.super_admin,
        )
        # A SENT invoice that has since been reversed drops out, and its
        # negative counter-entry must not be double-counted either.
        original = Invoice.objects.create(
            company=self.company,
            customer=self.customer,
            status=Invoice.Status.SENT,
            total_amount=Decimal("500.00"),
            created_by=self.super_admin,
        )
        Invoice.objects.create(
            company=self.company,
            customer=self.customer,
            status=Invoice.Status.SENT,
            total_amount=Decimal("-500.00"),
            is_reversal=True,
            reverses=original,
            created_by=self.super_admin,
        )

        self.authenticate(self.company_admin)
        response = self.client.get(summary_url(self.customer.id))
        self.assertEqual(response.data["unpaid_invoice_count"], 1)
        self.assertEqual(response.data["unpaid_invoice_total"], "1250.00")

    def test_zero_invoices_is_zero_not_null(self):
        self.authenticate(self.company_admin)
        response = self.client.get(summary_url(self.customer.id))
        self.assertEqual(response.data["unpaid_invoice_count"], 0)
        self.assertEqual(response.data["unpaid_invoice_total"], "0.00")

    def test_staff_cannot_reach_a_customer_summary_at_all(self):
        """STAFF is outside `scope_customers_for`, so the 404 floor fires
        before any per-module block runs. The null-degradation path is
        exercised by the CUSTOMER_USER pricing case below, where the
        customer IS reachable but one module is not."""
        from accounts.models import UserRole

        staff = self.make_user("staff-a@example.com", UserRole.STAFF)
        CustomerUserMembership.objects.filter(user=staff).delete()
        self.authenticate(staff)
        response = self.client.get(summary_url(self.customer.id))
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    # ---- tenant floor -------------------------------------------------

    def test_cross_tenant_summary_404s_exactly_like_a_nonexistent_id(self):
        """H-1: a company-B customer must be indistinguishable from an id
        that was never issued."""
        self.authenticate(self.company_admin)

        foreign = self.client.get(summary_url(self.other_customer.id))
        fictional_id = Customer.objects.order_by("-id").first().id + 10_000
        fictional = self.client.get(summary_url(fictional_id))

        self.assertEqual(foreign.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(fictional.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(foreign.json(), fictional.json())

    def test_customer_user_reads_their_own_summary(self):
        self.authenticate(self.customer_user)
        response = self.client.get(summary_url(self.customer.id))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        # Provider-only surfaces degrade to null rather than leaking a
        # count the customer has no page for.
        self.assertIsNone(response.data["pricing_rule_count"])

    def test_customer_user_cannot_read_another_customers_summary(self):
        self.authenticate(self.customer_user)
        response = self.client.get(summary_url(self.other_customer.id))
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_anonymous_is_rejected(self):
        response = self.client.get(summary_url(self.customer.id))
        self.assertIn(
            response.status_code,
            (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN),
        )
