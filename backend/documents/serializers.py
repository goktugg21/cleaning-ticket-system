"""Sprint 125 — read + input serializers for customer documents.

Read serializers expose `origin` / `is_system` so the client can grey out
what the actor may not modify. Input serializers stay deliberately thin: the
authorization (side × origin × is_system), the cross-tenant scoping, and the
tree rules (cycle / depth) all live in the view so there is ONE chokepoint,
not rules split between serializer and view.
"""
from __future__ import annotations

from rest_framework import serializers

from .models import Document, DocumentFolder
from .uploads import validate_document_upload


class DocumentFolderReadSerializer(serializers.ModelSerializer):
    parent = serializers.PrimaryKeyRelatedField(read_only=True)

    class Meta:
        model = DocumentFolder
        fields = [
            "id",
            "parent",
            "name",
            "is_system",
            "system_slug",
            "origin",
            "created_at",
        ]
        read_only_fields = fields


class DocumentReadSerializer(serializers.ModelSerializer):
    uploaded_by_email = serializers.SerializerMethodField()

    class Meta:
        model = Document
        fields = [
            "public_id",
            "folder",
            "original_filename",
            "mime_type",
            "file_size",
            "origin",
            "uploaded_by_email",
            "created_at",
        ]
        read_only_fields = fields

    def get_uploaded_by_email(self, obj: Document):
        return obj.uploaded_by.email if obj.uploaded_by_id else None


class FolderCreateSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=255)
    # Resolved + scoped in the view (None = root). IntegerField (not a
    # PK-related field) so an out-of-scope / cross-tenant parent is a clean
    # 404 from the view, not a global "does this pk exist" 400.
    parent = serializers.IntegerField(required=False, allow_null=True)

    def validate_name(self, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise serializers.ValidationError("A folder name is required.")
        return cleaned


class FolderUpdateSerializer(serializers.Serializer):
    """Rename and/or move. Both optional; `parent` present (even as null)
    means MOVE — the view checks `'parent' in validated_data`."""

    name = serializers.CharField(max_length=255, required=False)
    parent = serializers.IntegerField(required=False, allow_null=True)

    def validate_name(self, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise serializers.ValidationError("A folder name is required.")
        return cleaned


class DocumentUploadSerializer(serializers.Serializer):
    folder = serializers.IntegerField()
    file = serializers.FileField(write_only=True)

    def validate_file(self, value):
        return validate_document_upload(value)


class DocumentUpdateSerializer(serializers.Serializer):
    """Rename (`original_filename`) and/or move (`folder`). Both optional;
    `folder` present means MOVE."""

    original_filename = serializers.CharField(max_length=255, required=False)
    folder = serializers.IntegerField(required=False)

    def validate_original_filename(self, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise serializers.ValidationError("A filename is required.")
        return cleaned
