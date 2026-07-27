"""Sprint 125 — the documents permission matrix + cross-tenant scoping.

The security core: who may see / write a customer's document store, and the
hard rule that a user of one customer 404s on every endpoint of another
(cross-tenant, H-1/H-2). Provider side is SUPER_ADMIN + COMPANY_ADMIN ONLY;
BUILDING_MANAGER / STAFF get 404 on read and 403 on write.
"""
from __future__ import annotations

from rest_framework import status
from rest_framework.test import APITestCase

from documents.models import DocumentFolder
from test_utils import TenantFixtureMixin

from ._helpers import (
    DocumentsActorsMixin,
    file_url,
    files_url,
    folder_url,
    folders_url,
    pdf_upload,
)


class DocumentsAccessMatrixTests(
    DocumentsActorsMixin, TenantFixtureMixin, APITestCase
):
    def setUp(self):
        super().setUp()
        self.setup_documents_actors()
        # A system folder of Customer A to target for reads/writes.
        self.folder_a = DocumentFolder.objects.get(
            customer=self.customer, system_slug="overig"
        )

    # -- default folders exist (signal on Customer create) ------------------

    def test_customer_gets_four_system_folders_on_create(self):
        slugs = set(
            DocumentFolder.objects.filter(
                customer=self.customer, is_system=True
            ).values_list("system_slug", flat=True)
        )
        self.assertEqual(
            slugs, {"facturen", "contracten", "overeenkomsten", "overig"}
        )

    # -- provider read/write -------------------------------------------------

    def test_super_admin_can_list_and_create(self):
        self.authenticate(self.super_admin)
        self.assertEqual(
            self.client.get(folders_url(self.customer.id)).status_code,
            status.HTTP_200_OK,
        )
        resp = self.client.post(
            folders_url(self.customer.id), {"name": "SA folder"}
        )
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)

    def test_company_admin_of_same_company_can_list_and_create(self):
        self.authenticate(self.company_admin)
        self.assertEqual(
            self.client.get(folders_url(self.customer.id)).status_code,
            status.HTTP_200_OK,
        )
        resp = self.client.post(
            folders_url(self.customer.id), {"name": "CA folder"}
        )
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)

    def test_company_admin_of_other_company_404s(self):
        # CA of Company B has no business with Customer A (Company A).
        self.authenticate(self.other_company_admin)
        self.assertEqual(
            self.client.get(folders_url(self.customer.id)).status_code,
            status.HTTP_404_NOT_FOUND,
        )
        self.assertEqual(
            self.client.post(
                folders_url(self.customer.id), {"name": "x"}
            ).status_code,
            status.HTTP_404_NOT_FOUND,
        )

    # -- BUILDING_MANAGER / STAFF: 404 read, 403 write -----------------------

    def test_building_manager_404_read_403_write(self):
        # self.manager manages self.building, which is Customer A's building,
        # so the customer is in their scope — read 404 (tab hidden), write 403.
        self.authenticate(self.manager)
        self.assertEqual(
            self.client.get(folders_url(self.customer.id)).status_code,
            status.HTTP_404_NOT_FOUND,
        )
        self.assertEqual(
            self.client.post(
                folders_url(self.customer.id), {"name": "bm"}
            ).status_code,
            status.HTTP_403_FORBIDDEN,
        )

    def test_staff_without_scope_404s_everywhere(self):
        # A STAFF with no visibility of this customer leaks nothing: 404 on
        # both read and write (the 403-write branch is reserved for a
        # provider role that can already SEE the customer — same code path
        # the BM case above exercises).
        self.authenticate(self.staff)
        self.assertEqual(
            self.client.get(folders_url(self.customer.id)).status_code,
            status.HTTP_404_NOT_FOUND,
        )
        self.assertEqual(
            self.client.post(
                folders_url(self.customer.id), {"name": "s"}
            ).status_code,
            status.HTTP_404_NOT_FOUND,
        )

    # -- customer side -------------------------------------------------------

    def test_member_customer_user_can_read_and_create(self):
        self.authenticate(self.customer_user)
        self.assertEqual(
            self.client.get(folders_url(self.customer.id)).status_code,
            status.HTTP_200_OK,
        )
        resp = self.client.post(
            folders_url(self.customer.id), {"name": "My folder"}
        )
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)

    def test_company_wide_cca_can_read(self):
        # A CCA with NO per-building access rows still resolves via user_can.
        self.authenticate(self.cca)
        self.assertEqual(
            self.client.get(folders_url(self.customer.id)).status_code,
            status.HTTP_200_OK,
        )

    def test_customer_user_without_key_404s(self):
        # Member of Customer A but the documents key is revoked -> 404.
        self.authenticate(self.nokey_user)
        self.assertEqual(
            self.client.get(folders_url(self.customer.id)).status_code,
            status.HTTP_404_NOT_FOUND,
        )
        self.assertEqual(
            self.client.post(
                folders_url(self.customer.id), {"name": "x"}
            ).status_code,
            status.HTTP_404_NOT_FOUND,
        )

    # -- cross-tenant: every endpoint 404s -----------------------------------

    def test_cross_tenant_customer_user_404s_on_every_endpoint(self):
        # self.other_customer_user is a member of Customer B (Company B).
        # Every Customer A documents endpoint must 404 for them.
        self.authenticate(self.other_customer_user)
        cid = self.customer.id
        # GET folders
        self.assertEqual(
            self.client.get(folders_url(cid)).status_code,
            status.HTTP_404_NOT_FOUND,
        )
        # POST folders
        self.assertEqual(
            self.client.post(folders_url(cid), {"name": "x"}).status_code,
            status.HTTP_404_NOT_FOUND,
        )
        # PATCH folder
        self.assertEqual(
            self.client.patch(
                folder_url(cid, self.folder_a.id), {"name": "x"}
            ).status_code,
            status.HTTP_404_NOT_FOUND,
        )
        # DELETE folder
        self.assertEqual(
            self.client.delete(folder_url(cid, self.folder_a.id)).status_code,
            status.HTTP_404_NOT_FOUND,
        )
        # POST files
        self.assertEqual(
            self.client.post(
                files_url(cid),
                {"folder": self.folder_a.id, "file": pdf_upload()},
                format="multipart",
            ).status_code,
            status.HTTP_404_NOT_FOUND,
        )
        # GET / PATCH / DELETE a file by a (nonexistent-for-them) uuid
        import uuid

        self.assertEqual(
            self.client.get(file_url(cid, uuid.uuid4())).status_code,
            status.HTTP_404_NOT_FOUND,
        )
        self.assertEqual(
            self.client.patch(
                file_url(cid, uuid.uuid4()), {"original_filename": "x.pdf"}
            ).status_code,
            status.HTTP_404_NOT_FOUND,
        )
        self.assertEqual(
            self.client.delete(file_url(cid, uuid.uuid4())).status_code,
            status.HTTP_404_NOT_FOUND,
        )

    def test_same_tenant_other_customer_user_404s(self):
        # A user of a DIFFERENT customer in the SAME provider company still
        # 404s on this customer's documents (membership-level isolation).
        _second, second_user = self.make_second_customer_same_tenant()
        self.authenticate(second_user)
        self.assertEqual(
            self.client.get(folders_url(self.customer.id)).status_code,
            status.HTTP_404_NOT_FOUND,
        )
