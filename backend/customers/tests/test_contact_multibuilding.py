"""
Sprint 12B Batch 3 — Contact multi-building (`ContactBuildingLink`)
coverage.

A Contact can serve multiple buildings under the same customer. The
serializer's `building_ids` (write-only) replaces the link set; the
read projection is `linked_building_ids`. The legacy single-building
`building` FK is back-compat only — `create()` ensures a link exists
for it (runtime equivalent of the 12B migration backfill).

Scenarios 1-6, 8 (multi-building + contact-is-not-a-user) live here;
scenario 7 (contact_type / is_primary) lives in test_contact_types.py.
"""
from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from rest_framework import status
from rest_framework.test import APITestCase

from customers.models import (
    Contact,
    ContactBuildingLink,
    CustomerUserBuildingAccess,
    CustomerUserMembership,
)

from ._promote_base import PromoteContactFixtureMixin


class ContactMultiBuildingTests(PromoteContactFixtureMixin, APITestCase):
    def setUp(self):
        super().setUp()
        self.authenticate(self.super_admin)

    # 1 — create with multiple building_ids ------------------------------
    def test_create_with_multiple_building_ids(self):
        response = self.client.post(
            self.contact_list_url(),
            {
                "full_name": "Multi Building",
                "building_ids": [self.building.id, self.building2.id],
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertCountEqual(
            response.data["linked_building_ids"],
            [self.building.id, self.building2.id],
        )
        contact = Contact.objects.get(pk=response.data["id"])
        self.assertEqual(contact.building_links.count(), 2)

    # 2 — legacy single-building create backfills a link -----------------
    def test_legacy_single_building_create_ensures_link(self):
        response = self.client.post(
            self.contact_list_url(),
            {"full_name": "Legacy Anchor", "building": self.building.id},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["building"], self.building.id)
        contact = Contact.objects.get(pk=response.data["id"])
        self.assertTrue(
            ContactBuildingLink.objects.filter(
                contact=contact, building=self.building
            ).exists()
        )

    # 3 — duplicate ids in building_ids dedup to one link ----------------
    def test_duplicate_building_ids_dedup_to_one_link(self):
        response = self.client.post(
            self.contact_list_url(),
            {
                "full_name": "Dedup",
                "building_ids": [self.building.id, self.building.id],
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        contact = Contact.objects.get(pk=response.data["id"])
        self.assertEqual(
            contact.building_links.filter(building=self.building).count(), 1
        )

    def test_duplicate_link_model_level_raises_integrity_error(self):
        contact = self.make_contact(full_name="Direct Dup")
        ContactBuildingLink.objects.create(
            contact=contact, building=self.building
        )
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                ContactBuildingLink.objects.create(
                    contact=contact, building=self.building
                )

    # 4 — building outside customer is rejected --------------------------
    def test_building_ids_outside_customer_rejected(self):
        response = self.client.post(
            self.contact_list_url(),
            {
                "full_name": "Cross Tenant",
                "building_ids": [self.other_building.id],
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("building_ids", response.data)

    # 5 — serializer exposes read projection, hides write-only field -----
    def test_detail_exposes_linked_building_ids_and_hides_building_ids(self):
        create = self.client.post(
            self.contact_list_url(),
            {
                "full_name": "Read Projection",
                "building_ids": [self.building.id, self.building2.id],
            },
            format="json",
        )
        self.assertEqual(create.status_code, status.HTTP_201_CREATED)
        contact_id = create.data["id"]

        detail = self.client.get(self.contact_detail_url(contact_id))
        self.assertEqual(detail.status_code, status.HTTP_200_OK)
        self.assertIn("linked_building_ids", detail.data)
        self.assertCountEqual(
            detail.data["linked_building_ids"],
            [self.building.id, self.building2.id],
        )
        # building_ids is write-only — never serialized on read.
        self.assertNotIn("building_ids", detail.data)

    # 6 — PATCH building_ids is a replace-set ----------------------------
    def test_patch_building_ids_replace_set(self):
        contact = self.make_contact(full_name="Replace Set")
        ContactBuildingLink.objects.create(
            contact=contact, building=self.building
        )
        ContactBuildingLink.objects.create(
            contact=contact, building=self.building2
        )

        response = self.client.patch(
            self.contact_detail_url(contact.id),
            {"building_ids": [self.building2.id]},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertCountEqual(
            list(
                contact.building_links.values_list("building_id", flat=True)
            ),
            [self.building2.id],
        )

    # 8 — contact-is-not-a-user is preserved across multi-building -------
    def test_multibuilding_create_does_not_create_user_or_membership(self):
        user_before = get_user_model().objects.count()
        membership_before = CustomerUserMembership.objects.count()
        access_before = CustomerUserBuildingAccess.objects.count()

        response = self.client.post(
            self.contact_list_url(),
            {
                "full_name": "Phonebook Only",
                "email": "phonebook-only@cust-a.example",
                "building_ids": [self.building.id, self.building2.id],
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        self.assertEqual(get_user_model().objects.count(), user_before)
        self.assertEqual(
            CustomerUserMembership.objects.count(), membership_before
        )
        self.assertEqual(
            CustomerUserBuildingAccess.objects.count(), access_before
        )

    def test_user_cannot_be_set_via_create_or_patch_body(self):
        # Create with a smuggled "user" id — must be ignored.
        create = self.client.post(
            self.contact_list_url(),
            {
                "full_name": "No User Smuggle",
                "user": self.customer_user.id,
            },
            format="json",
        )
        self.assertEqual(create.status_code, status.HTTP_201_CREATED)
        contact = Contact.objects.get(pk=create.data["id"])
        self.assertIsNone(contact.user_id)

        # PATCH with a smuggled "user" id — also ignored.
        patch = self.client.patch(
            self.contact_detail_url(contact.id),
            {"user": self.customer_user.id},
            format="json",
        )
        self.assertEqual(patch.status_code, status.HTTP_200_OK)
        contact.refresh_from_db()
        self.assertIsNone(contact.user_id)
