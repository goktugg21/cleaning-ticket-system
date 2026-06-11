"""
M2 P2 — model-level tests for staff credentials & custom profile
properties (SoT Addendum A.3).

Pure model-layer coverage: full_clean() validation, the save()-level
defense-in-depth for the EU-national-ID compliance hard block, the DB
singleton constraint, the PDF-only document pairing rule, and the
create-time-only ceiling rule (with its inert-on-lower asymmetry) for
the per-customer share-grant tables. Serializer / view / resolver
behaviour is Phase P3 and is deliberately not exercised here.
"""
from __future__ import annotations

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import IntegrityError, transaction
from django.test import TestCase

from accounts.models import (
    CredentialCustomerVisibility,
    CustomProfileProperty,
    PropertyCustomerVisibility,
    StaffCredential,
    StaffProfile,
    UserRole,
    VisibilityLevel,
)
from buildings.models import Building
from companies.models import Company
from customers.models import Customer

User = get_user_model()
PASSWORD = "StrongerTestPassword123!"


class CredentialModelTestBase(TestCase):
    """Shared fixture: one provider company, one staff user with a
    StaffProfile, one customer org, one customer-role user."""

    @classmethod
    def setUpTestData(cls):
        cls.company = Company.objects.create(
            name="Provider Co", slug="provider-co"
        )
        cls.building = Building.objects.create(
            company=cls.company, name="HQ"
        )
        cls.customer = Customer.objects.create(
            company=cls.company, building=cls.building, name="Customer Org"
        )
        cls.staff_user = User.objects.create_user(
            email="staff@example.com", password=PASSWORD, role=UserRole.STAFF
        )
        cls.staff_profile = StaffProfile.objects.create(user=cls.staff_user)
        cls.customer_user = User.objects.create_user(
            email="customer@example.com",
            password=PASSWORD,
            role=UserRole.CUSTOMER_USER,
        )

    def make_credential(self, **overrides):
        params = dict(
            staff_profile=self.staff_profile,
            credential_type=StaffCredential.CredentialType.VCA,
        )
        params.update(overrides)
        return StaffCredential(**params)


class EuNationalIdHardBlockTests(CredentialModelTestBase):
    """SoT Addendum A.3.1 — the EU-ID compliance hard block lives in
    code (clean + save), not in a toggle."""

    def test_eu_id_above_pa_sa_only_rejected_then_forced_on_save(self):
        cred = self.make_credential(
            credential_type=StaffCredential.CredentialType.EU_NATIONAL_ID,
            visibility_level=VisibilityLevel.CUSTOMER_VISIBLE,
        )
        with self.assertRaises(ValidationError) as ctx:
            cred.full_clean()
        self.assertIn("visibility_level", ctx.exception.message_dict)

        cred.save()
        cred.refresh_from_db()
        self.assertEqual(cred.visibility_level, VisibilityLevel.PA_SA_ONLY)
        self.assertFalse(cred.document_customer_visible)

    def test_eu_id_document_customer_visible_rejected_then_cleared_on_save(self):
        cred = self.make_credential(
            credential_type=StaffCredential.CredentialType.EU_NATIONAL_ID,
            visibility_level=VisibilityLevel.PA_SA_ONLY,
            document_customer_visible=True,
        )
        with self.assertRaises(ValidationError) as ctx:
            cred.full_clean()
        self.assertIn(
            "document_customer_visible", ctx.exception.message_dict
        )

        cred.save()
        cred.refresh_from_db()
        self.assertFalse(cred.document_customer_visible)
        self.assertEqual(cred.visibility_level, VisibilityLevel.PA_SA_ONLY)

    def test_eu_id_save_with_update_fields_still_forces_invariants(self):
        cred = self.make_credential(
            credential_type=StaffCredential.CredentialType.EU_NATIONAL_ID,
        )
        cred.save()
        cred.visibility_level = VisibilityLevel.CUSTOMER_VISIBLE
        cred.save(update_fields=["visibility_level"])
        cred.refresh_from_db()
        self.assertEqual(cred.visibility_level, VisibilityLevel.PA_SA_ONLY)


class CredentialGrantTests(CredentialModelTestBase):
    def test_grant_on_eu_id_credential_rejected_any_state(self):
        cred = self.make_credential(
            credential_type=StaffCredential.CredentialType.EU_NATIONAL_ID,
        )
        cred.save()
        grant = CredentialCustomerVisibility(
            credential=cred, customer=self.customer
        )
        with self.assertRaises(ValidationError):
            grant.full_clean()
        # Defense-in-depth: a plain save() that skips full_clean() must
        # also refuse to persist the grant.
        with self.assertRaises(ValidationError):
            grant.save()
        self.assertEqual(CredentialCustomerVisibility.objects.count(), 0)

    def test_grant_creation_requires_customer_visible_ceiling(self):
        cred = self.make_credential(
            visibility_level=VisibilityLevel.PROVIDER_ONLY
        )
        cred.save()
        grant = CredentialCustomerVisibility(
            credential=cred, customer=self.customer
        )
        with self.assertRaises(ValidationError) as ctx:
            grant.full_clean()
        self.assertIn("credential", ctx.exception.message_dict)

        cred.visibility_level = VisibilityLevel.CUSTOMER_VISIBLE
        cred.save()
        grant = CredentialCustomerVisibility(
            credential=cred, customer=self.customer
        )
        grant.full_clean()
        grant.save()
        self.assertEqual(cred.customer_grants.count(), 1)

    def test_lowering_ceiling_keeps_existing_grant_inert(self):
        cred = self.make_credential(
            visibility_level=VisibilityLevel.CUSTOMER_VISIBLE
        )
        cred.save()
        grant = CredentialCustomerVisibility.objects.create(
            credential=cred, customer=self.customer
        )

        cred.visibility_level = VisibilityLevel.PROVIDER_ONLY
        cred.full_clean()
        cred.save()

        # The grant row survives the lowering — it becomes inert (the
        # P3 resolver gates on the ceiling), it is NOT cascade-deleted.
        grant.refresh_from_db()
        self.assertEqual(cred.customer_grants.count(), 1)


class CredentialSingletonConstraintTests(CredentialModelTestBase):
    def test_second_residence_permit_rejected_second_vca_allowed(self):
        StaffCredential.objects.create(
            staff_profile=self.staff_profile,
            credential_type=StaffCredential.CredentialType.RESIDENCE_PERMIT,
        )
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                StaffCredential.objects.create(
                    staff_profile=self.staff_profile,
                    credential_type=(
                        StaffCredential.CredentialType.RESIDENCE_PERMIT
                    ),
                )

        StaffCredential.objects.create(
            staff_profile=self.staff_profile,
            credential_type=StaffCredential.CredentialType.VCA,
        )
        StaffCredential.objects.create(
            staff_profile=self.staff_profile,
            credential_type=StaffCredential.CredentialType.VCA,
        )
        self.assertEqual(
            self.staff_profile.credentials.filter(
                credential_type=StaffCredential.CredentialType.VCA
            ).count(),
            2,
        )


class DocumentPairingTests(CredentialModelTestBase):
    """The PDF-only rule checks BOTH the extension and the MIME type,
    and requires the metadata trio exactly when a document is set."""

    @staticmethod
    def _pdf_file(name="scan.pdf"):
        return SimpleUploadedFile(
            name, b"%PDF-1.4 test", content_type="application/pdf"
        )

    def credential_with_document(self, **overrides):
        params = dict(
            staff_profile=self.staff_profile,
            credential_type=StaffCredential.CredentialType.VCA,
            document=self._pdf_file(),
            original_filename="scan.pdf",
            mime_type="application/pdf",
            file_size=1024,
        )
        params.update(overrides)
        return StaffCredential(**params)

    def test_pdf_extension_with_pdf_mime_passes(self):
        self.credential_with_document().full_clean()

    def test_pdf_extension_with_image_mime_rejected(self):
        cred = self.credential_with_document(mime_type="image/jpeg")
        with self.assertRaises(ValidationError) as ctx:
            cred.full_clean()
        self.assertIn("mime_type", ctx.exception.message_dict)

    def test_image_extension_with_pdf_mime_rejected(self):
        cred = self.credential_with_document(original_filename="scan.jpg")
        with self.assertRaises(ValidationError) as ctx:
            cred.full_clean()
        self.assertIn("original_filename", ctx.exception.message_dict)

    def test_document_with_missing_metadata_rejected(self):
        cred = self.credential_with_document(
            original_filename="", mime_type="", file_size=None
        )
        with self.assertRaises(ValidationError) as ctx:
            cred.full_clean()
        for field in ("original_filename", "mime_type", "file_size"):
            self.assertIn(field, ctx.exception.message_dict)

    def test_zero_file_size_rejected(self):
        cred = self.credential_with_document(file_size=0)
        with self.assertRaises(ValidationError) as ctx:
            cred.full_clean()
        self.assertIn("file_size", ctx.exception.message_dict)

    def test_metadata_without_document_rejected(self):
        cred = self.make_credential(
            original_filename="scan.pdf",
            mime_type="application/pdf",
            file_size=1024,
        )
        with self.assertRaises(ValidationError) as ctx:
            cred.full_clean()
        for field in ("original_filename", "mime_type", "file_size"):
            self.assertIn(field, ctx.exception.message_dict)

    def test_property_document_uses_same_pairing_rule(self):
        prop = CustomProfileProperty(
            user=self.staff_user,
            name="Diploma",
            document=self._pdf_file("diploma.pdf"),
            original_filename="diploma.pdf",
            mime_type="image/jpeg",
            file_size=512,
        )
        with self.assertRaises(ValidationError) as ctx:
            prop.full_clean()
        self.assertIn("mime_type", ctx.exception.message_dict)


class DocumentCustomerVisibleFlagTests(CredentialModelTestBase):
    def test_document_customer_visible_on_vca_rejected(self):
        cred = self.make_credential(
            credential_type=StaffCredential.CredentialType.VCA,
            document_customer_visible=True,
        )
        with self.assertRaises(ValidationError) as ctx:
            cred.full_clean()
        self.assertIn(
            "document_customer_visible", ctx.exception.message_dict
        )

    def test_document_customer_visible_on_residence_permit_allowed(self):
        cred = self.make_credential(
            credential_type=StaffCredential.CredentialType.RESIDENCE_PERMIT,
            visibility_level=VisibilityLevel.CUSTOMER_VISIBLE,
            document_customer_visible=True,
        )
        cred.full_clean()
        cred.save()
        cred.refresh_from_db()
        self.assertTrue(cred.document_customer_visible)


class CustomProfilePropertyTests(CredentialModelTestBase):
    def test_property_on_customer_user_saves(self):
        prop = CustomProfileProperty(
            user=self.customer_user, name="Loyalty tier", value="Gold"
        )
        prop.full_clean()
        prop.save()
        self.assertEqual(self.customer_user.profile_properties.count(), 1)

    def test_duplicate_property_names_allowed(self):
        CustomProfileProperty.objects.create(
            user=self.staff_user, name="Note", value="first"
        )
        CustomProfileProperty.objects.create(
            user=self.staff_user, name="Note", value="second"
        )
        self.assertEqual(
            self.staff_user.profile_properties.filter(name="Note").count(), 2
        )

    def test_property_grant_on_non_staff_owner_rejected(self):
        prop = CustomProfileProperty.objects.create(
            user=self.customer_user,
            name="Loyalty tier",
            value="Gold",
            visibility_level=VisibilityLevel.CUSTOMER_VISIBLE,
        )
        grant = PropertyCustomerVisibility(
            property=prop, customer=self.customer
        )
        with self.assertRaises(ValidationError) as ctx:
            grant.full_clean()
        self.assertIn("property", ctx.exception.message_dict)

    def test_property_grant_follows_ceiling_rules_and_inert_asymmetry(self):
        prop = CustomProfileProperty.objects.create(
            user=self.staff_user,
            name="Diploma",
            value="HBO Facility Management",
            visibility_level=VisibilityLevel.PA_SA_ONLY,
        )
        grant = PropertyCustomerVisibility(
            property=prop, customer=self.customer
        )
        with self.assertRaises(ValidationError):
            grant.full_clean()

        prop.visibility_level = VisibilityLevel.CUSTOMER_VISIBLE
        prop.save()
        grant = PropertyCustomerVisibility(
            property=prop, customer=self.customer
        )
        grant.full_clean()
        grant.save()

        # Same inert-on-lower asymmetry as credential grants.
        prop.visibility_level = VisibilityLevel.PROVIDER_ONLY
        prop.save()
        grant.refresh_from_db()
        self.assertEqual(prop.customer_grants.count(), 1)
