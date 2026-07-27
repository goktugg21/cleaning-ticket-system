"""
Sprint 125 — customer documents endpoints, all under
`/api/customers/<customer_id>/documents/`.

The view layer is the ONE chokepoint: it resolves the actor's access SIDE
(provider / customer / none → 404), then combines that side with each row's
`origin` / `is_system` to authorize the mutation, and owns the tree rules
(cycle / depth) and the origin-stamping. Every row lookup is scoped to the
URL customer, so a cross-tenant id is a 404 at the row level too.
"""
from __future__ import annotations

from urllib.parse import quote

from django.db import IntegrityError
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.exceptions import PermissionDenied
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.models import UserRole
from accounts.permissions import IsAuthenticatedAndActive
from accounts.scoping import scope_customers_for
from audit import context as audit_context
from customers.models import Customer

from .access import (
    AccessSide,
    can_modify_row,
    can_place_in_folder,
    can_rename_system_folder,
    origin_for_side,
    resolve_access,
)
from .models import MAX_FOLDER_DEPTH, Document, DocumentFolder
from .serializers import (
    DocumentFolderReadSerializer,
    DocumentReadSerializer,
    DocumentUpdateSerializer,
    DocumentUploadSerializer,
    FolderCreateSerializer,
    FolderUpdateSerializer,
)


def _err(message: str, code: str, http_status: int) -> Response:
    return Response({"detail": message, "code": code}, status=http_status)


class _DocumentsBase(APIView):
    """Shared access resolution.

    READ (`resolve_read`): an actor with no access side 404s the whole
    customer's document space — no existence leak, cross-tenant included.

    WRITE (`resolve_write`): same, EXCEPT a provider employee who can already
    SEE this customer elsewhere in the app but isn't SA/CA (a BUILDING_MANAGER
    or STAFF in scope) gets 403, not 404 — "the tab doesn't exist for you"
    on read, "you may not write here" on write (spec §3). Everyone with no
    legitimate view at all (cross-tenant customer user, other-company admin,
    no-key customer user) still 404s so nothing leaks across tenants.
    """

    permission_classes = [IsAuthenticatedAndActive]

    def resolve_read(self, request, customer_id):
        customer = get_object_or_404(Customer, pk=customer_id)
        side = resolve_access(request.user, customer)
        if side is None:
            raise Http404("No documents.")
        return customer, side

    def resolve_write(self, request, customer_id):
        customer = get_object_or_404(Customer, pk=customer_id)
        side = resolve_access(request.user, customer)
        if side is not None:
            return customer, side
        actor = request.user
        if actor.role in (
            UserRole.BUILDING_MANAGER,
            UserRole.STAFF,
        ) and scope_customers_for(actor).filter(pk=customer.pk).exists():
            raise PermissionDenied(
                "You may not modify this customer's documents."
            )
        raise Http404("No documents.")

    def _scoped_folder(self, customer, folder_id) -> DocumentFolder:
        return get_object_or_404(DocumentFolder, pk=folder_id, customer=customer)


class DocumentFolderListCreateView(_DocumentsBase):
    def get(self, request, customer_id):
        # The whole flat folder list for this customer (each row carries its
        # `parent`, so the client assembles the tree in one round trip — no
        # per-node fetch). Bounded by the single customer; a customer's folder
        # count is small by construction.
        customer, _side = self.resolve_read(request, customer_id)
        folders = DocumentFolder.objects.filter(customer=customer)
        return Response(DocumentFolderReadSerializer(folders, many=True).data)

    def post(self, request, customer_id):
        customer, side = self.resolve_write(request, customer_id)
        serializer = FolderCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        name = serializer.validated_data["name"]
        parent_id = serializer.validated_data.get("parent")

        parent = None
        if parent_id is not None:
            parent = self._scoped_folder(customer, parent_id)

        if not can_place_in_folder(side, parent):
            return _err(
                "You may not create a folder inside a system folder.",
                "system_folder_readonly",
                status.HTTP_403_FORBIDDEN,
            )

        base_depth = 1 if parent is None else parent.depth() + 1
        if base_depth > MAX_FOLDER_DEPTH:
            return _err(
                f"Folders may be nested at most {MAX_FOLDER_DEPTH} deep.",
                "folder_depth_exceeded",
                status.HTTP_400_BAD_REQUEST,
            )

        folder = DocumentFolder(
            customer=customer,
            parent=parent,
            name=name,
            is_system=False,
            system_slug="",
            origin=origin_for_side(side),
            created_by=request.user,
        )
        audit_context.set_current_reason("document_folder_create")
        try:
            folder.save()
        except IntegrityError:
            return _err(
                "A folder with this name already exists here.",
                "folder_name_conflict",
                status.HTTP_400_BAD_REQUEST,
            )
        return Response(
            DocumentFolderReadSerializer(folder).data,
            status=status.HTTP_201_CREATED,
        )


class DocumentFolderDetailView(_DocumentsBase):
    def patch(self, request, customer_id, folder_id):
        customer, side = self.resolve_write(request, customer_id)
        folder = self._scoped_folder(customer, folder_id)
        serializer = FolderUpdateSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        rename = "name" in data
        move = "parent" in data
        if not rename and not move:
            return _err(
                "Nothing to update.", "no_changes", status.HTTP_400_BAD_REQUEST
            )

        if folder.is_system:
            # System folders: rename is provider-only; move is always
            # rejected (for provider AND customer).
            if move:
                return _err(
                    "A system folder cannot be moved.",
                    "system_folder_immovable",
                    status.HTTP_400_BAD_REQUEST,
                )
            if not can_rename_system_folder(side):
                return _err(
                    "You may not modify a system folder.",
                    "system_folder_readonly",
                    status.HTTP_403_FORBIDDEN,
                )
        else:
            if not can_modify_row(
                side, origin=folder.origin, is_system=False
            ):
                return _err(
                    "You may not modify this folder.",
                    "not_owner",
                    status.HTTP_403_FORBIDDEN,
                )

        # --- apply move (validate cycle + depth + placement first) ---
        if move:
            new_parent_id = data["parent"]
            new_parent = None
            if new_parent_id is not None:
                new_parent = self._scoped_folder(customer, new_parent_id)
            if not can_place_in_folder(side, new_parent):
                return _err(
                    "You may not move a folder into a system folder.",
                    "system_folder_readonly",
                    status.HTTP_403_FORBIDDEN,
                )
            if new_parent is not None:
                if new_parent.id == folder.id or new_parent.id in (
                    folder.descendant_ids()
                ):
                    return _err(
                        "A folder cannot be moved into itself or a descendant.",
                        "folder_cycle",
                        status.HTTP_400_BAD_REQUEST,
                    )
            base_depth = 1 if new_parent is None else new_parent.depth() + 1
            deepest = base_depth + folder.subtree_height() - 1
            if deepest > MAX_FOLDER_DEPTH:
                return _err(
                    f"That move would nest folders more than "
                    f"{MAX_FOLDER_DEPTH} deep.",
                    "folder_depth_exceeded",
                    status.HTTP_400_BAD_REQUEST,
                )
            folder.parent = new_parent

        if rename:
            folder.name = data["name"]

        audit_context.set_current_reason("document_folder_update")
        try:
            folder.save()
        except IntegrityError:
            return _err(
                "A folder with this name already exists here.",
                "folder_name_conflict",
                status.HTTP_400_BAD_REQUEST,
            )
        return Response(DocumentFolderReadSerializer(folder).data)

    def delete(self, request, customer_id, folder_id):
        customer, side = self.resolve_write(request, customer_id)
        folder = self._scoped_folder(customer, folder_id)

        if folder.is_system:
            return _err(
                "A system folder cannot be deleted.",
                "system_folder_undeletable",
                status.HTTP_400_BAD_REQUEST,
            )
        if not can_modify_row(side, origin=folder.origin, is_system=False):
            return _err(
                "You may not delete this folder.",
                "not_owner",
                status.HTTP_403_FORBIDDEN,
            )
        if folder.children.exists() or folder.documents.exists():
            return _err(
                "Only an empty folder can be deleted.",
                "folder_not_empty",
                status.HTTP_400_BAD_REQUEST,
            )
        audit_context.set_current_reason("document_folder_delete")
        folder.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class DocumentUploadView(_DocumentsBase):
    parser_classes = [MultiPartParser, FormParser]

    def post(self, request, customer_id):
        customer, side = self.resolve_write(request, customer_id)
        serializer = DocumentUploadSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        upload = serializer.validated_data["file"]
        folder = self._scoped_folder(
            customer, serializer.validated_data["folder"]
        )

        if not can_place_in_folder(side, folder):
            return _err(
                "You may not upload into a system folder.",
                "system_folder_readonly",
                status.HTTP_403_FORBIDDEN,
            )

        document = Document(
            folder=folder,
            customer=customer,
            file=upload,
            original_filename=upload.name,
            mime_type=(upload.content_type or "application/octet-stream"),
            file_size=upload.size,
            origin=origin_for_side(side),
            uploaded_by=request.user,
        )
        audit_context.set_current_reason("document_upload")
        document.save()
        return Response(
            DocumentReadSerializer(document).data,
            status=status.HTTP_201_CREATED,
        )


class DocumentDetailView(_DocumentsBase):
    parser_classes = [MultiPartParser, FormParser]

    def _scoped_document(self, customer, public_id) -> Document:
        return get_object_or_404(Document, public_id=public_id, customer=customer)

    def get(self, request, customer_id, public_id):
        customer, _side = self.resolve_read(request, customer_id)
        document = self._scoped_document(customer, public_id)
        # Inline only for PDF + images (§4); everything else forced to
        # attachment, no exceptions.
        from .uploads import INLINE_MIME_TYPES

        disposition = (
            "inline" if document.mime_type in INLINE_MIME_TYPES else "attachment"
        )
        try:
            handle = document.file.open("rb")
        except (FileNotFoundError, ValueError):
            # A missing physical file behaves like a missing row: 404, no leak.
            raise Http404("No document.")
        response = FileResponse(handle, content_type=document.mime_type)
        filename = quote(document.original_filename)
        response["Content-Disposition"] = (
            f"{disposition}; filename*=UTF-8''{filename}"
        )
        return response

    def patch(self, request, customer_id, public_id):
        customer, side = self.resolve_write(request, customer_id)
        document = self._scoped_document(customer, public_id)
        if not can_modify_row(side, origin=document.origin, is_system=False):
            return _err(
                "You may not modify this document.",
                "not_owner",
                status.HTTP_403_FORBIDDEN,
            )
        serializer = DocumentUpdateSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        rename = "original_filename" in data
        move = "folder" in data
        if not rename and not move:
            return _err(
                "Nothing to update.", "no_changes", status.HTTP_400_BAD_REQUEST
            )

        if move:
            new_folder = self._scoped_folder(customer, data["folder"])
            if not can_place_in_folder(side, new_folder):
                return _err(
                    "You may not move a document into a system folder.",
                    "system_folder_readonly",
                    status.HTTP_403_FORBIDDEN,
                )
            document.folder = new_folder
        if rename:
            document.original_filename = data["original_filename"]

        audit_context.set_current_reason("document_update")
        document.save(update_fields=["folder", "original_filename"])
        return Response(DocumentReadSerializer(document).data)

    def delete(self, request, customer_id, public_id):
        customer, side = self.resolve_write(request, customer_id)
        document = self._scoped_document(customer, public_id)
        if not can_modify_row(side, origin=document.origin, is_system=False):
            return _err(
                "You may not delete this document.",
                "not_owner",
                status.HTTP_403_FORBIDDEN,
            )
        # Delete the ROW first (fires the filenames-only DELETE audit while
        # the instance still carries filename / folder / uploader), THEN the
        # physical file. A failed file delete leaves an orphan blob, never an
        # un-audited row.
        file_ref = document.file
        audit_context.set_current_reason("document_delete")
        document.delete()
        if file_ref:
            file_ref.delete(save=False)
        return Response(status=status.HTTP_204_NO_CONTENT)
