from datetime import timedelta
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import override_settings
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from accounts.invitations import (
    Invitation,
    InvitationStatus,
    generate_invitation_token,
    hash_invitation_token,
)
from accounts.models import UserRole
from buildings.models import BuildingManagerAssignment
from companies.models import CompanyUserMembership
from customers.models import CustomerUserMembership
from notifications.models import NotificationEventType, NotificationLog
from test_utils import TenantFixtureMixin


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
class InvitationTests(TenantFixtureMixin, APITestCase):
    LIST_URL = "/api/auth/invitations/"
    PREVIEW_URL = "/api/auth/invitations/preview/"
    ACCEPT_URL = "/api/auth/invitations/accept/"

    def revoke_url(self, pk):
        return f"/api/auth/invitations/{pk}/revoke/"

    def _create_invitation_via_api(self, actor, payload):
        self.authenticate(actor)
        return self.client.post(self.LIST_URL, payload, format="json")

    def _create_invitation_and_capture_raw(self, actor, payload):
        """
        POST the create endpoint, but capture the raw token by intercepting
        the call to send_invitation_email. The raw token never leaves the
        view in the API response, so test code can only see it by hooking
        the email helper. Returns (response, raw_token).
        """
        captured = {}

        def fake_send(invitation, raw_token, accept_url):
            captured["raw"] = raw_token

        with mock.patch(
            "accounts.views_invitations.send_invitation_email",
            side_effect=fake_send,
        ):
            response = self._create_invitation_via_api(actor, payload)
        return response, captured.get("raw")

    def _make_invitation(self, *, role, email, created_by, companies=(), buildings=(), customers=()):
        raw, token_hash = generate_invitation_token()
        invitation = Invitation.objects.create(
            email=email,
            role=role,
            token_hash=token_hash,
            created_by=created_by,
        )
        if companies:
            invitation.companies.set(companies)
        if buildings:
            invitation.buildings.set(buildings)
        if customers:
            invitation.customers.set(customers)
        return invitation, raw

    # ---- Creation permission ----------------------------------------------

    def test_super_admin_can_invite_company_admin_and_create_membership_on_accept(self):
        response, raw = self._create_invitation_and_capture_raw(
            self.super_admin,
            {
                "email": "new-ca@example.com",
                "role": UserRole.COMPANY_ADMIN,
                "company_ids": [self.company.id],
            },
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertIsNotNone(raw)

        accept = self.client.post(
            self.ACCEPT_URL,
            {"token": raw, "new_password": "AStrongPassword123!"},
            format="json",
        )
        self.assertEqual(accept.status_code, status.HTTP_201_CREATED)

        user = get_user_model().objects.get(email="new-ca@example.com")
        self.assertEqual(user.role, UserRole.COMPANY_ADMIN)
        self.assertTrue(
            CompanyUserMembership.objects.filter(user=user, company=self.company).exists()
        )

    def test_super_admin_can_invite_building_manager_and_create_assignment_on_accept(self):
        response, raw = self._create_invitation_and_capture_raw(
            self.super_admin,
            {
                "email": "new-bm@example.com",
                "role": UserRole.BUILDING_MANAGER,
                "building_ids": [self.building.id],
            },
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertIsNotNone(raw)

        accept = self.client.post(
            self.ACCEPT_URL,
            {"token": raw, "new_password": "AStrongPassword123!"},
            format="json",
        )
        self.assertEqual(accept.status_code, status.HTTP_201_CREATED)
        user = get_user_model().objects.get(email="new-bm@example.com")
        self.assertEqual(user.role, UserRole.BUILDING_MANAGER)
        self.assertTrue(
            BuildingManagerAssignment.objects.filter(user=user, building=self.building).exists()
        )

    def test_super_admin_can_invite_customer_user_and_create_membership_on_accept(self):
        response, raw = self._create_invitation_and_capture_raw(
            self.super_admin,
            {
                "email": "new-cu@example.com",
                "role": UserRole.CUSTOMER_USER,
                "customer_ids": [self.customer.id],
            },
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertIsNotNone(raw)

        accept = self.client.post(
            self.ACCEPT_URL,
            {"token": raw, "new_password": "AStrongPassword123!"},
            format="json",
        )
        self.assertEqual(accept.status_code, status.HTTP_201_CREATED)
        user = get_user_model().objects.get(email="new-cu@example.com")
        self.assertEqual(user.role, UserRole.CUSTOMER_USER)
        self.assertTrue(
            CustomerUserMembership.objects.filter(user=user, customer=self.customer).exists()
        )

    def test_company_admin_can_invite_within_own_company(self):
        response = self._create_invitation_via_api(
            self.company_admin,
            {
                "email": "ca-invite-bm@example.com",
                "role": UserRole.BUILDING_MANAGER,
                "building_ids": [self.building.id],
            },
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    def test_company_admin_cannot_invite_outside_own_company(self):
        # other_building belongs to other_company; company_admin is not a
        # member of other_company, so this must fail.
        response = self._create_invitation_via_api(
            self.company_admin,
            {
                "email": "outside@example.com",
                "role": UserRole.BUILDING_MANAGER,
                "building_ids": [self.other_building.id],
            },
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_company_admin_cannot_invite_super_admin(self):
        response = self._create_invitation_via_api(
            self.company_admin,
            {
                "email": "rogue-sa@example.com",
                "role": UserRole.SUPER_ADMIN,
            },
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_building_manager_cannot_create_invitation(self):
        self.authenticate(self.manager)
        response = self.client.post(
            self.LIST_URL,
            {
                "email": "x@example.com",
                "role": UserRole.CUSTOMER_USER,
                "customer_ids": [self.customer.id],
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_customer_user_cannot_create_invitation(self):
        self.authenticate(self.customer_user)
        response = self.client.post(
            self.LIST_URL,
            {
                "email": "x@example.com",
                "role": UserRole.CUSTOMER_USER,
                "customer_ids": [self.customer.id],
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    # ---- Email collisions and revoke-on-reinvite --------------------------

    def test_invitation_with_existing_active_user_email_is_rejected(self):
        response = self._create_invitation_via_api(
            self.super_admin,
            {
                "email": self.customer_user.email,
                "role": UserRole.CUSTOMER_USER,
                "customer_ids": [self.customer.id],
            },
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_creating_a_new_invitation_revokes_prior_pending_invitation_for_same_email(self):
        first = self._create_invitation_via_api(
            self.super_admin,
            {
                "email": "reinvite@example.com",
                "role": UserRole.CUSTOMER_USER,
                "customer_ids": [self.customer.id],
            },
        )
        self.assertEqual(first.status_code, status.HTTP_201_CREATED)
        first_id = first.data["id"]

        second = self._create_invitation_via_api(
            self.super_admin,
            {
                "email": "reinvite@example.com",
                "role": UserRole.CUSTOMER_USER,
                "customer_ids": [self.customer.id],
            },
        )
        self.assertEqual(second.status_code, status.HTTP_201_CREATED)

        first_inv = Invitation.objects.get(pk=first_id)
        self.assertIsNotNone(first_inv.revoked_at)
        self.assertEqual(first_inv.revoked_by, self.super_admin)

    def test_create_invitation_enqueues_email(self):
        before = NotificationLog.objects.filter(
            event_type=NotificationEventType.INVITATION_SENT
        ).count()
        self._create_invitation_via_api(
            self.super_admin,
            {
                "email": "enqueue@example.com",
                "role": UserRole.CUSTOMER_USER,
                "customer_ids": [self.customer.id],
            },
        )
        after = NotificationLog.objects.filter(
            event_type=NotificationEventType.INVITATION_SENT
        ).count()
        self.assertEqual(after - before, 1)

    # ---- Token security ---------------------------------------------------

    def test_token_is_hashed_at_rest_not_stored_raw(self):
        invitation, raw = self._make_invitation(
            role=UserRole.CUSTOMER_USER,
            email="hashed@example.com",
            created_by=self.super_admin,
            customers=[self.customer],
        )
        # The DB column does not contain the raw token anywhere.
        self.assertNotEqual(invitation.token_hash, raw)
        self.assertEqual(invitation.token_hash, hash_invitation_token(raw))
        self.assertFalse(
            Invitation.objects.filter(token_hash__contains=raw).exists()
        )

    # ---- Preview ----------------------------------------------------------

    def test_preview_returns_invitation_details_for_valid_token(self):
        invitation, raw = self._make_invitation(
            role=UserRole.COMPANY_ADMIN,
            email="preview@example.com",
            created_by=self.super_admin,
            companies=[self.company],
        )
        response = self.client.get(self.PREVIEW_URL, {"token": raw})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["email"], invitation.email)
        self.assertEqual(response.data["role"], UserRole.COMPANY_ADMIN)
        self.assertEqual(response.data["company_names"], [self.company.name])

    def test_preview_returns_410_for_expired_token(self):
        invitation, raw = self._make_invitation(
            role=UserRole.CUSTOMER_USER,
            email="expired@example.com",
            created_by=self.super_admin,
            customers=[self.customer],
        )
        invitation.expires_at = timezone.now() - timedelta(seconds=1)
        invitation.save(update_fields=["expires_at"])
        response = self.client.get(self.PREVIEW_URL, {"token": raw})
        self.assertEqual(response.status_code, status.HTTP_410_GONE)

    def test_preview_returns_410_for_revoked_token(self):
        invitation, raw = self._make_invitation(
            role=UserRole.CUSTOMER_USER,
            email="revoked@example.com",
            created_by=self.super_admin,
            customers=[self.customer],
        )
        invitation.revoked_at = timezone.now()
        invitation.revoked_by = self.super_admin
        invitation.save(update_fields=["revoked_at", "revoked_by"])
        response = self.client.get(self.PREVIEW_URL, {"token": raw})
        self.assertEqual(response.status_code, status.HTTP_410_GONE)

    def test_preview_returns_410_for_accepted_token(self):
        invitation, raw = self._make_invitation(
            role=UserRole.CUSTOMER_USER,
            email="accepted@example.com",
            created_by=self.super_admin,
            customers=[self.customer],
        )
        invitation.accepted_at = timezone.now()
        invitation.save(update_fields=["accepted_at"])
        response = self.client.get(self.PREVIEW_URL, {"token": raw})
        self.assertEqual(response.status_code, status.HTTP_410_GONE)

    def test_preview_returns_404_for_unknown_token(self):
        response = self.client.get(self.PREVIEW_URL, {"token": "definitely-not-a-real-token"})
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    # ---- Accept -----------------------------------------------------------

    def test_accept_marks_invitation_accepted_and_sets_accepted_by(self):
        invitation, raw = self._make_invitation(
            role=UserRole.CUSTOMER_USER,
            email="mark-accepted@example.com",
            created_by=self.super_admin,
            customers=[self.customer],
        )
        response = self.client.post(
            self.ACCEPT_URL,
            {"token": raw, "new_password": "AStrongPassword123!"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        invitation.refresh_from_db()
        self.assertIsNotNone(invitation.accepted_at)
        self.assertEqual(invitation.accepted_by.email, "mark-accepted@example.com")

    def test_accept_cannot_be_done_twice(self):
        invitation, raw = self._make_invitation(
            role=UserRole.CUSTOMER_USER,
            email="twice@example.com",
            created_by=self.super_admin,
            customers=[self.customer],
        )
        ok = self.client.post(
            self.ACCEPT_URL,
            {"token": raw, "new_password": "AStrongPassword123!"},
            format="json",
        )
        self.assertEqual(ok.status_code, status.HTTP_201_CREATED)
        again = self.client.post(
            self.ACCEPT_URL,
            {"token": raw, "new_password": "DifferentStrongPassword456!"},
            format="json",
        )
        self.assertEqual(again.status_code, status.HTTP_410_GONE)

    def test_accept_rejects_expired_token_with_410(self):
        invitation, raw = self._make_invitation(
            role=UserRole.CUSTOMER_USER,
            email="expired-accept@example.com",
            created_by=self.super_admin,
            customers=[self.customer],
        )
        invitation.expires_at = timezone.now() - timedelta(seconds=1)
        invitation.save(update_fields=["expires_at"])
        response = self.client.post(
            self.ACCEPT_URL,
            {"token": raw, "new_password": "AStrongPassword123!"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_410_GONE)

    def test_accept_rejects_revoked_token_with_410(self):
        invitation, raw = self._make_invitation(
            role=UserRole.CUSTOMER_USER,
            email="revoked-accept@example.com",
            created_by=self.super_admin,
            customers=[self.customer],
        )
        invitation.revoked_at = timezone.now()
        invitation.revoked_by = self.super_admin
        invitation.save(update_fields=["revoked_at", "revoked_by"])
        response = self.client.post(
            self.ACCEPT_URL,
            {"token": raw, "new_password": "AStrongPassword123!"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_410_GONE)

    def test_accept_validates_password_against_django_validators(self):
        invitation, raw = self._make_invitation(
            role=UserRole.CUSTOMER_USER,
            email="weak@example.com",
            created_by=self.super_admin,
            customers=[self.customer],
        )
        response = self.client.post(
            self.ACCEPT_URL,
            {"token": raw, "new_password": "password"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        invitation.refresh_from_db()
        self.assertIsNone(invitation.accepted_at)

    def test_accept_returns_user_exists_when_active_user_with_email_exists(self):
        # An active user already on file blocks accept with a structured 400.
        # Returning IntegrityError 500 here would white-screen the frontend.
        get_user_model().objects.create_user(
            email="duplicate-active@example.com",
            password="ExistingPassword123!",
            full_name="Existing User",
            role=UserRole.CUSTOMER_USER,
        )
        invitation, raw = self._make_invitation(
            role=UserRole.CUSTOMER_USER,
            email="duplicate-active@example.com",
            created_by=self.super_admin,
            customers=[self.customer],
        )
        response = self.client.post(
            self.ACCEPT_URL,
            {"token": raw, "new_password": "AStrongPassword123!"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data.get("detail"), "user_exists")
        self.assertIn("message", response.data)
        invitation.refresh_from_db()
        self.assertIsNone(invitation.accepted_at)

    def test_accept_returns_user_exists_when_soft_deleted_user_with_email_exists(self):
        # The unique email column on User collides regardless of is_active /
        # deleted_at, so a soft-deleted row would still trip create_user with
        # an IntegrityError. Pre-checking by email keeps the response clean.
        existing = get_user_model().objects.create_user(
            email="duplicate-soft-deleted@example.com",
            password="ExistingPassword123!",
            full_name="Soft Deleted",
            role=UserRole.CUSTOMER_USER,
        )
        existing.soft_delete()
        invitation, raw = self._make_invitation(
            role=UserRole.CUSTOMER_USER,
            email="duplicate-soft-deleted@example.com",
            created_by=self.super_admin,
            customers=[self.customer],
        )
        response = self.client.post(
            self.ACCEPT_URL,
            {"token": raw, "new_password": "AStrongPassword123!"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data.get("detail"), "user_exists")
        invitation.refresh_from_db()
        self.assertIsNone(invitation.accepted_at)

    # ---- Revoke -----------------------------------------------------------

    def test_revoke_marks_invitation_revoked(self):
        invitation, _raw = self._make_invitation(
            role=UserRole.CUSTOMER_USER,
            email="revoke-me@example.com",
            created_by=self.company_admin,
            customers=[self.customer],
        )
        self.authenticate(self.company_admin)
        response = self.client.post(self.revoke_url(invitation.id))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        invitation.refresh_from_db()
        self.assertIsNotNone(invitation.revoked_at)
        self.assertEqual(invitation.revoked_by, self.company_admin)

    def test_revoke_blocked_for_non_creator_non_super_admin(self):
        invitation, _raw = self._make_invitation(
            role=UserRole.CUSTOMER_USER,
            email="not-mine@example.com",
            created_by=self.company_admin,
            customers=[self.customer],
        )
        self.authenticate(self.other_company_admin)
        response = self.client.post(self.revoke_url(invitation.id))
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_revoke_cannot_revoke_accepted_invitation(self):
        invitation, raw = self._make_invitation(
            role=UserRole.CUSTOMER_USER,
            email="cant-revoke@example.com",
            created_by=self.super_admin,
            customers=[self.customer],
        )
        # Accept first
        accept = self.client.post(
            self.ACCEPT_URL,
            {"token": raw, "new_password": "AStrongPassword123!"},
            format="json",
        )
        self.assertEqual(accept.status_code, status.HTTP_201_CREATED)

        self.authenticate(self.super_admin)
        response = self.client.post(self.revoke_url(invitation.id))
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    # ---- List -------------------------------------------------------------

    def test_list_super_admin_sees_all_invitations(self):
        self._make_invitation(
            role=UserRole.CUSTOMER_USER,
            email="list-a@example.com",
            created_by=self.company_admin,
            customers=[self.customer],
        )
        self._make_invitation(
            role=UserRole.CUSTOMER_USER,
            email="list-b@example.com",
            created_by=self.other_company_admin,
            customers=[self.other_customer],
        )
        self.authenticate(self.super_admin)
        response = self.client.get(self.LIST_URL)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        emails = {row["email"] for row in response.data.get("results", response.data)}
        self.assertIn("list-a@example.com", emails)
        self.assertIn("list-b@example.com", emails)

    def test_list_company_admin_sees_only_own_scope(self):
        own_inv, _ = self._make_invitation(
            role=UserRole.CUSTOMER_USER,
            email="own@example.com",
            created_by=self.company_admin,
            customers=[self.customer],
        )
        own_inv.companies.add(self.company)
        other_inv, _ = self._make_invitation(
            role=UserRole.CUSTOMER_USER,
            email="other@example.com",
            created_by=self.other_company_admin,
            customers=[self.other_customer],
        )
        other_inv.companies.add(self.other_company)

        self.authenticate(self.company_admin)
        response = self.client.get(self.LIST_URL)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        emails = {row["email"] for row in response.data.get("results", response.data)}
        self.assertIn("own@example.com", emails)
        self.assertNotIn("other@example.com", emails)

    # ---- Status filter ----------------------------------------------------

    def _seed_status_fixture(self):
        # Returns (pending, accepted, revoked, expired) Invitation rows.
        pending, _ = self._make_invitation(
            role=UserRole.CUSTOMER_USER,
            email="pending@example.com",
            created_by=self.super_admin,
            customers=[self.customer],
        )
        accepted, _ = self._make_invitation(
            role=UserRole.CUSTOMER_USER,
            email="accepted@example.com",
            created_by=self.super_admin,
            customers=[self.customer],
        )
        accepted.accepted_at = timezone.now()
        accepted.save(update_fields=["accepted_at"])
        revoked, _ = self._make_invitation(
            role=UserRole.CUSTOMER_USER,
            email="revoked@example.com",
            created_by=self.super_admin,
            customers=[self.customer],
        )
        revoked.revoked_at = timezone.now()
        revoked.revoked_by = self.super_admin
        revoked.save(update_fields=["revoked_at", "revoked_by"])
        expired, _ = self._make_invitation(
            role=UserRole.CUSTOMER_USER,
            email="expired@example.com",
            created_by=self.super_admin,
            customers=[self.customer],
        )
        expired.expires_at = timezone.now() - timedelta(seconds=1)
        expired.save(update_fields=["expires_at"])
        return pending, accepted, revoked, expired

    def test_status_filter_pending_returns_only_pending(self):
        self._seed_status_fixture()
        self.authenticate(self.super_admin)
        response = self.client.get(self.LIST_URL, {"status": "PENDING"})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        emails = {row["email"] for row in response.data.get("results", response.data)}
        self.assertEqual(emails, {"pending@example.com"})

    def test_status_filter_accepted(self):
        self._seed_status_fixture()
        self.authenticate(self.super_admin)
        response = self.client.get(self.LIST_URL, {"status": "ACCEPTED"})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        emails = {row["email"] for row in response.data.get("results", response.data)}
        self.assertEqual(emails, {"accepted@example.com"})

    def test_status_filter_revoked(self):
        self._seed_status_fixture()
        self.authenticate(self.super_admin)
        response = self.client.get(self.LIST_URL, {"status": "REVOKED"})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        emails = {row["email"] for row in response.data.get("results", response.data)}
        self.assertEqual(emails, {"revoked@example.com"})

    def test_status_filter_expired(self):
        self._seed_status_fixture()
        self.authenticate(self.super_admin)
        response = self.client.get(self.LIST_URL, {"status": "EXPIRED"})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        emails = {row["email"] for row in response.data.get("results", response.data)}
        self.assertEqual(emails, {"expired@example.com"})

    def test_status_filter_multi_value(self):
        self._seed_status_fixture()
        self.authenticate(self.super_admin)
        response = self.client.get(self.LIST_URL, {"status": "PENDING,ACCEPTED"})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        emails = {row["email"] for row in response.data.get("results", response.data)}
        self.assertEqual(emails, {"pending@example.com", "accepted@example.com"})
