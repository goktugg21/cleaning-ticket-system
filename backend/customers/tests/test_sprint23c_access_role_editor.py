"""
Sprint 23C — access_role editor tests.

Pins the PATCH /api/customers/<id>/users/<uid>/access/<bid>/ contract:

  - SUPER_ADMIN may PATCH any customer's access rows.
  - COMPANY_ADMIN may PATCH only their own company's access rows.
  - BUILDING_MANAGER, STAFF, CUSTOMER_USER receive 403 from the class-
    level role gate before object-level checks fire.
  - Cross-company COMPANY_ADMIN attempts are rejected with 403 (the
    object-level membership gate denies it).
  - Promoting a CUSTOMER_USER row to CUSTOMER_LOCATION_MANAGER actually
    widens that user's ticket scope, as resolved by
    `accounts.scoping.scope_tickets_for`. Sprint 23A already pins
    the resolver itself; this test pins the path through the API.
"""

from django.contrib.auth import get_user_model
from rest_framework import status
from rest_framework.test import APITestCase

from accounts.models import UserRole
from accounts.scoping import scope_tickets_for
from customers.models import CustomerUserBuildingAccess
from tickets.models import Ticket
from test_utils import TenantFixtureMixin


CUSTOMER_USER = CustomerUserBuildingAccess.AccessRole.CUSTOMER_USER
CUSTOMER_LOCATION_MANAGER = (
    CustomerUserBuildingAccess.AccessRole.CUSTOMER_LOCATION_MANAGER
)
CUSTOMER_COMPANY_ADMIN = (
    CustomerUserBuildingAccess.AccessRole.CUSTOMER_COMPANY_ADMIN
)


class AccessRolePatchTests(TenantFixtureMixin, APITestCase):
    def url(self, customer_id, user_id, building_id):
        return (
            f"/api/customers/{customer_id}"
            f"/users/{user_id}/access/{building_id}/"
        )

    # ---- Auth / role gate ------------------------------------------------

    def test_super_admin_can_promote_access_role(self):
        self.authenticate(self.super_admin)
        response = self.client.patch(
            self.url(self.customer.id, self.customer_user.id, self.building.id),
            {"access_role": CUSTOMER_LOCATION_MANAGER},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["access_role"], CUSTOMER_LOCATION_MANAGER)
        access = CustomerUserBuildingAccess.objects.get(
            membership__user=self.customer_user,
            membership__customer=self.customer,
            building=self.building,
        )
        self.assertEqual(access.access_role, CUSTOMER_LOCATION_MANAGER)

    def test_company_admin_can_promote_in_own_company(self):
        self.authenticate(self.company_admin)
        response = self.client.patch(
            self.url(self.customer.id, self.customer_user.id, self.building.id),
            {"access_role": CUSTOMER_LOCATION_MANAGER},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["access_role"], CUSTOMER_LOCATION_MANAGER)

    def test_company_admin_cannot_promote_in_other_company(self):
        """Cross-company PATCH must fail at the object-level gate."""
        self.authenticate(self.company_admin)
        response = self.client.patch(
            self.url(
                self.other_customer.id,
                self.other_customer_user.id,
                self.other_building.id,
            ),
            {"access_role": CUSTOMER_LOCATION_MANAGER},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        access = CustomerUserBuildingAccess.objects.get(
            membership__user=self.other_customer_user,
            membership__customer=self.other_customer,
            building=self.other_building,
        )
        self.assertEqual(access.access_role, CUSTOMER_USER)

    def test_building_manager_cannot_patch(self):
        self.authenticate(self.manager)
        response = self.client.patch(
            self.url(self.customer.id, self.customer_user.id, self.building.id),
            {"access_role": CUSTOMER_LOCATION_MANAGER},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_customer_user_cannot_patch(self):
        self.authenticate(self.customer_user)
        response = self.client.patch(
            self.url(self.customer.id, self.customer_user.id, self.building.id),
            {"access_role": CUSTOMER_LOCATION_MANAGER},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_staff_cannot_patch(self):
        staff = get_user_model().objects.create_user(
            email="ahmet-test-staff@example.com",
            password=self.password,
            role=UserRole.STAFF,
        )
        self.client.force_authenticate(user=staff)
        response = self.client.patch(
            self.url(self.customer.id, self.customer_user.id, self.building.id),
            {"access_role": CUSTOMER_LOCATION_MANAGER},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    # ---- Input validation ------------------------------------------------

    def test_invalid_access_role_rejected(self):
        self.authenticate(self.super_admin)
        response = self.client.patch(
            self.url(self.customer.id, self.customer_user.id, self.building.id),
            {"access_role": "NOT_A_REAL_ROLE"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("access_role", response.data)

    def test_patch_returns_full_serializer(self):
        """Response carries the joined building / user fields the UI renders."""
        self.authenticate(self.super_admin)
        response = self.client.patch(
            self.url(self.customer.id, self.customer_user.id, self.building.id),
            {"access_role": CUSTOMER_LOCATION_MANAGER},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        for key in (
            "id",
            "membership_id",
            "user_id",
            "user_email",
            "building_id",
            "building_name",
            "access_role",
            "is_active",
            "permission_overrides",
            "created_at",
        ):
            self.assertIn(key, response.data)

    def test_patch_unknown_access_row_404(self):
        self.authenticate(self.super_admin)
        response = self.client.patch(
            self.url(self.customer.id, self.customer_user.id, 999_999),
            {"access_role": CUSTOMER_LOCATION_MANAGER},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    # ---- Visibility effect ----------------------------------------------

    def test_promotion_widens_ticket_scope(self):
        """
        With access_role=CUSTOMER_USER the fixture user only sees tickets
        they created at (customer, building). Promoting to
        CUSTOMER_LOCATION_MANAGER unlocks every ticket at the same pair,
        regardless of creator. Pinning the path through scope_tickets_for
        catches a regression where the resolver stops honouring an
        access_role change.
        """
        # Create a ticket at (customer, building) authored by a
        # DIFFERENT customer user so view_own does NOT match.
        author = get_user_model().objects.create_user(
            email="other-cu-author@example.com",
            password=self.password,
            role=UserRole.CUSTOMER_USER,
        )
        other_pair_ticket = Ticket.objects.create(
            company=self.company,
            building=self.building,
            customer=self.customer,
            created_by=author,
            title="Authored by someone else at the same pair",
            description="Visible at view_location, hidden at view_own.",
        )

        # Pre-promotion: plain CUSTOMER_USER → view_own only → ticket
        # authored by `author` is NOT visible to `customer_user`.
        visible_before = set(
            scope_tickets_for(self.customer_user).values_list("id", flat=True)
        )
        self.assertNotIn(other_pair_ticket.id, visible_before)

        # Promote via the API.
        self.authenticate(self.super_admin)
        response = self.client.patch(
            self.url(self.customer.id, self.customer_user.id, self.building.id),
            {"access_role": CUSTOMER_LOCATION_MANAGER},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # Post-promotion: view_location resolves True → the same ticket
        # IS visible without changing the row's overrides.
        visible_after = set(
            scope_tickets_for(self.customer_user).values_list("id", flat=True)
        )
        self.assertIn(other_pair_ticket.id, visible_after)

    def test_demotion_back_to_customer_user_narrows_scope(self):
        """Symmetric guard: demoting collapses scope back to view_own."""
        # Promote first.
        access = CustomerUserBuildingAccess.objects.get(
            membership__user=self.customer_user,
            membership__customer=self.customer,
            building=self.building,
        )
        access.access_role = CUSTOMER_LOCATION_MANAGER
        access.save(update_fields=["access_role"])

        author = get_user_model().objects.create_user(
            email="other-cu-author-2@example.com",
            password=self.password,
            role=UserRole.CUSTOMER_USER,
        )
        other_pair_ticket = Ticket.objects.create(
            company=self.company,
            building=self.building,
            customer=self.customer,
            created_by=author,
            title="Authored by someone else at the same pair (2)",
            description="Visible at view_location, hidden at view_own.",
        )

        # While promoted, customer_user can see the cross-author ticket.
        self.assertIn(
            other_pair_ticket.id,
            set(scope_tickets_for(self.customer_user).values_list("id", flat=True)),
        )

        # Demote via the API.
        self.authenticate(self.company_admin)
        response = self.client.patch(
            self.url(self.customer.id, self.customer_user.id, self.building.id),
            {"access_role": CUSTOMER_USER},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # Now hidden again.
        self.assertNotIn(
            other_pair_ticket.id,
            set(scope_tickets_for(self.customer_user).values_list("id", flat=True)),
        )
