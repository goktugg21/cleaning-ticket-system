"""
Sprint 125 — upload validation for customer documents.

Mirrors `customers/pdf_uploads.py`'s discipline (size cap + extension
allow-list + declared content-type check + magic-byte content check) and
extends it to a wider allow-list with two cases that need real inspection,
not a header peek:

  * DOCX / XLSX are ZIP containers (both start `PK\\x03\\x04`), so the magic
    bytes alone cannot tell a real OOXML package from a `.zip` renamed
    `.docx`. We open the container and require the OOXML marker member
    `[Content_Types].xml`, plus the app-specific `word/` or `xl/` prefix.
  * TXT / CSV have NO magic bytes, so "check the header" is meaningless. We
    require the payload to decode as UTF-8 and contain no NUL byte — enough
    to reject a binary blob renamed `.txt` without imposing a schema on the
    text itself.

Explicitly NOT allowed: ZIP (a renamed archive is exactly the payload the
OOXML check exists to reject). No model imports here, so it is safe to
import from the documents views without circular-import risk.

Every rejection raises `serializers.ValidationError` with a STABLE `code`.
"""
from __future__ import annotations

import io
import zipfile
from pathlib import Path

from rest_framework import serializers


MAX_DOCUMENT_SIZE = 25 * 1024 * 1024  # 25 MB

# Human-readable summary used on the size / extension / mime rejections.
ALLOWED_DOCUMENT_MESSAGE = (
    "Allowed: PDF, PNG, JPG, WEBP, TXT, CSV, DOCX, XLSX (max 25 MB)."
)
DOCUMENT_CONTENT_MESSAGE = "The uploaded file's contents do not match its type."

# Magic-byte signatures for the binary formats. WEBP and the OOXML pair need
# structural checks beyond a prefix, handled below.
_PDF_MAGIC = b"%PDF-"
_PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
_JPEG_MAGIC = b"\xff\xd8\xff"
_ZIP_MAGIC = b"PK\x03\x04"  # DOCX / XLSX containers (and bare ZIP — rejected)

# ext -> the declared content-types we accept for it. The declared MIME must
# be in this set (mirrors pdf_uploads' declared-type gate); the magic-byte /
# structural check below is the real guarantee.
_EXTENSION_CONTENT_TYPES: dict[str, set[str]] = {
    ".pdf": {"application/pdf"},
    ".png": {"image/png"},
    ".jpg": {"image/jpeg"},
    ".jpeg": {"image/jpeg"},
    ".webp": {"image/webp"},
    ".txt": {"text/plain"},
    ".csv": {"text/csv", "text/plain", "application/csv"},
    ".docx": {
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    },
    ".xlsx": {
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    },
}

# Inline-serve set (§4): PDF + images render inline; everything else is
# forced to `attachment`. Keyed by stored mime_type.
INLINE_MIME_TYPES: frozenset[str] = frozenset(
    {"application/pdf", "image/png", "image/jpeg", "image/webp"}
)


def _read_head(value, n: int) -> bytes:
    try:
        value.seek(0)
        return value.read(n)
    except (OSError, ValueError):
        raise serializers.ValidationError(
            DOCUMENT_CONTENT_MESSAGE, code="invalid_document_content"
        )
    finally:
        try:
            value.seek(0)
        except (OSError, ValueError):
            pass


def _read_all(value) -> bytes:
    try:
        value.seek(0)
        return value.read()
    except (OSError, ValueError):
        raise serializers.ValidationError(
            DOCUMENT_CONTENT_MESSAGE, code="invalid_document_content"
        )
    finally:
        try:
            value.seek(0)
        except (OSError, ValueError):
            pass


def _validate_webp(value) -> None:
    # RIFF container: bytes 0-3 == "RIFF", bytes 8-11 == "WEBP".
    head = _read_head(value, 12)
    if len(head) < 12 or head[0:4] != b"RIFF" or head[8:12] != b"WEBP":
        raise serializers.ValidationError(
            DOCUMENT_CONTENT_MESSAGE, code="invalid_document_content"
        )


def _validate_ooxml(value, *, expected_prefix: str) -> None:
    """Verify the payload is a real OOXML package, not a renamed ZIP.

    Requires: the ZIP local-file magic, a readable central directory, the
    `[Content_Types].xml` marker every OOXML package carries, and at least
    one member under the app-specific prefix (`word/` for DOCX, `xl/` for
    XLSX). A plain `.zip` renamed `.docx` has the magic but lacks the marker
    member, so it is rejected with `invalid_ooxml_package`.
    """
    head = _read_head(value, len(_ZIP_MAGIC))
    if head != _ZIP_MAGIC:
        raise serializers.ValidationError(
            DOCUMENT_CONTENT_MESSAGE, code="invalid_document_content"
        )
    raw = _read_all(value)
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as zf:
            names = set(zf.namelist())
    except zipfile.BadZipFile:
        raise serializers.ValidationError(
            "The file is not a valid Office document.",
            code="invalid_ooxml_package",
        )
    if "[Content_Types].xml" not in names or not any(
        n.startswith(expected_prefix) for n in names
    ):
        raise serializers.ValidationError(
            "The file is not a valid Office document.",
            code="invalid_ooxml_package",
        )


def _validate_text(value) -> None:
    """TXT / CSV have no magic bytes; require valid UTF-8 with no NUL byte
    (a NUL is the cheapest reliable 'this is actually binary' tell)."""
    raw = _read_all(value)
    if b"\x00" in raw:
        raise serializers.ValidationError(
            "The file does not look like text.", code="invalid_text_encoding"
        )
    try:
        raw.decode("utf-8")
    except UnicodeDecodeError:
        raise serializers.ValidationError(
            "The file is not valid UTF-8 text.", code="invalid_text_encoding"
        )


def _validate_content(value, extension: str) -> None:
    if extension == ".pdf":
        if _read_head(value, len(_PDF_MAGIC)) != _PDF_MAGIC:
            raise serializers.ValidationError(
                DOCUMENT_CONTENT_MESSAGE, code="invalid_document_content"
            )
    elif extension == ".png":
        if _read_head(value, len(_PNG_MAGIC)) != _PNG_MAGIC:
            raise serializers.ValidationError(
                DOCUMENT_CONTENT_MESSAGE, code="invalid_document_content"
            )
    elif extension in (".jpg", ".jpeg"):
        if _read_head(value, len(_JPEG_MAGIC)) != _JPEG_MAGIC:
            raise serializers.ValidationError(
                DOCUMENT_CONTENT_MESSAGE, code="invalid_document_content"
            )
    elif extension == ".webp":
        _validate_webp(value)
    elif extension == ".docx":
        _validate_ooxml(value, expected_prefix="word/")
    elif extension == ".xlsx":
        _validate_ooxml(value, expected_prefix="xl/")
    elif extension in (".txt", ".csv"):
        _validate_text(value)
    else:  # pragma: no cover — unreachable; extension gate ran first.
        raise serializers.ValidationError(
            ALLOWED_DOCUMENT_MESSAGE, code="invalid_document_extension"
        )


def validate_document_upload(value):
    """Validate an uploaded document. Raises `serializers.ValidationError`
    (stable `code`s) on oversize, disallowed extension, wrong declared MIME,
    or content that does not match the claimed type. Returns the file
    unchanged on success (seek reset to 0 so storage reads from the start)."""
    file_size = getattr(value, "size", 0)
    extension = Path(getattr(value, "name", "")).suffix.lower()
    mime_type = getattr(value, "content_type", "") or "application/octet-stream"

    if file_size > MAX_DOCUMENT_SIZE:
        raise serializers.ValidationError(
            ALLOWED_DOCUMENT_MESSAGE, code="document_too_large"
        )
    if extension not in _EXTENSION_CONTENT_TYPES:
        raise serializers.ValidationError(
            ALLOWED_DOCUMENT_MESSAGE, code="invalid_document_extension"
        )
    if mime_type not in _EXTENSION_CONTENT_TYPES[extension]:
        raise serializers.ValidationError(
            ALLOWED_DOCUMENT_MESSAGE, code="invalid_document_mime"
        )

    _validate_content(value, extension)
    try:
        value.seek(0)
    except (OSError, ValueError):
        pass
    return value
