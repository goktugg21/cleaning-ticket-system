"""
Sprint 178 §1 — the building-type catalog, and the filter that is its point.

The owner's requirement, in his own words:

    Ramazan may want one building to be of type "health building" even
    though no other building uses it — but it should still appear in the
    filters.

So the test that matters most here is not "can a type be created" — it is
`test_a_type_only_one_building_uses_still_filters`. A catalog whose values
do not reach the list filter is a dropdown, not a taxonomy, and adding a
type must never need a deployment.

What these pin:

  * a company invents a type, tags ONE building, and filtering the
    buildings list by it returns exactly that building;
  * uniqueness is per company and case/whitespace-insensitive — two
    providers may both have "Kantoor", one provider may not have it
    twice, and " kantoor " is the same name;
  * a type in use cannot be deleted, because `Building.building_type` is
    SET_NULL and a delete would silently untag buildings. Archive is the
    supported way to stop offering one;
  * **the endpoints that carry the new fields are RENDERED** — the Sprint
    174 §0 rule. A missing `fields` entry took the whole Extra Work page
    down in Sprint 173 and no filter test would have caught it;
  * cross-tenant: a company admin cannot read, write or tag with another
    company's types.
"""
from __future__ import annotations

from rest_framework import status
from rest_framework.test import APITestCase

from buildings.models import Building, BuildingType
from companies.models import CompanyUserMembership
from test_utils import TenantFixtureMixin

LIST = "/api/buildings/types/"


class BuildingTypeCatalogTests(TenantFixtureMixin, APITestCase):
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
    # The owner's example, end to end
    # ------------------------------------------------------------------
    def test_a_type_only_one_building_uses_still_filters(self):
        """THE test. One company, one bespoke type, one building."""
        created = self.as_(self.company_admin).post(
            LIST,
            {"company": self.company.id, "name": "Health building"},
            format="json",
        )
        self.assertEqual(created.status_code, 201, created.data)
        type_id = created.data["id"]

        # A second, untagged building so the filter has something to
        # exclude — a filter test where everything matches proves nothing.
        Building.objects.create(
            company=self.company, name="Untagged", address="x"
        )
        self.building.building_type_id = type_id
        self.building.save(update_fields=["building_type"])

        response = self.as_(self.company_admin).get(
            "/api/buildings/", {"building_type": type_id}
        )
        self.assertEqual(response.status_code, 200, response.data)
        rows = response.data["results"]
        self.assertEqual([row["id"] for row in rows], [self.building.id])

    def test_adding_a_type_needs_no_deployment(self):
        """Stated as a test because it is the acceptance criterion: the
        type is created through the API and is immediately offerable and
        filterable, with no code change and no restart."""
        before = self.as_(self.company_admin).get(
            LIST, {"company": self.company.id}
        )
        self.assertEqual(len(before.data["results"]), 0)
        self.as_(self.company_admin).post(
            LIST,
            {"company": self.company.id, "name": "Zorggebouw"},
            format="json",
        )
        after = self.as_(self.company_admin).get(
            LIST, {"company": self.company.id}
        )
        self.assertEqual(
            [row["name"] for row in after.data["results"]], ["Zorggebouw"]
        )

    # ------------------------------------------------------------------
    # Sprint 174 §0 — render the endpoints that carry the new fields
    # ------------------------------------------------------------------
    def test_the_building_LIST_renders_the_type_and_its_name(self):
        building_type = BuildingType.objects.create(
            company=self.company, name="Kantoor"
        )
        self.building.building_type = building_type
        self.building.save(update_fields=["building_type"])

        response = self.as_(self.company_admin).get("/api/buildings/")
        self.assertEqual(response.status_code, 200, response.data)
        row = next(
            r for r in response.data["results"] if r["id"] == self.building.id
        )
        for key in ("building_type", "building_type_name"):
            with self.subTest(key=key):
                self.assertIn(key, row)
        self.assertEqual(row["building_type"], building_type.id)
        self.assertEqual(row["building_type_name"], "Kantoor")

    def test_the_building_DETAIL_renders_the_type_and_its_name(self):
        building_type = BuildingType.objects.create(
            company=self.company, name="Kantoor"
        )
        self.building.building_type = building_type
        self.building.save(update_fields=["building_type"])

        response = self.as_(self.company_admin).get(
            f"/api/buildings/{self.building.id}/"
        )
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["building_type"], building_type.id)
        self.assertEqual(response.data["building_type_name"], "Kantoor")

    def test_an_unclassified_building_renders_null_not_a_missing_key(self):
        """The keys are always present. A client that has to distinguish
        "absent" from "null" is a client that will get it wrong."""
        response = self.as_(self.company_admin).get(
            f"/api/buildings/{self.building.id}/"
        )
        self.assertIn("building_type", response.data)
        self.assertIn("building_type_name", response.data)
        self.assertIsNone(response.data["building_type"])
        self.assertIsNone(response.data["building_type_name"])

    def test_the_catalog_LIST_renders_every_field_it_promises(self):
        BuildingType.objects.create(company=self.company, name="Kantoor")
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
        ):
            with self.subTest(key=key):
                self.assertIn(key, row)

    def test_usage_count_counts_the_buildings_carrying_it(self):
        building_type = BuildingType.objects.create(
            company=self.company, name="Kantoor"
        )
        self.building.building_type = building_type
        self.building.save(update_fields=["building_type"])
        response = self.as_(self.company_admin).get(
            LIST, {"company": self.company.id}
        )
        self.assertEqual(response.data["results"][0]["usage_count"], 1)

    # ------------------------------------------------------------------
    # Uniqueness
    # ------------------------------------------------------------------
    def test_the_same_name_twice_in_one_company_is_refused(self):
        payload = {"company": self.company.id, "name": "Kantoor"}
        self.as_(self.company_admin).post(LIST, payload, format="json")
        again = self.as_(self.company_admin).post(LIST, payload, format="json")
        self.assertEqual(again.status_code, 400, again.data)

    def test_case_and_whitespace_do_not_make_it_a_different_name(self):
        self.as_(self.company_admin).post(
            LIST, {"company": self.company.id, "name": "Kantoor"}, format="json"
        )
        again = self.as_(self.company_admin).post(
            LIST,
            {"company": self.company.id, "name": "  kANTOOR  "},
            format="json",
        )
        self.assertEqual(again.status_code, 400, again.data)

    def test_two_companies_may_each_have_the_same_name(self):
        self.as_(self.company_admin).post(
            LIST, {"company": self.company.id, "name": "Kantoor"}, format="json"
        )
        other = self.as_(self.other_company_admin).post(
            LIST,
            {"company": self.other_company.id, "name": "Kantoor"},
            format="json",
        )
        self.assertEqual(other.status_code, 201, other.data)

    def test_the_stored_name_is_trimmed(self):
        response = self.as_(self.company_admin).post(
            LIST,
            {"company": self.company.id, "name": "  Kantoor  "},
            format="json",
        )
        self.assertEqual(response.data["name"], "Kantoor")

    # ------------------------------------------------------------------
    # Delete vs archive
    # ------------------------------------------------------------------
    def test_a_type_in_use_cannot_be_deleted(self):
        building_type = BuildingType.objects.create(
            company=self.company, name="Kantoor"
        )
        self.building.building_type = building_type
        self.building.save(update_fields=["building_type"])
        response = self.as_(self.company_admin).delete(
            f"{LIST}{building_type.id}/"
        )
        self.assertEqual(response.status_code, 400, response.data)
        self.assertEqual(response.data["code"], "building_type_in_use")
        self.building.refresh_from_db()
        self.assertEqual(self.building.building_type_id, building_type.id)

    def test_an_unused_type_can_be_deleted(self):
        building_type = BuildingType.objects.create(
            company=self.company, name="Mistake"
        )
        response = self.as_(self.company_admin).delete(
            f"{LIST}{building_type.id}/"
        )
        self.assertEqual(response.status_code, 204, response.data)

    def test_archiving_keeps_it_on_the_buildings_that_carry_it(self):
        building_type = BuildingType.objects.create(
            company=self.company, name="Kantoor"
        )
        self.building.building_type = building_type
        self.building.save(update_fields=["building_type"])
        response = self.as_(self.company_admin).patch(
            f"{LIST}{building_type.id}/", {"is_active": False}, format="json"
        )
        self.assertEqual(response.status_code, 200, response.data)
        self.building.refresh_from_db()
        self.assertEqual(self.building.building_type_id, building_type.id)

    # ------------------------------------------------------------------
    # Tenancy
    # ------------------------------------------------------------------
    def test_a_company_admin_does_not_see_another_companys_types(self):
        BuildingType.objects.create(company=self.other_company, name="Secret")
        response = self.as_(self.company_admin).get(LIST)
        self.assertEqual(
            [row["name"] for row in response.data["results"]], []
        )

    def test_a_company_admin_cannot_create_in_another_company(self):
        response = self.as_(self.company_admin).post(
            LIST,
            {"company": self.other_company.id, "name": "Trespass"},
            format="json",
        )
        self.assertEqual(response.status_code, 403, response.data)
        self.assertFalse(
            BuildingType.objects.filter(name="Trespass").exists()
        )

    def test_a_company_admin_cannot_edit_another_companys_type(self):
        foreign = BuildingType.objects.create(
            company=self.other_company, name="Theirs"
        )
        response = self.as_(self.company_admin).patch(
            f"{LIST}{foreign.id}/", {"name": "Mine now"}, format="json"
        )
        # 404 through the read scope is the correct answer, and 403 is
        # acceptable — what must NOT happen is a 200.
        self.assertIn(response.status_code, (403, 404), response.data)
        foreign.refresh_from_db()
        self.assertEqual(foreign.name, "Theirs")

    def test_a_customer_user_gets_nothing(self):
        BuildingType.objects.create(company=self.company, name="Kantoor")
        response = self.as_(self.customer_user).get(LIST)
        self.assertEqual(
            [row["name"] for row in response.data["results"]], []
        )

    def test_a_super_admin_sees_every_company(self):
        BuildingType.objects.create(company=self.company, name="A type")
        BuildingType.objects.create(company=self.other_company, name="B type")
        response = self.as_(self.super_admin).get(LIST)
        names = {row["name"] for row in response.data["results"]}
        self.assertEqual(names, {"A type", "B type"})


class BuildingTypeQueryCountTests(TenantFixtureMixin, APITestCase):
    """The usage count is annotated for the page, not counted per row."""

    def setUp(self):
        super().setUp()
        CompanyUserMembership.objects.get_or_create(
            user=self.company_admin, company=self.company
        )

    def test_more_rows_do_not_cost_more_queries(self):
        self.client.force_authenticate(user=self.company_admin)
        for index in range(2):
            BuildingType.objects.create(
                company=self.company, name=f"Type {index}"
            )
        with self.assertNumQueries(3) as small:
            self.client.get(LIST, {"company": self.company.id})
        for index in range(2, 12):
            BuildingType.objects.create(
                company=self.company, name=f"Type {index}"
            )
        with self.assertNumQueries(len(small.captured_queries)):
            self.client.get(LIST, {"company": self.company.id})
