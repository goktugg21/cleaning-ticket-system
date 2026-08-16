"""
Sprint 185 E §2 — the cost-share write path.

The endpoint is a WHOLE-SET replace, and these tests pin why:

  * the shares must sum to exactly 100, refused with a clear message
    naming the number the operator actually typed;
  * an empty set is a legitimate edit — a building stops being shared and
    goes back to behaving exactly as it did before this sprint;
  * a customer that does not operate at the building cannot be given a
    share of it. Billing a share to a customer who is not there is not a
    division of the cost, it is an invoice to a stranger;
  * the same customer cannot hold two shares;
  * writes are provider-admin only, reads follow the building's own
    scope, and a foreign building is not reachable at all.
"""
from __future__ import annotations

from decimal import Decimal

from rest_framework.test import APITestCase

from buildings.models import BuildingCostShare
from companies.models import CompanyUserMembership
from customers.models import Customer, CustomerBuildingMembership
from test_utils import TenantFixtureMixin


def url(building_id):
    return f"/api/buildings/{building_id}/cost-shares/"


class BuildingCostShareEndpointTests(TenantFixtureMixin, APITestCase):
    def setUp(self):
        super().setUp()
        CompanyUserMembership.objects.get_or_create(
            user=self.company_admin, company=self.company
        )
        from accounts.models import UserRole

        self.staff_user = self.make_user("staff-cs@example.com", UserRole.STAFF)
        self.second = Customer.objects.create(
            company=self.company, name="Second tenant", building=self.building
        )
        CustomerBuildingMembership.objects.get_or_create(
            customer=self.second, building=self.building
        )

    def as_(self, user):
        self.client.force_authenticate(user=user)
        return self.client

    def _put(self, user, shares, building=None):
        return self.as_(user).put(
            url((building or self.building).id),
            {"shares": shares},
            format="json",
        )

    # ------------------------------------------------------------------
    # The invariant
    # ------------------------------------------------------------------
    def test_shares_that_sum_to_100_are_accepted(self):
        response = self._put(
            self.company_admin,
            [
                {"customer": self.customer.id, "share_pct": "60.00"},
                {"customer": self.second.id, "share_pct": "40.00"},
            ],
        )
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(
            BuildingCostShare.objects.filter(building=self.building).count(), 2
        )

    def test_shares_that_do_not_sum_to_100_are_refused(self):
        response = self._put(
            self.company_admin,
            [
                {"customer": self.customer.id, "share_pct": "60.00"},
                {"customer": self.second.id, "share_pct": "30.00"},
            ],
        )
        self.assertEqual(response.status_code, 400, response.data)
        body = str(response.data)
        self.assertIn("cost_shares_must_sum_to_100", body)
        # The message names what they typed, not just what was wanted.
        self.assertIn("90.00", body)
        self.assertEqual(
            BuildingCostShare.objects.filter(building=self.building).count(), 0
        )

    def test_the_empty_set_clears_the_division(self):
        self._put(
            self.company_admin,
            [
                {"customer": self.customer.id, "share_pct": "60.00"},
                {"customer": self.second.id, "share_pct": "40.00"},
            ],
        )
        response = self._put(self.company_admin, [])
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(
            BuildingCostShare.objects.filter(building=self.building).count(), 0
        )

    def test_a_replace_is_atomic_and_total(self):
        """PUT replaces; it does not merge. A share that is not in the new
        set is gone, which is the only way "these are the tenants now" can
        be expressed."""
        self._put(
            self.company_admin,
            [
                {"customer": self.customer.id, "share_pct": "50.00"},
                {"customer": self.second.id, "share_pct": "50.00"},
            ],
        )
        response = self._put(
            self.company_admin,
            [{"customer": self.customer.id, "share_pct": "100.00"}],
        )
        self.assertEqual(response.status_code, 200, response.data)
        rows = BuildingCostShare.objects.filter(building=self.building)
        self.assertEqual(
            [(r.customer_id, r.share_pct) for r in rows],
            [(self.customer.id, Decimal("100.00"))],
        )

    # ------------------------------------------------------------------
    # What cannot be divided
    # ------------------------------------------------------------------
    def test_a_customer_not_linked_to_the_building_cannot_hold_a_share(self):
        stranger = Customer.objects.create(
            company=self.company, name="Not here", building=self.other_building
        )
        response = self._put(
            self.company_admin,
            [
                {"customer": self.customer.id, "share_pct": "50.00"},
                {"customer": stranger.id, "share_pct": "50.00"},
            ],
        )
        self.assertEqual(response.status_code, 400, response.data)
        self.assertIn("cost_share_customer_not_linked", str(response.data))

    def test_the_same_customer_cannot_hold_two_shares(self):
        response = self._put(
            self.company_admin,
            [
                {"customer": self.customer.id, "share_pct": "50.00"},
                {"customer": self.customer.id, "share_pct": "50.00"},
            ],
        )
        self.assertEqual(response.status_code, 400, response.data)
        self.assertIn("cost_share_duplicate_customer", str(response.data))

    def test_a_zero_share_is_refused(self):
        """0% is not a tenant with no cost, it is a row that should not
        exist — and the allocator must never see one."""
        response = self._put(
            self.company_admin,
            [
                {"customer": self.customer.id, "share_pct": "100.00"},
                {"customer": self.second.id, "share_pct": "0.00"},
            ],
        )
        self.assertEqual(response.status_code, 400, response.data)

    # ------------------------------------------------------------------
    # Who may do it
    # ------------------------------------------------------------------
    def test_a_building_manager_may_read_but_not_write(self):
        BuildingCostShare.objects.create(
            building=self.building,
            customer=self.customer,
            share_pct=Decimal("100.00"),
        )
        read = self.as_(self.manager).get(url(self.building.id))
        self.assertEqual(read.status_code, 200, read.data)
        self.assertEqual(len(read.data["results"]), 1)

        write = self._put(
            self.manager,
            [{"customer": self.customer.id, "share_pct": "100.00"}],
        )
        self.assertEqual(write.status_code, 403, write.data)

    def test_a_customer_user_cannot_read_the_division(self):
        """A tenant must not learn what the OTHER tenants of its building
        pay. This test found a real leak: the read gate was "can you
        reach the building", and a customer user can reach their own —
        so the whole division was readable by every tenant on it."""
        response = self.as_(self.customer_user).get(url(self.building.id))
        self.assertEqual(response.status_code, 403, response.data)

    def test_a_staff_user_cannot_read_the_division(self):
        response = self.as_(self.staff_user).get(url(self.building.id))
        self.assertEqual(response.status_code, 403, response.data)

    def test_another_companys_building_is_not_reachable(self):
        response = self._put(
            self.company_admin,
            [{"customer": self.other_customer.id, "share_pct": "100.00"}],
            building=self.other_building,
        )
        self.assertIn(response.status_code, (403, 404), response.data)

    def test_the_read_renders_every_field_it_promises(self):
        BuildingCostShare.objects.create(
            building=self.building,
            customer=self.customer,
            share_pct=Decimal("100.00"),
        )
        response = self.as_(self.company_admin).get(url(self.building.id))
        row = response.data["results"][0]
        for key in (
            "id",
            "building",
            "customer",
            "customer_name",
            "share_pct",
            "created_at",
            "updated_at",
        ):
            self.assertIn(key, row)
        self.assertEqual(row["customer_name"], self.customer.name)
