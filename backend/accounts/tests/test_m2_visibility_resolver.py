"""
M2 P3 — visibility resolver tests (SoT Addendum A.3).

Three blocks:
  1. PARITY (the B5 lockstep discipline): for EVERY (viewer-role,
     visibility_level, grant-state) cell, the per-item predicate and
     the queryset filter must agree — for credentials AND properties.
     This is the regression guard that keeps the two expressions of
     the canonical table in lockstep.
  2. Resolver semantics: STAFF sees nothing (including their own
     credential); BM sees PROVIDER_ONLY but never PA_SA_ONLY; a
     customer viewer needs ALL THREE legs (level + grant + membership)
     and the context customer must match.
  3. Document sub-rule + the 0007 DB CheckConstraint (QuerySet.update()
     can no longer smuggle an EU national ID above PA_SA_ONLY).
"""
from __future__ import annotations

from datetime import date

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
from accounts.visibility import (
    credential_document_visible_to_user,
    credential_visible_to_user,
    filter_credentials_visible_to,
    filter_properties_visible_to,
    property_document_visible_to_user,
    property_visible_to_user,
)
from test_utils import TenantFixtureMixin


class ResolverFixtureMixin(TenantFixtureMixin):
    def setUp(self):
        super().setUp()
        self.staff_a = self.make_user("staff-a@example.com", UserRole.STAFF)
        self.staff_profile = StaffProfile.objects.create(user=self.staff_a)

    def make_credential(self, level, *, credential_type=None, **extra):
        return StaffCredential.objects.create(
            staff_profile=self.staff_profile,
            credential_type=(
                credential_type or StaffCredential.CredentialType.VCA
            ),
            visibility_level=level,
            **extra,
        )

    def make_property(self, level, *, user=None, name="Diploma"):
        return CustomProfileProperty.objects.create(
            user=user or self.staff_a,
            name=name,
            value="HBO Facility Management",
            visibility_level=level,
        )

    def force_credential_grant(self, credential, customer):
        """Grant-row setup that bypasses clean() — simulates both the
        legit create-then-lower path and an adversarially smuggled row."""
        return CredentialCustomerVisibility.objects.bulk_create(
            [CredentialCustomerVisibility(credential=credential, customer=customer)]
        )[0]

    def force_property_grant(self, prop, customer):
        return PropertyCustomerVisibility.objects.bulk_create(
            [PropertyCustomerVisibility(property=prop, customer=customer)]
        )[0]


class ResolverParityTests(ResolverFixtureMixin, TestCase):
    """Block 1 — predicate == queryset membership for every cell."""

    def test_predicate_matches_queryset_for_every_cell(self):
        viewers = [
            ("SA", self.super_admin),
            ("PA", self.company_admin),
            ("BM", self.manager),
            ("STAFF", self.staff_a),
            ("CUSTOMER_member", self.customer_user),
            ("CUSTOMER_non_member", self.other_customer_user),
        ]
        for level in VisibilityLevel.values:
            for granted in (False, True):
                credential = self.make_credential(level)
                prop = self.make_property(level)
                if granted:
                    self.force_credential_grant(credential, self.customer)
                    self.force_property_grant(prop, self.customer)
                for label, viewer in viewers:
                    with self.subTest(
                        viewer=label, level=level, granted=granted
                    ):
                        predicate = credential_visible_to_user(
                            credential, viewer, self.customer
                        )
                        in_queryset = filter_credentials_visible_to(
                            StaffCredential.objects.filter(pk=credential.pk),
                            viewer,
                            self.customer,
                        ).exists()
                        self.assertEqual(
                            predicate,
                            in_queryset,
                            f"credential parity drift: {label}/{level}/"
                            f"granted={granted} predicate={predicate} "
                            f"queryset={in_queryset}",
                        )

                        prop_predicate = property_visible_to_user(
                            prop, viewer, self.customer
                        )
                        prop_in_queryset = filter_properties_visible_to(
                            CustomProfileProperty.objects.filter(pk=prop.pk),
                            viewer,
                            self.customer,
                        ).exists()
                        self.assertEqual(
                            prop_predicate,
                            prop_in_queryset,
                            f"property parity drift: {label}/{level}/"
                            f"granted={granted}",
                        )
                credential.delete()
                prop.delete()


class ResolverSemanticsTests(ResolverFixtureMixin, TestCase):
    """Block 2 — the table's individual rules."""

    def test_staff_viewer_sees_nothing_including_own_credential(self):
        for level in VisibilityLevel.values:
            credential = self.make_credential(level)
            self.force_credential_grant(credential, self.customer)
            with self.subTest(level=level):
                # staff_a IS the credential owner — no self-view in M2.
                self.assertFalse(
                    credential_visible_to_user(
                        credential, self.staff_a, self.customer
                    )
                )
                self.assertFalse(
                    filter_credentials_visible_to(
                        StaffCredential.objects.all(),
                        self.staff_a,
                        self.customer,
                    ).exists()
                )
            credential.delete()

    def test_bm_sees_provider_only_but_not_pa_sa_only(self):
        hidden = self.make_credential(VisibilityLevel.PA_SA_ONLY)
        visible = self.make_credential(VisibilityLevel.PROVIDER_ONLY)
        self.assertFalse(
            credential_visible_to_user(hidden, self.manager, None)
        )
        self.assertTrue(
            credential_visible_to_user(visible, self.manager, None)
        )
        ids = set(
            filter_credentials_visible_to(
                StaffCredential.objects.all(), self.manager, None
            ).values_list("id", flat=True)
        )
        self.assertEqual(ids, {visible.id})

    def test_customer_needs_all_three_legs(self):
        # Leg 1 missing — level below CUSTOMER_VISIBLE (grant + membership ok).
        low = self.make_credential(VisibilityLevel.PROVIDER_ONLY)
        self.force_credential_grant(low, self.customer)
        self.assertFalse(
            credential_visible_to_user(low, self.customer_user, self.customer)
        )

        # Leg 2 missing — no grant (level + membership ok).
        ungranted = self.make_credential(VisibilityLevel.CUSTOMER_VISIBLE)
        self.assertFalse(
            credential_visible_to_user(
                ungranted, self.customer_user, self.customer
            )
        )

        # Leg 3 missing — viewer is not a member of the context customer
        # (level + grant ok).
        granted = self.make_credential(VisibilityLevel.CUSTOMER_VISIBLE)
        self.force_credential_grant(granted, self.customer)
        self.assertFalse(
            credential_visible_to_user(
                granted, self.other_customer_user, self.customer
            )
        )

        # All three legs -> visible.
        self.assertTrue(
            credential_visible_to_user(
                granted, self.customer_user, self.customer
            )
        )

    def test_context_customer_mismatch_invisible(self):
        credential = self.make_credential(VisibilityLevel.CUSTOMER_VISIBLE)
        self.force_credential_grant(credential, self.customer)
        # Viewer is a member of customer A and the grant is for customer
        # A — but the CONTEXT is customer B: invisible both ways.
        self.assertFalse(
            credential_visible_to_user(
                credential, self.customer_user, self.other_customer
            )
        )
        # And a grant for customer B does not help a customer-A context.
        credential_b = self.make_credential(VisibilityLevel.CUSTOMER_VISIBLE)
        self.force_credential_grant(credential_b, self.other_customer)
        self.assertFalse(
            credential_visible_to_user(
                credential_b, self.customer_user, self.customer
            )
        )

    def test_none_context_blocks_customer_but_not_provider(self):
        credential = self.make_credential(VisibilityLevel.CUSTOMER_VISIBLE)
        self.force_credential_grant(credential, self.customer)
        self.assertFalse(
            credential_visible_to_user(credential, self.customer_user, None)
        )
        self.assertTrue(
            credential_visible_to_user(credential, self.super_admin, None)
        )


class DocumentSubRuleTests(ResolverFixtureMixin, TestCase):
    """Block 3a — the stricter document gate layered on field visibility."""

    def test_residence_permit_photocopy_rule(self):
        credential = self.make_credential(
            VisibilityLevel.CUSTOMER_VISIBLE,
            credential_type=StaffCredential.CredentialType.RESIDENCE_PERMIT,
            permit_number="RP-123",
            expiry_date=date(2027, 1, 1),
            document_customer_visible=False,
        )
        self.force_credential_grant(credential, self.customer)
        # Fields visible, photocopy not.
        self.assertTrue(
            credential_visible_to_user(
                credential, self.customer_user, self.customer
            )
        )
        self.assertFalse(
            credential_document_visible_to_user(
                credential, self.customer_user, self.customer
            )
        )
        # Flag on -> photocopy too.
        credential.document_customer_visible = True
        credential.save()
        self.assertTrue(
            credential_document_visible_to_user(
                credential, self.customer_user, self.customer
            )
        )
        # Provider roles passing the field gate see the document
        # regardless of the customer-facing flag.
        credential.document_customer_visible = False
        credential.save()
        self.assertTrue(
            credential_document_visible_to_user(credential, self.manager, None)
        )

    def test_eu_id_document_blocked_for_bm_and_customers(self):
        credential = self.make_credential(
            VisibilityLevel.PA_SA_ONLY,
            credential_type=StaffCredential.CredentialType.EU_NATIONAL_ID,
        )
        # Even with an adversarially smuggled grant row (bulk_create
        # bypasses both clean() and the save() guard), the resolver
        # still blocks every non-PA/SA viewer.
        self.force_credential_grant(credential, self.customer)
        self.assertFalse(
            credential_document_visible_to_user(credential, self.manager, None)
        )
        self.assertFalse(
            credential_document_visible_to_user(
                credential, self.customer_user, self.customer
            )
        )
        self.assertFalse(
            credential_document_visible_to_user(
                credential, self.staff_a, None
            )
        )
        self.assertTrue(
            credential_document_visible_to_user(
                credential, self.super_admin, None
            )
        )
        self.assertTrue(
            credential_document_visible_to_user(
                credential, self.company_admin, None
            )
        )

    def test_vca_and_property_documents_follow_field_visibility(self):
        vca = self.make_credential(VisibilityLevel.CUSTOMER_VISIBLE)
        self.force_credential_grant(vca, self.customer)
        self.assertTrue(
            credential_document_visible_to_user(
                vca, self.customer_user, self.customer
            )
        )
        prop = self.make_property(VisibilityLevel.CUSTOMER_VISIBLE)
        self.force_property_grant(prop, self.customer)
        self.assertEqual(
            property_visible_to_user(prop, self.customer_user, self.customer),
            property_document_visible_to_user(
                prop, self.customer_user, self.customer
            ),
        )
        hidden_prop = self.make_property(VisibilityLevel.PA_SA_ONLY)
        self.assertFalse(
            property_document_visible_to_user(hidden_prop, self.manager, None)
        )


class EuIdDbConstraintTests(ResolverFixtureMixin, TestCase):
    """Block 3b — migration 0007: the EU-ID hard block is DB-enforced,
    closing the QuerySet.update()/bulk_create() bypass from P2."""

    def test_queryset_update_raising_eu_id_visibility_hits_constraint(self):
        credential = self.make_credential(
            VisibilityLevel.PA_SA_ONLY,
            credential_type=StaffCredential.CredentialType.EU_NATIONAL_ID,
        )
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                StaffCredential.objects.filter(pk=credential.pk).update(
                    visibility_level=VisibilityLevel.CUSTOMER_VISIBLE
                )
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                StaffCredential.objects.filter(pk=credential.pk).update(
                    document_customer_visible=True
                )

    def test_bulk_create_of_invalid_eu_id_hits_constraint(self):
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                StaffCredential.objects.bulk_create(
                    [
                        StaffCredential(
                            staff_profile=self.staff_profile,
                            credential_type=(
                                StaffCredential.CredentialType.EU_NATIONAL_ID
                            ),
                            visibility_level=VisibilityLevel.CUSTOMER_VISIBLE,
                        )
                    ]
                )

    def test_valid_rows_unaffected_by_constraint(self):
        credential = self.make_credential(VisibilityLevel.PA_SA_ONLY)
        StaffCredential.objects.filter(pk=credential.pk).update(
            visibility_level=VisibilityLevel.CUSTOMER_VISIBLE
        )
        credential.refresh_from_db()
        self.assertEqual(
            credential.visibility_level, VisibilityLevel.CUSTOMER_VISIBLE
        )
