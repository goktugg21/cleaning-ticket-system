"""
Sprint 155 §3 — `file_count` on the folder read.

The Documents page now renders folders as cards in the same visual
language as the pricing categories, and that language's headline is a
count. The number therefore has to come from the folder list itself: the
grid shows every folder at once, so counting per folder would turn one
request into one-per-folder for a purely visual field.

Two things are pinned here — that the number is RIGHT (it counts this
folder's own files, not a subtree, and not another customer's), and that
it costs NOTHING (the folder list stays a fixed number of queries as
folders are added).
"""
from __future__ import annotations

import tempfile

from django.db import connection
from django.test.utils import CaptureQueriesContext, override_settings
from rest_framework import status
from rest_framework.test import APITestCase

from documents.models import DocumentFolder, DocumentOrigin
from test_utils import TenantFixtureMixin

from ._helpers import DocumentsActorsMixin, files_url, folders_url, txt_upload


_MEDIA = tempfile.mkdtemp(prefix="doc-count-tests-")


@override_settings(MEDIA_ROOT=_MEDIA)
class FolderFileCountTests(
    DocumentsActorsMixin, TenantFixtureMixin, APITestCase
):
    def setUp(self):
        super().setUp()
        self.setup_documents_actors()
        self.overig = DocumentFolder.objects.get(
            customer=self.customer, system_slug="overig"
        )

    def _folders(self):
        response = self.client.get(folders_url(self.customer.id))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        return {row["id"]: row for row in response.data}

    def _upload(self, folder, name):
        return self.client.post(
            files_url(self.customer.id),
            {"folder": folder.id, "file": txt_upload(name)},
            format="multipart",
        )

    def test_an_empty_folder_reports_zero_not_null(self):
        self.authenticate(self.super_admin)
        rows = self._folders()
        self.assertEqual(rows[self.overig.id]["file_count"], 0)

    def test_the_count_follows_the_files(self):
        self.authenticate(self.super_admin)
        self._upload(self.overig, "a.txt")
        self._upload(self.overig, "b.txt")
        rows = self._folders()
        self.assertEqual(rows[self.overig.id]["file_count"], 2)

    def test_the_count_is_per_folder_not_per_subtree(self):
        """A parent's card shows ITS files, not its children's.

        The grid drills in one level at a time, so a parent whose number
        included its descendants would promise files that are not there
        when you open it.
        """
        self.authenticate(self.super_admin)
        child = DocumentFolder.objects.create(
            customer=self.customer,
            parent=self.overig,
            name="Child",
            origin=DocumentOrigin.PROVIDER,
            created_by=None,
        )
        self._upload(child, "in-child.txt")

        rows = self._folders()
        self.assertEqual(rows[self.overig.id]["file_count"], 0)
        self.assertEqual(rows[child.id]["file_count"], 1)

    def test_another_customers_files_are_not_counted(self):
        """Tenant scoping, asserted on the new field specifically.

        The endpoint is already customer-scoped; this pins that the
        annotation did not widen it by joining across the folder's own
        customer boundary.
        """
        self.authenticate(self.super_admin)
        second, _user = self.make_second_customer_same_tenant()
        other_overig = DocumentFolder.objects.get(
            customer=second, system_slug="overig"
        )
        self.client.post(
            files_url(second.id),
            {"folder": other_overig.id, "file": txt_upload("theirs.txt")},
            format="multipart",
        )

        rows = self._folders()
        self.assertNotIn(other_overig.id, rows)
        self.assertEqual(rows[self.overig.id]["file_count"], 0)

    def test_the_folder_list_cost_does_not_grow_with_folder_count(self):
        self.authenticate(self.super_admin)

        def measure():
            with CaptureQueriesContext(connection) as ctx:
                self.client.get(folders_url(self.customer.id))
            return len(ctx.captured_queries)

        # Warm-up, discarded: the first request pays one-off costs.
        measure()
        few = measure()

        for index in range(10):
            DocumentFolder.objects.create(
                customer=self.customer,
                parent=None,
                name=f"Folder {index:02d}",
                origin=DocumentOrigin.PROVIDER,
                created_by=None,
            )
        many = measure()

        self.assertEqual(
            few,
            many,
            f"the folder list grew with folder count ({few} -> {many}); "
            "file_count is no longer annotated",
        )
