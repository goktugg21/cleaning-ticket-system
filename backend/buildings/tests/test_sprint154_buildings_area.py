"""
Sprint 154 §I.2–§I.6 — the buildings backend surface.

Covers:
  * §I.5 sortable columns, the four annotated counts, the bounded
    `customer_names` preview, and the N+1 guard.
  * §I.5 the inverse read `GET /api/buildings/<id>/customers/`.
  * §I.6 `GET /api/buildings/<id>/summary/`, incl. the 404-not-403 floor.
  * §I.2 `POST /api/buildings/bulk-link/` across all four relations,
    both modes, and the H-1 requirement that a FOREIGN id, a FICTIONAL
    id and a CROSS-COMPANY pair are byte-identical rejections.
  * §I.3 `POST /api/buildings/bulk-deactivate/`.
  * §I.4 `POST /api/buildings/bulk-update/` + `/api/customers/bulk-update/`.
"""
from rest_framework import status
from rest_framework.test import APITestCase

from accounts.models import UserRole
from buildings.models import (
    Building,
    BuildingManagerAssignment,
    BuildingStaffVisibility,
)
from customers.models import (
    Contact,
    ContactBuildingLink,
    Customer,
    CustomerBuildingMembership,
    CustomerUserBuildingAccess,
)
from test_utils import TenantFixtureMixin


LIST_URL = "/api/buildings/"
BULK_LINK_URL = "/api/buildings/bulk-link/"
BULK_DEACTIVATE_URL = "/api/buildings/bulk-deactivate/"
BULK_UPDATE_URL = "/api/buildings/bulk-update/"
CUSTOMER_BULK_UPDATE_URL = "/api/customers/bulk-update/"


def summary_url(building_id):
    return f"/api/buildings/{building_id}/summary/"


def customers_url(building_id):
    return f"/api/buildings/{building_id}/customers/"


class BuildingListTests(TenantFixtureMixin, APITestCase):
    """§I.5 — ordering, counts, and the N+1 guard."""

    def _make_buildings(self, n, prefix):
        return [
            Building.objects.create(
                company=self.company, name=f"{prefix} {i:02d}", city="Amsterdam"
            )
            for i in range(n)
        ]

    def test_ordering_by_name_both_directions(self):
        self._make_buildings(3, "Zed")
        self.authenticate(self.company_admin)

        asc = self.client.get(LIST_URL, {"ordering": "name"})
        self.assertEqual(asc.status_code, status.HTTP_200_OK)
        names = [r["name"] for r in asc.data["results"]]
        self.assertEqual(names, sorted(names))

        desc = self.client.get(LIST_URL, {"ordering": "-name"})
        self.assertEqual([r["name"] for r in desc.data["results"]], list(reversed(names)))

    def test_ordering_by_city_and_postal_code_are_accepted(self):
        self.authenticate(self.company_admin)
        for field in ("city", "postal_code", "is_active"):
            response = self.client.get(LIST_URL, {"ordering": field})
            self.assertEqual(
                response.status_code, status.HTTP_200_OK, f"ordering={field}"
            )

    def test_counts_are_correct(self):
        contact = Contact.objects.create(
            customer=self.customer, full_name="Site Contact"
        )
        ContactBuildingLink.objects.create(contact=contact, building=self.building)
        BuildingStaffVisibility.objects.create(
            user=self.make_user("staff-b@example.com", UserRole.STAFF),
            building=self.building,
        )

        self.authenticate(self.company_admin)
        response = self.client.get(LIST_URL, {"search": self.building.name})
        row = next(r for r in response.data["results"] if r["id"] == self.building.id)
        # The shared fixture links one customer and one manager.
        self.assertEqual(row["customer_count"], 1)
        self.assertEqual(row["manager_count"], 1)
        self.assertEqual(row["staff_count"], 1)
        self.assertEqual(row["contact_count"], 1)

    def test_customer_names_is_bounded_and_carries_the_true_total(self):
        for i in range(5):
            extra = Customer.objects.create(
                company=self.company, name=f"Extra Customer {i}"
            )
            CustomerBuildingMembership.objects.create(
                customer=extra, building=self.building
            )

        self.authenticate(self.company_admin)
        response = self.client.get(LIST_URL, {"search": self.building.name})
        row = next(r for r in response.data["results"] if r["id"] == self.building.id)
        self.assertEqual(row["customer_names"]["total"], 6)
        self.assertLessEqual(
            len(row["customer_names"]["names"]),
            3,
            "customer_names must be bounded — an unbounded cell breaks on real data",
        )

    def _measure(self, params):
        from django.db import connection
        from django.test.utils import CaptureQueriesContext

        with CaptureQueriesContext(connection) as ctx:
            self.client.get(LIST_URL, params)
        return len(ctx.captured_queries)

    def test_two_row_and_ten_row_pages_cost_the_same(self):
        """§I.5's N+1 guard. Four counts + a name preview computed per row
        would make the ten-row page cost ~5 x (10 - 2) = 40 queries more.
        The same guard caught a real pre-existing N+1 last sprint."""
        self.authenticate(self.company_admin)
        for b in self._make_buildings(12, "Bulk"):
            CustomerBuildingMembership.objects.create(
                customer=self.customer, building=b
            )

        # Warm-up, discarded: the first request of a test pays one-off
        # bootstrap costs unrelated to row count.
        self._measure({"page_size": 2, "ordering": "name"})
        two = self._measure({"page_size": 2, "ordering": "name"})
        ten = self._measure({"page_size": 10, "ordering": "name"})

        small = self.client.get(LIST_URL, {"page_size": 2, "ordering": "name"})
        big = self.client.get(LIST_URL, {"page_size": 10, "ordering": "name"})
        self.assertEqual(len(small.data["results"]), 2)
        self.assertEqual(len(big.data["results"]), 10)

        self.assertEqual(
            two,
            ten,
            f"query count grew with page size ({two} -> {ten}); the per-row "
            "counts or the customer_names preview are no longer batched",
        )


class BuildingInverseCustomerReadTests(TenantFixtureMixin, APITestCase):
    """§I.5 — GET /api/buildings/<id>/customers/."""

    def test_lists_the_linked_customers(self):
        self.authenticate(self.company_admin)
        response = self.client.get(customers_url(self.building.id))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        rows = response.data.get("results", response.data)
        self.assertEqual([r["customer"] for r in rows], [self.customer.id])
        # Same row shape as the customer-side read — one serializer.
        self.assertIn("building_name", rows[0])
        self.assertIn("building_city", rows[0])

    def test_cross_tenant_building_404s(self):
        self.authenticate(self.company_admin)
        response = self.client.get(customers_url(self.other_building.id))
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)


class BuildingSummaryTests(TenantFixtureMixin, APITestCase):
    """§I.6."""

    def test_shape_and_counts(self):
        self.authenticate(self.company_admin)
        response = self.client.get(summary_url(self.building.id))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        for key in (
            "room_count",
            "customer_count",
            "manager_count",
            "staff_count",
            "contact_count",
            "ticket_count",
            "open_ticket_count",
            "extra_work_count",
            "open_extra_work_count",
        ):
            self.assertIn(key, response.data, f"missing summary key {key}")
        self.assertEqual(response.data["customer_count"], 1)
        self.assertEqual(response.data["manager_count"], 1)

    def test_room_count_is_null_because_this_system_has_no_rooms(self):
        """Pinned deliberately. There is no Room model anywhere in this
        codebase; the key exists so the contract is stable and the UI
        renders an em dash rather than a misleading 0."""
        self.authenticate(self.company_admin)
        response = self.client.get(summary_url(self.building.id))
        self.assertIsNone(response.data["room_count"])

    def test_cross_tenant_summary_404s_exactly_like_a_nonexistent_id(self):
        self.authenticate(self.company_admin)
        foreign = self.client.get(summary_url(self.other_building.id))
        fictional_id = Building.objects.order_by("-id").first().id + 10_000
        fictional = self.client.get(summary_url(fictional_id))
        self.assertEqual(foreign.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(fictional.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(foreign.json(), fictional.json())


class BuildingBulkLinkTests(TenantFixtureMixin, APITestCase):
    """§I.2 — one endpoint, four relations, both modes."""

    def setUp(self):
        super().setUp()
        self.second_building = Building.objects.create(
            company=self.company, name="Building A2"
        )
        self.second_customer = Customer.objects.create(
            company=self.company, name="Customer A2"
        )
        self.staff = self.make_user("staff-a@example.com", UserRole.STAFF)
        BuildingStaffVisibility.objects.create(
            user=self.staff, building=self.building
        )
        self.contact = Contact.objects.create(
            customer=self.customer, full_name="Contact One"
        )

    def _post(self, **body):
        return self.client.post(BULK_LINK_URL, body, format="json")

    # ---- customers ----------------------------------------------------

    def test_links_n_buildings_to_m_customers_in_one_request(self):
        self.authenticate(self.company_admin)
        response = self._post(
            buildings=[self.building.id, self.second_building.id],
            relation="customers",
            targets=[self.customer.id, self.second_customer.id],
            mode="link",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        # 2x2 = 4 pairs; the fixture already links (building, customer).
        self.assertEqual(response.data["created"], 3)
        self.assertEqual(response.data["already_linked"], 1)
        self.assertEqual(
            CustomerBuildingMembership.objects.filter(
                building__in=[self.building, self.second_building],
                customer__in=[self.customer, self.second_customer],
            ).count(),
            4,
        )

    def test_relinking_is_not_an_error(self):
        self.authenticate(self.company_admin)
        response = self._post(
            buildings=[self.building.id],
            relation="customers",
            targets=[self.customer.id],
            mode="link",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["created"], 0)
        self.assertEqual(response.data["already_linked"], 1)

    def test_unlink_removes_the_row(self):
        self.authenticate(self.company_admin)
        response = self._post(
            buildings=[self.building.id],
            relation="customers",
            targets=[self.customer.id],
            mode="unlink",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["removed"], 1)
        self.assertFalse(
            CustomerBuildingMembership.objects.filter(
                building=self.building, customer=self.customer
            ).exists()
        )

    def test_unlinking_a_customer_cascades_the_per_user_access_revoke(self):
        """The scope-leak guard. An orphaned CustomerUserBuildingAccess row
        still matches the scope subquery, so leaving it behind keeps a
        customer user's visibility on a building their customer is no
        longer linked to."""
        self.assertTrue(
            CustomerUserBuildingAccess.objects.filter(
                membership__customer=self.customer, building=self.building
            ).exists()
        )
        self.authenticate(self.company_admin)
        self._post(
            buildings=[self.building.id],
            relation="customers",
            targets=[self.customer.id],
            mode="unlink",
        )
        self.assertFalse(
            CustomerUserBuildingAccess.objects.filter(
                membership__customer=self.customer, building=self.building
            ).exists(),
            "bulk unlink left an orphaned access row behind",
        )

    def test_unlink_of_an_unlinked_pair_counts_not_linked(self):
        self.authenticate(self.company_admin)
        response = self._post(
            buildings=[self.second_building.id],
            relation="customers",
            targets=[self.second_customer.id],
            mode="unlink",
        )
        self.assertEqual(response.data["removed"], 0)
        self.assertEqual(response.data["not_linked"], 1)

    # ---- the other three relations ------------------------------------

    def test_links_managers(self):
        self.authenticate(self.company_admin)
        response = self._post(
            buildings=[self.second_building.id],
            relation="managers",
            targets=[self.manager.id],
            mode="link",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(
            BuildingManagerAssignment.objects.filter(
                building=self.second_building, user=self.manager
            ).exists()
        )

    def test_links_staff(self):
        self.authenticate(self.company_admin)
        response = self._post(
            buildings=[self.second_building.id],
            relation="staff",
            targets=[self.staff.id],
            mode="link",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(
            BuildingStaffVisibility.objects.filter(
                building=self.second_building, user=self.staff
            ).exists()
        )

    def test_links_contacts(self):
        self.authenticate(self.company_admin)
        response = self._post(
            buildings=[self.building.id],
            relation="contacts",
            targets=[self.contact.id],
            mode="link",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(
            ContactBuildingLink.objects.filter(
                building=self.building, contact=self.contact
            ).exists()
        )

    def test_a_manager_target_must_actually_be_a_building_manager(self):
        self.authenticate(self.company_admin)
        response = self._post(
            buildings=[self.building.id],
            relation="managers",
            targets=[self.staff.id],  # STAFF, not BUILDING_MANAGER
            mode="link",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    # ---- H-1: the three rejections are indistinguishable ---------------

    def test_foreign_and_fictional_target_reject_identically(self):
        """H-1, the property that actually matters: for ONE request
        shape, an id belonging to another tenant and an id that never
        existed must be byte-identical. Anything else lets a caller walk
        integer ids and learn which ones are real.

        Compared side-for-side on purpose. The rejection is keyed on the
        field that failed (`buildings` vs `targets`), which tells the
        caller only which half of their OWN request was bad — something
        they already know by construction, and which is constant across
        the exists/does-not-exist question being probed here.
        """
        self.authenticate(self.company_admin)

        foreign = self._post(
            buildings=[self.building.id],
            relation="customers",
            targets=[self.other_customer.id],
            mode="link",
        )
        fictional_id = Customer.objects.order_by("-id").first().id + 10_000
        fictional = self._post(
            buildings=[self.building.id],
            relation="customers",
            targets=[fictional_id],
            mode="link",
        )
        self.assertEqual(foreign.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(fictional.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(foreign.json(), fictional.json())

    def test_foreign_and_fictional_building_reject_identically(self):
        self.authenticate(self.company_admin)
        foreign = self._post(
            buildings=[self.other_building.id],
            relation="customers",
            targets=[self.customer.id],
            mode="link",
        )
        fictional_id = Building.objects.order_by("-id").first().id + 10_000
        fictional = self._post(
            buildings=[fictional_id],
            relation="customers",
            targets=[self.customer.id],
            mode="link",
        )
        self.assertEqual(foreign.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(fictional.json(), foreign.json())

    def test_cross_company_pair_is_indistinguishable_from_a_fictional_target(self):
        """A SUPER_ADMIN can resolve BOTH ids, so the pair check is what
        rejects. It must read exactly like an unresolvable target — a
        distinguishable answer would confirm that a specific customer id
        exists in some other company."""
        self.authenticate(self.super_admin)

        cross_company = self._post(
            buildings=[self.building.id],
            relation="customers",
            targets=[self.other_customer.id],
            mode="link",
        )
        fictional_id = Customer.objects.order_by("-id").first().id + 10_000
        fictional = self._post(
            buildings=[self.building.id],
            relation="customers",
            targets=[fictional_id],
            mode="link",
        )
        self.assertEqual(cross_company.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(cross_company.json(), fictional.json())

    def test_super_admin_cross_company_pair_is_still_rejected(self):
        """Even a SUPER_ADMIN cannot link a customer to a building of
        another company — the pair is impossible by construction, not a
        permission question."""
        self.authenticate(self.super_admin)
        response = self._post(
            buildings=[self.building.id],
            relation="customers",
            targets=[self.other_customer.id],
            mode="link",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertFalse(
            CustomerBuildingMembership.objects.filter(
                building=self.building, customer=self.other_customer
            ).exists()
        )

    def test_one_bad_target_writes_nothing_at_all(self):
        self.authenticate(self.company_admin)
        before = CustomerBuildingMembership.objects.count()
        response = self._post(
            buildings=[self.building.id, self.second_building.id],
            relation="customers",
            targets=[self.second_customer.id, self.other_customer.id],
            mode="link",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(CustomerBuildingMembership.objects.count(), before)

    def test_building_manager_is_forbidden(self):
        self.authenticate(self.manager)
        response = self._post(
            buildings=[self.building.id],
            relation="customers",
            targets=[self.customer.id],
            mode="link",
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_customer_user_is_forbidden(self):
        self.authenticate(self.customer_user)
        response = self._post(
            buildings=[self.building.id],
            relation="customers",
            targets=[self.customer.id],
            mode="link",
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_unknown_relation_is_rejected(self):
        self.authenticate(self.company_admin)
        response = self._post(
            buildings=[self.building.id],
            relation="invoices",
            targets=[1],
            mode="link",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)


class BuildingBulkDeactivateTests(TenantFixtureMixin, APITestCase):
    """§I.3."""

    def setUp(self):
        super().setUp()
        self.extra = Building.objects.create(company=self.company, name="Extra B")

    def test_deactivates_and_is_not_a_hard_delete(self):
        self.authenticate(self.company_admin)
        response = self.client.post(
            BULK_DEACTIVATE_URL, {"buildings": [self.extra.id]}, format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data, {"deactivated": 1})
        self.extra.refresh_from_db()
        self.assertFalse(self.extra.is_active)
        self.assertTrue(Building.objects.filter(pk=self.extra.id).exists())

    def test_foreign_and_fictional_reject_identically(self):
        self.authenticate(self.company_admin)
        foreign = self.client.post(
            BULK_DEACTIVATE_URL, {"buildings": [self.other_building.id]}, format="json"
        )
        fictional_id = Building.objects.order_by("-id").first().id + 10_000
        fictional = self.client.post(
            BULK_DEACTIVATE_URL, {"buildings": [fictional_id]}, format="json"
        )
        self.assertEqual(foreign.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(foreign.json(), fictional.json())

    def test_one_bad_id_writes_nothing(self):
        self.authenticate(self.company_admin)
        response = self.client.post(
            BULK_DEACTIVATE_URL,
            {"buildings": [self.extra.id, self.other_building.id]},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.extra.refresh_from_db()
        self.assertTrue(self.extra.is_active)


class BulkUpdateTests(TenantFixtureMixin, APITestCase):
    """§I.4 — both bulk-update endpoints."""

    def setUp(self):
        super().setUp()
        self.extra_building = Building.objects.create(
            company=self.company, name="Extra B"
        )
        self.extra_customer = Customer.objects.create(
            company=self.company, name="Extra C"
        )

    def test_building_bulk_update_sets_an_allow_listed_field(self):
        self.authenticate(self.company_admin)
        response = self.client.post(
            BULK_UPDATE_URL,
            {"buildings": [self.extra_building.id], "patch": {"city": "Rotterdam"}},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data, {"updated": 1})
        self.extra_building.refresh_from_db()
        self.assertEqual(self.extra_building.city, "Rotterdam")

    def test_customer_bulk_update_sets_language(self):
        self.authenticate(self.company_admin)
        response = self.client.post(
            CUSTOMER_BULK_UPDATE_URL,
            {"customers": [self.extra_customer.id], "patch": {"language": "en"}},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.extra_customer.refresh_from_db()
        self.assertEqual(self.extra_customer.language, "en")

    def test_a_field_outside_the_allow_list_is_a_400_not_a_silent_skip(self):
        """Silently ignoring it would mean the operator believes an edit
        applied that never did."""
        self.authenticate(self.company_admin)
        response = self.client.post(
            CUSTOMER_BULK_UPDATE_URL,
            {"customers": [self.extra_customer.id], "patch": {"name": "Hijacked"}},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.extra_customer.refresh_from_db()
        self.assertNotEqual(self.extra_customer.name, "Hijacked")

    def test_status_inactive_deactivates(self):
        self.authenticate(self.company_admin)
        response = self.client.post(
            BULK_UPDATE_URL,
            {"buildings": [self.extra_building.id], "patch": {"status": "inactive"}},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.extra_building.refresh_from_db()
        self.assertFalse(self.extra_building.is_active)

    def test_reactivation_is_super_admin_only(self):
        """The bulk door must not do what the single-row door refuses:
        `reactivate` is IsSuperAdmin on both viewsets."""
        self.extra_building.is_active = False
        self.extra_building.save(update_fields=["is_active"])

        self.authenticate(self.company_admin)
        response = self.client.post(
            BULK_UPDATE_URL,
            {"buildings": [self.extra_building.id], "patch": {"status": "active"}},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

        self.authenticate(self.super_admin)
        response = self.client.post(
            BULK_UPDATE_URL,
            {"buildings": [self.extra_building.id], "patch": {"status": "active"}},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.extra_building.refresh_from_db()
        self.assertTrue(self.extra_building.is_active)

    def test_foreign_and_fictional_reject_identically(self):
        self.authenticate(self.company_admin)
        foreign = self.client.post(
            BULK_UPDATE_URL,
            {"buildings": [self.other_building.id], "patch": {"city": "X"}},
            format="json",
        )
        fictional_id = Building.objects.order_by("-id").first().id + 10_000
        fictional = self.client.post(
            BULK_UPDATE_URL,
            {"buildings": [fictional_id], "patch": {"city": "X"}},
            format="json",
        )
        self.assertEqual(foreign.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(foreign.json(), fictional.json())

    def test_empty_patch_is_rejected(self):
        self.authenticate(self.company_admin)
        response = self.client.post(
            BULK_UPDATE_URL,
            {"buildings": [self.extra_building.id], "patch": {}},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_customer_user_is_forbidden(self):
        self.authenticate(self.customer_user)
        response = self.client.post(
            CUSTOMER_BULK_UPDATE_URL,
            {"customers": [self.customer.id], "patch": {"language": "en"}},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
