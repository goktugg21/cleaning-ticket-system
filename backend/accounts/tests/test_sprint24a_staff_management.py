"""
Sprint 24A — admin write endpoints for StaffProfile +
BuildingStaffVisibility.

Pins the new `/api/users/<id>/staff-profile/` and
`/api/users/<id>/staff-visibility[/<building_id>/]` contract:

  - SUPER_ADMIN can edit any STAFF profile and visibility row.
  - COMPANY_ADMIN can edit only their own company's STAFF; trying to
    reach cross-company STAFF returns 403.
  - COMPANY_ADMIN cannot grant visibility on a building from another
    company (400 because the building fails the same-company guard).
  - BUILDING_MANAGER / STAFF / CUSTOMER_USER receive 403 from the
    class-level role gate.
  - Visibility changes flow through to Sprint 23A scope: adding a row
    widens the staff user's ticket scope, removing narrows it.
  - A staff user cannot patch their own visibility (the role gate
    catches them before the object-level check).
  - Non-STAFF users cannot have a StaffProfile created via the admin
    surface (400, never 500).
"""

from django.contrib.auth import get_user_model
from rest_framework import status
from rest_framework.test import APITestCase

from accounts.models import StaffProfile, UserRole
from accounts.scoping import scope_tickets_for
from buildings.models import BuildingStaffVisibility
from test_utils import TenantFixtureMixin
from tickets.models import Ticket


User = get_user_model()


class StaffAdminTestMixin(TenantFixtureMixin):
    """Adds STAFF users + extra fixture buildings on top of the base mixin."""

    def setUp(self):
        super().setUp()
        # Two STAFF users — one per company. Each starts with visibility
        # on their company's anchor building so they appear in the
        # COMPANY_ADMIN's scope (Sprint 24A `_user_in_actor_company`
        # extension treats BuildingStaffVisibility as scope-overlap).
        self.staff_a = self.make_user(
            "staff-a@example.com", UserRole.STAFF
        )
        self.staff_b = self.make_user(
            "staff-b@example.com", UserRole.STAFF
        )
        StaffProfile.objects.create(
            user=self.staff_a, phone="", is_active=True
        )
        StaffProfile.objects.create(
            user=self.staff_b, phone="", is_active=True
        )
        BuildingStaffVisibility.objects.create(
            user=self.staff_a, building=self.building
        )
        BuildingStaffVisibility.objects.create(
            user=self.staff_b, building=self.other_building
        )

    def profile_url(self, user_id):
        return f"/api/users/{user_id}/staff-profile/"

    def visibility_list_url(self, user_id):
        return f"/api/users/{user_id}/staff-visibility/"

    def visibility_detail_url(self, user_id, building_id):
        return f"/api/users/{user_id}/staff-visibility/{building_id}/"


class StaffProfileTests(StaffAdminTestMixin, APITestCase):
    # ---- StaffProfile -- read ------------------------------------------

    def test_super_admin_can_get_any_profile(self):
        self.authenticate(self.super_admin)
        response = self.client.get(self.profile_url(self.staff_a.id))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["user_id"], self.staff_a.id)
        self.assertEqual(response.data["user_email"], self.staff_a.email)
        # All four editable fields are present in the read shape.
        for key in ("phone", "internal_note", "can_request_assignment", "is_active"):
            self.assertIn(key, response.data)

    def test_company_admin_can_get_own_company_profile(self):
        self.authenticate(self.company_admin)
        response = self.client.get(self.profile_url(self.staff_a.id))
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_company_admin_cannot_get_cross_company_profile(self):
        self.authenticate(self.company_admin)
        response = self.client.get(self.profile_url(self.staff_b.id))
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_profile_auto_created_on_first_get(self):
        # A STAFF user without a profile row (none seeded in setUp for
        # this one) is auto-provisioned on first GET so the admin UI
        # never needs a separate "create profile" call.
        fresh = self.make_user("staff-c@example.com", UserRole.STAFF)
        BuildingStaffVisibility.objects.create(
            user=fresh, building=self.building
        )
        self.assertFalse(StaffProfile.objects.filter(user=fresh).exists())
        self.authenticate(self.super_admin)
        response = self.client.get(self.profile_url(fresh.id))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(StaffProfile.objects.filter(user=fresh).exists())

    def test_non_staff_user_rejected(self):
        # A COMPANY_ADMIN user is not a STAFF user; admin endpoint
        # returns 400 before any auto-create can fire.
        self.authenticate(self.super_admin)
        response = self.client.get(self.profile_url(self.company_admin.id))
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        # And no spurious StaffProfile got created.
        self.assertFalse(
            StaffProfile.objects.filter(user=self.company_admin).exists()
        )

    # ---- StaffProfile -- write -----------------------------------------

    def test_super_admin_can_patch_profile(self):
        self.authenticate(self.super_admin)
        response = self.client.patch(
            self.profile_url(self.staff_a.id),
            {
                "phone": "+31 6 9999 0000",
                "internal_note": "Owns evening shift.",
                "can_request_assignment": False,
                "is_active": True,
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["phone"], "+31 6 9999 0000")
        self.assertEqual(response.data["can_request_assignment"], False)
        profile = StaffProfile.objects.get(user=self.staff_a)
        self.assertEqual(profile.phone, "+31 6 9999 0000")
        self.assertEqual(profile.internal_note, "Owns evening shift.")
        self.assertFalse(profile.can_request_assignment)

    def test_company_admin_can_patch_own_company_profile(self):
        self.authenticate(self.company_admin)
        response = self.client.patch(
            self.profile_url(self.staff_a.id),
            {"phone": "+31 6 1111 2222"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["phone"], "+31 6 1111 2222")

    def test_company_admin_cannot_patch_cross_company_profile(self):
        self.authenticate(self.company_admin)
        response = self.client.patch(
            self.profile_url(self.staff_b.id),
            {"phone": "stolen"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.staff_b.refresh_from_db()
        self.assertEqual(
            StaffProfile.objects.get(user=self.staff_b).phone, ""
        )

    def test_building_manager_cannot_patch_profile(self):
        self.authenticate(self.manager)
        response = self.client.patch(
            self.profile_url(self.staff_a.id),
            {"phone": "should-fail"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_staff_cannot_patch_own_profile(self):
        # STAFF users do not pass the class-level role gate at all,
        # even for their own profile row. Self-edits flow through
        # /api/auth/me/ instead.
        self.authenticate(self.staff_a)
        response = self.client.patch(
            self.profile_url(self.staff_a.id),
            {"phone": "self-edit-attempt"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_customer_user_cannot_patch_profile(self):
        self.authenticate(self.customer_user)
        response = self.client.patch(
            self.profile_url(self.staff_a.id),
            {"phone": "should-fail"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)


class StaffVisibilityTests(StaffAdminTestMixin, APITestCase):
    # ---- Visibility -- list / add --------------------------------------

    def test_super_admin_lists_visibility(self):
        self.authenticate(self.super_admin)
        response = self.client.get(self.visibility_list_url(self.staff_a.id))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        building_ids = [row["building_id"] for row in response.data["results"]]
        self.assertIn(self.building.id, building_ids)

    def test_company_admin_lists_own_company_visibility(self):
        self.authenticate(self.company_admin)
        response = self.client.get(self.visibility_list_url(self.staff_a.id))
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_company_admin_cannot_list_cross_company_visibility(self):
        self.authenticate(self.company_admin)
        response = self.client.get(self.visibility_list_url(self.staff_b.id))
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_super_admin_can_add_visibility(self):
        # Build a second building in company A so we have somewhere to
        # add visibility for staff_a beyond the single fixture row.
        from buildings.models import Building

        b2 = Building.objects.create(
            company=self.company, name="Building A-2"
        )
        self.authenticate(self.super_admin)
        response = self.client.post(
            self.visibility_list_url(self.staff_a.id),
            {"building_id": b2.id},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["building_id"], b2.id)
        self.assertTrue(
            BuildingStaffVisibility.objects.filter(
                user=self.staff_a, building=b2
            ).exists()
        )

    def test_company_admin_can_add_in_own_company(self):
        from buildings.models import Building

        b2 = Building.objects.create(
            company=self.company, name="Building A-3"
        )
        self.authenticate(self.company_admin)
        response = self.client.post(
            self.visibility_list_url(self.staff_a.id),
            {"building_id": b2.id},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    def test_company_admin_cannot_assign_cross_company_building(self):
        # Try to attach staff_a (Company A staff) to other_building
        # (Company B). The same-company guard kicks in and returns 400
        # before any row is created.
        self.authenticate(self.company_admin)
        response = self.client.post(
            self.visibility_list_url(self.staff_a.id),
            {"building_id": self.other_building.id},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("building_id", response.data)
        self.assertFalse(
            BuildingStaffVisibility.objects.filter(
                user=self.staff_a, building=self.other_building
            ).exists()
        )

    def test_company_admin_cannot_add_cross_company_staff(self):
        # Attaching ANY building to a cross-company STAFF is blocked by
        # the staff-side scope gate (403 from has_object_permission).
        self.authenticate(self.company_admin)
        response = self.client.post(
            self.visibility_list_url(self.staff_b.id),
            {"building_id": self.building.id},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_missing_building_id_400(self):
        self.authenticate(self.super_admin)
        response = self.client.post(
            self.visibility_list_url(self.staff_a.id),
            {},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_add_is_idempotent(self):
        # Re-POSTing an existing row returns 200 with the existing
        # serialized payload, never a duplicate IntegrityError.
        self.authenticate(self.super_admin)
        response = self.client.post(
            self.visibility_list_url(self.staff_a.id),
            {"building_id": self.building.id},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            BuildingStaffVisibility.objects.filter(
                user=self.staff_a, building=self.building
            ).count(),
            1,
        )

    # ---- Visibility -- patch / delete ----------------------------------

    def test_super_admin_can_patch_can_request(self):
        self.authenticate(self.super_admin)
        response = self.client.patch(
            self.visibility_detail_url(self.staff_a.id, self.building.id),
            {"can_request_assignment": False},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["can_request_assignment"], False)

    def test_super_admin_can_delete(self):
        self.authenticate(self.super_admin)
        response = self.client.delete(
            self.visibility_detail_url(self.staff_a.id, self.building.id),
        )
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(
            BuildingStaffVisibility.objects.filter(
                user=self.staff_a, building=self.building
            ).exists()
        )

    def test_company_admin_can_delete_in_own_company(self):
        self.authenticate(self.company_admin)
        response = self.client.delete(
            self.visibility_detail_url(self.staff_a.id, self.building.id),
        )
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)

    def test_company_admin_cannot_delete_cross_company(self):
        self.authenticate(self.company_admin)
        response = self.client.delete(
            self.visibility_detail_url(self.staff_b.id, self.other_building.id),
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertTrue(
            BuildingStaffVisibility.objects.filter(
                user=self.staff_b, building=self.other_building
            ).exists()
        )

    def test_patch_unknown_visibility_returns_404(self):
        from buildings.models import Building

        unrelated = Building.objects.create(
            company=self.company, name="Unrelated"
        )
        self.authenticate(self.super_admin)
        response = self.client.patch(
            self.visibility_detail_url(self.staff_a.id, unrelated.id),
            {"can_request_assignment": False},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_building_manager_cannot_patch_visibility(self):
        self.authenticate(self.manager)
        response = self.client.patch(
            self.visibility_detail_url(self.staff_a.id, self.building.id),
            {"can_request_assignment": False},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_staff_cannot_patch_own_visibility(self):
        self.authenticate(self.staff_a)
        response = self.client.patch(
            self.visibility_detail_url(self.staff_a.id, self.building.id),
            {"can_request_assignment": False},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_customer_user_cannot_patch_visibility(self):
        self.authenticate(self.customer_user)
        response = self.client.patch(
            self.visibility_detail_url(self.staff_a.id, self.building.id),
            {"can_request_assignment": False},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)


class StaffVisibilityScopeEffectTests(StaffAdminTestMixin, APITestCase):
    """
    Sprint 23A defines STAFF ticket scope as the union of TicketStaffAssignment
    and BuildingStaffVisibility. Sprint 24A must not break that — adding a
    visibility row should widen scope, removing one should narrow it.
    """

    def test_adding_visibility_widens_staff_scope(self):
        from buildings.models import Building

        # Build a fresh in-company building + ticket the staff cannot
        # see yet (no visibility, no assignment).
        b2 = Building.objects.create(
            company=self.company, name="Scope Effect B"
        )
        ticket = Ticket.objects.create(
            company=self.company,
            building=b2,
            customer=self.customer,
            created_by=self.customer_user,
            title="Hidden until visibility lands",
            description="—",
        )
        self.assertNotIn(
            ticket.id,
            set(scope_tickets_for(self.staff_a).values_list("id", flat=True)),
        )
        # Add visibility via the new admin endpoint.
        self.authenticate(self.company_admin)
        response = self.client.post(
            self.visibility_list_url(self.staff_a.id),
            {"building_id": b2.id},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        # Scope widened.
        self.assertIn(
            ticket.id,
            set(scope_tickets_for(self.staff_a).values_list("id", flat=True)),
        )

    def test_removing_visibility_narrows_staff_scope(self):
        ticket_id = self.ticket.id  # ticket in company A, building A.
        # Pre-state: staff_a holds visibility on building A → sees ticket.
        self.assertIn(
            ticket_id,
            set(scope_tickets_for(self.staff_a).values_list("id", flat=True)),
        )
        # Revoke via API.
        self.authenticate(self.company_admin)
        response = self.client.delete(
            self.visibility_detail_url(self.staff_a.id, self.building.id),
        )
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        # Post-state: ticket disappears (no visibility, no assignment).
        self.assertNotIn(
            ticket_id,
            set(scope_tickets_for(self.staff_a).values_list("id", flat=True)),
        )
