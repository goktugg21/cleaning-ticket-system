"""
M2 P3 — audit coverage for staff credentials, custom profile
properties and their per-customer share grants (matrix H-10).

Pins:
  - StaffCredential CREATE / DELETE rows + UPDATE diffs; severity HIGH
    when visibility_level or document_customer_visible changes, NORMAL
    for permit_number / expiry_date edits.
  - CustomProfileProperty UPDATE diff: visibility_level HIGH,
    name/value NORMAL.
  - Grant CREATE / DELETE rows always HIGH (a per-customer share grant
    IS a sensitive-visibility change).
  - Audit payloads never contain document bytes or storage paths —
    filenames only.
"""
from __future__ import annotations

import json
import tempfile

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings

from accounts.models import (
    CredentialCustomerVisibility,
    CustomProfileProperty,
    PropertyCustomerVisibility,
    StaffCredential,
    StaffProfile,
    UserRole,
    VisibilityLevel,
)
from audit.models import AuditAction, AuditLog, AuditSeverity
from test_utils import TenantFixtureMixin

_MEDIA_ROOT = tempfile.mkdtemp(prefix="m2p3-audit-media-")


@override_settings(MEDIA_ROOT=_MEDIA_ROOT)
class CredentialAuditTests(TenantFixtureMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.staff_a = self.make_user("staff-a@example.com", UserRole.STAFF)
        self.profile_a = StaffProfile.objects.create(user=self.staff_a)

    def latest_log(self, model_label, action):
        return (
            AuditLog.objects.filter(target_model=model_label, action=action)
            .order_by("-id")
            .first()
        )

    def test_credential_create_and_delete_rows(self):
        credential = StaffCredential.objects.create(
            staff_profile=self.profile_a,
            credential_type=StaffCredential.CredentialType.VCA,
        )
        log = self.latest_log("accounts.StaffCredential", AuditAction.CREATE)
        self.assertIsNotNone(log)
        self.assertEqual(log.target_id, credential.id)
        self.assertEqual(log.severity, AuditSeverity.NORMAL)
        self.assertEqual(
            log.changes["credential_type"]["after"], "VCA"
        )
        self.assertEqual(
            log.changes["staff_user_email"]["after"], self.staff_a.email
        )
        credential.delete()
        log = self.latest_log("accounts.StaffCredential", AuditAction.DELETE)
        self.assertIsNotNone(log)
        self.assertEqual(log.changes["credential_type"]["before"], "VCA")

    def test_visibility_change_is_high_with_before_after(self):
        credential = StaffCredential.objects.create(
            staff_profile=self.profile_a,
            credential_type=StaffCredential.CredentialType.VCA,
            visibility_level=VisibilityLevel.PA_SA_ONLY,
        )
        credential.visibility_level = VisibilityLevel.CUSTOMER_VISIBLE
        credential.save()
        log = self.latest_log("accounts.StaffCredential", AuditAction.UPDATE)
        self.assertIsNotNone(log)
        self.assertEqual(log.severity, AuditSeverity.HIGH)
        self.assertEqual(
            log.changes["visibility_level"],
            {"before": "PA_SA_ONLY", "after": "CUSTOMER_VISIBLE"},
        )

    def test_permit_number_change_is_normal(self):
        credential = StaffCredential.objects.create(
            staff_profile=self.profile_a,
            credential_type=StaffCredential.CredentialType.RESIDENCE_PERMIT,
            permit_number="RP-1",
        )
        credential.permit_number = "RP-2"
        credential.save()
        log = self.latest_log("accounts.StaffCredential", AuditAction.UPDATE)
        self.assertIsNotNone(log)
        self.assertEqual(log.severity, AuditSeverity.NORMAL)
        self.assertEqual(
            log.changes["permit_number"], {"before": "RP-1", "after": "RP-2"}
        )

    def test_grant_create_and_delete_are_high(self):
        credential = StaffCredential.objects.create(
            staff_profile=self.profile_a,
            credential_type=StaffCredential.CredentialType.VCA,
            visibility_level=VisibilityLevel.CUSTOMER_VISIBLE,
        )
        grant = CredentialCustomerVisibility.objects.create(
            credential=credential, customer=self.customer
        )
        log = self.latest_log(
            "accounts.CredentialCustomerVisibility", AuditAction.CREATE
        )
        self.assertIsNotNone(log)
        self.assertEqual(log.severity, AuditSeverity.HIGH)
        self.assertEqual(
            log.changes["customer_name"]["after"], self.customer.name
        )
        grant.delete()
        log = self.latest_log(
            "accounts.CredentialCustomerVisibility", AuditAction.DELETE
        )
        self.assertIsNotNone(log)
        self.assertEqual(log.severity, AuditSeverity.HIGH)

    def test_property_grant_rows_are_high(self):
        prop = CustomProfileProperty.objects.create(
            user=self.staff_a,
            name="Diploma",
            value="HBO",
            visibility_level=VisibilityLevel.CUSTOMER_VISIBLE,
        )
        grant = PropertyCustomerVisibility.objects.create(
            property=prop, customer=self.customer
        )
        log = self.latest_log(
            "accounts.PropertyCustomerVisibility", AuditAction.CREATE
        )
        self.assertIsNotNone(log)
        self.assertEqual(log.severity, AuditSeverity.HIGH)
        self.assertEqual(log.changes["property_name"]["after"], "Diploma")
        grant.delete()
        log = self.latest_log(
            "accounts.PropertyCustomerVisibility", AuditAction.DELETE
        )
        self.assertEqual(log.severity, AuditSeverity.HIGH)

    def test_property_update_severity_split(self):
        prop = CustomProfileProperty.objects.create(
            user=self.customer_user, name="Tier", value="Gold"
        )
        prop.value = "Platinum"
        prop.save()
        log = self.latest_log(
            "accounts.CustomProfileProperty", AuditAction.UPDATE
        )
        self.assertEqual(log.severity, AuditSeverity.NORMAL)
        self.assertEqual(
            log.changes["value"], {"before": "Gold", "after": "Platinum"}
        )
        prop.visibility_level = VisibilityLevel.PROVIDER_ONLY
        prop.save()
        log = self.latest_log(
            "accounts.CustomProfileProperty", AuditAction.UPDATE
        )
        self.assertEqual(log.severity, AuditSeverity.HIGH)

    def test_no_document_bytes_or_paths_in_payloads(self):
        credential = StaffCredential(
            staff_profile=self.profile_a,
            credential_type=StaffCredential.CredentialType.VCA,
        )
        credential.document = SimpleUploadedFile(
            "vca-cert.pdf", b"%PDF-1.4 audit", content_type="application/pdf"
        )
        credential.original_filename = "vca-cert.pdf"
        credential.mime_type = "application/pdf"
        credential.file_size = 14
        credential.save()
        log = self.latest_log("accounts.StaffCredential", AuditAction.CREATE)
        self.assertIsNotNone(log)
        self.assertEqual(
            log.changes["original_filename"]["after"], "vca-cert.pdf"
        )
        serialized = json.dumps(log.changes)
        # The storage path (upload_to root + uuid name) and the raw
        # FieldFile must never appear — filenames only.
        self.assertNotIn("staff_credentials/", serialized)
        self.assertNotIn("document", log.changes)
