"""
Sprint 12B Batch 3 — Contact promote-to-user endpoint.

POST /api/customers/<customer_id>/contacts/<contact_id>/promote-to-user/

Two modes (`customers.promotion.promote_contact`):

  * LINK — a matching active CUSTOMER_USER already exists. Materialise
    the membership + per-building CUBA rows now and link `Contact.user`.
    HTTP 200, body `mode == "linked"`.
  * INVITE — no User yet. Seed a pending `Invitation` tied to the
    contact; the invitation email is sent after the atomic commit; the
    accept handler creates the User + membership + CUBA + links the
    contact. HTTP 201, body `mode == "invited"`.

Conflicts raise `PromotionError` with a stable `code` surfaced as the
JSON `code` field. Permission / tenancy is the provider-only gate
`IsSuperAdminOrCompanyAdminForCompany` plus the H-7 CCA-grant policy on
the provider company.
"""
from django.contrib.auth import get_user_model
from django.test import override_settings
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from accounts.invitations import Invitation, InvitationStatus
from accounts.models import UserRole
from customers.models import (
    Contact,
    CustomerUserBuildingAccess,
    CustomerUserMembership,
)

from ._promote_base import PromoteContactFixtureMixin

User = get_user_model()

ACCEPT_URL = "/api/auth/invitations/accept/"


# ===========================================================================
# LINK MODE (9-11)
# ===========================================================================


class PromoteLinkModeTests(PromoteContactFixtureMixin, APITestCase):
    def setUp(self):
        super().setUp()
        # A CUSTOMER_USER that exists but is NOT yet a member of customer A.
        self.spare = self.make_user("spare@example.com", UserRole.CUSTOMER_USER)
        self.authenticate(self.super_admin)

    def _linked_contact(self, building_ids=None):
        contact = self.make_contact(
            full_name="Spare Person", email="spare@example.com"
        )
        self.client.patch(
            self.contact_detail_url(contact.id),
            {"building_ids": building_ids or [self.building.id]},
            format="json",
        )
        contact.refresh_from_db()
        return contact

    # 9 — existing active CUSTOMER_USER is linked ------------------------
    def test_promote_existing_customer_user_links(self):
        contact = self._linked_contact()
        response = self.client.post(
            self.promote_url(contact.id), {}, format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["mode"], "linked")
        self.assertEqual(response.data["user_id"], self.spare.id)

        membership = CustomerUserMembership.objects.get(
            customer=self.customer, user=self.spare
        )
        self.assertTrue(
            CustomerUserBuildingAccess.objects.filter(
                membership=membership, building=self.building
            ).exists()
        )
        contact.refresh_from_db()
        self.assertEqual(contact.user_id, self.spare.id)

        detail = self.client.get(self.contact_detail_url(contact.id))
        self.assertEqual(detail.data["promotion_status"], "linked")

    # 10 — idempotent re-promote, no duplicate rows ----------------------
    def test_repromote_is_idempotent(self):
        contact = self._linked_contact()
        first = self.client.post(self.promote_url(contact.id), {}, format="json")
        self.assertEqual(first.status_code, status.HTTP_200_OK)

        membership_count = CustomerUserMembership.objects.filter(
            customer=self.customer, user=self.spare
        ).count()
        access_count = CustomerUserBuildingAccess.objects.filter(
            membership__customer=self.customer,
            membership__user=self.spare,
        ).count()

        second = self.client.post(
            self.promote_url(contact.id), {}, format="json"
        )
        self.assertEqual(second.status_code, status.HTTP_200_OK)
        self.assertEqual(second.data["mode"], "linked")

        self.assertEqual(
            CustomerUserMembership.objects.filter(
                customer=self.customer, user=self.spare
            ).count(),
            membership_count,
        )
        self.assertEqual(
            CustomerUserBuildingAccess.objects.filter(
                membership__customer=self.customer,
                membership__user=self.spare,
            ).count(),
            access_count,
        )

    # 11 — default building set from contact's links when body omits them
    def test_promote_defaults_buildings_from_contact_links(self):
        contact = self._linked_contact(
            building_ids=[self.building.id, self.building2.id]
        )
        # No building_ids in the body — service uses the contact's links.
        response = self.client.post(
            self.promote_url(contact.id), {}, format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        membership = CustomerUserMembership.objects.get(
            customer=self.customer, user=self.spare
        )
        granted = set(
            CustomerUserBuildingAccess.objects.filter(
                membership=membership
            ).values_list("building_id", flat=True)
        )
        self.assertEqual(granted, {self.building.id, self.building2.id})


# ===========================================================================
# INVITE MODE (12-14)
# ===========================================================================


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
class PromoteInviteModeTests(PromoteContactFixtureMixin, APITestCase):
    def setUp(self):
        super().setUp()
        self.authenticate(self.super_admin)

    # 12 — brand-new email seeds an invitation, sends one email ----------
    def test_promote_new_email_invites(self):
        contact = self.make_contact(
            full_name="New Person", email="newperson@example.com"
        )
        response, raw_token = self.promote_and_capture_raw(
            contact.id,
            {
                "building_ids": [self.building.id],
                "access_role": "CUSTOMER_USER",
            },
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["mode"], "invited")
        self.assertIsNotNone(raw_token)

        # No active User was created.
        self.assertFalse(
            User.objects.filter(email__iexact="newperson@example.com").exists()
        )

        invitation = Invitation.objects.get(contact=contact)
        self.assertEqual(invitation.role, UserRole.CUSTOMER_USER)
        self.assertEqual(invitation.customer_access_role, "CUSTOMER_USER")
        self.assertIn(self.customer, list(invitation.customers.all()))
        self.assertIn(self.building, list(invitation.buildings.all()))

        detail = self.client.get(self.contact_detail_url(contact.id))
        self.assertEqual(detail.data["promotion_status"], "invited")

    # 13 — accepting the invitation creates the user + membership + CUBA -
    def test_accept_invitation_creates_user_and_links_contact(self):
        contact = self.make_contact(
            full_name="New Person", email="newperson@example.com"
        )
        _resp, raw_token = self.promote_and_capture_raw(
            contact.id,
            {"building_ids": [self.building.id], "access_role": "CUSTOMER_USER"},
        )
        self.assertIsNotNone(raw_token)

        # Accept is unauthenticated.
        self.client.force_authenticate(user=None)
        accept = self.client.post(
            ACCEPT_URL,
            {"token": raw_token, "new_password": self.password},
            format="json",
        )
        self.assertEqual(accept.status_code, status.HTTP_201_CREATED)

        new_user = User.objects.get(email__iexact="newperson@example.com")
        self.assertEqual(new_user.role, UserRole.CUSTOMER_USER)
        membership = CustomerUserMembership.objects.get(
            customer=self.customer, user=new_user
        )
        access = CustomerUserBuildingAccess.objects.get(
            membership=membership, building=self.building
        )
        self.assertEqual(
            access.access_role,
            CustomerUserBuildingAccess.AccessRole.CUSTOMER_USER,
        )

        contact.refresh_from_db()
        self.assertEqual(contact.user_id, new_user.id)

        self.authenticate(self.super_admin)
        detail = self.client.get(self.contact_detail_url(contact.id))
        self.assertEqual(detail.data["promotion_status"], "linked")

    # 14 — re-invite is idempotent: one pending invite, no second email --
    def test_repromote_new_email_does_not_resend(self):
        contact = self.make_contact(
            full_name="New Person", email="newperson@example.com"
        )
        first, first_raw = self.promote_and_capture_raw(
            contact.id, {"building_ids": [self.building.id]}
        )
        self.assertEqual(first.status_code, status.HTTP_201_CREATED)
        self.assertIsNotNone(first_raw)

        second, second_raw = self.promote_and_capture_raw(
            contact.id, {"building_ids": [self.building.id]}
        )
        self.assertIn(
            second.status_code,
            (status.HTTP_200_OK, status.HTTP_201_CREATED),
        )
        self.assertEqual(second.data["mode"], "invited")
        self.assertEqual(second.data.get("detail"), "already_invited")
        # No second email sent.
        self.assertIsNone(second_raw)

        pending = Invitation.objects.filter(
            contact=contact,
            accepted_at__isnull=True,
            revoked_at__isnull=True,
        )
        self.assertEqual(
            pending.filter(expires_at__gt=timezone.now()).count(),
            1,
        )


# ===========================================================================
# CONFLICTS (15-19)
# ===========================================================================


class PromoteConflictTests(PromoteContactFixtureMixin, APITestCase):
    def setUp(self):
        super().setUp()
        self.authenticate(self.super_admin)

    # 15 — provider-side email -> email_belongs_to_non_customer_user -----
    def test_provider_side_email_conflict(self):
        contact = self.make_contact(
            full_name="Provider Person", email=self.company_admin.email
        )
        response = self.client.post(
            self.promote_url(contact.id), {}, format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            response.data["code"], "email_belongs_to_non_customer_user"
        )

    # 16 — inactive / soft-deleted user -> user_inactive -----------------
    def test_inactive_user_conflict(self):
        dead = self.make_user("dead-cu@example.com", UserRole.CUSTOMER_USER)
        dead.soft_delete()
        contact = self.make_contact(
            full_name="Dead Person", email="dead-cu@example.com"
        )
        response = self.client.post(
            self.promote_url(contact.id), {}, format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data["code"], "user_inactive")

    # 17 — missing email -> contact_email_required -----------------------
    def test_missing_email_conflict(self):
        contact = self.make_contact(full_name="No Email", email="")
        response = self.client.post(
            self.promote_url(contact.id), {}, format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data["code"], "contact_email_required")

    # 18 — building not linked -> building_not_linked --------------------
    def test_building_not_linked_conflict(self):
        contact = self.make_contact(
            full_name="Cross Building", email="cross-building@example.com"
        )
        response = self.client.post(
            self.promote_url(contact.id),
            {"building_ids": [self.other_building.id]},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data["code"], "building_not_linked")

    # 19 — already promoted to a different user -> contact_already_promoted
    def test_already_promoted_to_different_user_conflict(self):
        user_a = self.make_user("user-a-link@example.com", UserRole.CUSTOMER_USER)
        user_b = self.make_user("user-b-link@example.com", UserRole.CUSTOMER_USER)
        contact = self.make_contact(
            full_name="Already Promoted", email=user_b.email, user=user_a
        )
        response = self.client.post(
            self.promote_url(contact.id), {}, format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data["code"], "contact_already_promoted")

    # 19b — already promoted, then email edited to a BRAND-NEW address and
    # re-promoted: the invite-mode path must also reject (no spurious second
    # invitation for a different identity).
    def test_already_promoted_then_new_email_invite_path_conflict(self):
        user_a = self.make_user("promoted-a@example.com", UserRole.CUSTOMER_USER)
        contact = self.make_contact(
            full_name="Promoted Then Renamed",
            email="brand-new-nobody@example.com",  # matches NO existing user
            user=user_a,
        )
        response = self.client.post(
            self.promote_url(contact.id), {}, format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data["code"], "contact_already_promoted")
        # And no stray invitation was created for the contact.
        self.assertFalse(Invitation.objects.filter(contact=contact).exists())


# ===========================================================================
# PERMISSIONS / TENANCY (20-24)
# ===========================================================================


class PromotePermissionTests(PromoteContactFixtureMixin, APITestCase):
    # 20 / 9 — SA allowed is covered in PromoteLinkModeTests; here we
    # confirm CA-in-own-company succeeds.
    def test_company_admin_can_promote_in_own_company(self):
        spare = self.make_user("ca-spare@example.com", UserRole.CUSTOMER_USER)
        contact = self.make_contact(
            full_name="CA Spare", email="ca-spare@example.com"
        )
        self.authenticate(self.company_admin)
        response = self.client.post(
            self.promote_url(contact.id),
            {"building_ids": [self.building.id]},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["mode"], "linked")
        self.assertEqual(response.data["user_id"], spare.id)

    # 21 — CA cross-company blocked --------------------------------------
    def test_company_admin_cross_company_blocked(self):
        contact = self.make_contact(
            customer=self.other_customer, full_name="B Contact"
        )
        self.authenticate(self.company_admin)
        response = self.client.post(
            self.promote_url(contact.id, customer_id=self.other_customer.id),
            {},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    # 22 — BM / STAFF / CUSTOMER_USER all 403 ----------------------------
    def test_building_manager_blocked(self):
        contact = self.make_contact(full_name="BM Target")
        self.authenticate(self.manager)
        response = self.client.post(
            self.promote_url(contact.id), {}, format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_staff_blocked(self):
        contact = self.make_contact(full_name="Staff Target")
        self.authenticate(self.staff)
        response = self.client.post(
            self.promote_url(contact.id), {}, format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_customer_user_blocked(self):
        contact = self.make_contact(full_name="CU Target")
        self.authenticate(self.customer_user)
        response = self.client.post(
            self.promote_url(contact.id), {}, format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    # 23 — cross-customer contact id smuggling -> 404 --------------------
    def test_cross_customer_id_smuggling_returns_404(self):
        other_contact = self.make_contact(
            customer=self.other_customer, full_name="Other Customer Contact"
        )
        self.authenticate(self.super_admin)
        response = self.client.post(
            self.promote_url(other_contact.id, customer_id=self.customer.id),
            {},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    # 24 — H-7 CCA-grant policy ------------------------------------------
    def test_h7_company_admin_cca_grant_forbidden_when_policy_off(self):
        self.company.provider_admin_may_manage_customer_company_admins = False
        self.company.save(
            update_fields=["provider_admin_may_manage_customer_company_admins"]
        )
        spare = self.make_user("cca-spare@example.com", UserRole.CUSTOMER_USER)
        contact = self.make_contact(
            full_name="CCA Spare", email="cca-spare@example.com"
        )
        self.authenticate(self.company_admin)
        response = self.client.post(
            self.promote_url(contact.id),
            {
                "building_ids": [self.building.id],
                "access_role": "CUSTOMER_COMPANY_ADMIN",
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(response.data["code"], "cca_grant_forbidden")
        # SUPER_ADMIN with the same policy off still succeeds (link mode).
        self.authenticate(self.super_admin)
        sa_response = self.client.post(
            self.promote_url(contact.id),
            {
                "building_ids": [self.building.id],
                "access_role": "CUSTOMER_COMPANY_ADMIN",
            },
            format="json",
        )
        self.assertEqual(sa_response.status_code, status.HTTP_200_OK)
        self.assertEqual(sa_response.data["mode"], "linked")
        self.assertEqual(sa_response.data["user_id"], spare.id)
        membership = CustomerUserMembership.objects.get(
            customer=self.customer, user=spare
        )
        # SoT Addendum A.1 — Customer Company Admin is now the company-wide
        # membership flag, not a per-building access row. A CCA promote
        # routes to the flag and creates NO per-building CCA CUBA row.
        self.assertTrue(membership.is_company_admin)
        self.assertFalse(
            CustomerUserBuildingAccess.objects.filter(
                membership=membership,
                access_role=(
                    CustomerUserBuildingAccess.AccessRole.CUSTOMER_COMPANY_ADMIN
                ),
            ).exists()
        )
