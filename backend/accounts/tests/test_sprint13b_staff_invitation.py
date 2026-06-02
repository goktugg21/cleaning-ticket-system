"""
Sprint 13B — STAFF invitation orphan-bug fix.

Before this sprint, ``InvitationCreateSerializer.validate`` had no
``UserRole.STAFF`` branch and ``InvitationAcceptSerializer.save`` had no
STAFF branch, so accepting a STAFF invitation produced a User with role
STAFF but NO ``StaffProfile`` and NO ``BuildingStaffVisibility`` rows —
an orphan that could not be assigned to tickets and was invisible to the
direct-assignment eligibility checks.

These tests pin the fixed contract:

  - Create-side shape: STAFF invites require >=1 building, reject
    company/customer scope.
  - Accept-side materialisation: a ``StaffProfile`` is created and a
    ``BuildingStaffVisibility`` row per invited building.
  - Default ``visibility_level`` is ``ASSIGNED_ONLY`` — the
    privacy-preserving onboarding default per the Ramazan transcript
    (docs/transkript.txt lines 27/31/35): a freshly onboarded STAFF sees
    ONLY their own assigned tickets; a BM/admin explicitly widens later.
  - Functional scoping proof: the accepted STAFF can see a ticket they
    are explicitly assigned to (H-4 floor) but NOT an unassigned ticket
    in the same building (ASSIGNED_ONLY is in effect).
  - Regression: CUSTOMER_USER invite+accept still works unchanged.
"""

from unittest import mock

from django.contrib.auth import get_user_model
from django.test import override_settings
from rest_framework import status
from rest_framework.test import APITestCase

from accounts.models import StaffProfile, UserRole
from accounts.scoping import scope_tickets_for
from buildings.models import BuildingStaffVisibility
from customers.models import CustomerUserMembership
from tickets.models import Ticket, TicketStaffAssignment
from test_utils import TenantFixtureMixin


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
class StaffInvitationTests(TenantFixtureMixin, APITestCase):
    LIST_URL = "/api/auth/invitations/"
    ACCEPT_URL = "/api/auth/invitations/accept/"
    TICKETS_URL = "/api/tickets/"

    def _create_invitation_via_api(self, actor, payload):
        self.authenticate(actor)
        return self.client.post(self.LIST_URL, payload, format="json")

    def _create_invitation_and_capture_raw(self, actor, payload):
        captured = {}

        def fake_send(invitation, raw_token, accept_url):
            captured["raw"] = raw_token

        with mock.patch(
            "accounts.views_invitations.send_invitation_email",
            side_effect=fake_send,
        ):
            response = self._create_invitation_via_api(actor, payload)
        return response, captured.get("raw")

    def _accept(self, raw):
        # Accept runs unauthenticated (public token-based endpoint).
        self.client.force_authenticate(user=None)
        return self.client.post(
            self.ACCEPT_URL,
            {"token": raw, "new_password": "AStrongPassword123!"},
            format="json",
        )

    # ---- create-side shape -------------------------------------------------

    def test_staff_invite_without_building_ids_is_rejected(self):
        response = self._create_invitation_via_api(
            self.super_admin,
            {
                "email": "staff-no-building@example.com",
                "role": UserRole.STAFF,
            },
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("building_ids", response.data)

    def test_staff_invite_rejects_company_scope(self):
        response = self._create_invitation_via_api(
            self.super_admin,
            {
                "email": "staff-company-scope@example.com",
                "role": UserRole.STAFF,
                "building_ids": [self.building.id],
                "company_ids": [self.company.id],
            },
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_staff_invite_rejects_customer_scope(self):
        response = self._create_invitation_via_api(
            self.super_admin,
            {
                "email": "staff-customer-scope@example.com",
                "role": UserRole.STAFF,
                "building_ids": [self.building.id],
                "customer_ids": [self.customer.id],
            },
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_staff_invite_with_in_scope_building_is_created_and_carries_buildings(self):
        response, raw = self._create_invitation_and_capture_raw(
            self.super_admin,
            {
                "email": "staff-ok@example.com",
                "role": UserRole.STAFF,
                "building_ids": [self.building.id],
            },
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        self.assertIsNotNone(raw)
        from accounts.invitations import Invitation

        invitation = Invitation.objects.get(email="staff-ok@example.com")
        self.assertEqual(invitation.role, UserRole.STAFF)
        self.assertEqual(
            set(invitation.buildings.values_list("id", flat=True)),
            {self.building.id},
        )

    def test_company_admin_cannot_invite_staff_outside_scope(self):
        # other_building belongs to other_company; company_admin is not a
        # member of other_company, so this must fail (mirrors the existing
        # BUILDING_MANAGER scope guard at serializers_invitations:167-176).
        response = self._create_invitation_via_api(
            self.company_admin,
            {
                "email": "staff-outside@example.com",
                "role": UserRole.STAFF,
                "building_ids": [self.other_building.id],
            },
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    # ---- accept-side materialisation --------------------------------------

    def test_accept_staff_invite_creates_user_profile_and_visibility(self):
        response, raw = self._create_invitation_and_capture_raw(
            self.super_admin,
            {
                "email": "staff-accept@example.com",
                "role": UserRole.STAFF,
                "building_ids": [self.building.id],
            },
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)

        accept = self._accept(raw)
        self.assertEqual(accept.status_code, status.HTTP_201_CREATED, accept.data)

        user = get_user_model().objects.get(email="staff-accept@example.com")
        self.assertEqual(user.role, UserRole.STAFF)

        # StaffProfile materialised.
        self.assertTrue(StaffProfile.objects.filter(user=user).exists())

        # One BuildingStaffVisibility row per invited building, default
        # visibility_level == ASSIGNED_ONLY.
        bsv = BuildingStaffVisibility.objects.get(user=user, building=self.building)
        self.assertEqual(
            bsv.visibility_level,
            BuildingStaffVisibility.VisibilityLevel.ASSIGNED_ONLY,
        )
        self.assertEqual(
            BuildingStaffVisibility.objects.filter(user=user).count(), 1
        )

    def test_accept_staff_invite_materialises_visibility_for_each_building(self):
        # A second in-company building so we can prove one BSV row per
        # invited building.
        from buildings.models import Building

        building2 = Building.objects.create(
            company=self.company, name="Building A2", address="Main Street 2"
        )
        response, raw = self._create_invitation_and_capture_raw(
            self.super_admin,
            {
                "email": "staff-multi@example.com",
                "role": UserRole.STAFF,
                "building_ids": [self.building.id, building2.id],
            },
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        accept = self._accept(raw)
        self.assertEqual(accept.status_code, status.HTTP_201_CREATED, accept.data)

        user = get_user_model().objects.get(email="staff-multi@example.com")
        rows = BuildingStaffVisibility.objects.filter(user=user)
        self.assertEqual(rows.count(), 2)
        for row in rows:
            self.assertEqual(
                row.visibility_level,
                BuildingStaffVisibility.VisibilityLevel.ASSIGNED_ONLY,
            )

    # ---- functional scoping proof -----------------------------------------

    def test_accepted_staff_sees_assigned_ticket_but_not_unassigned_one(self):
        response, raw = self._create_invitation_and_capture_raw(
            self.super_admin,
            {
                "email": "staff-scope@example.com",
                "role": UserRole.STAFF,
                "building_ids": [self.building.id],
            },
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        accept = self._accept(raw)
        self.assertEqual(accept.status_code, status.HTTP_201_CREATED, accept.data)
        staff = get_user_model().objects.get(email="staff-scope@example.com")

        # self.ticket already lives in self.building (TenantFixtureMixin).
        # Assign the staff to it directly.
        TicketStaffAssignment.objects.create(
            ticket=self.ticket, user=staff, assigned_by=self.super_admin
        )

        # A second, UNASSIGNED ticket in the same building.
        unassigned = Ticket.objects.create(
            company=self.company,
            building=self.building,
            customer=self.customer,
            created_by=self.super_admin,
            title="Unassigned in same building",
            description="x",
        )

        # scope_tickets_for: ASSIGNED_ONLY → sees only the assigned one.
        scoped_ids = set(scope_tickets_for(staff).values_list("id", flat=True))
        self.assertIn(self.ticket.id, scoped_ids)
        self.assertNotIn(unassigned.id, scoped_ids)

        # Same contract through the list endpoint.
        self.authenticate(staff)
        listed = self.client.get(self.TICKETS_URL)
        self.assertEqual(listed.status_code, status.HTTP_200_OK)
        listed_ids = self.response_ids(listed)
        self.assertIn(self.ticket.id, listed_ids)
        self.assertNotIn(unassigned.id, listed_ids)

    # ---- regression: CUSTOMER_USER path unchanged -------------------------

    def test_customer_user_invite_and_accept_still_works(self):
        response, raw = self._create_invitation_and_capture_raw(
            self.super_admin,
            {
                "email": "regression-cu@example.com",
                "role": UserRole.CUSTOMER_USER,
                "customer_ids": [self.customer.id],
            },
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        accept = self._accept(raw)
        self.assertEqual(accept.status_code, status.HTTP_201_CREATED, accept.data)

        user = get_user_model().objects.get(email="regression-cu@example.com")
        self.assertEqual(user.role, UserRole.CUSTOMER_USER)
        self.assertTrue(
            CustomerUserMembership.objects.filter(
                user=user, customer=self.customer
            ).exists()
        )
        # A CUSTOMER_USER accept must NOT fabricate STAFF artefacts.
        self.assertFalse(StaffProfile.objects.filter(user=user).exists())
        self.assertFalse(BuildingStaffVisibility.objects.filter(user=user).exists())
