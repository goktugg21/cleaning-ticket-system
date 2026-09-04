"""W13 — one classification replaces two, and it is filterable and countable.

The owner's father, a programmer of twenty years, used the ticket page
and asked two questions. Both are pinned here as tests:

    "Where is its category? It has to be there. Because you have to show
     all of it -- is it a complaint, a request, a compliment?"

    "The person says, how many tickets did we open in 2026? What are the
     groups of these tickets?"

What these pin, in the order they matter:

  * every company HAS the owner's seven, without anybody pressing a
    button. Starting empty would be a regression from the enum this
    replaces;
  * "Ongegrond" is a VERDICT -- refused at creation by the SERVER, not
    merely hidden by a form, and settable afterwards on the melding;
  * the seven are filterable and countable, including the
    not-yet-classified queue;
  * the endpoints that carry the new fields RENDER them (the Sprint 174
    §0 rule: a filter test issues a query and never serialises a row);
  * `Ticket.type` still gets a coherent value from the category, because
    the pre-existing tickets-by-type report reads it;
  * cross-tenant: a foreign category reads as NONEXISTENT, not
    forbidden (H-1).
"""
from __future__ import annotations

from datetime import date

from rest_framework.test import APITestCase

from companies.models import Company, CompanyUserMembership
from test_utils import TenantFixtureMixin
from tickets.category_seed import (
    LEGACY_TYPE_TO_SLUG,
    TICKET_CATEGORY_SEED,
    seed_rows,
)
from tickets.models import Ticket, TicketCategory

LIST = "/api/tickets/categories/"
TICKETS = "/api/tickets/"
REPORT = "/api/reports/meldingen-by-category/"


def detail(category_id):
    return f"/api/tickets/categories/{category_id}/"


def ticket_category_url(ticket_id):
    return f"/api/tickets/{ticket_id}/category/"


class TicketCategoryFixture(TenantFixtureMixin, APITestCase):
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

    def cat(self, slug, company=None):
        return TicketCategory.objects.get(
            company=company or self.company, slug=slug
        )


class TheOwnersListExistsEverywhere(TicketCategoryFixture):
    def test_every_company_starts_with_the_seven(self):
        """No button to press. A company with no categories would have a
        create form with no classification on it, which is worse than the
        enum this replaces."""
        slugs = list(
            TicketCategory.objects.filter(company=self.company)
            .order_by("sort_order")
            .values_list("slug", flat=True)
        )
        self.assertEqual(
            slugs,
            [
                "verzoek",
                "extra",
                "compliment",
                "melden",
                "storing",
                "ongegrond",
                "klacht",
            ],
        )

    def test_a_company_created_later_gets_them_too(self):
        fresh = Company.objects.create(name="Later BV", slug="later-bv")
        self.assertEqual(
            TicketCategory.objects.filter(company=fresh).count(),
            len(TICKET_CATEGORY_SEED),
        )

    def test_the_seed_is_ordered_ten_apart(self):
        """So a company can slot an eighth in between without
        renumbering the other seven."""
        self.assertEqual(
            [row["sort_order"] for row in seed_rows()],
            [10, 20, 30, 40, 50, 60, 70],
        )

    def test_both_languages_are_filled_for_every_seeded_row(self):
        for row in TicketCategory.objects.filter(company=self.company):
            self.assertTrue(row.label_nl, row.slug)
            self.assertTrue(row.label_en, row.slug)

    def test_the_label_resolver_falls_back_to_dutch(self):
        klacht = self.cat("klacht")
        self.assertEqual(klacht.label_for("en-GB"), "Complaint")
        self.assertEqual(klacht.label_for("nl-NL"), "Klacht")
        self.assertEqual(klacht.label_for(None), "Klacht")
        klacht.label_en = ""
        self.assertEqual(klacht.label_for("en"), "Klacht")

    def test_the_catalog_LIST_renders_every_field_it_promises(self):
        response = self.as_(self.company_admin).get(
            LIST, {"company": self.company.id}
        )
        self.assertEqual(response.status_code, 200, response.data)
        row = next(
            r for r in response.data["results"] if r["slug"] == "klacht"
        )
        for key in (
            "id",
            "company",
            "slug",
            "label",
            "label_nl",
            "label_en",
            "color",
            "sort_order",
            "is_active",
            "available_at_intake",
            "legacy_type",
            "usage_count",
        ):
            self.assertIn(key, row)

    def test_adding_an_eighth_needs_no_deployment(self):
        """The point of a catalog over an enum, stated as a test."""
        created = self.as_(self.company_admin).post(
            LIST,
            {
                "company": self.company.id,
                "slug": "schade",
                "label_nl": "Schade",
                "label_en": "Damage",
                "sort_order": 80,
            },
            format="json",
        )
        self.assertEqual(created.status_code, 201, created.data)
        listed = self.as_(self.company_admin).get(
            LIST, {"company": self.company.id}
        )
        self.assertIn(
            "schade", [r["slug"] for r in listed.data["results"]]
        )


class OngegrondIsAVerdict(TicketCategoryFixture):
    """W13 §4 — nobody raises a melding saying it is unfounded."""

    def test_it_is_in_the_list(self):
        self.assertTrue(
            TicketCategory.objects.filter(
                company=self.company, slug="ongegrond"
            ).exists()
        )

    def test_it_is_not_offered_at_intake(self):
        self.assertFalse(self.cat("ongegrond").available_at_intake)

    def test_the_intake_filter_hides_it_and_keeps_the_other_six(self):
        response = self.as_(self.company_admin).get(
            LIST,
            {"company": self.company.id, "available_at_intake": "true"},
        )
        slugs = [r["slug"] for r in response.data["results"]]
        self.assertNotIn("ongegrond", slugs)
        self.assertEqual(len(slugs), 6)

    def test_the_SERVER_refuses_it_at_creation(self):
        """The reference system does the modal and skips the
        enforcement. This is the enforcement."""
        response = self.as_(self.company_admin).post(
            TICKETS,
            self.create_ticket_payload(category=self.cat("ongegrond").id),
            format="json",
        )
        self.assertEqual(response.status_code, 400, response.data)
        self.assertIn("category", response.data)

    def test_a_customer_is_refused_it_too(self):
        response = self.as_(self.customer_user).post(
            TICKETS,
            self.create_ticket_payload(category=self.cat("ongegrond").id),
            format="json",
        )
        self.assertEqual(response.status_code, 400, response.data)

    def test_but_it_CAN_be_reached_afterwards(self):
        """Which is the whole distinction: a verdict is reached by
        reading the melding, on the melding's own page."""
        response = self.as_(self.company_admin).patch(
            ticket_category_url(self.ticket.id),
            {"category": self.cat("ongegrond").id},
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.data)
        self.ticket.refresh_from_db()
        self.assertEqual(self.ticket.category.slug, "ongegrond")

    def test_an_archived_category_is_refused_at_creation_the_same_way(self):
        archived = self.cat("compliment")
        archived.is_active = False
        archived.save(update_fields=["is_active"])
        response = self.as_(self.company_admin).post(
            TICKETS,
            self.create_ticket_payload(category=archived.id),
            format="json",
        )
        self.assertEqual(response.status_code, 400, response.data)


class TheLegacyTypeBridge(TicketCategoryFixture):
    def test_creating_with_a_category_derives_the_type(self):
        """`Ticket.type` is superseded and no screen offers it, but the
        column is NOT NULL and the tickets-by-type report reads it. A
        create that left it at the model default would file every new
        melding as a REPORT."""
        payload = self.create_ticket_payload(category=self.cat("klacht").id)
        payload.pop("type")
        response = self.as_(self.company_admin).post(
            TICKETS, payload, format="json"
        )
        self.assertEqual(response.status_code, 201, response.data)
        created = Ticket.objects.get(id=response.data["id"])
        self.assertEqual(created.category.slug, "klacht")
        self.assertEqual(created.type, "COMPLAINT")

    def test_an_explicitly_sent_type_still_wins(self):
        """The API contract is unchanged for callers still sending one."""
        payload = self.create_ticket_payload(
            category=self.cat("klacht").id, type="REQUEST"
        )
        response = self.as_(self.company_admin).post(
            TICKETS, payload, format="json"
        )
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(
            Ticket.objects.get(id=response.data["id"]).type, "REQUEST"
        )

    def test_a_customer_melding_stays_a_REPORT_whatever_it_is_categorised(self):
        """M7's invariant, which the M6 meldingen split reads. The
        category is the richer classification; `type` is the legacy
        split and must not move."""
        payload = self.create_ticket_payload(category=self.cat("klacht").id)
        payload.pop("type")
        response = self.as_(self.customer_user).post(
            TICKETS, payload, format="json"
        )
        self.assertEqual(response.status_code, 201, response.data)
        created = Ticket.objects.get(id=response.data["id"])
        self.assertEqual(created.type, "REPORT")
        self.assertEqual(created.category.slug, "klacht")

    def test_every_mappable_legacy_type_has_a_seeded_home(self):
        seeded = {row["slug"] for row in TICKET_CATEGORY_SEED}
        for legacy_type, slug in LEGACY_TYPE_TO_SLUG.items():
            self.assertIn(slug, seeded, legacy_type)

    def test_suggestion_and_other_are_deliberately_unmapped(self):
        """Neither has a home in the owner's seven, and inventing one
        would be the migration classifying meldingen the owner did not.
        They land uncategorised, which is a state somebody can clear."""
        self.assertNotIn("SUGGESTION", LEGACY_TYPE_TO_SLUG)
        self.assertNotIn("OTHER", LEGACY_TYPE_TO_SLUG)


class TheCategoryIsVisibleAndFilterable(TicketCategoryFixture):
    def test_the_ticket_LIST_renders_the_category_its_slug_and_colour(self):
        klacht = self.cat("klacht")
        self.ticket.category = klacht
        self.ticket.save(update_fields=["category"])
        response = self.as_(self.company_admin).get(TICKETS)
        row = next(
            r for r in response.data["results"] if r["id"] == self.ticket.id
        )
        self.assertEqual(row["category"], klacht.id)
        self.assertEqual(row["category_name"], "Klacht")
        self.assertEqual(row["category_slug"], "klacht")
        self.assertEqual(row["category_color"], klacht.color)

    def test_an_uncategorised_melding_renders_nulls_not_missing_keys(self):
        response = self.as_(self.company_admin).get(TICKETS)
        row = next(
            r for r in response.data["results"] if r["id"] == self.ticket.id
        )
        self.assertIsNone(row["category"])
        self.assertIsNone(row["category_name"])
        self.assertIsNone(row["category_slug"])
        self.assertIsNone(row["category_color"])

    def test_the_ticket_DETAIL_renders_them_too(self):
        self.ticket.category = self.cat("storing")
        self.ticket.save(update_fields=["category"])
        response = self.as_(self.company_admin).get(
            f"/api/tickets/{self.ticket.id}/"
        )
        self.assertEqual(response.data["category_name"], "Storing")
        self.assertEqual(response.data["category_slug"], "storing")

    def test_the_english_reader_gets_the_english_label(self):
        """W14 §1 — "the English reader" is the reader whose LANGUAGE is
        English, not the one whose browser happens to be.

        This test previously set `HTTP_ACCEPT_LANGUAGE="en-GB"` and
        asserted "Complaint". It passed, and it was asserting the
        defect: nothing in `frontend/src` sets `Accept-Language`, so the
        value the serializer read was the BROWSER's locale, and the
        owner's Dutch operator on a Dutch page in an English-locale
        browser was served English labels on every ticket row.
        `user.language` is the app's language -- the same field
        `i18n/useLanguageSync.ts` reads from `/auth/me/` and hands to
        i18next -- so it is the only value that can agree with the rest
        of the page. See `serializers_ticket_categories.reader_language`.
        """
        self.ticket.category = self.cat("klacht")
        self.ticket.save(update_fields=["category"])
        self.company_admin.language = "en"
        self.company_admin.save(update_fields=["language"])
        response = self.as_(self.company_admin).get(
            f"/api/tickets/{self.ticket.id}/"
        )
        self.assertEqual(response.data["category_name"], "Complaint")

    def test_the_browsers_locale_does_not_override_the_users_language(self):
        """W14 §1 — the owner's report, locked down.

        A Dutch operator reading a Dutch page from an English-locale
        browser gets Dutch. The header is present and is ignored,
        because the reader already told us what language they read in.
        """
        self.ticket.category = self.cat("klacht")
        self.ticket.save(update_fields=["category"])
        self.assertEqual(self.company_admin.language, "nl")
        self.client.force_authenticate(user=self.company_admin)
        response = self.client.get(
            f"/api/tickets/{self.ticket.id}/", HTTP_ACCEPT_LANGUAGE="en-GB"
        )
        self.assertEqual(response.data["category_name"], "Klacht")

    def test_the_list_and_the_picker_name_one_row_the_same_way(self):
        """W14 §1 — the defect was that they did not.

        W13-FIX moved the CATALOG serializer onto `user.language` and
        left `TicketCategoryFieldsMixin` reading the header, so on one
        screen the picker said "Malfunction" while the chip beside it
        said "Storing". One resolver now, so this cannot come back
        without failing here.
        """
        klacht = self.cat("klacht")
        self.ticket.category = klacht
        self.ticket.save(update_fields=["category"])
        self.company_admin.language = "en"
        self.company_admin.save(update_fields=["language"])

        detail = self.as_(self.company_admin).get(
            f"/api/tickets/{self.ticket.id}/"
        )
        listing = self.as_(self.company_admin).get(TICKETS)
        row = next(
            r for r in listing.data["results"] if r["id"] == self.ticket.id
        )
        catalog = self.as_(self.company_admin).get(
            f"{LIST}?company={self.company.id}"
        )
        picker = next(
            c for c in catalog.data["results"] if c["id"] == klacht.id
        )

        self.assertEqual(detail.data["category_name"], "Complaint")
        self.assertEqual(row["category_name"], "Complaint")
        self.assertEqual(picker["label"], "Complaint")

    def test_filtering_by_one_category_narrows_to_it(self):
        self.ticket.category = self.cat("klacht")
        self.ticket.save(update_fields=["category"])
        Ticket.objects.create(
            company=self.company,
            building=self.building,
            customer=self.customer,
            created_by=self.customer_user,
            title="Untagged",
            description="No category",
        )
        response = self.as_(self.company_admin).get(
            TICKETS, {"category": self.cat("klacht").id}
        )
        self.assertEqual(
            [r["id"] for r in response.data["results"]], [self.ticket.id]
        )

    def test_the_not_yet_classified_queue_is_listable(self):
        """The list an operator actually works through."""
        self.ticket.category = self.cat("melden")
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
            TICKETS, {"category__isnull": "true"}
        )
        self.assertEqual(
            [r["id"] for r in response.data["results"]], [untagged.id]
        )


class TheGroupsQuestion(TicketCategoryFixture):
    """"How many tickets did we open in 2026? What are the groups?\""""

    def setUp(self):
        super().setUp()
        self.ticket.category = self.cat("klacht")
        self.ticket.save(update_fields=["category"])
        for _ in range(2):
            Ticket.objects.create(
                company=self.company,
                building=self.building,
                customer=self.customer,
                created_by=self.customer_user,
                title="Verzoekje",
                description="x",
                category=self.cat("verzoek"),
            )
        Ticket.objects.create(
            company=self.company,
            building=self.building,
            customer=self.customer,
            created_by=self.customer_user,
            title="Untagged",
            description="x",
        )

    def _report(self):
        today = date.today()
        return self.as_(self.company_admin).get(
            REPORT,
            {
                "from": today.replace(month=1, day=1).isoformat(),
                "to": today.replace(month=12, day=31).isoformat(),
                "company": self.company.id,
            },
        )

    def test_the_groups_are_answered_in_one_list(self):
        response = self._report()
        self.assertEqual(response.status_code, 200, response.data)
        counts = {
            row["category_slug"]: row["count"]
            for row in response.data["categories"]
        }
        self.assertEqual(counts["klacht"], 1)
        self.assertEqual(counts["verzoek"], 2)
        # Uncategorised is a GROUP, not a gap: dropping it would make the
        # total disagree with the number of meldingen in the period.
        self.assertEqual(counts[None], 1)

    def test_the_groups_add_up_to_the_total(self):
        response = self._report()
        self.assertEqual(
            sum(row["count"] for row in response.data["categories"]),
            response.data["total"],
        )

    def test_the_groups_carry_their_colour_so_the_report_can_show_them(self):
        response = self._report()
        klacht_row = next(
            r for r in response.data["categories"] if r["category_slug"] == "klacht"
        )
        self.assertEqual(klacht_row["category_color"], self.cat("klacht").color)

    def test_the_per_building_breakdown_still_works(self):
        response = self._report()
        bucket = next(
            b
            for b in response.data["buildings"]
            if b["building"] == self.building.id
        )
        self.assertEqual(bucket["total"], 4)


class TheCatalogRules(TicketCategoryFixture):
    def test_the_same_dutch_label_twice_in_one_company_is_refused(self):
        response = self.as_(self.company_admin).post(
            LIST,
            {
                "company": self.company.id,
                "slug": "klacht-2",
                "label_nl": "Klacht",
                "label_en": "Complaint again",
            },
            format="json",
        )
        self.assertEqual(response.status_code, 400, response.data)

    def test_case_and_whitespace_do_not_make_it_a_different_label(self):
        response = self.as_(self.company_admin).post(
            LIST,
            {
                "company": self.company.id,
                "slug": "klacht-3",
                "label_nl": "  kLaChT ",
                "label_en": "x",
            },
            format="json",
        )
        self.assertEqual(response.status_code, 400, response.data)

    def test_the_same_slug_twice_in_one_company_is_refused(self):
        response = self.as_(self.company_admin).post(
            LIST,
            {
                "company": self.company.id,
                "slug": "klacht",
                "label_nl": "Andere klacht",
                "label_en": "x",
            },
            format="json",
        )
        self.assertEqual(response.status_code, 400, response.data)

    def test_two_companies_may_each_have_the_same_slug(self):
        """Which every company does, since they are all seeded."""
        self.assertTrue(
            TicketCategory.objects.filter(
                company=self.other_company, slug="klacht"
            ).exists()
        )

    def test_a_bad_colour_is_refused_rather_than_silently_ignored(self):
        response = self.as_(self.company_admin).patch(
            detail(self.cat("klacht").id),
            {"color": "red"},
            format="json",
        )
        self.assertEqual(response.status_code, 400, response.data)

    def test_a_category_in_use_cannot_be_deleted(self):
        self.ticket.category = self.cat("klacht")
        self.ticket.save(update_fields=["category"])
        response = self.as_(self.company_admin).delete(
            detail(self.cat("klacht").id)
        )
        self.assertEqual(response.status_code, 400, response.data)
        self.assertEqual(response.data["code"], "ticket_category_in_use")

    def test_an_unused_category_can_be_deleted(self):
        response = self.as_(self.company_admin).delete(
            detail(self.cat("compliment").id)
        )
        self.assertEqual(response.status_code, 204)

    def test_archiving_keeps_it_on_the_meldingen_that_carry_it(self):
        klacht = self.cat("klacht")
        self.ticket.category = klacht
        self.ticket.save(update_fields=["category"])
        self.as_(self.company_admin).patch(
            detail(klacht.id), {"is_active": False}, format="json"
        )
        self.ticket.refresh_from_db()
        self.assertEqual(self.ticket.category_id, klacht.id)

    def test_usage_count_counts_the_meldingen_carrying_it(self):
        self.ticket.category = self.cat("klacht")
        self.ticket.save(update_fields=["category"])
        response = self.as_(self.company_admin).get(
            LIST, {"company": self.company.id}
        )
        row = next(
            r for r in response.data["results"] if r["slug"] == "klacht"
        )
        self.assertEqual(row["usage_count"], 1)


class TenantIsolation(TicketCategoryFixture):
    def test_a_company_admin_does_not_see_another_companys_categories(self):
        response = self.as_(self.company_admin).get(LIST)
        company_ids = {r["company"] for r in response.data["results"]}
        self.assertEqual(company_ids, {self.company.id})

    def test_a_company_admin_cannot_create_in_another_company(self):
        response = self.as_(self.company_admin).post(
            LIST,
            {
                "company": self.other_company.id,
                "slug": "smokkel",
                "label_nl": "Smokkel",
                "label_en": "x",
            },
            format="json",
        )
        self.assertEqual(response.status_code, 403, response.data)

    def test_a_foreign_category_reads_as_nonexistent_when_creating(self):
        """H-1: nonexistent, never forbidden — a permission error is an
        existence oracle."""
        foreign = self.cat("klacht", company=self.other_company)
        response = self.as_(self.company_admin).post(
            TICKETS,
            self.create_ticket_payload(category=foreign.id),
            format="json",
        )
        self.assertEqual(response.status_code, 400, response.data)

    def test_a_customer_user_gets_nothing_from_the_catalog(self):
        response = self.as_(self.customer_user).get(LIST)
        self.assertEqual(len(response.data["results"]), 0)

    def test_a_customer_user_cannot_recategorise_a_melding(self):
        response = self.as_(self.customer_user).patch(
            ticket_category_url(self.ticket.id),
            {"category": self.cat("klacht").id},
            format="json",
        )
        self.assertIn(response.status_code, (403, 404))
