"""Shared builders for the Sprint 125 documents tests.

Layers on top of the repo-wide `test_utils.TenantFixtureMixin`, which already
gives us Company A / B, a customer per company, and one member customer-user
each. We add: a document-specific URL set, sample uploads (real magic bytes,
a genuine OOXML package, a bare zip, binary-as-text), and small helpers to
mint the extra actors the permission matrix needs (STAFF, a company-wide CCA,
a no-key customer user, a second customer in the same tenant).
"""
from __future__ import annotations

import io
import zipfile

from django.core.files.uploadedfile import SimpleUploadedFile

from accounts.models import UserRole
from customers.models import (
    Customer,
    CustomerBuildingMembership,
    CustomerUserBuildingAccess,
    CustomerUserMembership,
)


# ---- URLs -----------------------------------------------------------------

def folders_url(customer_id) -> str:
    return f"/api/customers/{customer_id}/documents/folders/"


def folder_url(customer_id, folder_id) -> str:
    return f"/api/customers/{customer_id}/documents/folders/{folder_id}/"


def files_url(customer_id) -> str:
    return f"/api/customers/{customer_id}/documents/files/"


def file_url(customer_id, public_id) -> str:
    return f"/api/customers/{customer_id}/documents/files/{public_id}/"


# ---- sample upload payloads ----------------------------------------------

_PNG_1PX = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00"
    b"\x01\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
)


def pdf_upload(name="doc.pdf"):
    return SimpleUploadedFile(
        name, b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n1 0 obj\n", content_type="application/pdf"
    )


def png_upload(name="pic.png"):
    return SimpleUploadedFile(name, _PNG_1PX, content_type="image/png")


def jpeg_upload(name="pic.jpg"):
    return SimpleUploadedFile(
        name, b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01body", content_type="image/jpeg"
    )


def webp_upload(name="pic.webp"):
    body = b"RIFF" + b"\x1a\x00\x00\x00" + b"WEBP" + b"VP8 fakevp8payload"
    return SimpleUploadedFile(name, body, content_type="image/webp")


def txt_upload(name="notes.txt", body=b"hello, this is text\n"):
    return SimpleUploadedFile(name, body, content_type="text/plain")


def csv_upload(name="rows.csv", body=b"a,b,c\n1,2,3\n"):
    return SimpleUploadedFile(name, body, content_type="text/csv")


def _ooxml_bytes(prefix: str) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("[Content_Types].xml", "<?xml version='1.0'?><Types/>")
        zf.writestr(f"{prefix}/document.xml", "<w:document/>")
    return buf.getvalue()


def docx_upload(name="letter.docx"):
    return SimpleUploadedFile(
        name,
        _ooxml_bytes("word"),
        content_type=(
            "application/vnd.openxmlformats-officedocument."
            "wordprocessingml.document"
        ),
    )


def xlsx_upload(name="sheet.xlsx"):
    return SimpleUploadedFile(
        name,
        _ooxml_bytes("xl"),
        content_type=(
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        ),
    )


def bare_zip_as_docx(name="fake.docx"):
    """A real ZIP with NO OOXML marker members, uploaded claiming to be a
    DOCX — the OOXML structural check must reject it."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("hello.txt", "just a zip")
    return SimpleUploadedFile(
        name,
        buf.getvalue(),
        content_type=(
            "application/vnd.openxmlformats-officedocument."
            "wordprocessingml.document"
        ),
    )


def binary_as_txt(name="notes.txt"):
    """Binary (contains NUL) claiming to be text — the text check rejects it."""
    return SimpleUploadedFile(name, b"\x00\x01\x02binary", content_type="text/plain")


# ---- extra actors ---------------------------------------------------------

class DocumentsActorsMixin:
    """Adds the actors the documents permission matrix needs, on top of
    TenantFixtureMixin.setUp()."""

    def setup_documents_actors(self):
        # STAFF in company A (a provider role that is neither SA nor CA).
        self.staff = self.make_user("staff-a@example.com", UserRole.STAFF)

        # A company-wide Customer Company Admin of Customer A.
        self.cca = self.make_user("cca-a@example.com", UserRole.CUSTOMER_USER)
        CustomerUserMembership.objects.create(
            user=self.cca, customer=self.customer, is_company_admin=True
        )

        # A customer user who is a MEMBER of Customer A but whose documents
        # key is explicitly revoked (override False on the access row).
        self.nokey_user = self.make_user(
            "nokey-a@example.com", UserRole.CUSTOMER_USER
        )
        nokey_membership = CustomerUserMembership.objects.create(
            user=self.nokey_user, customer=self.customer
        )
        CustomerUserBuildingAccess.objects.create(
            membership=nokey_membership,
            building=self.building,
            permission_overrides={"customer.documents.manage": False},
        )

    def make_second_customer_same_tenant(self):
        """A SECOND customer in Company A, with its own member user — for the
        same-tenant-different-customer scoping checks."""
        second = Customer.objects.create(
            company=self.company, building=self.building, name="Customer A2"
        )
        CustomerBuildingMembership.objects.create(
            customer=second, building=self.building
        )
        user = self.make_user("cust-a2@example.com", UserRole.CUSTOMER_USER)
        membership = CustomerUserMembership.objects.create(
            user=user, customer=second
        )
        CustomerUserBuildingAccess.objects.create(
            membership=membership, building=self.building
        )
        return second, user
