"""
M2 P3 — serializers for the staff-credential / custom-profile-property
admin endpoints under /api/users/<user_id>/credentials|properties/
(SoT Addendum A.3).

Write-surface rules enforced here (the model layer repeats most of
them as defense-in-depth; the serializer makes them EXPLICIT 400s):

  - `credential_type` is IMMUTABLE after create. A PATCH that carries
    the field at all is a 400 (stable code `credential_type_immutable`)
    — this closes the P2 residual where a granted VCA could be mutated
    into an EU national ID.
  - EU_NATIONAL_ID: `visibility_level` must stay PA_SA_ONLY and
    `document_customer_visible` must stay False. Explicit 400s — the
    silent save() coercion is the model-layer backstop, not the API
    contract.
  - Document uploads are PDF-only (extension AND content type — the
    ALLOWED_EXTENSION_MIME_MAP pairing discipline), capped at the same
    10 MB the ticket-attachment upload uses. The metadata trio
    (original_filename / mime_type / file_size) is populated
    SERVER-SIDE from the uploaded file and is never accepted from the
    client (the write serializers simply do not expose those fields).
"""
from pathlib import Path as FilePath

from django.core.exceptions import ValidationError as DjangoValidationError
from django.urls import reverse
from rest_framework import serializers

from .models import (
    ALLOWED_DOCUMENT_EXTENSION,
    ALLOWED_DOCUMENT_MIME,
    CredentialCustomerVisibility,
    CustomProfileProperty,
    PropertyCustomerVisibility,
    StaffCredential,
    VisibilityLevel,
)

# Mirrors the ticket-attachment upload limit (tickets/serializers.py
# `validate_file`). Kept as a local constant — accounts must not import
# from tickets.
MAX_DOCUMENT_SIZE = 10 * 1024 * 1024


def _validate_pdf_upload(value):
    """PDF-only upload rule: extension AND declared content type must
    BOTH be PDF (a scan.pdf sent as image/jpeg and a scan.jpg sent as
    application/pdf are both rejected), size-capped like ticket
    attachments."""
    mime_type = getattr(value, "content_type", "") or "application/octet-stream"
    extension = FilePath(getattr(value, "name", "")).suffix.lower()
    if getattr(value, "size", 0) > MAX_DOCUMENT_SIZE:
        raise serializers.ValidationError(
            "Document file size cannot exceed 10 MB."
        )
    if extension != ALLOWED_DOCUMENT_EXTENSION or mime_type != ALLOWED_DOCUMENT_MIME:
        raise serializers.ValidationError(
            "Only PDF documents are allowed (.pdf with content type"
            " application/pdf).",
            code="invalid_document_type",
        )
    return value


def _full_clean_or_400(instance):
    """Run model full_clean() and surface Django ValidationErrors as a
    DRF 400 instead of an unhandled 500."""
    try:
        instance.full_clean()
    except DjangoValidationError as exc:
        raise serializers.ValidationError(serializers.as_serializer_error(exc))


def _apply_document(instance, document):
    """Attach an uploaded document and derive the metadata trio
    SERVER-SIDE — client-sent metadata is never trusted."""
    instance.document = document
    instance.original_filename = document.name
    instance.mime_type = (
        getattr(document, "content_type", "") or "application/octet-stream"
    )
    instance.file_size = getattr(document, "size", 0)


class CredentialGrantSerializer(serializers.ModelSerializer):
    """Read row for a per-customer credential share grant — inlined on
    the credential list so the P4 editor needs no extra round-trips."""

    customer_id = serializers.IntegerField(source="customer.id", read_only=True)
    customer_name = serializers.CharField(source="customer.name", read_only=True)

    class Meta:
        model = CredentialCustomerVisibility
        fields = ["id", "customer_id", "customer_name", "created_at"]
        read_only_fields = fields


class PropertyGrantSerializer(serializers.ModelSerializer):
    """Read row for a per-customer property share grant."""

    customer_id = serializers.IntegerField(source="customer.id", read_only=True)
    customer_name = serializers.CharField(source="customer.name", read_only=True)

    class Meta:
        model = PropertyCustomerVisibility
        fields = ["id", "customer_id", "customer_name", "created_at"]
        read_only_fields = fields


class StaffCredentialSerializer(serializers.ModelSerializer):
    """Admin read shape for a staff credential. The raw `document`
    FieldFile is never serialized — only the download URL."""

    has_document = serializers.SerializerMethodField()
    document_url = serializers.SerializerMethodField()
    grants = CredentialGrantSerializer(
        source="customer_grants", many=True, read_only=True
    )

    class Meta:
        model = StaffCredential
        fields = [
            "id",
            "credential_type",
            "permit_number",
            "expiry_date",
            "visibility_level",
            "document_customer_visible",
            "has_document",
            "original_filename",
            "mime_type",
            "file_size",
            "document_url",
            "grants",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields

    def get_has_document(self, obj) -> bool:
        return bool(obj.document)

    def get_document_url(self, obj):
        if not obj.document:
            return None
        path = reverse(
            "user-credential-download",
            kwargs={"user_id": obj.staff_profile.user_id, "pk": obj.id},
        )
        request = self.context.get("request")
        if request:
            return request.build_absolute_uri(path)
        return path


class StaffCredentialWriteSerializer(serializers.ModelSerializer):
    """Create / PATCH surface. Expects `context["staff_profile"]` (the
    target staff member's profile) on create."""

    document = serializers.FileField(write_only=True, required=False)

    class Meta:
        model = StaffCredential
        fields = [
            "credential_type",
            "permit_number",
            "expiry_date",
            "visibility_level",
            "document_customer_visible",
            "document",
        ]
        extra_kwargs = {"credential_type": {"required": True}}

    def validate_document(self, value):
        return _validate_pdf_upload(value)

    def _effective(self, attrs, field, create_default):
        if field in attrs:
            return attrs[field]
        if self.instance is not None:
            return getattr(self.instance, field)
        return create_default

    def validate(self, attrs):
        # credential_type is immutable after create — reject the PATCH
        # outright (even a same-value resend) so the API contract is
        # unambiguous. Checked against initial_data because DRF would
        # otherwise just bind the value silently.
        if self.instance is not None and "credential_type" in self.initial_data:
            raise serializers.ValidationError(
                {
                    "credential_type": serializers.ErrorDetail(
                        "credential_type is immutable after creation.",
                        code="credential_type_immutable",
                    )
                }
            )

        credential_type = self._effective(attrs, "credential_type", None)
        visibility_level = self._effective(
            attrs, "visibility_level", VisibilityLevel.PA_SA_ONLY
        )
        document_customer_visible = self._effective(
            attrs, "document_customer_visible", False
        )

        if credential_type == StaffCredential.CredentialType.EU_NATIONAL_ID:
            # Explicit API-level hard block (A.3.1) — don't rely on the
            # silent save() coercion for API writes.
            if visibility_level != VisibilityLevel.PA_SA_ONLY:
                raise serializers.ValidationError(
                    {
                        "visibility_level": serializers.ErrorDetail(
                            "EU national ID credentials are restricted to"
                            " provider admins (PA_SA_ONLY).",
                            code="eu_id_visibility_locked",
                        )
                    }
                )
            if document_customer_visible:
                raise serializers.ValidationError(
                    {
                        "document_customer_visible": serializers.ErrorDetail(
                            "EU national ID documents can never be"
                            " customer-visible.",
                            code="eu_id_document_blocked",
                        )
                    }
                )
        elif (
            document_customer_visible
            and credential_type != StaffCredential.CredentialType.RESIDENCE_PERMIT
        ):
            raise serializers.ValidationError(
                {
                    "document_customer_visible": serializers.ErrorDetail(
                        "Only residence-permit documents can be marked"
                        " customer-visible.",
                        code="document_customer_visible_residence_permit_only",
                    )
                }
            )
        return attrs

    def create(self, validated_data):
        document = validated_data.pop("document", None)
        credential = StaffCredential(
            staff_profile=self.context["staff_profile"], **validated_data
        )
        if document is not None:
            _apply_document(credential, document)
        _full_clean_or_400(credential)
        credential.save()
        return credential

    def update(self, instance, validated_data):
        document = validated_data.pop("document", None)
        for field, value in validated_data.items():
            setattr(instance, field, value)
        if document is not None:
            _apply_document(instance, document)
        _full_clean_or_400(instance)
        instance.save()
        return instance

    def to_representation(self, instance):
        return StaffCredentialSerializer(instance, context=self.context).data


class CustomProfilePropertySerializer(serializers.ModelSerializer):
    """Admin read shape for a custom profile property."""

    has_document = serializers.SerializerMethodField()
    document_url = serializers.SerializerMethodField()
    grants = PropertyGrantSerializer(
        source="customer_grants", many=True, read_only=True
    )

    class Meta:
        model = CustomProfileProperty
        fields = [
            "id",
            "name",
            "value",
            "visibility_level",
            "has_document",
            "original_filename",
            "mime_type",
            "file_size",
            "document_url",
            "grants",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields

    def get_has_document(self, obj) -> bool:
        return bool(obj.document)

    def get_document_url(self, obj):
        if not obj.document:
            return None
        path = reverse(
            "user-property-download",
            kwargs={"user_id": obj.user_id, "pk": obj.id},
        )
        request = self.context.get("request")
        if request:
            return request.build_absolute_uri(path)
        return path


class CustomProfilePropertyWriteSerializer(serializers.ModelSerializer):
    """Create / PATCH surface. Expects `context["target_user"]` (the
    property owner) on create. No immutability rule — name and value
    are freely editable; name repeats are allowed by design."""

    document = serializers.FileField(write_only=True, required=False)

    class Meta:
        model = CustomProfileProperty
        fields = ["name", "value", "visibility_level", "document"]

    def validate_document(self, value):
        return _validate_pdf_upload(value)

    def create(self, validated_data):
        document = validated_data.pop("document", None)
        prop = CustomProfileProperty(
            user=self.context["target_user"], **validated_data
        )
        if document is not None:
            _apply_document(prop, document)
        _full_clean_or_400(prop)
        prop.save()
        return prop

    def update(self, instance, validated_data):
        document = validated_data.pop("document", None)
        for field, value in validated_data.items():
            setattr(instance, field, value)
        if document is not None:
            _apply_document(instance, document)
        _full_clean_or_400(instance)
        instance.save()
        return instance

    def to_representation(self, instance):
        return CustomProfilePropertySerializer(instance, context=self.context).data
