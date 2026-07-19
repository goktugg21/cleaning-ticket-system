"""RF-1 — shared image-upload validation for profile photos and
customer / company logos.

This module has NO Django-model imports so it is safe to import from
`accounts`, `customers`, and `companies` without circular-import risk.

The validation mirrors the ticket-attachment discipline
(`tickets/serializers.py`: extension in an allow-list, declared
content-type in an allow-list, extension <-> declared MIME must agree)
and ADDS genuine content inspection: Pillow decodes the header and
confirms the real image format, so a mislabelled or non-image payload
(a PDF renamed `avatar.png`, a truncated file) cannot be stored. That
content check is the "magic-byte" validation the credentials infra was
believed to have but never actually did.
"""
from __future__ import annotations

from pathlib import Path

from PIL import Image, UnidentifiedImageError
from rest_framework import serializers

# jpeg / png / webp only (no HEIC — browsers can't render it inline, and
# these three cover every avatar/logo source we care about).
ALLOWED_IMAGE_EXTENSION_MIME_MAP: dict[str, set[str]] = {
    ".jpg": {"image/jpeg"},
    ".jpeg": {"image/jpeg"},
    ".png": {"image/png"},
    ".webp": {"image/webp"},
}

# Pillow's `Image.format` for each allowed declared MIME. Used to prove
# the decoded bytes match the claimed type, not just the extension.
_MIME_TO_PIL_FORMAT: dict[str, str] = {
    "image/jpeg": "JPEG",
    "image/png": "PNG",
    "image/webp": "WEBP",
}

MAX_IMAGE_SIZE = 2 * 1024 * 1024  # 2 MB

ALLOWED_IMAGE_MESSAGE = (
    "Only JPEG, PNG or WebP images are allowed (max 2 MB)."
)
IMAGE_MIME_PAIR_MESSAGE = "The file extension does not match its content type."
IMAGE_CONTENT_MESSAGE = "The uploaded file is not a valid image."


def validate_image_upload(value):
    """Validate an uploaded avatar/logo image.

    Raises `serializers.ValidationError` (stable `code`s) on any of:
    oversize, disallowed extension, disallowed declared MIME,
    extension<->MIME mismatch, or bytes that Pillow cannot decode as the
    claimed format. Returns the file unchanged on success (seek reset to
    0 so the storage backend reads from the start).
    """
    mime_type = getattr(value, "content_type", "") or "application/octet-stream"
    file_size = getattr(value, "size", 0)
    extension = Path(getattr(value, "name", "")).suffix.lower()

    if file_size > MAX_IMAGE_SIZE:
        raise serializers.ValidationError(
            ALLOWED_IMAGE_MESSAGE, code="image_too_large"
        )
    if extension not in ALLOWED_IMAGE_EXTENSION_MIME_MAP:
        raise serializers.ValidationError(
            ALLOWED_IMAGE_MESSAGE, code="invalid_image_extension"
        )
    if mime_type not in _MIME_TO_PIL_FORMAT:
        raise serializers.ValidationError(
            ALLOWED_IMAGE_MESSAGE, code="invalid_image_mime"
        )
    if mime_type not in ALLOWED_IMAGE_EXTENSION_MIME_MAP[extension]:
        raise serializers.ValidationError(
            IMAGE_MIME_PAIR_MESSAGE, code="invalid_image_mime_pair"
        )

    # Content inspection — decode the header and confirm the real format
    # matches the declared MIME. `verify()` validates structure without a
    # full decode; it leaves the file unusable for further reads, so the
    # caller-facing seek is reset afterwards.
    try:
        value.seek(0)
        with Image.open(value) as img:
            detected = (img.format or "").upper()
            img.verify()
    except (UnidentifiedImageError, OSError, ValueError, SyntaxError):
        raise serializers.ValidationError(
            IMAGE_CONTENT_MESSAGE, code="invalid_image_content"
        )
    finally:
        try:
            value.seek(0)
        except (OSError, ValueError):
            pass

    if detected != _MIME_TO_PIL_FORMAT[mime_type]:
        raise serializers.ValidationError(
            IMAGE_MIME_PAIR_MESSAGE, code="invalid_image_mime_pair"
        )

    return value


class ImageUploadSerializer(serializers.Serializer):
    """Shared multipart body for profile-photo / logo uploads: a single
    `file` part, validated by `validate_image_upload`. The view owns the
    permission gate + which model field the file lands on.
    """

    # FileField (not ImageField) so `validate_image_upload` owns every
    # check with stable codes, rather than DRF's generic image error
    # firing first.
    file = serializers.FileField(write_only=True)

    def validate_file(self, value):
        return validate_image_upload(value)
