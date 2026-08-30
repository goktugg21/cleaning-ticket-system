"""
P-6 V4 — `GET /api/search/?q=` — the global search box's one endpoint.

Five groups of at most five rows each, every group scoped by the SAME
helper the corresponding list endpoint already uses. The security tests
here are the point: an out-of-scope record is simply absent from the
answer (H-1/H-2), a STAFF viewer's extra-work group is always empty
(`scope_extra_work_for` returns `.none()` for STAFF by design), and only
SUPER_ADMIN / COMPANY_ADMIN ever see a person.
"""
from __future__ import annotations

from rest_framework import status
from rest_framework.test import APITestCase

from accounts.models import UserRole
from buildings.models import Building, BuildingStaffVisibility
from extra_work.models import ExtraWorkRequest
from test_utils import TenantFixtureMixin
from tickets.models import Ticket

URL = "/api/search/"
GROUPS = ("tickets", "extra_work", "customers", "buildings", "people")
LIMIT = 5


class GlobalSearchTests(TenantFixtureMixin, APITestCase):
    def search(self, q):
        response = self.client.get(URL, {"q": q})
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        return response

    def ids(self, response, group):
        return [row["id"] for row in response.data["groups"][group]]

    def make_extra_work(self, title, *, company=None, building=None, customer=None):
        return ExtraWorkRequest.objects.create(
            company=company or self.company,
            building=building or self.building,
            customer=customer or self.customer,
            created_by=self.manager,
            title=title,
            description="",
        )

    def make_ticket(self, title, *, company=None, building=None, customer=None):
        return Ticket.objects.create(
            company=company or self.company,
            building=building or self.building,
            customer=customer or self.customer,
            created_by=self.customer_user,
            title=title,
            description="Search fixture",
        )

    # 1. The door -------------------------------------------------------

    def test_anonymous_is_refused(self):
        response = self.client.get(URL, {"q": "Ticket"})
        self.assertIn(
            response.status_code,
            (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN),
        )

    def test_query_too_short_is_400(self):
        self.authenticate(self.super_admin)
        for q in ("", "a", "  b  "):
            with self.subTest(q=q):
                response = self.client.get(URL, {"q": q})
                self.assertEqual(
                    response.status_code, status.HTTP_400_BAD_REQUEST, response.data
                )
                self.assertEqual(response.data["code"], "query_too_short")
                self.assertIsInstance(response.data["detail"], str)
                self.assertTrue(response.data["detail"])
        response = self.client.get(URL)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data["code"], "query_too_short")

    # 2. Tickets, H-1 ---------------------------------------------------

    def test_company_admin_cannot_find_the_other_company_ticket_number(self):
        self.authenticate(self.company_admin)
        response = self.search(self.other_ticket.ticket_no)
        self.assertEqual(self.ids(response, "tickets"), [])
        self.assertEqual(response.data["q"], self.other_ticket.ticket_no)

    def test_company_admin_finds_own_ticket_by_number_fragment_and_title(self):
        self.authenticate(self.company_admin)
        # "TCK-2026-000042" -> "000042": the bare digits the user types.
        fragment = self.ticket.ticket_no[-6:]
        response = self.search(fragment)
        self.assertEqual(self.ids(response, "tickets"), [self.ticket.id])
        row = response.data["groups"]["tickets"][0]
        self.assertEqual(
            set(row),
            {
                "id",
                "ticket_no",
                "title",
                "status",
                "display_phase",
                "customer_name",
                "building_name",
            },
        )
        self.assertEqual(row["ticket_no"], self.ticket.ticket_no)
        self.assertEqual(row["title"], "Ticket A")
        self.assertEqual(row["status"], self.ticket.status)
        self.assertIsInstance(row["display_phase"], str)
        self.assertEqual(row["customer_name"], "Customer A")
        self.assertEqual(row["building_name"], "Building A")

        response = self.search("Ticket A")
        self.assertEqual(self.ids(response, "tickets"), [self.ticket.id])

    # 3. Super admin ----------------------------------------------------

    def test_super_admin_finds_both_tickets_by_a_common_title_word(self):
        self.authenticate(self.super_admin)
        response = self.search("Ticket")
        self.assertEqual(
            set(self.ids(response, "tickets")),
            {self.ticket.id, self.other_ticket.id},
        )
        # Ordered -id: the newest first.
        self.assertEqual(
            self.ids(response, "tickets"), [self.other_ticket.id, self.ticket.id]
        )

    # 4. Customer user --------------------------------------------------

    def test_customer_user_sees_own_ticket_own_customer_and_nobody(self):
        self.authenticate(self.customer_user)
        response = self.search("Ticket")
        self.assertEqual(self.ids(response, "tickets"), [self.ticket.id])

        response = self.search("Customer")
        self.assertEqual(self.ids(response, "customers"), [self.customer.id])
        self.assertEqual(
            response.data["groups"]["customers"][0],
            {"id": self.customer.id, "name": "Customer A", "company_name": "Company A"},
        )

        # Every fixture email contains "example"; a customer user
        # administers nobody, so the people group stays empty.
        response = self.search("example")
        self.assertEqual(self.ids(response, "people"), [])

    # 5. STAFF ----------------------------------------------------------

    def test_staff_gets_an_empty_extra_work_group(self):
        staff = self.make_user("staff-a@example.com", UserRole.STAFF)
        BuildingStaffVisibility.objects.create(user=staff, building=self.building)
        self.make_extra_work("Hidden from staff")

        self.authenticate(staff)
        response = self.search("Hidden")
        self.assertEqual(self.ids(response, "extra_work"), [])
        # The building-wide visibility row does make the ticket visible,
        # so the empty extra-work group is the STAFF rule, not an empty
        # scope in general.
        response = self.search("Ticket")
        self.assertEqual(self.ids(response, "tickets"), [self.ticket.id])
        self.assertEqual(self.ids(response, "people"), [])

    # 6. Shape and truncation -------------------------------------------

    def test_every_group_is_present_and_truncation_flags_the_sixth_row(self):
        self.authenticate(self.company_admin)
        response = self.search("nothing-matches-this")
        self.assertEqual(response.data["limit"], LIMIT)
        self.assertEqual(response.data["q"], "nothing-matches-this")
        self.assertEqual(set(response.data["groups"]), set(GROUPS))
        self.assertEqual(set(response.data["truncated"]), set(GROUPS))
        for group in GROUPS:
            self.assertEqual(response.data["groups"][group], [])
            self.assertIs(response.data["truncated"][group], False)

        extra = [self.make_ticket(f"Shape ticket {n}") for n in range(LIMIT + 1)]
        response = self.search("  Shape ticket  ")
        self.assertEqual(response.data["q"], "Shape ticket")
        rows = self.ids(response, "tickets")
        self.assertEqual(len(rows), LIMIT)
        # Ordered -id: the five newest, newest first; the oldest is cut.
        self.assertEqual(rows, [t.id for t in reversed(extra)][:LIMIT])
        self.assertIs(response.data["truncated"]["tickets"], True)
        for group in GROUPS:
            if group != "tickets":
                self.assertIs(response.data["truncated"][group], False)

        # Exactly five matches is not truncated.
        Ticket.objects.filter(pk=extra[0].pk).delete()
        response = self.search("Shape ticket")
        self.assertEqual(len(self.ids(response, "tickets")), LIMIT)
        self.assertIs(response.data["truncated"]["tickets"], False)

    # 7. Buildings, customers, people -----------------------------------

    def test_buildings_match_by_city_within_scope(self):
        Building.objects.filter(pk=self.building.pk).update(city="Rotterdam")
        Building.objects.filter(pk=self.other_building.pk).update(city="Rotterdam")

        self.authenticate(self.company_admin)
        response = self.search("rotter")
        self.assertEqual(self.ids(response, "buildings"), [self.building.id])
        self.assertEqual(
            response.data["groups"]["buildings"][0],
            {
                "id": self.building.id,
                "name": "Building A",
                "city": "Rotterdam",
                "company_name": "Company A",
            },
        )
        # By name too; the other company's "Building B" is absent.
        response = self.search("Building")
        self.assertEqual(self.ids(response, "buildings"), [self.building.id])

        self.authenticate(self.super_admin)
        response = self.search("Rotterdam")
        self.assertEqual(
            self.ids(response, "buildings"),
            [self.building.id, self.other_building.id],
        )

    def test_customers_match_by_name_within_scope(self):
        self.authenticate(self.company_admin)
        response = self.search("customer")
        self.assertEqual(self.ids(response, "customers"), [self.customer.id])

        self.authenticate(self.other_company_admin)
        response = self.search("Customer A")
        self.assertEqual(self.ids(response, "customers"), [])

    def test_people_are_the_manageable_users_only(self):
        self.authenticate(self.company_admin)
        # self.manager is attached to Company A through a building
        # assignment; found by an email fragment.
        response = self.search("manager-a")
        self.assertEqual(self.ids(response, "people"), [self.manager.id])
        self.assertEqual(
            response.data["groups"]["people"][0],
            {
                "id": self.manager.id,
                "full_name": "manager-a",
                "email": "manager-a@example.com",
                "role": UserRole.BUILDING_MANAGER,
            },
        )
        # The other company's admin and customer user are absent.
        response = self.search("admin-b")
        self.assertEqual(self.ids(response, "people"), [])
        response = self.search("customer-b")
        self.assertEqual(self.ids(response, "people"), [])
        # A soft-deleted or deactivated user drops out, as on /api/users/.
        self.manager.soft_delete()
        response = self.search("manager-a")
        self.assertEqual(self.ids(response, "people"), [])

        # A building manager administers nobody.
        self.authenticate(self.other_manager)
        response = self.search("example")
        self.assertEqual(self.ids(response, "people"), [])

        # SUPER_ADMIN is unrestricted, ordered by full_name.
        self.authenticate(self.super_admin)
        response = self.search("admin-")
        self.assertEqual(
            self.ids(response, "people"),
            [self.company_admin.id, self.other_company_admin.id],
        )

    # 8. Extra work -----------------------------------------------------

    def test_extra_work_matches_by_title_and_by_exact_id(self):
        # A fresh test database hands out id 1, and "1" is shorter than
        # the two characters the endpoint requires. Real ids are the
        # "EW 89" kind, so climb the sequence past 9 first.
        for n in range(10):
            self.make_extra_work(f"Sequence filler {n}")
        ew = self.make_extra_work("Deep clean of the atrium")
        self.assertGreaterEqual(ew.id, 10)
        other = self.make_extra_work(
            "Deep clean elsewhere",
            company=self.other_company,
            building=self.other_building,
            customer=self.other_customer,
        )

        self.authenticate(self.company_admin)
        response = self.search("deep clean")
        self.assertEqual(self.ids(response, "extra_work"), [ew.id])
        row = response.data["groups"]["extra_work"][0]
        self.assertEqual(
            set(row),
            {
                "id",
                "title",
                "status",
                "display_phase",
                "customer_name",
                "building_name",
            },
        )
        self.assertEqual(row["title"], "Deep clean of the atrium")
        self.assertEqual(row["status"], ew.status)
        self.assertIsInstance(row["display_phase"], str)
        self.assertEqual(row["customer_name"], "Customer A")
        self.assertEqual(row["building_name"], "Building A")

        # "EW 89": an all-digit query is the id, exactly.
        response = self.search(str(ew.id))
        self.assertEqual(self.ids(response, "extra_work"), [ew.id])
        # ... and the other company's id is simply absent (H-1).
        response = self.search(str(other.id))
        self.assertEqual(self.ids(response, "extra_work"), [])
        # An absurd number is not a 500.
        response = self.search("99999999999999999999")
        self.assertEqual(self.ids(response, "extra_work"), [])

        self.authenticate(self.super_admin)
        response = self.search("Deep clean")
        self.assertEqual(self.ids(response, "extra_work"), [other.id, ew.id])
