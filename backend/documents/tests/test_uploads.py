"""Sprint 125 — upload validation, tested directly against
`validate_document_upload` (a pure function; no DB, no media).

Covers the happy path for each allowed type and every rejection branch,
including the two that needed real inspection: a bare ZIP renamed .docx
(OOXML structural check) and binary bytes renamed .txt (text check)."""
from __future__ import annotations

from django.test import SimpleTestCase
from rest_framework import serializers

from documents.uploads import MAX_DOCUMENT_SIZE, validate_document_upload

from ._helpers import (
    bare_zip_as_docx,
    binary_as_txt,
    csv_upload,
    docx_upload,
    jpeg_upload,
    pdf_upload,
    png_upload,
    txt_upload,
    webp_upload,
    xlsx_upload,
)
from django.core.files.uploadedfile import SimpleUploadedFile


class UploadValidationTests(SimpleTestCase):
    def _code(self, upload) -> str:
        with self.assertRaises(serializers.ValidationError) as ctx:
            validate_document_upload(upload)
        return ctx.exception.detail[0].code

    # -- happy path: every allowed type -------------------------------------

    def test_all_allowed_types_pass(self):
        for factory in (
            pdf_upload,
            png_upload,
            jpeg_upload,
            webp_upload,
            txt_upload,
            csv_upload,
            docx_upload,
            xlsx_upload,
        ):
            with self.subTest(factory=factory.__name__):
                # Should not raise.
                validate_document_upload(factory())

    # -- size / extension / declared mime -----------------------------------

    def test_oversize_rejected(self):
        f = pdf_upload()
        f.size = MAX_DOCUMENT_SIZE + 1
        self.assertEqual(self._code(f), "document_too_large")

    def test_disallowed_extension_rejected(self):
        f = SimpleUploadedFile(
            "archive.zip", b"PK\x03\x04rest", content_type="application/zip"
        )
        self.assertEqual(self._code(f), "invalid_document_extension")

    def test_wrong_declared_mime_rejected(self):
        # Real PDF bytes + .pdf name, but the declared content-type is wrong.
        f = SimpleUploadedFile(
            "doc.pdf", b"%PDF-1.4 body", content_type="image/png"
        )
        self.assertEqual(self._code(f), "invalid_document_mime")

    # -- magic-byte content checks ------------------------------------------

    def test_png_bytes_named_pdf_rejected_on_content(self):
        # Passes extension (.pdf) + declared mime (application/pdf) but the
        # bytes are a PNG -> content check fails.
        f = SimpleUploadedFile(
            "fake.pdf", png_upload().read(), content_type="application/pdf"
        )
        self.assertEqual(self._code(f), "invalid_document_content")

    def test_webp_bad_container_rejected(self):
        f = SimpleUploadedFile(
            "x.webp", b"RIFF\x10\x00\x00\x00NOPEpadding", content_type="image/webp"
        )
        self.assertEqual(self._code(f), "invalid_document_content")

    def test_jpeg_bad_magic_rejected(self):
        f = SimpleUploadedFile(
            "x.jpg", b"\xff\xd8\x00 notjpeg", content_type="image/jpeg"
        )
        self.assertEqual(self._code(f), "invalid_document_content")

    # -- OOXML structural check ---------------------------------------------

    def test_bare_zip_renamed_docx_rejected(self):
        self.assertEqual(self._code(bare_zip_as_docx()), "invalid_ooxml_package")

    def test_non_zip_named_docx_rejected_on_content(self):
        f = SimpleUploadedFile(
            "x.docx",
            b"not a zip at all",
            content_type=(
                "application/vnd.openxmlformats-officedocument."
                "wordprocessingml.document"
            ),
        )
        self.assertEqual(self._code(f), "invalid_document_content")

    # -- text check ----------------------------------------------------------

    def test_binary_named_txt_rejected(self):
        self.assertEqual(self._code(binary_as_txt()), "invalid_text_encoding")

    def test_invalid_utf8_named_csv_rejected(self):
        f = SimpleUploadedFile(
            "x.csv", b"\xff\xfeinvalid utf8", content_type="text/csv"
        )
        self.assertEqual(self._code(f), "invalid_text_encoding")
