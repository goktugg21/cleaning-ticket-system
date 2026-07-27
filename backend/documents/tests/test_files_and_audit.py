"""Sprint 125 — file upload / serve / rename / move / delete, the
denormalized-customer invariant, and the audit trail (a DELETE row must
survive the file and answer "who deleted the contract")."""
from __future__ import annotations

import tempfile

from django.test import override_settings
from rest_framework import status
from rest_framework.test import APITestCase

from audit.models import AuditAction, AuditLog
from documents.models import DocumentFolder, DocumentOrigin, Document
from test_utils import TenantFixtureMixin

from ._helpers import (
    DocumentsActorsMixin,
    docx_upload,
    file_url,
    files_url,
    folders_url,
    pdf_upload,
)

_MEDIA = tempfile.mkdtemp(prefix="doc-file-tests-")


@override_settings(MEDIA_ROOT=_MEDIA)
class FileEndpointTests(DocumentsActorsMixin, TenantFixtureMixin, APITestCase):
    def setUp(self):
        super().setUp()
        self.setup_documents_actors()
        self.overig = DocumentFolder.objects.get(
            customer=self.customer, system_slug="overig"
        )
        # A non-system CUSTOMER-origin folder the customer user may use.
        self.my_folder = DocumentFolder.objects.create(
            customer=self.customer,
            name="Mine",
            origin=DocumentOrigin.CUSTOMER,
            created_by=self.customer_user,
        )

    def _upload(self, actor, folder, upload=None):
        self.authenticate(actor)
        return self.client.post(
            files_url(self.customer.id),
            {"folder": folder.id, "file": upload or pdf_upload()},
            format="multipart",
        )

    # -- upload + origin + invariant ----------------------------------------

    def test_provider_upload_stamps_provider_origin(self):
        r = self._upload(self.super_admin, self.overig)
        self.assertEqual(r.status_code, status.HTTP_201_CREATED)
        self.assertEqual(r.data["origin"], DocumentOrigin.PROVIDER)

    def test_customer_upload_stamps_customer_origin_and_invariant_holds(self):
        r = self._upload(self.customer_user, self.my_folder)
        self.assertEqual(r.status_code, status.HTTP_201_CREATED)
        self.assertEqual(r.data["origin"], DocumentOrigin.CUSTOMER)
        doc = Document.objects.get(public_id=r.data["public_id"])
        # Denormalized customer ALWAYS equals folder.customer.
        self.assertEqual(doc.customer_id, doc.folder.customer_id)
        self.assertEqual(doc.customer_id, self.customer.id)

    def test_list_files_by_folder(self):
        # The file pane's data source: GET files/?folder=<id> is folder-scoped.
        self._upload(self.super_admin, self.overig, upload=pdf_upload("a.pdf"))
        self._upload(self.super_admin, self.my_folder, upload=pdf_upload("b.pdf"))
        self.authenticate(self.customer_user)
        r = self.client.get(
            f"{files_url(self.customer.id)}?folder={self.overig.id}"
        )
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.assertEqual(
            {row["original_filename"] for row in r.data}, {"a.pdf"}
        )

    def test_list_files_cross_tenant_404(self):
        # A user of another customer 404s on the list endpoint too.
        self.authenticate(self.other_customer_user)
        r = self.client.get(files_url(self.customer.id))
        self.assertEqual(r.status_code, status.HTTP_404_NOT_FOUND)

    def test_list_files_non_integer_folder_400(self):
        # A non-numeric ?folder= is a clean 400, never a 500 from the ORM.
        self.authenticate(self.customer_user)
        r = self.client.get(f"{files_url(self.customer.id)}?folder=abc")
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(r.data["code"], "invalid_folder_id")

    def test_customer_can_upload_into_system_folder(self):
        # Sprint 125 correction: a customer MAY upload into a system folder
        # (filing a contract into Contracten is the intended flow). The file
        # is stamped origin=CUSTOMER — placement does not transfer ownership.
        r = self._upload(self.customer_user, self.overig)
        self.assertEqual(r.status_code, status.HTTP_201_CREATED)
        self.assertEqual(r.data["origin"], DocumentOrigin.CUSTOMER)

    def test_provider_can_upload_into_system_folder(self):
        r = self._upload(self.company_admin, self.overig)
        self.assertEqual(r.status_code, status.HTTP_201_CREATED)

    def test_upload_rejects_invalid_type_through_endpoint(self):
        from django.core.files.uploadedfile import SimpleUploadedFile

        self.authenticate(self.super_admin)
        r = self.client.post(
            files_url(self.customer.id),
            {
                "folder": self.overig.id,
                "file": SimpleUploadedFile(
                    "a.zip", b"PK\x03\x04x", content_type="application/zip"
                ),
            },
            format="multipart",
        )
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)
        # Sprint 126 — the stable validator code is surfaced in the body so
        # the frontend can localize it (DRF would otherwise drop it).
        self.assertEqual(r.data["code"], "invalid_document_extension")

    # -- serve: inline vs attachment ----------------------------------------

    def test_pdf_serves_inline(self):
        up = self._upload(self.super_admin, self.overig)
        self.authenticate(self.customer_user)  # any reader may view
        r = self.client.get(file_url(self.customer.id, up.data["public_id"]))
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.assertTrue(r["Content-Disposition"].startswith("inline"))

    def test_docx_serves_as_attachment(self):
        up = self._upload(self.super_admin, self.overig, upload=docx_upload())
        self.authenticate(self.super_admin)
        r = self.client.get(file_url(self.customer.id, up.data["public_id"]))
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.assertTrue(r["Content-Disposition"].startswith("attachment"))

    # -- rename / move by origin --------------------------------------------

    def test_customer_can_rename_and_move_own_document(self):
        up = self._upload(self.customer_user, self.my_folder)
        pub = up.data["public_id"]
        self.authenticate(self.customer_user)
        r = self.client.patch(
            file_url(self.customer.id, pub), {"original_filename": "renamed.pdf"}
        )
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.assertEqual(r.data["original_filename"], "renamed.pdf")
        # move to another non-system CUSTOMER folder
        dest = DocumentFolder.objects.create(
            customer=self.customer, name="Dest",
            origin=DocumentOrigin.CUSTOMER, created_by=self.customer_user,
        )
        r = self.client.patch(
            file_url(self.customer.id, pub), {"folder": dest.id}
        )
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.assertEqual(r.data["folder"], dest.id)

    def test_customer_cannot_modify_provider_document(self):
        up = self._upload(self.super_admin, self.overig)
        pub = up.data["public_id"]
        self.authenticate(self.customer_user)
        r = self.client.patch(
            file_url(self.customer.id, pub), {"original_filename": "x.pdf"}
        )
        self.assertEqual(r.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(r.data["code"], "not_owner")
        r = self.client.delete(file_url(self.customer.id, pub))
        self.assertEqual(r.status_code, status.HTTP_403_FORBIDDEN)

    def test_customer_can_move_own_document_into_system_folder(self):
        # Sprint 125 correction: moving your OWN file into a system folder is
        # allowed (same placement rule as upload). Not named in the
        # correction prompt, but it asserted the same superseded behaviour.
        up = self._upload(self.customer_user, self.my_folder)
        pub = up.data["public_id"]
        self.authenticate(self.customer_user)
        r = self.client.patch(
            file_url(self.customer.id, pub), {"folder": self.overig.id}
        )
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.assertEqual(r.data["folder"], self.overig.id)

    def test_customer_file_in_system_folder_stays_customer_owned(self):
        # Files a contract into the PROVIDER's Contracten system folder, then
        # proves placement did NOT hand ownership to the provider: the
        # customer can still rename AND delete their own file.
        contracten = DocumentFolder.objects.get(
            customer=self.customer, system_slug="contracten"
        )
        up = self._upload(
            self.customer_user, contracten, upload=pdf_upload("my-contract.pdf")
        )
        self.assertEqual(up.status_code, status.HTTP_201_CREATED)
        self.assertEqual(up.data["origin"], DocumentOrigin.CUSTOMER)
        pub = up.data["public_id"]

        self.authenticate(self.customer_user)
        r = self.client.patch(
            file_url(self.customer.id, pub),
            {"original_filename": "signed-contract.pdf"},
        )
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.assertEqual(r.data["original_filename"], "signed-contract.pdf")

        r = self.client.delete(file_url(self.customer.id, pub))
        self.assertEqual(r.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(Document.objects.filter(public_id=pub).exists())

    # -- delete removes row + file ------------------------------------------

    def test_delete_removes_row_and_file(self):
        up = self._upload(self.super_admin, self.overig)
        pub = up.data["public_id"]
        doc = Document.objects.get(public_id=pub)
        storage = doc.file.storage
        name = doc.file.name
        self.assertTrue(storage.exists(name))
        self.authenticate(self.super_admin)
        r = self.client.delete(file_url(self.customer.id, pub))
        self.assertEqual(r.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(Document.objects.filter(public_id=pub).exists())
        self.assertFalse(storage.exists(name))

    def test_provider_can_delete_customer_document(self):
        up = self._upload(self.customer_user, self.my_folder)
        pub = up.data["public_id"]
        self.authenticate(self.company_admin)
        r = self.client.delete(file_url(self.customer.id, pub))
        self.assertEqual(r.status_code, status.HTTP_204_NO_CONTENT)

    # -- audit: DELETE row survives with the who/what -----------------------

    def test_delete_writes_audit_row_with_filename_folder_uploader_deleter(self):
        # Provider uploads a "contract" into Contracten; the customer's own
        # CCA is irrelevant — the CA deletes it. The audit row must retain
        # filename + folder path + uploader + origin, and name the DELETER.
        contracten = DocumentFolder.objects.get(
            customer=self.customer, system_slug="contracten"
        )
        up = self._upload(self.super_admin, contracten, upload=pdf_upload("contract.pdf"))
        doc = Document.objects.get(public_id=up.data["public_id"])
        deleted_pk = doc.id
        AuditLog.objects.all().delete()  # isolate the delete row

        self.authenticate(self.company_admin)
        self.client.delete(file_url(self.customer.id, up.data["public_id"]))

        log = AuditLog.objects.get(
            target_model="documents.Document",
            target_id=deleted_pk,
            action=AuditAction.DELETE,
        )
        # who deleted it
        self.assertEqual(log.actor, self.company_admin)
        # what it was (filenames only — never a storage path)
        self.assertEqual(log.changes["original_filename"]["before"], "contract.pdf")
        self.assertEqual(log.changes["folder_path"]["before"], "Contracten")
        self.assertEqual(
            log.changes["uploaded_by_email"]["before"], self.super_admin.email
        )
        self.assertEqual(log.changes["origin"]["before"], DocumentOrigin.PROVIDER)
        # no storage path leaked into the payload
        self.assertNotIn("file", log.changes)

    def test_upload_writes_create_audit_row(self):
        AuditLog.objects.all().delete()
        up = self._upload(self.super_admin, self.overig, upload=pdf_upload("c.pdf"))
        doc = Document.objects.get(public_id=up.data["public_id"])
        log = AuditLog.objects.get(
            target_model="documents.Document",
            target_id=doc.id,
            action=AuditAction.CREATE,
        )
        self.assertEqual(log.changes["original_filename"]["after"], "c.pdf")
        self.assertNotIn("file", log.changes)
