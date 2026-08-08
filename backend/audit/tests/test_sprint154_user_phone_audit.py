"""
Sprint 154 §I.1 — a change to `User.phone` writes an AuditLog row.

CLAUDE.md's rule is "new tracked field on an audited model -> edit
`_*_TRACKED_FIELDS` in `audit/signals.py` AND add a test in
`audit/tests/`". Only the second half applies here, and the reason is
worth stating because the prompt asked for the first half too:

**There is no `_USER_TRACKED_FIELDS`.** `accounts.User` is one of the
four models in the FULL-CRUD trio (`User` / `Company` / `Building` /
`Customer`), and those are audited by GENERIC FIELD INTROSPECTION —
`audit.diff._snapshot` walks `instance._meta.get_fields()` and records
every concrete field that is not a relation-to-many, not in
`NOISY_FIELDS` (`created_at` / `updated_at` / `last_login`) and does not
match `SENSITIVE_FIELD_TOKENS` (`password` / `token` / `secret` / `hash`
/ `otp` / `mfa`). `phone` is none of those, so it is picked up with no
registry edit at all. The explicit `_*_TRACKED_FIELDS` tuples exist only
for the models with hand-written handlers (`CustomerUserBuildingAccess`,
`BuildingStaffVisibility`, `BuildingManagerAssignment`, ...).

That makes this test the ONLY thing standing between the field and a
future change to `_is_auditable` that silently drops it — e.g. someone
adding "phone" to a privacy filter. Hence: assert the diff, not just the
row count.
"""
from rest_framework import status
from rest_framework.test import APITestCase

from audit.models import AuditAction, AuditLog
from test_utils import TenantFixtureMixin


class UserPhoneAuditTests(TenantFixtureMixin, APITestCase):
    def _user_update_logs(self, user):
        return AuditLog.objects.filter(
            target_model="accounts.User",
            target_id=user.id,
            action=AuditAction.UPDATE,
        )

    def test_setting_a_phone_via_the_admin_endpoint_is_audited(self):
        self.authenticate(self.super_admin)
        before = self._user_update_logs(self.manager).count()

        response = self.client.patch(
            f"/api/users/{self.manager.id}/",
            {"phone": "+31 20 555 0100"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["phone"], "+31 20 555 0100")

        logs = self._user_update_logs(self.manager)
        self.assertEqual(logs.count(), before + 1)
        log = logs.order_by("-created_at").first()
        self.assertIn(
            "phone",
            log.changes,
            "User.phone is not in the audit diff — check that "
            "audit.diff._is_auditable still admits it",
        )
        self.assertEqual(log.changes["phone"]["before"], "")
        self.assertEqual(log.changes["phone"]["after"], "+31 20 555 0100")
        self.assertEqual(log.actor_id, self.super_admin.id)

    def test_changing_an_existing_phone_records_both_sides(self):
        self.manager.phone = "+31 20 555 0100"
        self.manager.save(update_fields=["phone"])

        self.authenticate(self.super_admin)
        self.client.patch(
            f"/api/users/{self.manager.id}/",
            {"phone": "+31 20 555 0199"},
            format="json",
        )
        log = self._user_update_logs(self.manager).order_by("-created_at").first()
        self.assertEqual(log.changes["phone"]["before"], "+31 20 555 0100")
        self.assertEqual(log.changes["phone"]["after"], "+31 20 555 0199")

    def test_phone_is_not_treated_as_a_sensitive_field(self):
        """The audit engine drops any field whose name contains a
        SENSITIVE_FIELD_TOKENS substring. Pin that `phone` is not one of
        them, so the assertions above cannot start passing vacuously."""
        from audit.diff import _is_sensitive

        self.assertFalse(_is_sensitive("phone"))

    def test_a_users_own_profile_update_is_audited_too(self):
        self.authenticate(self.manager)
        response = self.client.patch(
            "/api/auth/me/", {"phone": "+31 6 1234 5678"}, format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.manager.refresh_from_db()
        self.assertEqual(self.manager.phone, "+31 6 1234 5678")
        log = self._user_update_logs(self.manager).order_by("-created_at").first()
        self.assertIsNotNone(log)
        self.assertEqual(log.changes["phone"]["after"], "+31 6 1234 5678")
