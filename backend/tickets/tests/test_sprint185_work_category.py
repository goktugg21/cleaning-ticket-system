"""
Sprint 185 E §1 — the work-category catalog, and the filter that is its point.

The owner's requirement: a melding says what kind of MESSAGE it is
(`Ticket.type`) and has never said what kind of WORK it is. The monthly
customer review is "how many meldingen per category per building", and
no tenant could answer it or add a category without a developer.

What these pin, in the order they matter:

  * **adding a category needs no deployment** — created through the API,
    immediately offerable and immediately filterable. That is the
    acceptance criterion for the whole item, stated as a test;
  * **the filter works**, including `category__isnull` for "not yet
    categorised", which is the queue an operator works through;
  * **the endpoints that carry the new field are RENDERED** — the Sprint
    174 §0 rule. A missing `fields` entry took the whole Extra Work page
    down in Sprint 173 and no filter test would have caught it, because a
    filter test issues a query and never serialises a row;
  * **the type is untouched.** The category sits beside it; a melding
    carries both, and tagging one must not disturb the other;
  * uniqueness is per company and case/whitespace-insensitive;
  * a category in use cannot be deleted (`Ticket.category` is SET_NULL,
    so a delete would silently untag meldingen and empty the report);
  * cross-tenant: a company admin cannot read, write, or tag with
    another company's categories, and a foreign id reads as NONEXISTENT
    rather than forbidden (H-1).
"""
from __future__ import annotations

from rest_framework import status
from rest_framework.test import APITestCase

from companies.models import CompanyUserMembership
from test_utils import TenantFixtureMixin
from tickets.models import Ticket, TicketType, WorkCategory

LIST = "/api/tickets/categories/"


def detail(category_id):
    return f"/api/tickets/categories/{category_id}/"


def ticket_category_url(ticket_id):
    return f"/api/tickets/{ticket_id}/category/"


class WorkCategoryCatalogTests(TenantFixtureMixin, APITestCase):
    def setUp(self):
        super().setUp()
        CompanyUserMembership.objects.get_or_create(
            user=self.company_admin, company=self.company
        )
        CompanyUserMembership.objects.get_or_create(
            user=self.other_company_admin, company=self.other_company
        )

    def as_(self, user):
        self.client.force_authenticate(user=user)
        return self.client

    # ------------------------------------------------------------------
    # The acceptance criterion
    # ------------------------------------------------------------------
    def test_adding_a_category_needs_no_deployment(self):
        """Created through the API, listed immediately, no code change
        and no restart. This is the test of whether the item worked."""
        before = self.as_(self.company_admin).get(
            LIST, {"company": self.company.id}
        )
        self.assertEqual(len(before.data["results"]), 0)

        created = self.as_(self.company_admin).post(
            LIST,
            {"company": self.company.id, "name": "Glasbewassing"},
            format="json",
        )
        self.assertEqual(created.status_code, 201, created.data)

        after = self.as_(self.company_admin).get(
            LIST, {"company": self.company.id}
        )
        self.assertEqual(
            [row["name"] for row in after.data["results"]], ["Glasbewassing"]
        )

    def test_a_category_only_one_melding_uses_still_filters(self):
        """The BuildingType test, restated for meldingen: a category one
        melding carries must still narrow the list to exactly it."""
        created = self.as_(self.company_admin).post(
            LIST,
            {"company": self.company.id, "name": "Sanitair"},
            format="json",
        )
        category_id = created.data["id"]

        self.as_(self.company_admin).patch(
            ticket_category_url(self.ticket.id),
            {"category": category_id},
            format="json",
        )
        # A second, untagged melding so the filter has something to
        # exclude — a filter test where everything matches proves nothing.
        Ticket.objects.create(
            company=self.company,
            building=self.building,
            customer=self.customer,
            created_by=self.customer_user,
            title="Untagged",
            description="No category",
        )

        response = self.as_(self.company_admin).get(
            "/api/tickets/", {"category": category_id}
        )
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(
            [row["id"] for row in response.data["results"]], [self.ticket.id]
        )

    def test_the_uncategorised_queue_is_listable(self):
        """`category__isnull=true` — "what have we not classified yet",
        which is the list an operator actually works through."""
        category = WorkCategory.objects.create(
            company=self.company, name="Vloeren"
        )
        self.ticket.category = category
        self.ticket.save(update_fields=["category"])
        untagged = Ticket.objects.create(
            company=self.company,
            building=self.building,
            customer=self.customer,
            created_by=self.customer_user,
            title="Untagged",
            description="No category",
        )

        response = self.as_(self.company_admin).get(
            "/api/tickets/", {"category__isnull": "true"}
        )
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(
            [row["id"] for row in response.data["results"]], [untagged.id]
        )

    # ------------------------------------------------------------------
    # Sprint 174 §0 — render the endpoints that carry the new field
    # ------------------------------------------------------------------
    def test_the_ticket_LIST_renders_the_category_and_its_name(self):
        category = WorkCategory.objects.create(
            company=self.company, name="Afval"
        )
        self.ticket.category = category
        self.ticket.save(update_fields=["category"])

        response = self.as_(self.company_admin).get("/api/tickets/")
        self.assertEqual(response.status_code, 200, response.data)
        row = next(
            r for r in response.data["results"] if r["id"] == self.ticket.id
        )
        for key in ("category", "category_name"):
            self.assertIn(key, row)
        self.assertEqual(row["category"], category.id)
        self.assertEqual(row["category_name"], "Afval")

    def test_the_ticket_DETAIL_renders_the_category_and_its_name(self):
        category = WorkCategory.objects.create(
            company=self.company, name="Afval"
        )
        self.ticket.category = category
        self.ticket.save(update_fields=["category"])

        response = self.as_(self.company_admin).get(
            f"/api/tickets/{self.ticket.id}/"
        )
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["category"], category.id)
        self.assertEqual(response.data["category_name"], "Afval")

    def test_an_uncategorised_melding_renders_null_not_a_missing_key(self):
        response = self.as_(self.company_admin).get(
            f"/api/tickets/{self.ticket.id}/"
        )
        self.assertEqual(response.status_code, 200, response.data)
        self.assertIn("category", response.data)
        self.assertIn("category_name", response.data)
        self.assertIsNone(response.data["category"])
        self.assertIsNone(response.data["category_name"])

    def test_the_catalog_LIST_renders_every_field_it_promises(self):
        WorkCategory.objects.create(company=self.company, name="Sanitair")
        response = self.as_(self.company_admin).get(
            LIST, {"company": self.company.id}
        )
        self.assertEqual(response.status_code, 200, response.data)
        row = response.data["results"][0]
        for key in (
            "id",
            "company",
            "company_name",
            "name",
            "is_active",
            "sort_order",
            "usage_count",
            "created_at",
            "updated_at",
        ):
            self.assertIn(key, row)

    # ------------------------------------------------------------------
    # The category is BESIDE the type, not instead of it
    # ------------------------------------------------------------------
    def test_tagging_a_category_leaves_the_message_type_alone(self):
        """Two classifications, two questions. The owner asked for the
        type to stay because the customer portal reads it."""
        self.ticket.type = TicketType.COMPLAINT
        self.ticket.save(update_fields=["type"])
        category = WorkCategory.objects.create(
            company=self.company, name="Sanitair"
        )

        response = self.as_(self.company_admin).patch(
            ticket_category_url(self.ticket.id),
            {"category": category.id},
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.data)
        self.ticket.refresh_from_db()
        self.assertEqual(self.ticket.category_id, category.id)
        self.assertEqual(self.ticket.type, TicketType.COMPLAINT)

    def test_a_melding_can_be_created_with_a_category(self):
        category = WorkCategory.objects.create(
            company=self.company, name="Sanitair"
        )
        response = self.as_(self.company_admin).post(
            "/api/tickets/",
            {
                "title": "Leaking tap",
                "description": "Drips",
                "building": self.building.id,
                "customer": self.customer.id,
                "category": category.id,
            },
            format="json",
        )
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(
            Ticket.objects.get(id=response.data["id"]).category_id, category.id
        )

    def test_the_category_can_be_cleared(self):
        """"Tagged wrong" has to be expressible or the first mistake is
        permanent."""
        category = WorkCategory.objects.create(
            company=self.company, name="Sanitair"
        )
        self.ticket.category = category
        self.ticket.save(update_fields=["category"])

        response = self.as_(self.company_admin).patch(
            ticket_category_url(self.ticket.id),
            {"category": None},
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.data)
        self.ticket.refresh_from_db()
        self.assertIsNone(self.ticket.category_id)

    # ------------------------------------------------------------------
    # Uniqueness, archiving, deletion
    # ------------------------------------------------------------------
    def test_the_same_name_twice_in_one_company_is_refused(self):
        self.as_(self.company_admin).post(
            LIST,
            {"company": self.company.id, "name": "Sanitair"},
            format="json",
        )
        again = self.as_(self.company_admin).post(
            LIST,
            {"company": self.company.id, "name": "Sanitair"},
            format="json",
        )
        self.assertEqual(again.status_code, 400, again.data)

    def test_case_and_whitespace_do_not_make_it_a_different_name(self):
        self.as_(self.company_admin).post(
            LIST,
            {"company": self.company.id, "name": "Sanitair"},
            format="json",
        )
        for clashing in ("sanitair", "  SANITAIR  ", "Sanitair "):
            with self.subTest(name=clashing):
                response = self.as_(self.company_admin).post(
                    LIST,
                    {"company": self.company.id, "name": clashing},
                    format="json",
                )
                self.assertEqual(response.status_code, 400, response.data)

    def test_two_companies_may_each_have_the_same_name(self):
        first = self.as_(self.company_admin).post(
            LIST,
            {"company": self.company.id, "name": "Sanitair"},
            format="json",
        )
        second = self.as_(self.other_company_admin).post(
            LIST,
            {"company": self.other_company.id, "name": "Sanitair"},
            format="json",
        )
        self.assertEqual(first.status_code, 201, first.data)
        self.assertEqual(second.status_code, 201, second.data)

    def test_the_stored_name_is_trimmed(self):
        created = self.as_(self.company_admin).post(
            LIST,
            {"company": self.company.id, "name": "  Sanitair  "},
            format="json",
        )
        self.assertEqual(created.status_code, 201, created.data)
        self.assertEqual(created.data["name"], "Sanitair")

    def test_a_category_in_use_cannot_be_deleted(self):
        category = WorkCategory.objects.create(
            company=self.company, name="Sanitair"
        )
        self.ticket.category = category
        self.ticket.save(update_fields=["category"])

        response = self.as_(self.company_admin).delete(detail(category.id))
        self.assertEqual(response.status_code, 400, response.data)
        self.assertEqual(response.data["code"], "work_category_in_use")
        self.assertTrue(WorkCategory.objects.filter(id=category.id).exists())

    def test_an_unused_category_can_be_deleted(self):
        category = WorkCategory.objects.create(
            company=self.company, name="Sanitair"
        )
        response = self.as_(self.company_admin).delete(detail(category.id))
        self.assertEqual(response.status_code, 204)
        self.assertFalse(WorkCategory.objects.filter(id=category.id).exists())

    def test_archiving_keeps_it_on_the_meldingen_that_carry_it(self):
        category = WorkCategory.objects.create(
            company=self.company, name="Sanitair"
        )
        self.ticket.category = category
        self.ticket.save(update_fields=["category"])

        response = self.as_(self.company_admin).patch(
            detail(category.id), {"is_active": False}, format="json"
        )
        self.assertEqual(response.status_code, 200, response.data)
        self.ticket.refresh_from_db()
        self.assertEqual(self.ticket.category_id, category.id)

        offered = self.as_(self.company_admin).get(
            LIST, {"company": self.company.id, "is_active": "true"}
        )
        self.assertEqual(offered.data["results"], [])

    def test_usage_count_counts_the_meldingen_carrying_it(self):
        category = WorkCategory.objects.create(
            company=self.company, name="Sanitair"
        )
        self.ticket.category = category
        self.ticket.save(update_fields=["category"])

        response = self.as_(self.company_admin).get(
            LIST, {"company": self.company.id}
        )
        self.assertEqual(response.data["results"][0]["usage_count"], 1)

    # ------------------------------------------------------------------
    # Tenancy (H-1)
    # ------------------------------------------------------------------
    def test_a_company_admin_does_not_see_another_companys_categories(self):
        WorkCategory.objects.create(
            company=self.other_company, name="Foreign"
        )
        response = self.as_(self.company_admin).get(LIST)
        self.assertEqual(
            [row["name"] for row in response.data["results"]], []
        )

    def test_a_company_admin_cannot_create_in_another_company(self):
        response = self.as_(self.company_admin).post(
            LIST,
            {"company": self.other_company.id, "name": "Sneak"},
            format="json",
        )
        self.assertEqual(response.status_code, 403, response.data)

    def test_a_foreign_category_reads_as_nonexistent_when_tagging(self):
        """H-1: "exists but is not yours" and "does not exist" must be
        the same answer, so this is a 400 naming an unknown category and
        not a 403 confirming one exists."""
        foreign = WorkCategory.objects.create(
            company=self.other_company, name="Foreign"
        )
        response = self.as_(self.company_admin).patch(
            ticket_category_url(self.ticket.id),
            {"category": foreign.id},
            format="json",
        )
        self.assertEqual(response.status_code, 400, response.data)
        self.ticket.refresh_from_db()
        self.assertIsNone(self.ticket.category_id)

    def test_a_customer_user_gets_nothing_from_the_catalog(self):
        WorkCategory.objects.create(company=self.company, name="Sanitair")
        response = self.as_(self.customer_user).get(LIST)
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["results"], [])

    def test_a_customer_user_cannot_categorise(self):
        """The category feeds a provider-side report; a customer choosing
        the trade would be the customer classifying the provider's work."""
        category = WorkCategory.objects.create(
            company=self.company, name="Sanitair"
        )
        response = self.as_(self.customer_user).patch(
            ticket_category_url(self.ticket.id),
            {"category": category.id},
            format="json",
        )
        self.assertEqual(response.status_code, 403, response.data)
        self.ticket.refresh_from_db()
        self.assertIsNone(self.ticket.category_id)

    def test_a_building_manager_may_categorise_in_their_own_scope(self):
        """Triage is the building manager's job — they see the melding
        first — and `get_object()` keeps them inside their own scope."""
        category = WorkCategory.objects.create(
            company=self.company, name="Sanitair"
        )
        response = self.as_(self.manager).patch(
            ticket_category_url(self.ticket.id),
            {"category": category.id},
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.data)
        self.ticket.refresh_from_db()
        self.assertEqual(self.ticket.category_id, category.id)

    def test_a_manager_of_another_building_cannot_reach_the_melding(self):
        category = WorkCategory.objects.create(
            company=self.company, name="Sanitair"
        )
        response = self.as_(self.other_manager).patch(
            ticket_category_url(self.ticket.id),
            {"category": category.id},
            format="json",
        )
        self.assertEqual(response.status_code, 404, response.data)
