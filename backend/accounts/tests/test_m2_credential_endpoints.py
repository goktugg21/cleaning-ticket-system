"""
M2 P3 — endpoint contract for /api/users/<user_id>/credentials|properties/.

Pins:
  - permission matrix: STAFF / BM / CUSTOMER_USER get 403 on every
    admin endpoint; COMPANY_ADMIN cross-company gets 403; SUPER_ADMIN
    passes everything.
  - credential_type is immutable after create (PATCH carrying it -> 400).
  - EU national ID gets explicit API-level 400s (visibility above
    PA_SA_ONLY / customer-visible document).
  - document metadata is derived SERVER-SIDE; client-sent metadata is
    ignored; non-PDF uploads (by extension OR by content type) -> 400.
  - grant create/delete incl. ceiling rule, EU-ID block, staff-owned
    rule for properties, cross-company customer guard, idempotency.
  - downloads: 404 whenever the gate fails (existence never leaks),
    FileResponse when it passes, customer downloads only with the full
    chain (membership + grant + ceiling + document sub-rule).
"""
from __future__ import annotations

import tempfile

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

PDF_BYTES = b"%PDF-1.4 m2 p3 test"

_MEDIA_ROOT = tempfile.mkdtemp(prefix="m2p3-test-media-")


def pdf_file(name="scan.pdf", content_type="application/pdf"):
    return SimpleUploadedFile(name, PDF_BYTES, content_type=content_type)


@override_settings(MEDIA_ROOT=_MEDIA_ROOT)
class CredentialEndpointTestBase(TenantFixtureMixin, APITestCase):
    def setUp(self):
        super().setUp()
        # staff_a is in company A scope via BuildingStaffVisibility;
        # staff_b in company B (mirrors the Sprint 24A fixture shape).
        self.staff_a = self.make_user("staff-a@example.com", UserRole.STAFF)
        self.staff_b = self.make_user("staff-b@example.com", UserRole.STAFF)
        self.profile_a = StaffProfile.objects.create(user=self.staff_a)
        self.profile_b = StaffProfile.objects.create(user=self.staff_b)
        BuildingStaffVisibility.objects.create(
            user=self.staff_a, building=self.building
        )
        BuildingStaffVisibility.objects.create(
            user=self.staff_b, building=self.other_building
        )

    # -- URL helpers ------------------------------------------------------

    def credentials_url(self, user_id):
        return f"/api/users/{user_id}/credentials/"

    def credential_url(self, user_id, pk):
        return f"/api/users/{user_id}/credentials/{pk}/"

    def credential_download_url(self, user_id, pk):
        return f"/api/users/{user_id}/credentials/{pk}/download/"

    def credential_grants_url(self, user_id, pk):
        return f"/api/users/{user_id}/credentials/{pk}/grants/"

    def credential_grant_url(self, user_id, pk, grant_id):
        return f"/api/users/{user_id}/credentials/{pk}/grants/{grant_id}/"

    def properties_url(self, user_id):
        return f"/api/users/{user_id}/properties/"

    def property_url(self, user_id, pk):
        return f"/api/users/{user_id}/properties/{pk}/"

    def property_download_url(self, user_id, pk):
        return f"/api/users/{user_id}/properties/{pk}/download/"

    def property_grants_url(self, user_id, pk):
        return f"/api/users/{user_id}/properties/{pk}/grants/"

    # -- fixture helpers --------------------------------------------------

    def make_credential(self, **overrides):
        params = dict(
            staff_profile=self.profile_a,
            credential_type=StaffCredential.CredentialType.VCA,
            visibility_level=VisibilityLevel.PA_SA_ONLY,
        )
        params.update(overrides)
        return StaffCredential.objects.create(**params)

    def attach_document(self, instance, name="scan.pdf"):
        instance.document = pdf_file(name)
        instance.original_filename = name
        instance.mime_type = "application/pdf"
        instance.file_size = len(PDF_BYTES)
        instance.save()
        return instance


class CredentialPermissionMatrixTests(CredentialEndpointTestBase):
    def test_non_admin_roles_403_on_admin_endpoints(self):
        credential = self.make_credential()
        for user in (self.manager, self.staff_a, self.customer_user):
            self.authenticate(user)
            with self.subTest(role=user.role, endpoint="credentials-list"):
                response = self.client.get(self.credentials_url(self.staff_a.id))
                self.assertEqual(
                    response.status_code, status.HTTP_403_FORBIDDEN
                )
            with self.subTest(role=user.role, endpoint="credential-grants"):
                response = self.client.get(
                    self.credential_grants_url(self.staff_a.id, credential.id)
                )
                self.assertEqual(
                    response.status_code, status.HTTP_403_FORBIDDEN
                )
            with self.subTest(role=user.role, endpoint="properties-list"):
                response = self.client.get(self.properties_url(self.staff_a.id))
                self.assertEqual(
                    response.status_code, status.HTTP_403_FORBIDDEN
                )

    def test_company_admin_cross_company_403(self):
        self.authenticate(self.company_admin)
        response = self.client.get(self.credentials_url(self.staff_b.id))
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        response = self.client.get(
            self.properties_url(self.other_customer_user.id)
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_company_admin_in_company_200(self):
        self.authenticate(self.company_admin)
        response = self.client.get(self.credentials_url(self.staff_a.id))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        # Properties reach customer users in company scope too (A.3.2).
        response = self.client.get(self.properties_url(self.customer_user.id))
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_credentials_on_non_staff_user_400(self):
        self.authenticate(self.super_admin)
        response = self.client.get(self.credentials_url(self.customer_user.id))
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)


class CredentialWriteSurfaceTests(CredentialEndpointTestBase):
    def test_create_and_list_with_inline_grants(self):
        self.authenticate(self.super_admin)
        response = self.client.post(
            self.credentials_url(self.staff_a.id),
            {
                "credential_type": "VCA",
                "visibility_level": "CUSTOMER_VISIBLE",
                "expiry_date": "2027-06-30",
            },
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        credential_id = response.data["id"]
        grant_response = self.client.post(
            self.credential_grants_url(self.staff_a.id, credential_id),
            {"customer_id": self.customer.id},
        )
        self.assertEqual(grant_response.status_code, status.HTTP_201_CREATED)
        list_response = self.client.get(self.credentials_url(self.staff_a.id))
        self.assertEqual(list_response.status_code, status.HTTP_200_OK)
        row = list_response.data[0]
        self.assertEqual(row["grants"][0]["customer_id"], self.customer.id)
        self.assertEqual(row["grants"][0]["customer_name"], self.customer.name)

    def test_credential_type_immutable_on_patch(self):
        credential = self.make_credential()
        self.authenticate(self.super_admin)
        response = self.client.patch(
            self.credential_url(self.staff_a.id, credential.id),
            {"credential_type": "RESIDENCE_PERMIT"},
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("credential_type", response.data)
        credential.refresh_from_db()
        self.assertEqual(
            credential.credential_type, StaffCredential.CredentialType.VCA
        )
        # Even a same-value resend is rejected — the field is immutable.
        response = self.client.patch(
            self.credential_url(self.staff_a.id, credential.id),
            {"credential_type": "VCA"},
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_eu_id_explicit_400s(self):
        self.authenticate(self.super_admin)
        response = self.client.post(
            self.credentials_url(self.staff_a.id),
            {
                "credential_type": "EU_NATIONAL_ID",
                "visibility_level": "CUSTOMER_VISIBLE",
            },
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("visibility_level", response.data)

        response = self.client.post(
            self.credentials_url(self.staff_a.id),
            {
                "credential_type": "EU_NATIONAL_ID",
                "document_customer_visible": True,
            },
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("document_customer_visible", response.data)

        # Plain create works and lands at the locked defaults.
        response = self.client.post(
            self.credentials_url(self.staff_a.id),
            {"credential_type": "EU_NATIONAL_ID", "permit_number": "ID-1"},
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["visibility_level"], "PA_SA_ONLY")
        self.assertFalse(response.data["document_customer_visible"])

        # And the lock holds on PATCH.
        response = self.client.patch(
            self.credential_url(self.staff_a.id, response.data["id"]),
            {"visibility_level": "PROVIDER_ONLY"},
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_document_customer_visible_only_for_residence_permit(self):
        self.authenticate(self.super_admin)
        response = self.client.post(
            self.credentials_url(self.staff_a.id),
            {"credential_type": "VCA", "document_customer_visible": True},
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("document_customer_visible", response.data)

    def test_document_metadata_derived_server_side(self):
        self.authenticate(self.super_admin)
        response = self.client.post(
            self.credentials_url(self.staff_a.id),
            {
                "credential_type": "VCA",
                "document": pdf_file("vca-cert.pdf"),
                # Client-sent metadata MUST be ignored.
                "original_filename": "evil.exe",
                "mime_type": "application/x-msdownload",
                "file_size": 1,
            },
            format="multipart",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["original_filename"], "vca-cert.pdf")
        self.assertEqual(response.data["mime_type"], "application/pdf")
        self.assertEqual(response.data["file_size"], len(PDF_BYTES))
        self.assertTrue(response.data["has_document"])
        self.assertIn("/download/", response.data["document_url"])

    def test_non_pdf_uploads_400(self):
        self.authenticate(self.super_admin)
        # Wrong extension.
        response = self.client.post(
            self.credentials_url(self.staff_a.id),
            {
                "credential_type": "VCA",
                "document": pdf_file("photo.jpg", content_type="image/jpeg"),
            },
            format="multipart",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        # PDF extension with non-PDF content type — pairing violation.
        response = self.client.post(
            self.credentials_url(self.staff_a.id),
            {
                "credential_type": "VCA",
                "document": pdf_file("scan.pdf", content_type="image/jpeg"),
            },
            format="multipart",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_delete_credential(self):
        credential = self.make_credential()
        self.authenticate(self.super_admin)
        response = self.client.delete(
            self.credential_url(self.staff_a.id, credential.id)
        )
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(
            StaffCredential.objects.filter(pk=credential.pk).exists()
        )


class GrantEndpointTests(CredentialEndpointTestBase):
    def test_grant_requires_customer_visible_ceiling(self):
        credential = self.make_credential(
            visibility_level=VisibilityLevel.PROVIDER_ONLY
        )
        self.authenticate(self.super_admin)
        response = self.client.post(
            self.credential_grants_url(self.staff_a.id, credential.id),
            {"customer_id": self.customer.id},
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_grant_on_eu_id_400(self):
        credential = self.make_credential(
            credential_type=StaffCredential.CredentialType.EU_NATIONAL_ID
        )
        self.authenticate(self.super_admin)
        response = self.client.post(
            self.credential_grants_url(self.staff_a.id, credential.id),
            {"customer_id": self.customer.id},
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertFalse(
            CredentialCustomerVisibility.objects.filter(
                credential=credential
            ).exists()
        )

    def test_grant_cross_company_customer_400(self):
        credential = self.make_credential(
            visibility_level=VisibilityLevel.CUSTOMER_VISIBLE
        )
        self.authenticate(self.company_admin)
        response = self.client.post(
            self.credential_grants_url(self.staff_a.id, credential.id),
            {"customer_id": self.other_customer.id},
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_grant_create_idempotent_and_delete(self):
        credential = self.make_credential(
            visibility_level=VisibilityLevel.CUSTOMER_VISIBLE
        )
        self.authenticate(self.super_admin)
        first = self.client.post(
            self.credential_grants_url(self.staff_a.id, credential.id),
            {"customer_id": self.customer.id},
        )
        self.assertEqual(first.status_code, status.HTTP_201_CREATED)
        second = self.client.post(
            self.credential_grants_url(self.staff_a.id, credential.id),
            {"customer_id": self.customer.id},
        )
        self.assertEqual(second.status_code, status.HTTP_200_OK)
        self.assertEqual(first.data["id"], second.data["id"])
        response = self.client.delete(
            self.credential_grant_url(
                self.staff_a.id, credential.id, first.data["id"]
            )
        )
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(
            CredentialCustomerVisibility.objects.filter(
                credential=credential
            ).exists()
        )

    def test_property_grant_staff_owned_only(self):
        prop = CustomProfileProperty.objects.create(
            user=self.customer_user,
            name="Loyalty tier",
            value="Gold",
            visibility_level=VisibilityLevel.CUSTOMER_VISIBLE,
        )
        self.authenticate(self.super_admin)
        response = self.client.post(
            self.property_grants_url(self.customer_user.id, prop.id),
            {"customer_id": self.customer.id},
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertFalse(
            PropertyCustomerVisibility.objects.filter(property=prop).exists()
        )

    def test_property_grant_on_staff_property_created(self):
        prop = CustomProfileProperty.objects.create(
            user=self.staff_a,
            name="Diploma",
            value="HBO",
            visibility_level=VisibilityLevel.CUSTOMER_VISIBLE,
        )
        self.authenticate(self.super_admin)
        response = self.client.post(
            self.property_grants_url(self.staff_a.id, prop.id),
            {"customer_id": self.customer.id},
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)


class DownloadEndpointTests(CredentialEndpointTestBase):
    def test_404_without_document(self):
        credential = self.make_credential(
            visibility_level=VisibilityLevel.PROVIDER_ONLY
        )
        self.authenticate(self.super_admin)
        response = self.client.get(
            self.credential_download_url(self.staff_a.id, credential.id)
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_provider_download_follows_table_and_company_scope(self):
        credential = self.attach_document(
            self.make_credential(visibility_level=VisibilityLevel.PROVIDER_ONLY)
        )
        # SA passes.
        self.authenticate(self.super_admin)
        response = self.client.get(
            self.credential_download_url(self.staff_a.id, credential.id)
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        # Consume the stream instead of close(): an explicit close() on
        # a FileResponse fires request_finished and closes the test DB
        # connection mid-transaction (breaks the NEXT test's setUp).
        self.assertEqual(b"".join(response.streaming_content), PDF_BYTES)
        # In-company BM passes PROVIDER_ONLY.
        self.authenticate(self.manager)
        response = self.client.get(
            self.credential_download_url(self.staff_a.id, credential.id)
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        # Consume the stream instead of close(): an explicit close() on
        # a FileResponse fires request_finished and closes the test DB
        # connection mid-transaction (breaks the NEXT test's setUp).
        self.assertEqual(b"".join(response.streaming_content), PDF_BYTES)
        # Cross-company BM gets 404 — never a 403, existence must not leak.
        self.authenticate(self.other_manager)
        response = self.client.get(
            self.credential_download_url(self.staff_a.id, credential.id)
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        # STAFF gets 404 even for their own document.
        self.authenticate(self.staff_a)
        response = self.client.get(
            self.credential_download_url(self.staff_a.id, credential.id)
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        # BM never reaches PA_SA_ONLY.
        locked = self.attach_document(
            self.make_credential(visibility_level=VisibilityLevel.PA_SA_ONLY)
        )
        self.authenticate(self.manager)
        response = self.client.get(
            self.credential_download_url(self.staff_a.id, locked.id)
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_customer_download_needs_full_chain(self):
        credential = self.attach_document(
            self.make_credential(
                credential_type=(
                    StaffCredential.CredentialType.RESIDENCE_PERMIT
                ),
                visibility_level=VisibilityLevel.CUSTOMER_VISIBLE,
                document_customer_visible=False,
            )
        )
        url = self.credential_download_url(self.staff_a.id, credential.id)
        # No grant yet -> 404.
        self.authenticate(self.customer_user)
        self.assertEqual(
            self.client.get(url).status_code, status.HTTP_404_NOT_FOUND
        )
        CredentialCustomerVisibility.objects.create(
            credential=credential, customer=self.customer
        )
        # Grant but photocopy flag off -> still 404 (fields-only).
        self.assertEqual(
            self.client.get(url).status_code, status.HTTP_404_NOT_FOUND
        )
        StaffCredential.objects.filter(pk=credential.pk).update(
            document_customer_visible=True
        )
        # Full chain -> FileResponse.
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(b"".join(response.streaming_content), PDF_BYTES)
        # A member of another customer org stays at 404.
        self.authenticate(self.other_customer_user)
        self.assertEqual(
            self.client.get(url).status_code, status.HTTP_404_NOT_FOUND
        )

    def test_eu_id_document_unreachable_for_bm_and_customer(self):
        credential = self.attach_document(
            self.make_credential(
                credential_type=StaffCredential.CredentialType.EU_NATIONAL_ID
            )
        )
        # Smuggle a grant row past save() to prove the endpoint still
        # blocks (bulk_create bypasses the model-layer guards).
        CredentialCustomerVisibility.objects.bulk_create(
            [
                CredentialCustomerVisibility(
                    credential=credential, customer=self.customer
                )
            ]
        )
        url = self.credential_download_url(self.staff_a.id, credential.id)
        self.authenticate(self.manager)
        self.assertEqual(
            self.client.get(url).status_code, status.HTTP_404_NOT_FOUND
        )
        self.authenticate(self.customer_user)
        self.assertEqual(
            self.client.get(url).status_code, status.HTTP_404_NOT_FOUND
        )
        self.authenticate(self.company_admin)
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        # Consume the stream instead of close(): an explicit close() on
        # a FileResponse fires request_finished and closes the test DB
        # connection mid-transaction (breaks the NEXT test's setUp).
        self.assertEqual(b"".join(response.streaming_content), PDF_BYTES)

    def test_property_download_chain(self):
        prop = CustomProfileProperty.objects.create(
            user=self.staff_a,
            name="Diploma",
            value="HBO",
            visibility_level=VisibilityLevel.CUSTOMER_VISIBLE,
        )
        self.attach_document(prop, name="diploma.pdf")
        url = self.property_download_url(self.staff_a.id, prop.id)
        self.authenticate(self.customer_user)
        # No grant -> 404.
        self.assertEqual(
            self.client.get(url).status_code, status.HTTP_404_NOT_FOUND
        )
        PropertyCustomerVisibility.objects.create(
            property=prop, customer=self.customer
        )
        # Property documents follow field visibility -> 200 with grant.
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        # Consume the stream instead of close(): an explicit close() on
        # a FileResponse fires request_finished and closes the test DB
        # connection mid-transaction (breaks the NEXT test's setUp).
        self.assertEqual(b"".join(response.streaming_content), PDF_BYTES)
