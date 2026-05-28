"""
Sprint 27F-B2 — audit-coverage tests for the new `AuditLog.reason` +
`AuditLog.actor_scope` columns (closes gap G-B6 from
`docs/architecture/sprint-27-rbac-matrix.md` §7).

Five test classes, five tests:

1. `LegacyWriteDefaultsTests.test_audit_log_default_reason_and_actor_scope_for_legacy_writes`
   — an audited write that does NOT set `set_current_reason` /
   `set_current_actor_scope` still produces an AuditLog row where
   `reason == ""` and `actor_scope` is a dict (may be empty if the
   middleware did not have an authenticated user, or populated if it
   did — the test asserts only the contract: the field is a dict).

2. `ReasonContextTests.test_audit_log_records_set_reason_from_context`
   — calling `set_current_reason("test reason")` before an audited
   write makes the resulting AuditLog row carry `reason == "test reason"`.

3. `ActorScopeCompanyAdminTests.test_audit_log_records_actor_scope_for_company_admin`
   — `snapshot_actor_scope(COMPANY_ADMIN)` includes both company ids
   from the actor's two `CompanyUserMembership` rows, and the audit
   row carries that snapshot.

4. `ActorScopeCustomerUserTests.test_actor_scope_for_customer_user_includes_customer_id`
   — `snapshot_actor_scope(CUSTOMER_USER)` includes the customer id
   from the actor's `CustomerUserMembership` row, and the audit row
   carries that snapshot.

5. `AnonymousActorScopeTests.test_anonymous_user_actor_scope_is_empty`
   — `snapshot_actor_scope(AnonymousUser())` returns `{}`. Pure
   unit-style assertion, no DB write needed.

Mirrors the test pattern of `audit/tests/test_audit_membership.py`.
"""
from django.contrib.auth.models import AnonymousUser
from rest_framework import status
from rest_framework.test import APITestCase

from accounts.models import UserRole
from audit import context as audit_context
from audit.context import (
    get_current_actor_scope,
    get_current_reason,
    set_current_actor_scope,
    set_current_reason,
    snapshot_actor_scope,
)
from audit.models import AuditAction, AuditLog
from companies.models import Company, CompanyUserMembership
from customers.models import CustomerUserMembership
from test_utils import TenantFixtureMixin


class _AuditColumnsBase(TenantFixtureMixin, APITestCase):
    def setUp(self):
        super().setUp()
        # Wipe pre-existing audit rows from the fixture so each test
        # starts with a known-empty slate.
        AuditLog.objects.all().delete()
        # And reset any thread-local context leakage from earlier tests
        # in the same process — these helpers explicitly support being
        # called without a prior set_request.
        audit_context.set_current_reason("")
        audit_context.set_current_actor_scope({})


# ===========================================================================
# 1. Legacy writes (no context plumbing) — reason "" and actor_scope is a dict.
# ===========================================================================


class LegacyWriteDefaultsTests(_AuditColumnsBase):
    def test_audit_log_default_reason_and_actor_scope_for_legacy_writes(self):
        # Trigger an audited write WITHOUT touching set_current_reason /
        # set_current_actor_scope. The middleware runs for this request,
        # so actor_scope MAY be populated (depending on JWT-auth-vs-
        # session timing) — we assert only the contract: reason is the
        # empty string and actor_scope is a JSON-able dict.
        self.authenticate(self.super_admin)
        response = self.client.patch(
            f"/api/users/{self.customer_user.id}/",
            {"full_name": "New Full Name"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        log = AuditLog.objects.filter(
            target_model="accounts.User",
            target_id=self.customer_user.id,
            action=AuditAction.UPDATE,
        ).get()

        # Contract: reason defaults to the empty string.
        self.assertEqual(log.reason, "")

        # Contract: actor_scope is always a dict (never None / never
        # missing). It may be empty or populated; both are valid for
        # legacy writes. The strict invariant is the type.
        self.assertIsInstance(log.actor_scope, dict)


# ===========================================================================
# 2. set_current_reason flows through to the audit row.
# ===========================================================================


class ReasonContextTests(_AuditColumnsBase):
    def test_audit_log_records_set_reason_from_context(self):
        # The test client's force_authenticate path doesn't run the
        # audit middleware (it bypasses request processing), so we set
        # the context helpers manually — the same lifecycle a view
        # would use after capturing an operator reason from its modal.
        self.authenticate(self.super_admin)
        set_current_reason("test reason")
        try:
            response = self.client.patch(
                f"/api/users/{self.customer_user.id}/",
                {"full_name": "Reason Aware"},
                format="json",
            )
            self.assertEqual(response.status_code, status.HTTP_200_OK)
        finally:
            # Clean up so a later test in the same process doesn't see
            # this reason bleed through.
            set_current_reason("")

        log = AuditLog.objects.filter(
            target_model="accounts.User",
            target_id=self.customer_user.id,
            action=AuditAction.UPDATE,
        ).get()
        self.assertEqual(log.reason, "test reason")


# ===========================================================================
# 3. COMPANY_ADMIN snapshot — includes both company ids.
# ===========================================================================


class ActorScopeCompanyAdminTests(_AuditColumnsBase):
    def setUp(self):
        super().setUp()
        # Give the COMPANY_ADMIN actor a SECOND CompanyUserMembership so
        # `company_ids` carries two ids in the snapshot. The fixture
        # already created one CompanyUserMembership for self.company_admin
        # → self.company.
        self.second_company = Company.objects.create(
            name="Second Provider Co", slug="second-provider"
        )
        CompanyUserMembership.objects.create(
            user=self.company_admin, company=self.second_company
        )

    def test_audit_log_records_actor_scope_for_company_admin(self):
        # Snapshot the actor scope BEFORE the audited write so the
        # signal handler picks it up from the thread-local.
        snapshot = snapshot_actor_scope(self.company_admin)
        self.assertEqual(snapshot["role"], UserRole.COMPANY_ADMIN)
        self.assertEqual(snapshot["user_id"], self.company_admin.id)
        self.assertIsInstance(snapshot["company_ids"], list)
        self.assertIn(self.company.id, snapshot["company_ids"])
        self.assertIn(self.second_company.id, snapshot["company_ids"])
        self.assertIsNone(snapshot["customer_id"])
        self.assertIsNone(snapshot["building_id"])

        self.authenticate(self.company_admin)
        set_current_actor_scope(snapshot)
        try:
            response = self.client.patch(
                f"/api/users/{self.customer_user.id}/",
                {"full_name": "Scoped Update"},
                format="json",
            )
            self.assertEqual(response.status_code, status.HTTP_200_OK)
        finally:
            set_current_actor_scope({})

        log = AuditLog.objects.filter(
            target_model="accounts.User",
            target_id=self.customer_user.id,
            action=AuditAction.UPDATE,
        ).get()
        self.assertEqual(log.actor_scope["role"], UserRole.COMPANY_ADMIN)
        self.assertIsInstance(log.actor_scope["company_ids"], list)
        self.assertIn(self.company.id, log.actor_scope["company_ids"])
        self.assertIn(self.second_company.id, log.actor_scope["company_ids"])


# ===========================================================================
# 4. CUSTOMER_USER snapshot — customer_id is populated.
# ===========================================================================


class ActorScopeCustomerUserTests(_AuditColumnsBase):
    def test_actor_scope_for_customer_user_includes_customer_id(self):
        # self.customer_user has a CustomerUserMembership pointing at
        # self.customer (created by TenantFixtureMixin).
        snapshot = snapshot_actor_scope(self.customer_user)
        self.assertEqual(snapshot["role"], UserRole.CUSTOMER_USER)
        self.assertEqual(snapshot["user_id"], self.customer_user.id)
        self.assertEqual(snapshot["customer_id"], self.customer.id)
        # CUSTOMER_USER has no provider-side memberships.
        self.assertEqual(snapshot["company_ids"], [])
        self.assertIsNone(snapshot["building_id"])

        # Sanity check that the membership table is the source of truth.
        self.assertTrue(
            CustomerUserMembership.objects.filter(
                user=self.customer_user, customer=self.customer
            ).exists()
        )

        # And confirm the snapshot lands on a written AuditLog row when
        # piped through the context helpers. We bypass the API + the
        # middleware here (a direct ORM save still fires the audit
        # signals, but does NOT overwrite the thread-local
        # actor_scope) so the customer-user snapshot is what the
        # _create_log handler sees at write time. This mirrors the
        # production flow where a view sets the scope AFTER DRF JWT
        # auth has resolved request.user.
        set_current_actor_scope(snapshot)
        try:
            # Direct ORM mutation on a tracked model (accounts.User)
            # fires the audit post_save handler.
            self.customer_user.full_name = "Customer-side scoped"
            self.customer_user.save(update_fields=["full_name"])
        finally:
            set_current_actor_scope({})

        log = AuditLog.objects.filter(
            target_model="accounts.User",
            target_id=self.customer_user.id,
            action=AuditAction.UPDATE,
        ).get()
        self.assertEqual(log.actor_scope["role"], UserRole.CUSTOMER_USER)
        self.assertEqual(log.actor_scope["customer_id"], self.customer.id)


# ===========================================================================
# 5. AnonymousUser snapshot — empty dict.
# ===========================================================================


class AnonymousActorScopeTests(_AuditColumnsBase):
    def test_anonymous_user_actor_scope_is_empty(self):
        snapshot = snapshot_actor_scope(AnonymousUser())
        self.assertEqual(snapshot, {})

        # Belt-and-braces: None is also handled.
        self.assertEqual(snapshot_actor_scope(None), {})

        # And the getter falls back to {} when nothing has been set.
        self.assertEqual(get_current_actor_scope(), {})
        self.assertEqual(get_current_reason(), "")
