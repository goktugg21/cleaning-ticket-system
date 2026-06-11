"""
M2 P3 — customer-side ticket payload extension (Step 5).

Pins:
  - CUSTOMER_USER viewers see a resolver-filtered `credentials` +
    `properties` list on each assigned-staff entry, scoped to the
    ticket's customer.
  - RESIDENCE_PERMIT entries expose ONLY {type, permit_number,
    expiry_date, document_url?}; the document_url appears iff the
    photocopy rule passes. VCA entries expose {type, expiry_date,
    document_url?}. EU_NATIONAL_ID can never appear.
  - Provider viewers get a payload byte-identical to pre-M2: NO
    credentials / properties keys.
  - The anonymous-collapse behaviour (all three show_assigned_staff_*
    flags off) is unchanged.
  - The payload's document_url actually downloads for the customer
    (end-to-end chain through the Step-3 endpoint).
"""
from __future__ import annotations

import tempfile
from datetime import date

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from rest_framework import status
from rest_framework.test import APITestCase

from accounts.models import (
    CredentialCustomerVisibility,
    CustomProfileProperty,
    PropertyCustomerVisibility,
    StaffCredential,
    StaffProfile,
    UserRole,
    VisibilityLevel,
)
from buildings.models import BuildingStaffVisibility
from test_utils import TenantFixtureMixin
from tickets.models import TicketStaffAssignment

PDF_BYTES = b"%PDF-1.4 payload test"

_MEDIA_ROOT = tempfile.mkdtemp(prefix="m2p3-payload-media-")


@override_settings(MEDIA_ROOT=_MEDIA_ROOT)
class TicketPayloadCredentialTests(TenantFixtureMixin, APITestCase):
    def setUp(self):
        super().setUp()
        self.staff_a = self.make_user("staff-a@example.com", UserRole.STAFF)
        self.profile_a = StaffProfile.objects.create(
            user=self.staff_a, phone="0612345678"
        )
        BuildingStaffVisibility.objects.create(
            user=self.staff_a, building=self.building
        )
        TicketStaffAssignment.objects.create(
            ticket=self.ticket, user=self.staff_a
        )

        # Residence permit: customer-visible fields + photocopy allowed.
        self.residence_permit = StaffCredential.objects.create(
            staff_profile=self.profile_a,
            credential_type=StaffCredential.CredentialType.RESIDENCE_PERMIT,
            permit_number="RP-42",
            expiry_date=date(2027, 3, 1),
            visibility_level=VisibilityLevel.CUSTOMER_VISIBLE,
            document_customer_visible=True,
        )
        self._attach_document(self.residence_permit, "permit.pdf")
        CredentialCustomerVisibility.objects.create(
            credential=self.residence_permit, customer=self.customer
        )

        # Granted, customer-visible VCA.
        self.vca_granted = StaffCredential.objects.create(
            staff_profile=self.profile_a,
            credential_type=StaffCredential.CredentialType.VCA,
            expiry_date=date(2026, 12, 31),
            visibility_level=VisibilityLevel.CUSTOMER_VISIBLE,
        )
        self._attach_document(self.vca_granted, "vca.pdf")
        CredentialCustomerVisibility.objects.create(
            credential=self.vca_granted, customer=self.customer
        )

        # Provider-only VCA — never reaches the customer payload.
        self.vca_provider_only = StaffCredential.objects.create(
            staff_profile=self.profile_a,
            credential_type=StaffCredential.CredentialType.VCA,
            expiry_date=date(2030, 1, 1),
            visibility_level=VisibilityLevel.PROVIDER_ONLY,
        )

        # EU national ID — pinned to PA_SA_ONLY by the model layer.
        self.eu_id = StaffCredential.objects.create(
            staff_profile=self.profile_a,
            credential_type=StaffCredential.CredentialType.EU_NATIONAL_ID,
            permit_number="NL-ID-1",
        )

        # Properties: one shared with the customer, one provider-internal.
        self.prop_shared = CustomProfileProperty.objects.create(
            user=self.staff_a,
            name="Diploma",
            value="HBO Facility Management",
            visibility_level=VisibilityLevel.CUSTOMER_VISIBLE,
        )
        PropertyCustomerVisibility.objects.create(
            property=self.prop_shared, customer=self.customer
        )
        self.prop_hidden = CustomProfileProperty.objects.create(
            user=self.staff_a,
            name="Salary band",
            value="B3",
            visibility_level=VisibilityLevel.PA_SA_ONLY,
        )

    def _attach_document(self, credential, name):
        credential.document = SimpleUploadedFile(
            name, PDF_BYTES, content_type="application/pdf"
        )
        credential.original_filename = name
        credential.mime_type = "application/pdf"
        credential.file_size = len(PDF_BYTES)
        credential.save()

    def _get_staff_entry(self, viewer):
        self.authenticate(viewer)
        response = self.client.get(f"/api/tickets/{self.ticket.id}/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        staff = response.data["assigned_staff"]
        self.assertEqual(len(staff), 1)
        return staff[0]

    def test_customer_sees_resolver_filtered_credentials(self):
        entry = self._get_staff_entry(self.customer_user)
        credentials = entry["credentials"]
        by_type = {}
        for item in credentials:
            by_type.setdefault(item["type"], []).append(item)

        # EU national ID can never appear.
        self.assertNotIn("EU_NATIONAL_ID", by_type)

        # Residence permit: exactly the allowed key set, photocopy URL on.
        permit = by_type["RESIDENCE_PERMIT"][0]
        self.assertEqual(permit["permit_number"], "RP-42")
        self.assertEqual(permit["expiry_date"], "2027-03-01")
        self.assertIn("document_url", permit)
        self.assertLessEqual(
            set(permit.keys()),
            {"type", "permit_number", "expiry_date", "document_url"},
        )

        # Only the GRANTED VCA appears (the PROVIDER_ONLY one is
        # filtered by the resolver), with its document.
        self.assertEqual(len(by_type["VCA"]), 1)
        vca = by_type["VCA"][0]
        self.assertEqual(vca["expiry_date"], "2026-12-31")
        self.assertNotIn("permit_number", vca)
        self.assertIn("document_url", vca)

        # Properties: shared yes, PA_SA_ONLY no.
        names = {p["name"] for p in entry["properties"]}
        self.assertEqual(names, {"Diploma"})
        diploma = entry["properties"][0]
        self.assertEqual(diploma["value"], "HBO Facility Management")

    def test_photocopy_rule_strips_document_url_only(self):
        StaffCredential.objects.filter(pk=self.residence_permit.pk).update(
            document_customer_visible=False
        )
        entry = self._get_staff_entry(self.customer_user)
        permit = next(
            item
            for item in entry["credentials"]
            if item["type"] == "RESIDENCE_PERMIT"
        )
        self.assertNotIn("document_url", permit)
        self.assertEqual(permit["permit_number"], "RP-42")

    def test_payload_document_url_downloads_for_customer(self):
        entry = self._get_staff_entry(self.customer_user)
        permit = next(
            item
            for item in entry["credentials"]
            if item["type"] == "RESIDENCE_PERMIT"
        )
        response = self.client.get(permit["document_url"])
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(b"".join(response.streaming_content), PDF_BYTES)

    def test_provider_payload_unchanged(self):
        for viewer in (self.super_admin, self.company_admin, self.manager):
            entry = self._get_staff_entry(viewer)
            with self.subTest(role=viewer.role):
                # Byte-identical pre-M2 shape: no new keys.
                self.assertEqual(
                    set(entry.keys()), {"id", "full_name", "email", "phone"}
                )

    def test_anonymous_collapse_unchanged(self):
        self.customer.show_assigned_staff_name = False
        self.customer.show_assigned_staff_email = False
        self.customer.show_assigned_staff_phone = False
        self.customer.save()
        self.authenticate(self.customer_user)
        response = self.client.get(f"/api/tickets/{self.ticket.id}/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            response.data["assigned_staff"],
            [{"anonymous": True, "label_key": "tickets.assigned_team_anonymous"}],
        )

    def test_other_customer_viewer_cannot_reach_ticket_at_all(self):
        self.authenticate(self.other_customer_user)
        response = self.client.get(f"/api/tickets/{self.ticket.id}/")
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
