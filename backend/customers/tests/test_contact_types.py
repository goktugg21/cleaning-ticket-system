"""
Sprint 12B Batch 3 — Contact `contact_type` taxonomy + `is_primary`
flag (scenario 7).
"""
from rest_framework import status
from rest_framework.test import APITestCase

from customers.models import Contact, ContactType

from ._promote_base import PromoteContactFixtureMixin


class ContactTypeTests(PromoteContactFixtureMixin, APITestCase):
    def setUp(self):
        super().setUp()
        self.authenticate(self.super_admin)

    def test_create_with_contact_type_and_is_primary(self):
        response = self.client.post(
            self.contact_list_url(),
            {
                "full_name": "Billing Lead",
                "contact_type": ContactType.BILLING,
                "is_primary": True,
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["contact_type"], ContactType.BILLING)
        self.assertTrue(response.data["is_primary"])

        contact = Contact.objects.get(pk=response.data["id"])
        self.assertEqual(contact.contact_type, ContactType.BILLING)
        self.assertTrue(contact.is_primary)

    def test_default_create_uses_general_type_and_not_primary(self):
        response = self.client.post(
            self.contact_list_url(),
            {"full_name": "Plain Contact"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["contact_type"], ContactType.GENERAL)
        self.assertFalse(response.data["is_primary"])

        contact = Contact.objects.get(pk=response.data["id"])
        self.assertEqual(contact.contact_type, ContactType.GENERAL)
        self.assertFalse(contact.is_primary)
