"""Sprint 125 — folder CRUD, name uniqueness, move (cycle + depth), and the
system-folder / origin write rules."""
from __future__ import annotations

from rest_framework import status
from rest_framework.test import APITestCase

from documents.models import (
    MAX_FOLDER_DEPTH,
    DocumentFolder,
    DocumentOrigin,
)
from test_utils import TenantFixtureMixin

from ._helpers import DocumentsActorsMixin, folder_url, folders_url


class FolderTests(DocumentsActorsMixin, TenantFixtureMixin, APITestCase):
    def setUp(self):
        super().setUp()
        self.setup_documents_actors()
        self.overig = DocumentFolder.objects.get(
            customer=self.customer, system_slug="overig"
        )

    def _mk_folder(self, *, name, parent=None, origin=DocumentOrigin.CUSTOMER,
                   is_system=False, system_slug=""):
        return DocumentFolder.objects.create(
            customer=self.customer,
            parent=parent,
            name=name,
            origin=origin,
            is_system=is_system,
            system_slug=system_slug,
            created_by=None,
        )

    # -- create + origin stamping -------------------------------------------

    def test_customer_create_stamps_origin_customer(self):
        self.authenticate(self.customer_user)
        resp = self.client.post(folders_url(self.customer.id), {"name": "Mine"})
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        self.assertEqual(resp.data["origin"], DocumentOrigin.CUSTOMER)

    def test_provider_create_stamps_origin_provider(self):
        self.authenticate(self.super_admin)
        resp = self.client.post(folders_url(self.customer.id), {"name": "Prov"})
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        self.assertEqual(resp.data["origin"], DocumentOrigin.PROVIDER)

    # -- name uniqueness (case-insensitive, per (customer, parent)) ----------

    def test_duplicate_root_name_case_insensitive_rejected(self):
        self.authenticate(self.super_admin)
        self.client.post(folders_url(self.customer.id), {"name": "Reports"})
        resp = self.client.post(
            folders_url(self.customer.id), {"name": "  reports "}
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(resp.data["code"], "folder_name_conflict")

    def test_same_name_under_different_parents_allowed(self):
        self.authenticate(self.super_admin)
        a = self._mk_folder(name="A", origin=DocumentOrigin.PROVIDER)
        b = self._mk_folder(name="B", origin=DocumentOrigin.PROVIDER)
        r1 = self.client.post(
            folders_url(self.customer.id), {"name": "Sub", "parent": a.id}
        )
        r2 = self.client.post(
            folders_url(self.customer.id), {"name": "Sub", "parent": b.id}
        )
        self.assertEqual(r1.status_code, status.HTTP_201_CREATED)
        self.assertEqual(r2.status_code, status.HTTP_201_CREATED)

    # -- rename / move -------------------------------------------------------

    def test_rename_and_move(self):
        self.authenticate(self.super_admin)
        parent = self._mk_folder(name="Parent", origin=DocumentOrigin.PROVIDER)
        child = self._mk_folder(name="Child", origin=DocumentOrigin.PROVIDER)
        # rename
        r = self.client.patch(
            folder_url(self.customer.id, child.id), {"name": "Renamed"}
        )
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.assertEqual(r.data["name"], "Renamed")
        # move under parent
        r = self.client.patch(
            folder_url(self.customer.id, child.id), {"parent": parent.id}
        )
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        child.refresh_from_db()
        self.assertEqual(child.parent_id, parent.id)

    def test_move_to_root_with_null_parent(self):
        self.authenticate(self.super_admin)
        parent = self._mk_folder(name="P", origin=DocumentOrigin.PROVIDER)
        child = self._mk_folder(
            name="C", parent=parent, origin=DocumentOrigin.PROVIDER
        )
        # Explicit null parent must go as JSON (the form encoder cannot
        # represent None; a real client sends `"parent": null`).
        r = self.client.patch(
            folder_url(self.customer.id, child.id), {"parent": None}, format="json"
        )
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        child.refresh_from_db()
        self.assertIsNone(child.parent_id)

    def test_empty_patch_rejected(self):
        self.authenticate(self.super_admin)
        f = self._mk_folder(name="F", origin=DocumentOrigin.PROVIDER)
        r = self.client.patch(folder_url(self.customer.id, f.id), {})
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(r.data["code"], "no_changes")

    # -- move validation: cycle + depth -------------------------------------

    def test_move_into_own_descendant_rejected(self):
        self.authenticate(self.super_admin)
        a = self._mk_folder(name="A", origin=DocumentOrigin.PROVIDER)
        b = self._mk_folder(name="B", parent=a, origin=DocumentOrigin.PROVIDER)
        c = self._mk_folder(name="C", parent=b, origin=DocumentOrigin.PROVIDER)
        # Move A under C (its own grandchild) -> cycle.
        r = self.client.patch(
            folder_url(self.customer.id, a.id), {"parent": c.id}
        )
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(r.data["code"], "folder_cycle")

    def test_move_into_self_rejected(self):
        self.authenticate(self.super_admin)
        a = self._mk_folder(name="A", origin=DocumentOrigin.PROVIDER)
        r = self.client.patch(
            folder_url(self.customer.id, a.id), {"parent": a.id}
        )
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(r.data["code"], "folder_cycle")

    def _build_chain(self, depth):
        """Create a root->...->leaf chain `depth` folders deep; return leaf."""
        node = self._mk_folder(name="d1", origin=DocumentOrigin.PROVIDER)
        for i in range(2, depth + 1):
            node = self._mk_folder(
                name=f"d{i}", parent=node, origin=DocumentOrigin.PROVIDER
            )
        return node

    def test_create_at_max_depth_ok_and_beyond_rejected(self):
        self.authenticate(self.super_admin)
        leaf9 = self._build_chain(MAX_FOLDER_DEPTH - 1)  # depth 9
        # child of depth-9 -> depth 10 == cap -> OK
        ok = self.client.post(
            folders_url(self.customer.id),
            {"name": "at_cap", "parent": leaf9.id},
        )
        self.assertEqual(ok.status_code, status.HTTP_201_CREATED)
        # child of the depth-10 folder -> depth 11 -> rejected
        too_deep = self.client.post(
            folders_url(self.customer.id),
            {"name": "too_deep", "parent": ok.data["id"]},
        )
        self.assertEqual(too_deep.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(too_deep.data["code"], "folder_depth_exceeded")

    def test_move_that_would_exceed_depth_rejected(self):
        self.authenticate(self.super_admin)
        # A two-level subtree (height 2) and a depth-9 leaf. Moving the
        # subtree root under the depth-9 leaf makes its deepest node depth 11.
        sub_root = self._mk_folder(name="sr", origin=DocumentOrigin.PROVIDER)
        self._mk_folder(name="sr_child", parent=sub_root,
                        origin=DocumentOrigin.PROVIDER)
        leaf9 = self._build_chain(MAX_FOLDER_DEPTH - 1)
        r = self.client.patch(
            folder_url(self.customer.id, sub_root.id), {"parent": leaf9.id}
        )
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(r.data["code"], "folder_depth_exceeded")

    # -- delete: empty-only --------------------------------------------------

    def test_delete_empty_folder(self):
        self.authenticate(self.super_admin)
        f = self._mk_folder(name="empty", origin=DocumentOrigin.PROVIDER)
        r = self.client.delete(folder_url(self.customer.id, f.id))
        self.assertEqual(r.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(DocumentFolder.objects.filter(pk=f.id).exists())

    def test_delete_folder_with_subfolder_rejected(self):
        self.authenticate(self.super_admin)
        parent = self._mk_folder(name="p", origin=DocumentOrigin.PROVIDER)
        self._mk_folder(name="c", parent=parent, origin=DocumentOrigin.PROVIDER)
        r = self.client.delete(folder_url(self.customer.id, parent.id))
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(r.data["code"], "folder_not_empty")

    # -- system folders ------------------------------------------------------

    def test_provider_can_rename_system_folder(self):
        self.authenticate(self.super_admin)
        r = self.client.patch(
            folder_url(self.customer.id, self.overig.id),
            {"name": "Diversen"},
        )
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.overig.refresh_from_db()
        self.assertEqual(self.overig.name, "Diversen")
        self.assertEqual(self.overig.system_slug, "overig")  # slug never moves

    def test_customer_cannot_rename_system_folder(self):
        self.authenticate(self.customer_user)
        r = self.client.patch(
            folder_url(self.customer.id, self.overig.id), {"name": "Nope"}
        )
        self.assertEqual(r.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(r.data["code"], "system_folder_readonly")

    def test_system_folder_move_rejected_even_for_provider(self):
        self.authenticate(self.super_admin)
        other = self._mk_folder(name="dest", origin=DocumentOrigin.PROVIDER)
        r = self.client.patch(
            folder_url(self.customer.id, self.overig.id), {"parent": other.id}
        )
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(r.data["code"], "system_folder_immovable")

    def test_system_folder_delete_rejected_even_for_provider(self):
        self.authenticate(self.super_admin)
        r = self.client.delete(folder_url(self.customer.id, self.overig.id))
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(r.data["code"], "system_folder_undeletable")

    def test_customer_can_create_subfolder_in_system_folder(self):
        # Sprint 125 correction: a customer MAY create a subfolder inside a
        # system folder; the new folder is stamped origin=CUSTOMER.
        self.authenticate(self.customer_user)
        r = self.client.post(
            folders_url(self.customer.id),
            {"name": "sub", "parent": self.overig.id},
        )
        self.assertEqual(r.status_code, status.HTTP_201_CREATED)
        self.assertEqual(r.data["origin"], DocumentOrigin.CUSTOMER)

    def test_provider_can_create_subfolder_in_system_folder(self):
        self.authenticate(self.super_admin)
        r = self.client.post(
            folders_url(self.customer.id),
            {"name": "sub", "parent": self.overig.id},
        )
        self.assertEqual(r.status_code, status.HTTP_201_CREATED)

    # -- origin ownership on non-system folders ------------------------------

    def test_customer_cannot_modify_provider_origin_folder(self):
        provider_folder = self._mk_folder(
            name="ProviderOwned", origin=DocumentOrigin.PROVIDER
        )
        self.authenticate(self.customer_user)
        r = self.client.patch(
            folder_url(self.customer.id, provider_folder.id), {"name": "x"}
        )
        self.assertEqual(r.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(r.data["code"], "not_owner")
        # delete likewise
        r = self.client.delete(folder_url(self.customer.id, provider_folder.id))
        self.assertEqual(r.status_code, status.HTTP_403_FORBIDDEN)

    def test_customer_can_modify_own_origin_folder(self):
        own = self._mk_folder(name="CustOwned", origin=DocumentOrigin.CUSTOMER)
        self.authenticate(self.customer_user)
        r = self.client.patch(
            folder_url(self.customer.id, own.id), {"name": "Renamed"}
        )
        self.assertEqual(r.status_code, status.HTTP_200_OK)

    def test_provider_can_modify_customer_origin_folder(self):
        cust = self._mk_folder(name="CustOwned", origin=DocumentOrigin.CUSTOMER)
        self.authenticate(self.company_admin)
        r = self.client.patch(
            folder_url(self.customer.id, cust.id), {"name": "ProviderTouched"}
        )
        self.assertEqual(r.status_code, status.HTTP_200_OK)
