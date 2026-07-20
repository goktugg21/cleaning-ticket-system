"""Invoicing Phase 4a — PDF-upload validation for the customer informational
contract PDF.

Mirrors `accounts.image_uploads` discipline (size cap + extension allow-list +
declared content-type check) and ADDS a magic-byte content check: a real PDF
starts with the `%PDF-` header, so a mislabelled payload (a PNG renamed
`contract.pdf`, an empty file) cannot be stored. No model imports here, so it
is safe to import from the customers views without circular-import risk.
"""
from __future__ import annotations

from pathlib import Path

from rest_framework import serializers

ALLOWED_PDF_CONTENT_TYPES: set[str] = {"application/pdf"}
MAX_PDF_SIZE = 10 * 1024 * 1024  # 10 MB
_PDF_MAGIC = b"%PDF-"

ALLOWED_PDF_MESSAGE = "Only a PDF file is allowed (max 10 MB)."
PDF_CONTENT_MESSAGE = "The uploaded file is not a valid PDF."


def validate_pdf_upload(value):
    """Validate an uploaded contract PDF. Raises `serializers.ValidationError`
    (stable `code`s) on oversize, wrong extension, wrong declared MIME, or
    bytes that do not begin with the `%PDF-` header. Returns the file unchanged
    on success (seek reset to 0 so storage reads from the start)."""
    file_size = getattr(value, "size", 0)
    extension = Path(getattr(value, "name", "")).suffix.lower()
    mime_type = (
        getattr(value, "content_type", "") or "application/octet-stream"
    )

    if file_size > MAX_PDF_SIZE:
        raise serializers.ValidationError(
            ALLOWED_PDF_MESSAGE, code="pdf_too_large"
        )
    if extension != ".pdf":
        raise serializers.ValidationError(
            ALLOWED_PDF_MESSAGE, code="invalid_pdf_extension"
        )
    if mime_type not in ALLOWED_PDF_CONTENT_TYPES:
        raise serializers.ValidationError(
            ALLOWED_PDF_MESSAGE, code="invalid_pdf_mime"
        )

    # Content inspection — the header must be the PDF magic bytes.
    try:
        value.seek(0)
        header = value.read(len(_PDF_MAGIC))
    except (OSError, ValueError):
        raise serializers.ValidationError(
            PDF_CONTENT_MESSAGE, code="invalid_pdf_content"
        )
    finally:
        try:
            value.seek(0)
        except (OSError, ValueError):
            pass

    if header != _PDF_MAGIC:
        raise serializers.ValidationError(
            PDF_CONTENT_MESSAGE, code="invalid_pdf_content"
        )
    return value


class PdfUploadSerializer(serializers.Serializer):
    """Shared multipart body for the customer contract-PDF upload: a single
    `file` part, validated by `validate_pdf_upload`. The view owns the
    permission gate + which model field the file lands on."""

    file = serializers.FileField(write_only=True)

    def validate_file(self, value):
        return validate_pdf_upload(value)
