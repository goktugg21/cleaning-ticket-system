"""
Sprint 12C — pre-push hardening for contact promote-to-user.

Covers two locked product invariants plus the NL phone validator:

  A) Phone hardening — a plain Contact may have a blank phone, but
     promoting/linking/inviting it to a customer User REQUIRES a valid
     Dutch phone. Missing -> `contact_phone_required`; invalid NL format
     -> `contact_phone_invalid`. A valid phone is normalised to E.164 and
     propagated to the new User in invite mode.

  B) Cross-customer invariant — one customer-user belongs to exactly one
     customer. Linking an existing customer-user of customer B into
     customer A is blocked with `customer_user_cross_customer_forbidden`;
     same-customer (re)link stays idempotent. A single CUSTOMER_USER
     invitation may not bind two customers.
"""
from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, override_settings
from rest_framework import status
from rest_framework.test import APIRequestFactory, APITestCase

from accounts.invitations import Invitation
from accounts.models import UserRole
from accounts.serializers_invitations import InvitationCreateSerializer
from customers.models import CustomerUserMembership
from customers.phone import normalize_nl_phone

from ._promote_base import PromoteContactFixtureMixin

User = get_user_model()

ACCEPT_URL = "/api/auth/invitations/accept/"


# ===========================================================================
# NL phone normalizer (unit)
# ===========================================================================
class NLPhoneNormalizerTests(SimpleTestCase):
    def test_accepts_and_normalizes_common_nl_formats(self):
        cases = {
            "+31612345678": "+31612345678",
            "+31 6 1234 5678": "+31612345678",
            "0031612345678": "+31612345678",
            "0031 6 1234 5678": "+31612345678",
            "0612345678": "+31612345678",
            "06 12345678": "+31612345678",
            "06-12345678": "+31612345678",
            "020 123 4567": "+31201234567",  # landline
            "(020) 123-4567": "+31201234567",
        }
        for raw, expected in cases.items():
            self.assertEqual(normalize_nl_phone(raw), expected, raw)

    def test_rejects_missing_and_invalid(self):
        for raw in (
            None,
            "",
            "   ",
            "not-a-phone",
            "12345",
            "06123456",  # too short (8 significant digits)
            "0612345678901",  # too long
            "+31012345678",  # +31 then a trunk 0 -> malformed
            "+441234567890",  # non-NL country code
            "00316123",  # too short
        ):
            self.assertIsNone(normalize_nl_phone(raw), repr(raw))


# ===========================================================================
# A) Phone hardening on promotion
# ===========================================================================
class PromotionPhoneTests(PromoteContactFixtureMixin, APITestCase):
    def setUp(self):
        super().setUp()
        self.authenticate(self.super_admin)

    def _link_building(self, contact):
        self.client.patch(
            self.contact_detail_url(contact.id),
            {"building_ids": [self.building.id]},
            format="json",
        )

    def test_missing_phone_blocks_promotion(self):
        contact = self.make_contact(
            full_name="No Phone", email="nophone@example.com", phone=""
        )
        self._link_building(contact)
        resp = self.client.post(self.promote_url(contact.id), {}, format="json")
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(resp.data["code"], "contact_phone_required")

    def test_invalid_phone_blocks_promotion(self):
        contact = self.make_contact(
            full_name="Bad Phone",
            email="badphone@example.com",
            phone="not-a-phone",
        )
        self._link_building(contact)
        resp = self.client.post(self.promote_url(contact.id), {}, format="json")
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(resp.data["code"], "contact_phone_invalid")

    def test_valid_phone_promotes_and_normalizes_contact(self):
        # Link mode: an existing CUSTOMER_USER with a matching email.
        self.make_user("haz-phone@example.com", UserRole.CUSTOMER_USER)
        contact = self.make_contact(
            full_name="Has Phone",
            email="haz-phone@example.com",
            phone="06 12345678",  # un-normalised but valid
        )
        self._link_building(contact)
        resp = self.client.post(self.promote_url(contact.id), {}, format="json")
        self.assertEqual(resp.status_code, status.HTTP_200_OK, resp.data)
        self.assertEqual(resp.data["mode"], "linked")
        contact.refresh_from_db()
        self.assertEqual(contact.phone, "+31612345678")

    def test_phone_supplied_in_body_promotes_blank_contact(self):
        self.make_user("bodyphone@example.com", UserRole.CUSTOMER_USER)
        contact = self.make_contact(
            full_name="Body Phone", email="bodyphone@example.com", phone=""
        )
        self._link_building(contact)
        resp = self.client.post(
            self.promote_url(contact.id),
            {"phone": "06-1234 5678"},
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK, resp.data)
        contact.refresh_from_db()
        self.assertEqual(contact.phone, "+31612345678")

    def test_plain_contact_create_allows_blank_phone(self):
        # CRUD path is unchanged: no phone required, no validation.
        resp = self.client.post(
            self.contact_list_url(),
            {"full_name": "Phonebook Only"},
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED, resp.data)
        self.assertEqual(resp.data["phone"], "")


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
class PromotionInvitePhoneTests(PromoteContactFixtureMixin, APITestCase):
    def setUp(self):
        super().setUp()
        self.authenticate(self.super_admin)

    def test_invite_normalizes_phone_and_links_contact_on_accept(self):
        # The User model carries no phone field; a customer user's phone
        # lives on the linked Contact, validated/normalised at promote
        # time. Assert the contact is normalised and linked on accept.
        contact = self.make_contact(
            full_name="Invite Phone",
            email="invitephone@example.com",
            phone="06 1234 5678",
        )
        self.client.patch(
            self.contact_detail_url(contact.id),
            {"building_ids": [self.building.id]},
            format="json",
        )
        # A plain contact edit does NOT normalise the phone (validation
        # is a promotion-time gate); promotion does.
        _resp, raw_token = self.promote_and_capture_raw(
            contact.id, {"building_ids": [self.building.id]}
        )
        self.assertIsNotNone(raw_token)
        contact.refresh_from_db()
        self.assertEqual(contact.phone, "+31612345678")

        self.client.force_authenticate(user=None)
        accept = self.client.post(
            ACCEPT_URL,
            {"token": raw_token, "new_password": self.password},
            format="json",
        )
        self.assertEqual(accept.status_code, status.HTTP_201_CREATED, accept.data)
        new_user = User.objects.get(email__iexact="invitephone@example.com")
        contact.refresh_from_db()
        self.assertEqual(contact.user_id, new_user.id)
        self.assertEqual(contact.phone, "+31612345678")


# ===========================================================================
# B) Cross-customer invariant
# ===========================================================================
class PromotionCrossCustomerTests(PromoteContactFixtureMixin, APITestCase):
    def setUp(self):
        super().setUp()
        self.authenticate(self.super_admin)

    def test_link_user_of_other_customer_is_forbidden(self):
        # A CUSTOMER_USER already a member of customer B (other_customer).
        dual = self.make_user("dual@example.com", UserRole.CUSTOMER_USER)
        CustomerUserMembership.objects.create(
            customer=self.other_customer, user=dual
        )
        contact = self.make_contact(
            full_name="Dual", email="dual@example.com"
        )
        self.client.patch(
            self.contact_detail_url(contact.id),
            {"building_ids": [self.building.id]},
            format="json",
        )
        resp = self.client.post(self.promote_url(contact.id), {}, format="json")
        self.assertEqual(resp.status_code, status.HTTP_409_CONFLICT)
        self.assertEqual(
            resp.data["code"], "customer_user_cross_customer_forbidden"
        )
        # No membership was created for customer A.
        self.assertFalse(
            CustomerUserMembership.objects.filter(
                customer=self.customer, user=dual
            ).exists()
        )

    def test_same_customer_relink_is_idempotent(self):
        # Already a member of THIS customer -> re-promote is allowed.
        spare = self.make_user("spare-same@example.com", UserRole.CUSTOMER_USER)
        CustomerUserMembership.objects.create(
            customer=self.customer, user=spare
        )
        contact = self.make_contact(
            full_name="Same Cust", email="spare-same@example.com"
        )
        self.client.patch(
            self.contact_detail_url(contact.id),
            {"building_ids": [self.building.id]},
            format="json",
        )
        resp = self.client.post(self.promote_url(contact.id), {}, format="json")
        self.assertEqual(resp.status_code, status.HTTP_200_OK, resp.data)
        self.assertEqual(resp.data["mode"], "linked")
        self.assertEqual(
            CustomerUserMembership.objects.filter(
                customer=self.customer, user=spare
            ).count(),
            1,
        )

    def test_public_invitation_serializer_rejects_customer_user(self):
        # Sprint 3 — contact-first enforcement. The public invitation
        # serializer rejects ANY CUSTOMER_USER invite outright (regardless
        # of how many customers are supplied); customer users come only
        # from promoting a Contact. The one-customer cross-customer
        # invariant for the promotion path is covered by
        # test_link_user_of_other_customer_is_forbidden above.
        factory = APIRequestFactory()
        request = factory.post("/api/auth/invitations/")
        request.user = self.super_admin
        serializer = InvitationCreateSerializer(
            data={
                "email": "twocust@example.com",
                "full_name": "Two Cust",
                "role": UserRole.CUSTOMER_USER,
                "customer_ids": [self.customer.id, self.other_customer.id],
            },
            context={"request": request},
        )
        self.assertFalse(serializer.is_valid())
        self.assertIn("role", serializer.errors)
        self.assertEqual(
            serializer.errors["role"][0].code,
            "customer_user_must_come_from_contact",
        )

    def test_promote_still_creates_customer_user_invitation(self):
        # Regression — the Sprint 3 serializer reject must NOT affect
        # promote-to-user, which creates the CUSTOMER_USER invitation
        # MODEL-DIRECT (bypassing the serializer). Promoting a contact
        # still produces a CUSTOMER_USER invitation linked to the contact.
        contact = self.make_contact(
            full_name="Promote Me",
            email="promote-me@example.com",
            phone="+31612345678",
        )
        self.client.patch(
            self.contact_detail_url(contact.id),
            {"building_ids": [self.building.id]},
            format="json",
        )
        resp = self.client.post(self.promote_url(contact.id), {}, format="json")
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED, resp.data)
        self.assertEqual(resp.data["mode"], "invited")
        self.assertTrue(
            Invitation.objects.filter(
                role=UserRole.CUSTOMER_USER, contact=contact
            ).exists()
        )
