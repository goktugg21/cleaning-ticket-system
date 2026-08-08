"""
Sprint 155 §2 — the customer overview's "Linked buildings" card.

The card sat beside About showing a building's name and city and nothing
else, so its right-hand half was visibly empty. It now shows the full
address line, how many customers and managers are at that building, and
an inactive marker — all of it on the row the card already fetched.

The rule this file enforces is the one that makes that affordable:
**the extra fields cost no extra queries.** A count computed per row
turns one request into one-per-building, which looks fine on seed data
and falls over on a customer with forty sites. The guard compares a
2-link customer with a 10-link one; if the counts stop being annotated
the second one gets ~16 queries more.

The same serializer is read from the BUILDING side too
(`/api/buildings/<id>/customers/`), so that anchor is covered as well —
one serializer with two anchors only stays honest if both annotate.
"""
from django.db import connection
from django.test.utils import CaptureQueriesContext
from rest_framework import status
from rest_framework.test import APITestCase

from buildings.models import Building, BuildingManagerAssignment
from customers.models import Customer, CustomerBuildingMembership
from test_utils import TenantFixtureMixin


def customer_buildings_url(customer_id):
    return f"/api/customers/{customer_id}/buildings/"


def building_customers_url(building_id):
    return f"/api/buildings/{building_id}/customers/"


class LinkedBuildingRowFieldsTests(TenantFixtureMixin, APITestCase):
    """The four fields the card renders."""

    def setUp(self):
        super().setUp()
        self.building.city = "Amsterdam"
        self.building.postal_code = "1012 AB"
        self.building.save(update_fields=["city", "postal_code"])
        self.authenticate(self.company_admin)

    def _row(self):
        response = self.client.get(customer_buildings_url(self.customer.id))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        rows = response.data.get("results", response.data)
        return next(r for r in rows if r["building_id"] == self.building.id)

    def test_the_row_carries_the_full_address_line(self):
        row = self._row()
        self.assertEqual(row["building_city"], "Amsterdam")
        self.assertEqual(row["building_postal_code"], "1012 AB")

    def test_the_row_says_when_the_building_is_inactive(self):
        """A customer stays linked to a building that gets deactivated.

        Nothing on the card said so before, which is the case where the
        operator most needs to be told.
        """
        row = self._row()
        self.assertTrue(row["building_is_active"])

        self.building.is_active = False
        self.building.save(update_fields=["is_active"])
        self.assertFalse(self._row()["building_is_active"])

    def test_the_row_counts_the_customers_and_managers_at_that_building(self):
        # TenantFixtureMixin already assigns `self.manager` to
        # `self.building`, so the manager count starts at one.
        second = Customer.objects.create(
            company=self.company, name="Second customer"
        )
        CustomerBuildingMembership.objects.create(
            customer=second, building=self.building
        )
        extra_manager = self.make_user(
            "second-manager@example.com", self.manager.role
        )
        BuildingManagerAssignment.objects.create(
            user=extra_manager, building=self.building
        )

        row = self._row()
        self.assertEqual(row["building_customer_count"], 2)
        self.assertEqual(row["building_manager_count"], 2)

    def test_a_building_with_nothing_at_it_reports_zero_not_null(self):
        """Zero is an answer; null would render as a missing field.

        This is also the case the `is not None` check in the serializer
        exists for — a truthiness test would send an annotated 0 down the
        per-row fallback path.
        """
        lonely = Building.objects.create(
            company=self.company, name="Lonely", address="Nowhere 1"
        )
        CustomerBuildingMembership.objects.create(
            customer=self.customer, building=lonely
        )
        response = self.client.get(customer_buildings_url(self.customer.id))
        row = next(
            r
            for r in response.data.get("results", response.data)
            if r["building_id"] == lonely.id
        )
        self.assertEqual(row["building_customer_count"], 1)
        self.assertEqual(row["building_manager_count"], 0)

    def test_the_link_create_response_has_the_same_shape_as_a_list_row(self):
        """A created row must not come back with null counts.

        The create path re-reads through the annotated queryset for
        exactly this reason: a response whose fields are null while every
        list row's are numbers is a contract with two shapes.
        """
        fresh = Building.objects.create(
            company=self.company, name="Fresh", address="New 1"
        )
        response = self.client.post(
            customer_buildings_url(self.customer.id), {"building_id": fresh.id}
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["building_customer_count"], 1)
        self.assertEqual(response.data["building_manager_count"], 0)
        self.assertTrue(response.data["building_is_active"])


class LinkedBuildingQueryCountTests(TenantFixtureMixin, APITestCase):
    """The N+1 guard. This is the point of the whole §2 approach."""

    def _measure(self, url):
        with CaptureQueriesContext(connection) as ctx:
            self.client.get(url)
        return len(ctx.captured_queries)

    def test_ten_links_cost_the_same_as_two(self):
        self.authenticate(self.company_admin)
        small = Customer.objects.create(company=self.company, name="Small")
        large = Customer.objects.create(company=self.company, name="Large")

        for index in range(10):
            building = Building.objects.create(
                company=self.company,
                name=f"Site {index:02d}",
                address=f"Street {index}",
            )
            BuildingManagerAssignment.objects.create(
                user=self.manager, building=building
            )
            CustomerBuildingMembership.objects.create(
                customer=large, building=building
            )
            if index < 2:
                CustomerBuildingMembership.objects.create(
                    customer=small, building=building
                )

        # Warm-up, discarded: the first request of a test pays one-off
        # bootstrap costs unrelated to row count.
        self._measure(customer_buildings_url(small.id))
        two = self._measure(customer_buildings_url(small.id))
        ten = self._measure(customer_buildings_url(large.id))

        self.assertEqual(
            len(
                self.client.get(customer_buildings_url(large.id)).data.get(
                    "results", []
                )
            ),
            10,
        )
        self.assertEqual(
            two,
            ten,
            f"query count grew with the number of linked buildings "
            f"({two} -> {ten}); the per-building counts are no longer "
            "annotated",
        )

    def test_the_building_side_read_is_annotated_too(self):
        """One serializer, two anchors — both must annotate.

        The building's customers card reads the same rows from the other
        end. If only the customer-side queryset annotated, this side
        would silently fall through to the per-row fallback and the N+1
        would exist on one anchor only.
        """
        self.authenticate(self.company_admin)
        for index in range(10):
            customer = Customer.objects.create(
                company=self.company, name=f"Tenant {index:02d}"
            )
            CustomerBuildingMembership.objects.create(
                customer=customer, building=self.building
            )

        url = building_customers_url(self.building.id)
        self._measure(url)
        many = self._measure(url)

        lonely = Building.objects.create(
            company=self.company, name="Lonely", address="Nowhere 1"
        )
        CustomerBuildingMembership.objects.create(
            customer=self.customer, building=lonely
        )
        one = self._measure(building_customers_url(lonely.id))

        self.assertEqual(
            one,
            many,
            f"the building-side read grew with row count ({one} -> {many})",
        )


class LinkedBuildingScopingTests(TenantFixtureMixin, APITestCase):
    """The new fields must not become a cross-tenant read.

    They are all facts about a building the customer is ALREADY linked
    to, so no new information crosses a boundary — but the counts are
    computed over the whole building, so the endpoint's own scoping is
    what keeps them inside the tenant. Pinned rather than assumed.
    """

    def test_a_foreign_customers_buildings_are_not_readable(self):
        self.authenticate(self.company_admin)
        response = self.client.get(customer_buildings_url(self.other_customer.id))
        self.assertIn(
            response.status_code,
            (status.HTTP_403_FORBIDDEN, status.HTTP_404_NOT_FOUND),
        )

    def test_a_foreign_building_customer_list_404s(self):
        self.authenticate(self.company_admin)
        response = self.client.get(
            building_customers_url(self.other_building.id)
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
